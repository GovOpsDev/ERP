from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_purchase_amount_internal = ContextVar('erp_purchase_amount_internal', default=False)
_POLICY_FIELDS = {'erp_budget_amount_mode', 'erp_budget_included_tax_ids', 'erp_budget_fx_rate', 'erp_budget_amount_captured'}


class PurchaseBudgetAmount(models.Model):
    _inherit = 'purchase.order'

    erp_budget_manual_rate = fields.Float(string='Budget Manual Exchange Rate', digits=0, help='Company currency per document currency unit; zero uses the native rate.')
    erp_budget_amount_mode = fields.Selection([('legacy', 'Compatibility'), ('net', 'Exclude taxes'), ('all', 'Include all taxes'), ('specific', 'Include selected taxes')], readonly=True, copy=False)
    erp_budget_included_tax_ids = fields.Many2many('account.tax', 'erp_po_budget_included_tax_rel', 'order_id', 'tax_id', readonly=True, copy=False, check_company=True)
    erp_budget_fx_rate = fields.Float(string='Confirmed Budget Exchange Rate', readonly=True, copy=False, digits=0)
    erp_budget_amount_captured = fields.Boolean(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(_POLICY_FIELDS & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in _POLICY_FIELDS):
            raise AccessError(_('Confirmed budget amount policies are captured by purchase approval.'))
        from .request_currency import _rate_transfer
        for vals in vals_list:
            if not _rate_transfer.get():
                self.env['erp.budget.control.service']._check_manual_amount_rate(vals.get('erp_budget_manual_rate', self.env.context.get('default_erp_budget_manual_rate', 0)) or 0)
        return super().create(vals_list)

    def write(self, vals):
        if _POLICY_FIELDS & vals.keys() and not _purchase_amount_internal.get():
            raise AccessError(_('Confirmed budget amount policies are immutable.'))
        if 'erp_budget_manual_rate' in vals:
            self.env['erp.budget.control.service']._check_manual_amount_rate(vals['erp_budget_manual_rate'] or 0)
            if any(order.state in ('purchase', 'done') for order in self):
                raise AccessError(_('Cancel the purchase before changing its budget exchange rate.'))
        return super().write(vals)

    def _capture_budget_amount_policy(self):
        service = self.env['erp.budget.control.service']
        for order in self.filtered(lambda order: order.erp_request_organization_id and order.state in ('draft', 'sent', 'to approve')):
            order._lock_request_scope()
            mode, taxes = service._amount_policy(order.company_id, 'purchase')
            rate = service._amount_rate(order.currency_id, order.company_id, fields.Date.to_date(order.date_order), order.erp_budget_manual_rate)
            token = _purchase_amount_internal.set(True)
            try:
                order.write({'erp_budget_amount_mode': mode, 'erp_budget_included_tax_ids': [(6, 0, taxes.ids)], 'erp_budget_fx_rate': rate, 'erp_budget_amount_captured': True})
                for line in order.order_line.filtered('erp_request_line_id'):
                    amount = line._erp_budget_amount()
                    details = [{'id': tax.id, 'amount': tax.amount, 'amount_type': tax.amount_type, 'price_include': getattr(tax, 'price_include', False)} for tax in line.tax_ids.flatten_taxes_hierarchy()]
                    line.write({'erp_budget_total_company': amount, 'erp_budget_unit_company': amount / line.product_qty if line.product_qty else 0, 'erp_budget_tax_snapshot': details, 'erp_budget_amount_captured': True})
            finally:
                _purchase_amount_internal.reset(token)

    def button_confirm(self):
        with self.env.cr.savepoint():
            self._capture_budget_amount_policy()
            return super().button_confirm()

    def button_approve(self, force=False):
        with self.env.cr.savepoint():
            self._capture_budget_amount_policy()
            return super().button_approve(force=force)


class PurchaseLineBudgetAmount(models.Model):
    _inherit = 'purchase.order.line'

    erp_budget_company_currency_id = fields.Many2one(related='company_id.currency_id')
    erp_budget_total_company = fields.Monetary(currency_field='erp_budget_company_currency_id', readonly=True, copy=False)
    erp_budget_unit_company = fields.Float(readonly=True, copy=False, digits=0)
    erp_budget_tax_snapshot = fields.Json(readonly=True, copy=False)
    erp_budget_amount_captured = fields.Boolean(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'erp_budget_total_company', 'erp_budget_unit_company', 'erp_budget_tax_snapshot', 'erp_budget_amount_captured'}
        if not _purchase_amount_internal.get() and (any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected)):
            raise AccessError(_('Purchase budget amounts are captured by approval.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'erp_budget_total_company', 'erp_budget_unit_company', 'erp_budget_tax_snapshot', 'erp_budget_amount_captured'} & vals.keys() and not _purchase_amount_internal.get():
            raise AccessError(_('Confirmed purchase budget amounts are immutable.'))
        return super().write(vals)

    def _budget_amount_policy(self):
        self.ensure_one()
        order = self.order_id
        if order.state in ('purchase', 'done', 'cancel'):
            return (order.erp_budget_amount_mode, order.erp_budget_included_tax_ids, order.erp_budget_fx_rate) if order.erp_budget_amount_captured else ('legacy', self.env['account.tax'], 1)
        mode, taxes = self.env['erp.budget.control.service']._amount_policy(self.company_id, 'purchase')
        rate = self.env['erp.budget.control.service']._amount_rate(order.currency_id, self.company_id, fields.Date.to_date(order.date_order), order.erp_budget_manual_rate)
        return mode, taxes, rate

    def _erp_budget_amount(self, quantity=None):
        self.ensure_one()
        if self.erp_budget_amount_captured and self.order_id.state in ('purchase', 'done', 'cancel'):
            return self.company_id.currency_id.round(self.erp_budget_unit_company * (self.product_qty if quantity is None else quantity))
        mode, taxes, rate = self._budget_amount_policy()
        return self.env['erp.budget.control.service']._document_amount(self.price_unit, self.product_qty if quantity is None else quantity, self.currency_id, self.company_id, fields.Date.to_date(self.order_id.date_order), taxes=self.tax_ids, mode=mode, selected_taxes=taxes, discount=self.discount, rate=rate, document_tax_mode=self.document_tax_mode)

    def _budget_amount_snapshot(self):
        self.ensure_one()
        mode, taxes, rate = self._budget_amount_policy()
        return {'scope': 'purchase', 'mode': mode, 'included_tax_ids': sorted(taxes.ids), 'line_tax_ids': sorted(self.tax_ids.ids), 'currency_id': self.currency_id.id, 'company_currency_id': self.company_id.currency_id.id, 'company_rate': rate, 'unit': self.price_unit, 'quantity': self.product_qty, 'discount': self.discount, 'unit_company': self.erp_budget_unit_company if self.erp_budget_amount_captured else False, 'total_company': self.erp_budget_total_company if self.erp_budget_amount_captured else False, 'taxes_at_approval': self.erp_budget_tax_snapshot}


class BudgetMovePurchaseAmount(models.Model):
    _inherit = 'erp.budget.move'

    def _source_amount_snapshot(self, values):
        model, separator, identifier = (values.get('source_key') or '').partition(':')
        if separator and model == 'purchase.order.line' and identifier.isdigit():
            line = self.env[model].browse(int(identifier)).exists()
            if line:
                return line._budget_amount_snapshot()
        return super()._source_amount_snapshot(values)
