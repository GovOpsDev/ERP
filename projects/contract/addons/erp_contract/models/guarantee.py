"""Purchase guarantees settled through native invoices, bills and payments."""
import math
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

_guarantee_workflow = ContextVar('erp_guarantee_workflow', default=False)


class GuaranteeMethod(models.Model):
    _name = 'erp.contract.guarantee.method'
    _description = 'Purchase Guarantee Method'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict')
    default_for = fields.Selection([('requisition', 'Purchase Agreement'), ('rfq', 'RFQ'), ('po', 'Purchase Order')], required=True)
    account_id = fields.Many2one('account.account', required=True, check_company=True, ondelete='restrict')
    active = fields.Boolean(default=True)

    @api.constrains('company_id', 'account_id')
    def _check_account(self):
        for method in self:
            if method.company_id not in method.account_id.company_ids or method.account_id.account_type in ('asset_receivable', 'liability_payable', 'off_balance'):
                raise ValidationError(_('Choose a guarantee account in the method company, separate from receivable/payable.'))

    def write(self, vals):
        if {'company_id', 'account_id'} & vals.keys() and self.env['erp.contract.guarantee'].sudo().search_count([('method_id', 'in', self.ids), ('move_ids', '!=', False)]):
            raise UserError(_('A guarantee method with financial history cannot change account or company.'))
        return super().write(vals)


class GuaranteeType(models.Model):
    _name = 'erp.contract.guarantee.type'
    _description = 'Purchase Guarantee Instrument Type'

    name = fields.Char(required=True)
    is_create_invoice = fields.Boolean(string='Uses accounting settlement')
    active = fields.Boolean(default=True)

    def write(self, vals):
        if 'is_create_invoice' in vals and self.env['erp.contract.guarantee'].sudo().search_count([('type_id', 'in', self.ids)]):
            raise UserError(_('The accounting meaning of a used guarantee instrument cannot change.'))
        return super().write(vals)


class Guarantee(models.Model):
    _name = 'erp.contract.guarantee'
    _description = 'Purchase Guarantee'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(required=True, default='New', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict', index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict', index=True)
    purchase_order_id = fields.Many2one('purchase.order', check_company=True, ondelete='restrict')
    requisition_id = fields.Many2one('purchase.requisition', check_company=True, ondelete='restrict')
    partner_id = fields.Many2one('res.partner', required=True, check_company=True, ondelete='restrict')
    method_id = fields.Many2one('erp.contract.guarantee.method', required=True, check_company=True, ondelete='restrict')
    type_id = fields.Many2one('erp.contract.guarantee.type', required=True, ondelete='restrict')
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(required=True)
    date_guarantee_receive = fields.Date(required=True, default=fields.Date.context_today)
    date_due_guarantee = fields.Date()
    document_ref = fields.Char(required=True)
    document_return_date = fields.Date(string='Document Instrument Return Date')
    date_return = fields.Date(compute='_compute_settlement', compute_sudo=True)
    note = fields.Text()
    analytic_distribution = fields.Json()
    fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict')
    move_ids = fields.One2many('account.move', 'erp_guarantee_id', readonly=True)
    amount_received = fields.Monetary(compute='_compute_settlement', compute_sudo=True)
    amount_returned = fields.Monetary(compute='_compute_settlement', compute_sudo=True)
    active = fields.Boolean(default=True)
    lock_version = fields.Integer(readonly=True, default=0)
    _name_company_unique = models.Constraint('unique(company_id, name)', 'Guarantee number must be unique within its company.')

    @api.onchange('purchase_order_id', 'requisition_id')
    def _onchange_source(self):
        source = self.purchase_order_id or self.requisition_id
        if not source:
            return
        self.company_id = source.company_id
        self.organization_id = source.erp_request_organization_id if self.purchase_order_id else source.erp_organization_id
        if self.purchase_order_id:
            self.partner_id = source.partner_id
        kind = ('po' if source.state == 'purchase' else 'rfq') if self.purchase_order_id else 'requisition'
        self.method_id = self.env['erp.contract.guarantee.method'].search([('company_id', '=', self.company_id.id), ('default_for', '=', kind)], limit=1)

    @api.depends('move_ids.state', 'move_ids.amount_residual', 'move_ids.amount_total', 'document_return_date')
    def _compute_settlement(self):
        for guarantee in self:
            posted = guarantee.move_ids.filtered(lambda m: m.state == 'posted')
            received = posted.filtered(lambda m: m.erp_guarantee_direction == 'receive')
            returned = posted.filtered(lambda m: m.erp_guarantee_direction == 'return')
            guarantee.amount_received = sum(m.amount_total - m.amount_residual for m in received)
            guarantee.amount_returned = sum(m.amount_total - m.amount_residual for m in returned)
            terms = returned.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable')
            partials = terms.matched_debit_ids | terms.matched_credit_ids
            payments = (partials.debit_move_id | partials.credit_move_id).move_id.origin_payment_id
            guarantee.date_return = max(payments.mapped('date'), default=False) if guarantee.type_id.is_create_invoice else guarantee.document_return_date

    @api.constrains('purchase_order_id', 'requisition_id', 'company_id', 'organization_id', 'partner_id', 'method_id', 'amount')
    def _check_identity(self):
        for guarantee in self:
            if bool(guarantee.purchase_order_id) == bool(guarantee.requisition_id):
                raise ValidationError(_('Choose exactly one RFQ/PO or purchase agreement.'))
            source = guarantee.purchase_order_id or guarantee.requisition_id
            source.check_access('read')
            unit = source.erp_request_organization_id if guarantee.purchase_order_id else source.erp_organization_id
            if source.company_id != guarantee.company_id or unit != guarantee.organization_id or not unit.active:
                raise ValidationError(_('Guarantee and source must share an active organization and company.'))
            if guarantee.purchase_order_id and source.partner_id != guarantee.partner_id:
                raise ValidationError(_('Guarantee supplier must match the RFQ/PO.'))
            if not math.isfinite(guarantee.amount) or guarantee.amount <= 0:
                raise ValidationError(_('Guarantee amount must be positive.'))
            if guarantee.method_id.company_id != guarantee.company_id:
                raise ValidationError(_('Guarantee method must belong to the same company.'))

    @api.model_create_multi
    def create(self, vals_list):
        if any(key in self.env.context for key in ('default_lock_version', 'default_move_ids')):
            raise AccessError(_('Guarantee settlement defaults are internal.'))
        for vals in vals_list:
            if {'lock_version', 'move_ids', 'amount_received', 'amount_returned', 'date_return'} & vals.keys():
                raise AccessError(_('Guarantee settlement history is created through accounting actions.'))
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('erp.contract.guarantee') or 'New'
            po = self.env['purchase.order'].browse(vals.get('purchase_order_id', self.env.context.get('default_purchase_order_id'))).exists()
            requisition = self.env['purchase.requisition'].browse(vals.get('requisition_id', self.env.context.get('default_requisition_id'))).exists()
            source = po or requisition
            if source:
                source.check_access('read')
                vals.setdefault('company_id', source.company_id.id)
                vals.setdefault('organization_id', (po.erp_request_organization_id if po else requisition.erp_organization_id).id)
                if po:
                    vals.setdefault('partner_id', po.partner_id.id)
                kind = ('po' if po.state == 'purchase' else 'rfq') if po else 'requisition'
                if not vals.get('method_id'):
                    vals['method_id'] = self.env['erp.contract.guarantee.method'].search([('company_id', '=', source.company_id.id), ('default_for', '=', kind)], limit=1).id
                lines = po.order_line if po else requisition.line_ids
                funds = lines.erp_budget_fund_id if po else lines.erp_request_line_id.fund_id
                if len(funds) == 1:
                    vals.setdefault('fund_id', funds.id)
                distributions = lines.mapped('analytic_distribution')
                if distributions and all(distribution == distributions[0] for distribution in distributions):
                    vals.setdefault('analytic_distribution', distributions[0])
        records = super().create(vals_list)
        for guarantee in records:
            source = guarantee.purchase_order_id or guarantee.requisition_id
            allowed = ('draft', 'sent', 'purchase') if guarantee.purchase_order_id else ('confirmed',)
            if source.state not in allowed:
                raise ValidationError(_('The guarantee requires an eligible RFQ/PO or confirmed purchase agreement.'))
        return records

    def write(self, vals):
        self.check_access('write')
        if {'lock_version', 'move_ids', 'name', 'amount_received', 'amount_returned', 'date_return', 'currency_id'} & vals.keys():
            raise AccessError(_('Guarantee identity and settlement history are internal.'))
        self._lock_settlement()
        immutable = {'company_id', 'organization_id', 'purchase_order_id', 'requisition_id', 'partner_id', 'method_id', 'type_id', 'amount', 'analytic_distribution', 'fund_id'}
        if immutable & vals.keys() and any(g.move_ids for g in self):
            raise UserError(_('Financial guarantee history freezes its source, account, dimensions and face value.'))
        if vals.get('active') is False and any(g.currency_id.compare_amounts(g.amount_received, g.amount_returned) != 0 for g in self):
            raise UserError(_('Settle the outstanding guarantee before archiving it.'))
        return super().write(vals)

    def unlink(self):
        if any(g.move_ids for g in self):
            raise UserError(_('A guarantee with accounting history cannot be deleted.'))
        return super().unlink()

    def _lock_settlement(self):
        if self:
            self.check_access('read')
            ids = tuple(sorted(self.ids))
            self.env.cr.execute('SELECT id FROM erp_contract_guarantee WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
            self.env.cr.execute('UPDATE erp_contract_guarantee SET lock_version = COALESCE(lock_version, 0) + 1 WHERE id IN %s', [ids])
            self.invalidate_recordset()

    def _check_settlement(self):
        for guarantee in self:
            claims = guarantee.move_ids.filtered(lambda m: m.state != 'cancel')
            received_claim = sum(claims.filtered(lambda m: m.erp_guarantee_direction == 'receive').mapped('amount_total'))
            return_claim = sum(claims.filtered(lambda m: m.erp_guarantee_direction == 'return').mapped('amount_total'))
            for move in claims.filtered(lambda m: m.state == 'posted'):
                if move.currency_id.compare_amounts(move.amount_residual, 0) < 0 or move.currency_id.compare_amounts(move.amount_residual, move.amount_total) > 0:
                    raise ValidationError(_('Guarantee reconciliation cannot overpay or reverse the sign of a settlement.'))
            if guarantee.currency_id.compare_amounts(received_claim, guarantee.amount) > 0:
                raise ValidationError(_('Guarantee receipt documents cannot exceed its face value.'))
            if guarantee.currency_id.compare_amounts(return_claim, guarantee.amount_received) > 0:
                raise ValidationError(_('Guarantee returns cannot exceed the amount actually received.'))

    def _create_document(self, direction):
        self.ensure_one()
        self.check_access('write')
        self._lock_settlement()
        self._check_identity()
        if not self.active or not self.type_id.is_create_invoice:
            raise UserError(_('Only active accounting-backed guarantees create settlement documents.'))
        existing = self.move_ids.filtered(lambda m: m.erp_guarantee_direction == direction and m.state == 'draft')[:1]
        if existing:
            return existing
        claimed = sum(self.move_ids.filtered(lambda m: m.erp_guarantee_direction == direction and m.state != 'cancel').mapped('amount_total'))
        amount = self.currency_id.round((self.amount if direction == 'receive' else self.amount_received) - claimed)
        if amount <= 0:
            raise UserError(_('No unclaimed amount remains for this guarantee settlement.'))
        journal = self.env['account.journal'].search([('company_id', '=', self.company_id.id), ('type', '=', 'sale' if direction == 'receive' else 'purchase')], limit=1)
        if not journal:
            raise ValidationError(_('Configure the company sales/purchase journal for guarantee settlement.'))
        token = _guarantee_workflow.set(True)
        try:
            with self.env.cr.savepoint():
                move = self.env['account.move'].with_company(self.company_id).create({
                    'move_type': 'out_invoice' if direction == 'receive' else 'in_invoice', 'company_id': self.company_id.id,
                    'partner_id': self.partner_id.id, 'currency_id': self.currency_id.id, 'journal_id': journal.id,
                    'invoice_date': self.date_guarantee_receive if direction == 'receive' else fields.Date.context_today(self),
                    'erp_guarantee_id': self.id, 'erp_guarantee_direction': direction,
                    'invoice_line_ids': [(0, 0, {'name': self.name + ': ' + self.method_id.name, 'account_id': self.method_id.account_id.id,
                                               'quantity': 1, 'price_unit': amount, 'tax_ids': [(5, 0, 0)], 'analytic_distribution': self.analytic_distribution})]})
                self._check_settlement()
                return move
        finally:
            _guarantee_workflow.reset(token)

    def action_create_receipt(self):
        move = self._create_document('receive')
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form'}

    def action_create_return(self):
        move = self._create_document('return')
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form'}


def _guarantee_access(uid):
    return Domain('organization_id.active', '=', True) & Domain('organization_id.assignment_ids.user_id', '=', uid)


def _guarantee_move_access(uid):
    invalid = Domain('erp_guarantee_id', 'any!', ~_guarantee_access(uid))
    return ~invalid & Domain('origin_payment_id', 'not any!', Domain('invoice_ids', 'any!', invalid))


class GuaranteeMove(models.Model):
    _inherit = 'account.move'

    erp_guarantee_id = fields.Many2one('erp.contract.guarantee', readonly=True, check_company=True, ondelete='restrict', copy=False, index=True)
    erp_guarantee_direction = fields.Selection([('receive', 'Receive Guarantee'), ('return', 'Return Guarantee')], readonly=True, copy=False)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & _guarantee_move_access(self.env.uid)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'erp_guarantee_id', 'erp_guarantee_direction'}
        if not _guarantee_workflow.get() and (any(protected & vals.keys() for vals in vals_list) or any('default_' + name in self.env.context for name in protected)):
            raise AccessError(_('Create guarantee documents through the guarantee actions.'))
        records = super().create(vals_list)
        records._check_guarantee_document()
        return records

    def _check_guarantee_document(self):
        for move in self.filtered('erp_guarantee_id'):
            guarantee = move.erp_guarantee_id
            if move.company_id != guarantee.company_id or move.currency_id != guarantee.currency_id or move.partner_id != guarantee.partner_id:
                raise ValidationError(_('Guarantee document company, currency and supplier must match its source.'))
            expected = 'out_invoice' if move.erp_guarantee_direction == 'receive' else 'in_invoice'
            lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
            if move.move_type != expected or not lines or any(l.account_id != guarantee.method_id.account_id or l.tax_ids or l.quantity <= 0 or l.price_subtotal <= 0 for l in lines):
                raise ValidationError(_('Guarantee settlement requires positive untaxed lines on its configured account.'))
            if any(l.purchase_line_id or l.expense_id or l.erp_contract_line_id or l.erp_budget_period_id for l in lines):
                raise ValidationError(_('Guarantee settlement must not consume a purchase/contract/expense budget again.'))

    def _post(self, soft=True):
        guarantees = self.erp_guarantee_id
        guarantees._lock_settlement()
        self._check_guarantee_document()
        token = _guarantee_workflow.set(True)
        try:
            with self.env.cr.savepoint():
                result = super()._post(soft=soft)
                guarantees._check_settlement()
                return result
        finally:
            _guarantee_workflow.reset(token)

    def _guarantee_reset(self, method):
        guarantees = self.erp_guarantee_id | self.origin_payment_id.invoice_ids.erp_guarantee_id
        guarantees._lock_settlement()
        token = _guarantee_workflow.set(True)
        try:
            with self.env.cr.savepoint():
                if guarantees:
                    self.line_ids.remove_move_reconcile()
                result = method()
                guarantees.invalidate_recordset()
                guarantees._check_settlement()
                return result
        finally:
            _guarantee_workflow.reset(token)

    def button_draft(self):
        return self._guarantee_reset(super().button_draft)

    def button_cancel(self):
        return self._guarantee_reset(super().button_cancel)

    def _reverse_moves(self, default_values_list=None, cancel=False):
        if self.erp_guarantee_id:
            raise UserError(_('Reset/cancel the guarantee settlement document so its received and return claims stay reconciled.'))
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    def write(self, vals):
        protected = {'erp_guarantee_id', 'erp_guarantee_direction'}
        financial = protected | {'state', 'partner_id', 'company_id', 'currency_id', 'move_type', 'journal_id', 'invoice_line_ids', 'line_ids', 'reversed_entry_id'}
        if not _guarantee_workflow.get() and (protected & vals.keys() or financial & vals.keys() and self.erp_guarantee_id):
            raise AccessError(_('Use guarantee accounting actions; its financial source and lines are protected.'))
        return super().write(vals)

    def unlink(self):
        if self.erp_guarantee_id:
            raise UserError(_('Cancel guarantee documents to preserve their financial history.'))
        return super().unlink()


class GuaranteeMoveLine(models.Model):
    _inherit = 'account.move.line'

    erp_guarantee_fund_id = fields.Many2one(related='move_id.erp_guarantee_id.fund_id', readonly=True)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_id', 'any!', _guarantee_move_access(self.env.uid))

    @api.model_create_multi
    def create(self, vals_list):
        move_ids = [v.get('move_id', self.env.context.get('default_move_id')) for v in vals_list]
        if not _guarantee_workflow.get() and self.env['account.move'].browse([i for i in move_ids if i]).erp_guarantee_id:
            raise AccessError(_('Guarantee journal lines are generated by the settlement action.'))
        return super().create(vals_list)

    def write(self, vals):
        economic = {'move_id', 'account_id', 'partner_id', 'balance', 'debit', 'credit', 'amount_currency', 'currency_id', 'company_id', 'product_id', 'display_type', 'tax_line_id', 'quantity', 'price_unit', 'discount', 'tax_ids', 'analytic_distribution', 'purchase_line_id', 'expense_id', 'erp_contract_line_id', 'erp_budget_period_id', 'erp_budget_organization_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_direct_activity_id', 'erp_budget_dimension_ids', 'erp_guarantee_fund_id'}
        moves = self.move_id | self.env['account.move'].browse(vals.get('move_id')).exists()
        if not _guarantee_workflow.get() and economic & vals.keys() and moves.erp_guarantee_id:
            raise AccessError(_('Guarantee journal line values and dimensions are protected.'))
        return super().write(vals)

    def unlink(self):
        if self.move_id.erp_guarantee_id and not _guarantee_workflow.get():
            raise AccessError(_('Guarantee journal lines are retained with their settlement document.'))
        return super().unlink()


class GuaranteePartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model
    def _access_domain(self, operation):
        valid = Domain('move_id', 'any!', _guarantee_move_access(self.env.uid))
        return super()._access_domain(operation) & Domain('debit_move_id', 'any!', valid) & Domain('credit_move_id', 'any!', valid)

    @api.model_create_multi
    def create(self, vals_list):
        lines = self.env['account.move.line'].browse([v[name] for v in vals_list for name in ('debit_move_id', 'credit_move_id') if v.get(name)])
        guarantees = lines.move_id.erp_guarantee_id
        guarantees._lock_settlement()
        for vals in vals_list:
            debit = self.env['account.move.line'].browse(vals.get('debit_move_id')).exists()
            credit = self.env['account.move.line'].browse(vals.get('credit_move_id')).exists()
            if (debit | credit).move_id.erp_guarantee_id:
                if debit.company_id != credit.company_id or debit.account_id != credit.account_id or any(l.parent_state != 'posted' for l in debit | credit):
                    raise ValidationError(_('Guarantee reconciliation requires posted lines on the same company account.'))
                for name in ('amount', 'debit_amount_currency', 'credit_amount_currency'):
                    value = vals.get(name, 0)
                    if not math.isfinite(value) or value < 0:
                        raise ValidationError(_('Guarantee reconciliation amounts must be finite and nonnegative.'))
                currency = debit.company_currency_id
                if currency.compare_amounts(vals.get('amount', 0), min(debit.amount_residual, -credit.amount_residual)) > 0:
                    raise ValidationError(_('Guarantee reconciliation exceeds the available journal balance.'))
        with self.env.cr.savepoint():
            result = super().create(vals_list)
            guarantees.invalidate_recordset()
            guarantees._check_settlement()
            return result

    def write(self, vals):
        endpoints = self.debit_move_id | self.credit_move_id | self.env['account.move.line'].browse([vals[key] for key in ('debit_move_id', 'credit_move_id') if vals.get(key)])
        if endpoints.move_id.erp_guarantee_id and {'amount', 'debit_amount_currency', 'credit_amount_currency', 'debit_move_id', 'credit_move_id', 'company_id', 'debit_currency_id', 'credit_currency_id'} & vals.keys():
            raise AccessError(_('Unreconcile and reconcile guarantee payments instead of rewriting their history.'))
        return super().write(vals)

    def unlink(self):
        guarantees = (self.debit_move_id | self.credit_move_id).move_id.erp_guarantee_id
        guarantees._lock_settlement()
        with self.env.cr.savepoint():
            result = super().unlink()
            guarantees.invalidate_recordset()
            guarantees._check_settlement()
            return result


class GuaranteePayment(models.Model):
    _inherit = 'account.payment'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('invoice_ids', 'not any!', Domain('erp_guarantee_id', 'any!', ~_guarantee_access(self.env.uid)))


class GuaranteeFullReconcile(models.Model):
    _inherit = 'account.full.reconcile'

    @api.model
    def _access_domain(self, operation):
        invalid = Domain('move_id', 'not any!', _guarantee_move_access(self.env.uid))
        return super()._access_domain(operation) & Domain('reconciled_line_ids', 'not any!', invalid)
