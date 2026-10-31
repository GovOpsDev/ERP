"""Source WA late-delivery fines: native accounting, explicitly outside Budget."""
import math
from contextvars import ContextVar
from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.exceptions import AccessError, UserError, ValidationError

_fine = ContextVar('erp_acceptance_fine', default=False)
_PROVENANCE = {'erp_late_acceptance_id', 'erp_fine_account_id'}


def _fine_move_access(uid):
    allowed = Domain('organization_id.active', '=', True) & Domain('organization_id.assignment_ids.user_id', '=', uid)
    invalid = Domain('erp_late_acceptance_id', 'any!', ~allowed)
    return ~invalid & Domain('origin_payment_id', 'not any!', Domain('invoice_ids', 'any!', invalid))


class FineCompany(models.Model):
    _inherit = 'res.company'
    erp_wa_fines_rate = fields.Monetary(string='Acceptance fines per day')
    erp_wa_fines_account_id = fields.Many2one('account.account', check_company=True, string='Acceptance fines revenue account')

    @api.constrains('erp_wa_fines_rate', 'erp_wa_fines_account_id')
    def _check_fine_configuration(self):
        for company in self:
            if not math.isfinite(company.erp_wa_fines_rate) or company.erp_wa_fines_rate < 0:
                raise ValidationError(_('Fine rates must be finite and nonnegative.'))
            account = company.erp_wa_fines_account_id
            if account and (company not in account.company_ids or account.account_type not in ('income', 'income_other')):
                raise ValidationError(_('Select a revenue account in this company.'))


class FineAcceptance(models.Model):
    _inherit = 'erp.inventory.acceptance'
    currency_id = fields.Many2one(related='purchase_order_id.currency_id')
    date_due = fields.Date()
    date_receive = fields.Date(default=fields.Date.context_today)
    late_days = fields.Integer()
    fines_rate = fields.Monetary()
    fines_late = fields.Monetary(string='Late delivery fine')
    fines_invoice_ids = fields.One2many('account.move', 'erp_late_acceptance_id', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            po = self.env['purchase.order'].browse(vals.get('purchase_order_id'))
            if po:
                # Like the source: a document-currency rate, explicitly overridable.
                vals.setdefault('fines_rate', po.company_id.erp_wa_fines_rate)
        return super().create(vals_list)

    @api.onchange('date_due', 'date_receive')
    def _onchange_late_days(self):
        self.late_days = max((self.date_receive - self.date_due).days, 0) if self.date_receive and self.date_due else 0

    @api.onchange('late_days', 'fines_rate')
    def _onchange_fines_late(self):
        self.fines_late = self.late_days * self.fines_rate

    @api.constrains('late_days', 'fines_rate', 'fines_late')
    def _check_fine_amounts(self):
        for record in self:
            if any(not math.isfinite(value) or value < 0 for value in (record.late_days, record.fines_rate, record.fines_late)):
                raise ValidationError(_('Late days, daily rate and fine must be finite and nonnegative.'))

    def write(self, vals):
        if {'late_days', 'fines_rate', 'fines_late', 'date_due', 'date_receive'} & vals.keys() and self.sudo().fines_invoice_ids:
            raise UserError(_('Fine terms with accounting history are immutable.'))
        return super().write(vals)

    def action_create_vendor_fine(self):
        return self.action_create_fines_invoice(move_type='in_refund')

    def action_create_fines_invoice(self, move_type='out_invoice'):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_inventory.group_acceptance_manager'):
            raise AccessError(_('Acceptance management is required to charge a fine.'))
        if move_type not in ('out_invoice', 'in_refund'):
            raise ValidationError(_('Choose a customer invoice or supplier credit note.'))
        with self.env.cr.savepoint():
            self.purchase_order_id._lock_request_scope()
            self.invalidate_recordset()
            if self.state != 'accept' or self.fines_late <= 0:
                raise UserError(_('Accept the work with a positive fine before creating its charge.'))
            existing = self.fines_invoice_ids.filtered(lambda m: not m.reversed_entry_id and m.state != 'cancel')
            if existing:
                existing.check_access('read')
                return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'view_mode': 'form', 'res_id': existing.id}
            account = self.company_id.erp_wa_fines_account_id
            if not account:
                raise UserError(_('Configure the acceptance fines revenue account.'))
            journal = self.env['account.journal'].search([('company_id', '=', self.company_id.id), ('type', '=', 'sale' if move_type == 'out_invoice' else 'purchase')], limit=1)
            if not journal:
                raise UserError(_('Configure a sales or purchase journal for this fine.'))
            token = _fine.set(True)
            try:
                move = self.env['account.move'].with_company(self.company_id).create({'move_type': move_type, 'company_id': self.company_id.id, 'currency_id': self.currency_id.id, 'partner_id': self.partner_id.id, 'journal_id': journal.id, 'invoice_date': fields.Date.context_today(self), 'erp_late_acceptance_id': self.id, 'erp_fine_account_id': account.id, 'erp_budget_exempt': True, 'invoice_line_ids': [(0, 0, {'name': _('Late delivery fine: %s', self.name), 'account_id': account.id, 'quantity': 1, 'price_unit': self.fines_late, 'tax_ids': [(5, 0, 0)]})]})
            finally:
                _fine.reset(token)
            return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'view_mode': 'form', 'res_id': move.id}


class FineMove(models.Model):
    _inherit = 'account.move'
    erp_late_acceptance_id = fields.Many2one('erp.inventory.acceptance', check_company=True, readonly=True, copy=False, ondelete='restrict', index=True)
    erp_fine_account_id = fields.Many2one('account.account', check_company=True, readonly=True, copy=False, ondelete='restrict')

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & _fine_move_access(self.env.uid)

    def _check_budget_exemption_value(self, journal, value):
        if _fine.get() and value is True:
            return
        return super()._check_budget_exemption_value(journal, value)

    @api.model_create_multi
    def create(self, vals_list):
        if not _fine.get() and (any(_PROVENANCE & v.keys() for v in vals_list) or any('default_' + n in self.env.context for n in _PROVENANCE)):
            raise AccessError(_('Fine provenance is created through the acceptance action.'))
        return super().create(vals_list)

    def write(self, vals):
        if _PROVENANCE & vals.keys():
            raise AccessError(_('Fine provenance is immutable.'))
        if self.erp_late_acceptance_id:
            self.erp_late_acceptance_id.purchase_order_id._lock_request_scope()
            if {'company_id', 'partner_id', 'currency_id', 'move_type', 'erp_budget_exempt', 'reversed_entry_id'} & vals.keys():
                for move in self.filtered('erp_late_acceptance_id'):
                    for key in vals.keys() & {'company_id', 'partner_id', 'currency_id', 'move_type', 'erp_budget_exempt', 'reversed_entry_id'}:
                        if (move[key].id if move._fields[key].type == 'many2one' else move[key]) != vals[key]:
                            raise UserError(_('The fine identity and Budget exemption cannot change.'))
            if vals.get('state') in ('draft', 'cancel'):
                if self.sudo().search_count([('reversed_entry_id', 'in', self.ids), ('state', '=', 'posted')]):
                    raise UserError(_('Reverse the fine credits before resetting their original charge.'))
        return super().write(vals)

    def unlink(self):
        if self.erp_late_acceptance_id:
            raise UserError(_('Cancel fine documents instead of deleting accounting provenance.'))
        return super().unlink()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        defaults = [dict(v) for v in (default_values_list or [{} for m in self])]
        for move, values in zip(self, defaults):
            if move.erp_late_acceptance_id:
                values.update(erp_late_acceptance_id=move.erp_late_acceptance_id.id, erp_fine_account_id=move.erp_fine_account_id.id, erp_budget_exempt=True)
        token = _fine.set(True)
        try:
            return super()._reverse_moves(default_values_list=defaults, cancel=cancel)
        finally:
            _fine.reset(token)

    def _post(self, soft=True):
        fines = self.filtered('erp_late_acceptance_id')
        if fines:
            fines.erp_late_acceptance_id.check_access('read')
            fines.erp_late_acceptance_id.purchase_order_id._lock_request_scope()
        with self.env.cr.savepoint():
            for move in fines:
                wa = move.erp_late_acceptance_id
                lines = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
                if wa.state != 'accept' or not move.erp_budget_exempt or move.company_id != wa.company_id or move.currency_id != wa.currency_id or move.partner_id != wa.partner_id or len(lines) != 1:
                    raise ValidationError(_('The charge must retain its accepted work, company, vendor, currency and Budget exemption.'))
                line = lines[0]
                if line.account_id != move.erp_fine_account_id or line.tax_ids or line.purchase_line_id or line.erp_budget_period_id or line.erp_budget_fund_id or line.erp_budget_analytic_id or line.erp_budget_dimension_ids or ('erp_contract_line_id' in line._fields and line.erp_contract_line_id) or line.quantity <= 0 or line.price_unit < 0:
                    raise ValidationError(_('A fine uses its original revenue account without purchase, contract, tax or Budget dimensions.'))
                original = move.reversed_entry_id
                if original:
                    if original.state != 'posted' or original.reversed_entry_id or original.erp_late_acceptance_id != wa or original.erp_fine_account_id != move.erp_fine_account_id or move.move_type != {'out_invoice': 'out_refund', 'in_refund': 'in_invoice'}.get(original.move_type):
                        raise ValidationError(_('Reverse a posted original fine through native credit notes.'))
                    other = self.sudo().search([('reversed_entry_id', '=', original.id), ('state', '=', 'posted'), ('id', '!=', move.id)])
                    if move.currency_id.compare_amounts(sum(other.mapped('amount_total')) + move.amount_total, original.amount_total) > 0:
                        raise ValidationError(_('Fine reversals cannot exceed their original charge.'))
                elif move.move_type not in ('out_invoice', 'in_refund') or move.currency_id.compare_amounts(move.amount_total, wa.fines_late):
                    raise ValidationError(_('The original charge must equal the accepted fine amount.'))
                elif self.sudo().search_count([('erp_late_acceptance_id', '=', wa.id), ('reversed_entry_id', '=', False), ('state', '!=', 'cancel'), ('id', '!=', move.id)]):
                    raise ValidationError(_('Only one live original fine charge is allowed.'))
            return super()._post(soft=soft)


class FineMoveLine(models.Model):
    _inherit = 'account.move.line'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_id', 'any!', _fine_move_access(self.env.uid))


class FinePayment(models.Model):
    _inherit = 'account.payment'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('invoice_ids', 'not any!', ~_fine_move_access(self.env.uid))


class FinePartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'
    @api.model
    def _access_domain(self, operation):
        valid = _fine_move_access(self.env.uid)
        return super()._access_domain(operation) & Domain('debit_move_id.move_id', 'any!', valid) & Domain('credit_move_id.move_id', 'any!', valid)


class FineFullReconcile(models.Model):
    _inherit = 'account.full.reconcile'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('reconciled_line_ids', 'not any!', Domain('move_id', 'not any!', _fine_move_access(self.env.uid)))
