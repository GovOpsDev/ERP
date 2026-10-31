from contextvars import ContextVar
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_invoice_amount_internal = ContextVar('erp_invoice_amount_internal', default=False)
_POLICY_FIELDS = {'erp_budget_amount_mode', 'erp_budget_included_tax_ids', 'erp_budget_amount_captured'}
_LINE_AMOUNT_FIELDS = {'erp_budget_actual_company', 'erp_budget_amount_snapshot', 'erp_budget_amount_captured'}


class InvoiceBudgetAmount(models.Model):
    _inherit = 'account.move'

    erp_budget_amount_mode = fields.Selection([('legacy', 'Compatibility'), ('net', 'Exclude taxes'), ('all', 'Include all taxes'), ('specific', 'Include selected taxes')], readonly=True, copy=False)
    erp_budget_included_tax_ids = fields.Many2many('account.tax', 'erp_invoice_budget_included_tax_rel', 'move_id', 'tax_id', readonly=True, copy=False, check_company=True)
    erp_budget_amount_captured = fields.Boolean(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(_POLICY_FIELDS & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in _POLICY_FIELDS):
            raise AccessError(_('Invoice budget amount policies are captured by native posting.'))
        return super().create(vals_list)

    def write(self, vals):
        if _POLICY_FIELDS & vals.keys() and not _invoice_amount_internal.get():
            raise AccessError(_('Posted invoice budget amount policies are immutable.'))
        return super().write(vals)

    def _erp_budget_amount_lines(self):
        return self._erp_finance_lines()

    def _capture_budget_amount_policy(self):
        for move in self:
            if not move._erp_budget_amount_lines():
                continue
            mode, taxes = self.env['erp.budget.control.service']._amount_policy(move.company_id, 'account')
            token = _invoice_amount_internal.set(True)
            try:
                move.write({'erp_budget_amount_mode': mode, 'erp_budget_included_tax_ids': [(6, 0, taxes.ids)], 'erp_budget_amount_captured': True})
            finally:
                _invoice_amount_internal.reset(token)


    def _finalize_budget_amounts(self):
        token = _invoice_amount_internal.set(True)
        try:
            for line in self._erp_budget_amount_lines().filtered(lambda item: item.move_id.state == 'posted'):
                amount = line._compute_actual_budget_amount()
                snapshot = line._amount_snapshot_values(amount)
                line.write({'erp_budget_actual_company': amount, 'erp_budget_amount_snapshot': snapshot, 'erp_budget_amount_captured': True})
        finally:
            _invoice_amount_internal.reset(token)



class InvoiceLineBudgetAmount(models.Model):
    _inherit = 'account.move.line'

    erp_budget_actual_company = fields.Monetary(currency_field='company_currency_id', readonly=True, copy=False)
    erp_budget_amount_snapshot = fields.Json(readonly=True, copy=False)
    erp_budget_amount_captured = fields.Boolean(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(_LINE_AMOUNT_FIELDS & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in _LINE_AMOUNT_FIELDS):
            raise AccessError(_('Native posting captures actual budget amounts.'))
        return super().create(vals_list)

    def write(self, vals):
        if _LINE_AMOUNT_FIELDS & vals.keys() and not _invoice_amount_internal.get():
            raise AccessError(_('Posted budget amounts are immutable.'))
        return super().write(vals)

    def _erp_actual_budget_amount(self):
        self.ensure_one()
        return self.erp_budget_actual_company if self.erp_budget_amount_captured else self._compute_actual_budget_amount()

    def _compute_actual_budget_amount(self):
        self.ensure_one()
        move = self.move_id
        mode = move.erp_budget_amount_mode if move.erp_budget_amount_captured else 'legacy'
        service = self.env['erp.budget.control.service']
        # Validate policy and company scope without imposing purchase-quantity
        # restrictions on native signed accounting lines (credits/deposits).
        service._amount_currency(0, 0, self.currency_id, self.company_id, self.tax_ids, mode, move.erp_budget_included_tax_ids)
        if any(not math.isfinite(value) for value in (self.balance, self.price_unit, self.quantity, self.discount)):
            raise ValidationError(_('Native accounting amounts must be finite.'))
        if mode in ('legacy', 'net') or not self.tax_ids:
            return self.balance
        base_lines, tax_lines = move._get_rounded_base_and_tax_lines(round_from_tax_lines=True)
        base = next((line for line in base_lines if line['record'] == self), None)
        if not base:
            raise ValidationError(_('A taxed budget actual requires a native accounting tax base.'))
        selected = set(move.erp_budget_included_tax_ids.flatten_taxes_hierarchy().ids)
        tax_amount = sum(tax['tax_amount'] for tax in base['tax_details']['taxes_data'] if not tax['tax'].is_withholding_tax and (mode == 'all' or tax['tax'].id in selected))
        return self.company_currency_id.round(self.balance + base['sign'] * tax_amount)

    def _amount_snapshot_values(self, amount):
        self.ensure_one()
        move = self.move_id
        return {'scope': 'account', 'mode': move.erp_budget_amount_mode if move.erp_budget_amount_captured else 'legacy', 'included_tax_ids': sorted(move.erp_budget_included_tax_ids.ids), 'line_tax_ids': sorted(self.tax_ids.ids), 'currency_id': self.currency_id.id, 'company_currency_id': self.company_currency_id.id, 'invoice_currency_rate': move.invoice_currency_rate, 'native_balance': self.balance, 'native_amount_currency': self.amount_currency, 'move_type': move.move_type, 'subtotal_currency': self.price_subtotal, 'unit': self.price_unit, 'quantity': self.quantity, 'discount': self.discount, 'included_tax_company': amount - self.balance, 'budget_company_amount': amount}

    def _budget_amount_snapshot(self):
        self.ensure_one()
        return self.erp_budget_amount_snapshot if self.erp_budget_amount_captured else self._amount_snapshot_values(self._compute_actual_budget_amount())


class BudgetMoveInvoiceAmount(models.Model):
    _inherit = 'erp.budget.move'

    def _source_amount_snapshot(self, values):
        model, separator, identifier = (values.get('source_key') or '').partition(':')
        if separator and model == 'account.move.line' and identifier.isdigit():
            line = self.env[model].browse(int(identifier)).exists()
            if line:
                return line._budget_amount_snapshot()
        return super()._source_amount_snapshot(values)
