"""Payment retention: native write-off liability and reconciled release bills.

The source expense/commitment is booked once on the original invoice. Retention
moves payable/receivable timing only, and never creates a second budget actual.
"""
import math
from contextvars import ContextVar
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

_retention_workflow = ContextVar('erp_retention_workflow', default=False)


def _retention_access(uid):
    return Domain('organization_id', '=', False) | (Domain('organization_id.active', '=', True) & Domain('organization_id.assignment_ids.user_id', '=', uid))


def _move_access(uid):
    invalid = ~_retention_access(uid)
    return Domain('erp_retention_release_id', 'not any!', invalid) & Domain('origin_payment_id', 'not any!', Domain('erp_retention_ids', 'any!', invalid))


class RetentionCompany(models.Model):
    _inherit = 'res.company'
    erp_retention_payable_account_id = fields.Many2one('account.account', check_company=True)
    erp_retention_receivable_account_id = fields.Many2one('account.account', check_company=True)

    @api.constrains('erp_retention_payable_account_id', 'erp_retention_receivable_account_id')
    def _check_retention_accounts(self):
        for company in self:
            for account in company.erp_retention_payable_account_id | company.erp_retention_receivable_account_id:
                if company not in account.company_ids or not account.reconcile or account.account_type in ('asset_receivable', 'liability_payable', 'off_balance'):
                    raise ValidationError(_('Retention requires a separate reconcilable account in the company.'))


class Retention(models.Model):
    _name = 'erp.finance.retention'
    _description = 'Payment Retention History'
    _check_company_auto = True
    _rec_name = 'source_move_id'

    source_move_id = fields.Many2one('account.move', required=True, check_company=True, ondelete='restrict')
    payment_id = fields.Many2one('account.payment', required=True, check_company=True, ondelete='restrict')
    payment_line_id = fields.Many2one('account.move.line', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one('res.company', required=True, ondelete='restrict')
    organization_id = fields.Many2one('erp.organization.unit', check_company=True, ondelete='restrict')
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(required=True)
    release_ids = fields.One2many('account.move', 'erp_retention_release_id', readonly=True)
    amount_remaining = fields.Monetary(compute='_compute_remaining')
    lock_version = fields.Integer(readonly=True)
    _payment_line_unique = models.Constraint('unique(payment_line_id)', 'Retention history already exists for this payment line.')

    @api.depends('payment_line_id.amount_residual', 'payment_line_id.parent_state')
    def _compute_remaining(self):
        for record in self:
            record.amount_remaining = abs(record.payment_line_id.amount_residual) if record.payment_line_id.parent_state == 'posted' else 0

    @api.model_create_multi
    def create(self, vals_list):
        if not _retention_workflow.get():
            raise AccessError(_('Retention history is generated from the payment register.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Retention financial history is immutable.'))

    def unlink(self):
        raise AccessError(_('Cancel accounting documents while retaining the retention history.'))

    def _lock_retention(self):
        if self:
            self.check_access('read')
            self.env.cr.execute('SELECT id FROM erp_finance_retention WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE erp_finance_retention SET lock_version=COALESCE(lock_version,0)+1 WHERE id IN %s', [tuple(self.ids)])
            self.invalidate_recordset()

    def _check_backing(self):
        for record in self:
            live = record.release_ids.filtered(lambda m: m.state != 'cancel')
            if not live:
                continue
            payment_lines = record.payment_id.move_id.line_ids
            partials = payment_lines.matched_debit_ids | payment_lines.matched_credit_ids
            linked = (partials.debit_move_id | partials.credit_move_id).move_id
            if record.payment_line_id.parent_state != 'posted' or record.source_move_id.state != 'posted' or record.source_move_id not in linked:
                raise ValidationError(_('Cancel retention releases before removing their source payment or reconciliation.'))
            if record.currency_id.compare_amounts(sum(live.mapped('amount_total')), record.amount) > 0:
                raise ValidationError(_('Retention releases cannot exceed the retained payment.'))

    def action_release(self):
        self.ensure_one()
        self.check_access('write')
        self.source_move_id.check_access('read')
        self._lock_retention()
        existing = self.release_ids.filtered(lambda m: m.state != 'cancel')[:1]
        if existing:
            return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': existing.id, 'view_mode': 'form'}
        if self.payment_line_id.parent_state != 'posted' or self.currency_id.is_zero(self.amount_remaining):
            raise UserError(_('No posted retained balance is available to release.'))
        token = _retention_workflow.set(True)
        try:
            with self.env.cr.savepoint():
                source = self.source_move_id
                move = self.env['account.move'].with_company(self.company_id).create({
                    'move_type': source.move_type, 'company_id': self.company_id.id, 'partner_id': source.partner_id.id,
                    'journal_id': source.journal_id.id, 'currency_id': self.currency_id.id, 'invoice_date': fields.Date.context_today(self),
                    'erp_retention_release_id': self.id,
                    'invoice_line_ids': [(0, 0, {'name': _('Retention release: %s', source.name), 'account_id': self.payment_line_id.account_id.id,
                                               'quantity': 1, 'price_unit': self.amount_remaining, 'tax_ids': [(5, 0, 0)]})]})
                self._check_backing()
                return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form'}
        finally:
            _retention_workflow.reset(token)


class RetentionMove(models.Model):
    _inherit = 'account.move'
    erp_payment_retention = fields.Selection([('percent', 'Percent'), ('amount', 'Amount')], copy=False)
    erp_retention_method = fields.Selection([('untax', 'Untaxed amount'), ('total', 'Total')], default='untax')
    erp_retention_value = fields.Float(copy=False)
    erp_retention_amount = fields.Monetary(compute='_compute_retention_amount')
    erp_retention_ids = fields.One2many('erp.finance.retention', 'source_move_id', readonly=True)
    erp_retention_release_id = fields.Many2one('erp.finance.retention', readonly=True, copy=False, check_company=True, ondelete='restrict')
    erp_retention_lock_version = fields.Integer(readonly=True, copy=False)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & _move_access(self.env.uid)

    @api.depends('erp_payment_retention', 'erp_retention_method', 'erp_retention_value', 'invoice_line_ids.price_subtotal', 'invoice_line_ids.price_total')
    def _compute_retention_amount(self):
        for move in self:
            base = sum(move.invoice_line_ids.filtered(lambda l: l.quantity > 0).mapped('price_total' if move.erp_retention_method == 'total' else 'price_subtotal'))
            move.erp_retention_amount = move.currency_id.round(move.erp_retention_value if move.erp_payment_retention == 'amount' else base * move.erp_retention_value / 100 if move.erp_payment_retention == 'percent' else 0)

    @api.constrains('erp_payment_retention', 'erp_retention_value', 'invoice_line_ids')
    def _check_retention_suggestion(self):
        for move in self.filtered('erp_payment_retention'):
            if move.move_type not in ('in_invoice', 'out_invoice') or not math.isfinite(move.erp_retention_value) or move.erp_retention_value < 0 or move.currency_id.compare_amounts(move.erp_retention_amount, sum(move.invoice_line_ids.mapped('price_subtotal'))) > 0 or move.erp_retention_release_id:
                raise ValidationError(_('Retention must be between zero and the untaxed original invoice amount.'))

    def _retention_unit(self):
        self.ensure_one()
        units = self.invoice_line_ids.purchase_line_id.order_id.erp_request_organization_id | self.invoice_line_ids.erp_budget_organization_id
        if 'erp_contract_line_id' in self.env['account.move.line']._fields:
            units |= self.invoice_line_ids.erp_contract_line_id.organization_id
        if len(units) > 1:
            raise ValidationError(_('Register retention separately for each organization.'))
        return units

    def _lock_retention_source(self):
        if self:
            self.check_access('read')
            self.env.cr.execute('SELECT id FROM account_move WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE account_move SET erp_retention_lock_version=COALESCE(erp_retention_lock_version,0)+1 WHERE id IN %s', [tuple(self.ids)])
            self.invalidate_recordset()

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'erp_retention_release_id', 'erp_retention_ids', 'erp_retention_lock_version'}
        if not _retention_workflow.get() and (any(protected & v.keys() for v in vals_list) or any('default_' + name in self.env.context for name in protected)):
            raise AccessError(_('Retention provenance is assigned by its accounting actions.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _retention_workflow.get():
            if {'erp_retention_release_id', 'erp_retention_ids', 'erp_retention_lock_version'} & vals.keys():
                raise AccessError(_('Retention provenance is immutable.'))
            if {'erp_payment_retention', 'erp_retention_value', 'erp_retention_method'} & vals.keys() and any(m.state != 'draft' or m.erp_retention_ids for m in self):
                raise UserError(_('Retention terms are fixed after posting/payment.'))
            if self.erp_retention_release_id and {'state', 'line_ids', 'invoice_line_ids', 'company_id', 'currency_id', 'partner_id', 'move_type', 'journal_id'} & vals.keys():
                raise AccessError(_('Use native posting/reset actions for retention release documents.'))
        return super().write(vals)

    def _post(self, soft=True):
        records = self.erp_retention_release_id
        records._lock_retention()
        token = _retention_workflow.set(True)
        try:
            with self.env.cr.savepoint():
                result = super()._post(soft=soft)
                for move in result.filtered('erp_retention_release_id'):
                    record = move.erp_retention_release_id
                    lines = move.line_ids.filtered(lambda l: l.account_id == record.payment_line_id.account_id)
                    (lines | record.payment_line_id).reconcile()
                records._check_backing()
                return result
        finally:
            _retention_workflow.reset(token)

    def _retention_reset(self, method):
        records = self.erp_retention_release_id | self.erp_retention_ids | self.origin_payment_id.erp_retention_ids
        records._lock_retention()
        token = _retention_workflow.set(True)
        try:
            with self.env.cr.savepoint():
                if records:
                    self.line_ids.remove_move_reconcile()
                result = method()
                records._check_backing()
                return result
        finally:
            _retention_workflow.reset(token)

    def button_draft(self):
        return self._retention_reset(super().button_draft)

    def button_cancel(self):
        return self._retention_reset(super().button_cancel)

    def _reverse_moves(self, default_values_list=None, cancel=False):
        if self.erp_retention_release_id or self.erp_retention_ids:
            raise UserError(_('Reset/cancel the retention documents first so their source balances remain auditable.'))
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    def unlink(self):
        if self.erp_retention_release_id or self.erp_retention_ids or self.origin_payment_id.erp_retention_ids:
            raise UserError(_('Retention accounting history must be retained.'))
        return super().unlink()


class RetentionLine(models.Model):
    _inherit = 'account.move.line'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_id', 'any!', _move_access(self.env.uid))

    @api.model_create_multi
    def create(self, vals_list):
        moves = self.env['account.move'].browse([v.get('move_id', self.env.context.get('default_move_id')) for v in vals_list if v.get('move_id', self.env.context.get('default_move_id'))])
        if moves.erp_retention_release_id and not _retention_workflow.get():
            raise AccessError(_('Retention release lines are generated by the release action.'))
        return super().create(vals_list)

    def write(self, vals):
        moves = self.move_id | self.env['account.move'].browse(vals.get('move_id')).exists()
        economic = {'move_id', 'account_id', 'partner_id', 'balance', 'debit', 'credit', 'amount_currency', 'currency_id', 'company_id', 'quantity', 'price_unit', 'discount', 'tax_ids', 'product_id', 'display_type', 'tax_line_id', 'analytic_distribution', 'purchase_line_id', 'expense_id', 'erp_contract_line_id', 'erp_budget_period_id', 'erp_budget_organization_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_direct_activity_id', 'erp_budget_dimension_ids'}
        retained = self.env['erp.finance.retention'].sudo().search_count([('payment_line_id', 'in', self.ids)]) if self else 0
        if (moves.erp_retention_release_id or retained) and economic & vals.keys() and not _retention_workflow.get():
            raise AccessError(_('Retention release amounts and sources are immutable.'))
        return super().write(vals)

    def unlink(self):
        if self.move_id.erp_retention_release_id and not _retention_workflow.get():
            raise AccessError(_('Retention release lines are retained with the document.'))
        return super().unlink()


class RetentionPayment(models.Model):
    _inherit = 'account.payment'

    def _get_outstanding_account(self, payment_type):
        if _retention_workflow.get() and self.withhold == 'withhold':
            # Native WH-only entries deliberately have no liquidity movement.
            return self.env['account.account']
        return super()._get_outstanding_account(payment_type)

    erp_retention_ids = fields.One2many('erp.finance.retention', 'payment_id', readonly=True)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('erp_retention_ids', 'not any!', ~_retention_access(self.env.uid))


class RetentionRegister(models.TransientModel):
    _inherit = 'account.payment.register'
    erp_apply_retention = fields.Boolean(string='Apply Retention')
    erp_enforce_retention = fields.Boolean(string='Enforce Suggested Retention', default=True)
    erp_retention_amount = fields.Monetary(compute='_compute_retention_amount')

    @api.depends('line_ids', 'currency_id', 'payment_date')
    def _compute_retention_amount(self):
        for wizard in self:
            wizard.erp_retention_amount = sum(m.currency_id._convert(m.erp_retention_amount, wizard.currency_id, m.company_id, wizard.payment_date) for m in wizard.line_ids.move_id if not m.erp_retention_ids.filtered(lambda r: r.payment_line_id.parent_state == 'posted')) if wizard.currency_id else 0

    def _create_payment_vals_from_wizard(self, batch_result):
        vals = super()._create_payment_vals_from_wizard(batch_result)
        if self.erp_apply_retention and _retention_workflow.get():
            invoice = self.line_ids.move_id
            amount = self.erp_retention_amount * (-1 if self.payment_type == 'outbound' else 1)
            vals['amount'] = invoice.currency_id._convert(invoice.amount_residual, self.currency_id, invoice.company_id, self.payment_date) - self.erp_retention_amount
            vals['write_off_line_vals'] = [{'name': _('Payment retention'), 'account_id': self.writeoff_account_id.id,
                                           'partner_id': self.partner_id.commercial_partner_id.id, 'currency_id': self.currency_id.id,
                                           'amount_currency': amount, 'balance': self.currency_id._convert(amount, self.company_id.currency_id, self.company_id, self.payment_date)}]
        return vals

    def _create_payments(self):
        self.ensure_one()
        invoices = self.line_ids.move_id
        retained = invoices.filtered('erp_payment_retention')
        if not retained:
            return super()._create_payments()
        if len(invoices) != 1:
            raise UserError(_('Register retained invoices separately.'))
        invoices._lock_retention_source()
        self.invalidate_recordset(['erp_retention_amount'])
        if not self.erp_apply_retention:
            if self.erp_enforce_retention and not self.currency_id.is_zero(self.erp_retention_amount):
                raise UserError(_('Apply the suggested retention or explicitly disable its enforcement.'))
            return super()._create_payments()
        invoice = invoices
        account = invoice.company_id.erp_retention_payable_account_id if invoice.move_type == 'in_invoice' else invoice.company_id.erp_retention_receivable_account_id
        invoice.company_id._check_retention_accounts()
        if not account or not self.erp_retention_amount or self.erp_retention_amount > invoice.currency_id._convert(invoice.amount_residual, self.currency_id, invoice.company_id, self.payment_date):
            raise ValidationError(_('Configure a retention account and a positive retention within the remaining payment.'))
        token = _retention_workflow.set(True)
        try:
            with self.env.cr.savepoint():
                withholding_payments = self.env['account.payment']
                if self.withhold == 'withhold_pay' and self.withholding_line_ids:
                    journal = self.env['account.journal'].search([('company_id', '=', invoice.company_id.id), ('type', '=', 'general')], limit=1)
                    if not journal:
                        raise ValidationError(_('Configure a general journal for native withholding-only settlement.'))
                    withholding_wizard = self.with_context(active_model='account.move', active_ids=invoice.ids).create({
                        'withhold': 'withhold', 'journal_id': journal.id, 'payment_date': self.payment_date,
                        'currency_id': self.currency_id.id, 'erp_enforce_retention': False})
                    withholding_payments = withholding_wizard._create_payments()
                    invoice.invalidate_recordset()
                    self.withhold = 'payment'
                self.write({'group_payment': True, 'amount': invoice.currency_id._convert(invoice.amount_residual, self.currency_id, invoice.company_id, self.payment_date) - self.erp_retention_amount,
                            'payment_difference_handling': 'reconcile', 'writeoff_account_id': account.id, 'writeoff_label': _('Payment retention')})
                payments = super()._create_payments()
                lines = payments.move_id.line_ids.filtered(lambda l: l.account_id == account)
                if len(lines) != 1 or lines.parent_state != 'posted':
                    raise ValidationError(_('The native payment must post one retained balance.'))
                self.env['erp.finance.retention'].create({'source_move_id': invoice.id, 'payment_id': payments.id, 'payment_line_id': lines.id, 'company_id': invoice.company_id.id, 'organization_id': invoice._retention_unit().id, 'amount': abs(lines.balance)})
                return withholding_payments | payments
        finally:
            _retention_workflow.reset(token)


class RetentionPartial(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model
    def _access_domain(self, operation):
        valid = Domain('move_id', 'any!', _move_access(self.env.uid))
        return super()._access_domain(operation) & Domain('debit_move_id', 'any!', valid) & Domain('credit_move_id', 'any!', valid)

    def _retention_records(self):
        moves = (self.debit_move_id | self.credit_move_id).move_id
        return moves.erp_retention_ids | moves.erp_retention_release_id | moves.origin_payment_id.erp_retention_ids

    @api.model_create_multi
    def create(self, vals_list):
        line_model = self.env['account.move.line']
        lines = line_model.browse([v[name] for v in vals_list for name in ('debit_move_id', 'credit_move_id') if v.get(name)])
        moves = lines.move_id
        records = moves.erp_retention_ids | moves.erp_retention_release_id | moves.origin_payment_id.erp_retention_ids
        records._lock_retention()
        for vals in vals_list:
            debit, credit = line_model.browse(vals.get('debit_move_id')), line_model.browse(vals.get('credit_move_id'))
            involved = (debit | credit).move_id
            if not (involved.erp_retention_ids or involved.erp_retention_release_id or involved.origin_payment_id.erp_retention_ids):
                continue
            if debit.company_id != credit.company_id or debit.account_id != credit.account_id or any(l.parent_state != 'posted' for l in debit | credit):
                raise ValidationError(_('Retention reconciliation requires posted lines on the same company account.'))
            for name in ('amount', 'debit_amount_currency', 'credit_amount_currency'):
                if not math.isfinite(vals.get(name, 0)) or vals.get(name, 0) < 0:
                    raise ValidationError(_('Retention reconciliation amounts must be finite and nonnegative.'))
            if debit.company_currency_id.compare_amounts(vals.get('amount', 0), min(debit.amount_residual, -credit.amount_residual)) > 0:
                raise ValidationError(_('Retention reconciliation exceeds the available journal balance.'))
            if debit.currency_id.compare_amounts(vals.get('debit_amount_currency', 0), debit.amount_residual_currency) > 0 or credit.currency_id.compare_amounts(vals.get('credit_amount_currency', 0), -credit.amount_residual_currency) > 0:
                raise ValidationError(_('Retention reconciliation exceeds the available currency balance.'))
        return super().create(vals_list)

    def write(self, vals):
        endpoints = self.env['account.move.line'].browse([vals[key] for key in ('debit_move_id', 'credit_move_id') if vals.get(key)]).move_id
        involved = self._retention_records() | endpoints.erp_retention_ids | endpoints.erp_retention_release_id | endpoints.origin_payment_id.erp_retention_ids
        if {'amount', 'debit_amount_currency', 'credit_amount_currency', 'debit_move_id', 'credit_move_id', 'company_id', 'debit_currency_id', 'credit_currency_id'} & vals.keys() and involved:
            raise AccessError(_('Unreconcile retention payments instead of rewriting history.'))
        return super().write(vals)

    def unlink(self):
        records = self._retention_records()
        records._lock_retention()
        with self.env.cr.savepoint():
            result = super().unlink()
            if not _retention_workflow.get():
                records._check_backing()
            return result


class RetentionFull(models.Model):
    _inherit = 'account.full.reconcile'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('reconciled_line_ids', 'not any!', Domain('move_id', 'not any!', _move_access(self.env.uid)))
