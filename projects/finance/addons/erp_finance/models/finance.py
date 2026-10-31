from contextvars import ContextVar
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

_finance_posting = ContextVar('erp_finance_budget_posting', default=False)
_finance_unposting = ContextVar('erp_finance_budget_unposting', default=False)


class ProcurementRequestLine(models.Model):
    _inherit = 'erp.procurement.request.line'

    def _reconcile_budget(self, pr_eligible, simulate=False):
        self.ensure_one()
        if simulate or not self.request_id._is_budget_approved():
            return super()._reconcile_budget(pr_eligible, simulate=simulate)
        self.check_access('read')
        controls = self._budget_controls()
        po_lines = self._confirmed_po_lines()
        orders, actuals, provenance = [], [], {}
        for po in po_lines:
            po._validate_request_budget_key()
            if po.discount and po._budget_amount_policy()[0] == 'legacy':
                raise ValidationError(_('Discounted controlled purchase orders are not supported by Finance budget integration.'))
            po_controls = po._erp_budget_controls()
            lines = self.env['account.move.line'].sudo().search([('purchase_line_id', '=', po.id), ('move_id.state', '=', 'posted')]).with_env(self.env)
            if lines:
                lines.check_access('read')
                lines.mapped('move_id').check_access('read')
            precision = self.env['decimal.precision'].precision_get('Product Unit')
            net_qty = 0.0
            remaining_qty = po.product_qty
            bill_qty = 0.0
            refund_qty = 0.0
            refunded_by_bill = {}
            for line in lines.sorted(key=lambda row: row.id):
                move = line.move_id
                if move.move_type not in ('in_invoice', 'in_refund'):
                    raise ValidationError(_('Only vendor bills and refunds are supported for controlled purchases.'))
                if move.company_id != po.company_id or move.partner_id != po.order_id.partner_id:
                    raise ValidationError(_('The bill must match the purchase company and supplier.'))
                expected_distribution = self.env['erp.budget.control.service']._source_distribution('purchase.order.line:%s' % po.id, po_controls, po.analytic_distribution, move.date)
                if (not po.erp_budget_activity_id and line.account_id != po.erp_budget_account_id) or line.analytic_distribution != expected_distribution:
                    raise ValidationError(_('Bill taxes, account or analytic distribution do not match the supported purchase budget key.'))
                if line.product_id != po.product_id or not all(math.isfinite(value) and value > 0 for value in (line.quantity, line.price_unit, line.price_subtotal)) or not line.product_uom_id:
                    raise ValidationError(_('A positive bill quantity, matching product and compatible unit are required.'))
                if move.move_type == 'in_refund' and (not move.reversed_entry_id or move.reversed_entry_id.move_type != 'in_invoice'):
                    raise ValidationError(_('A controlled refund must reverse a vendor bill.'))
                if line.product_uom_id.parent_path.split('/')[0] != po.uom_id.parent_path.split('/')[0]:
                    raise ValidationError(_('Bill and purchase units must have the same reference unit.'))
                qty = line.product_uom_id._compute_quantity(line.quantity, po.uom_id, round=False)
                if move.move_type == 'in_refund':
                    original = move.reversed_entry_id.invoice_line_ids.filtered(lambda l: l.purchase_line_id == po)
                    if not original or move.reversed_entry_id.state != 'posted' or move.currency_id != move.reversed_entry_id.currency_id:
                        raise ValidationError(_('A refund must reference a posted bill for the same purchase line.'))
                    original.check_access('read')
                    key = move.reversed_entry_id.id
                    prior_qty, prior_amount = refunded_by_bill.get(key, (0.0, 0.0))
                    refunded_by_bill[key] = (prior_qty + qty, prior_amount + line.price_subtotal)
                    sign = -1
                    refund_qty += qty
                    # Upstream only returns PO commitment while the PO has
                    # an existing amount_commit. Preserve that condition.
                    if float_compare(po.currency_id.round(remaining_qty * po.price_unit), 0, precision_rounding=po.currency_id.rounding) > 0:
                        remaining_qty = min(po.product_qty, remaining_qty + qty)
                else:
                    bill_qty += qty
                    sign = 1
                    remaining_qty = max(0.0, remaining_qty - qty)
                net_qty += sign * qty
                amount = line._erp_actual_budget_amount()
                if not float_is_zero(amount, precision_rounding=line.company_currency_id.rounding):
                    source_key = 'account.move.line:%s' % line.id
                    actuals.append((source_key, po_controls, amount, move.date))
                    provenance[source_key] = ('account.move:%s' % move.id, 'purchase.order.line:%s' % po.id)
            for bill_id, (refunded_qty, refunded_amount) in refunded_by_bill.items():
                original_lines = lines.filtered(lambda line: line.move_id.id == bill_id and line.move_id.move_type == 'in_invoice')
                original_qty = sum(line.product_uom_id._compute_quantity(line.quantity, po.uom_id, round=False) for line in original_lines)
                original_amount = sum(original_lines.mapped('price_subtotal'))
                if float_compare(refunded_qty, original_qty, precision_digits=precision) > 0 or float_compare(refunded_amount, original_amount, precision_rounding=original_lines.move_id.currency_id.rounding) > 0:
                    raise ValidationError(_('Refunds may not exceed the referenced posted bill line.'))
            if float_compare(refund_qty, bill_qty, precision_digits=precision) > 0 or float_compare(net_qty, po.product_qty, precision_digits=precision) > 0 or float_compare(net_qty, 0, precision_digits=precision) < 0:
                raise ValidationError(_('Posted bill and refund quantities must stay within the purchase quantity.'))
            remaining = po._erp_budget_amount(quantity=remaining_qty)
            remaining = po._reconcile_deposit_actuals(remaining, actuals, provenance)
            orders.append(('purchase.order.line:%s' % po.id, po_controls, remaining, fields.Date.to_date(po.order_id.date_order)))
        return self.env['erp.budget.control.service']._reconcile_purchase_multi(
            controls, self.request_id.date_start, 'erp.procurement.request.line:%s' % self.id,
            'erp.procurement.request.line:%s' % self.id, self._budget_estimated_cost(), pr_eligible, orders, actuals, provenance)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _reconcile_deposit_actuals(self, remaining, actuals, provenance):
        return remaining

    def _prepare_account_move_line(self, move=False):
        values = super()._prepare_account_move_line(move=move)
        if self.erp_request_line_id:
            controls = self._erp_budget_controls()
            values['analytic_distribution'] = self.env['erp.budget.control.service']._source_distribution('purchase.order.line:%s' % self.id, controls, self.analytic_distribution, fields.Date.to_date(self.order_id.date_order), actual=False)
        return values


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _budget_scope_specs(self):
        specs, families = [], []
        for line in self._erp_finance_requests().mapped('request_id.line_ids'):
            specs.append((line.period_id, line.organization_id, line.analytic_id, line.fund_id, line.account_id, line.dimension_ids, line.activity_id))
            families.append('erp.procurement.request.line:%s' % line.id)
            for po in line._confirmed_po_lines():
                specs.append((po.erp_budget_period_id or line.period_id, line.organization_id, po.erp_budget_analytic_id, po.erp_budget_fund_id, po.erp_budget_account_id, po.erp_budget_dimension_ids, po.erp_budget_activity_id))
        return specs, families

    def _prelock_budget_sources(self):
        # Prelock every mixed source before any adapter takes a subset of locks.
        specs, families = self._budget_scope_specs()
        activities = self.env['erp.budget.activity']
        for spec in specs:
            activities |= spec[6]
        if activities:
            activities._lock_activity_key()
        service = self.env['erp.budget.control.service']
        controls = self.env['erp.budget.control']
        for period, unit, analytic, fund, account, dimensions, activity in specs:
            controls |= service._resolve(period, unit, analytic, fund, account, dimensions, activity=activity)
        if families:
            old = self.env['erp.budget.move'].sudo().search([('family_key', 'in', families)]).control_id.with_env(self.env)
            old.check_access('read')
            controls |= old | service._carry_lock_controls(families)
        if controls:
            controls.check_access('read')
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
            controls.period_id._lock_plan_periods()
        return controls

    def _budget_financial_transition(self):
        return _finance_posting.get() or _finance_unposting.get()

    def _check_erp_budget_posting_ready(self):
        if _finance_posting.get():
            return
        return super()._check_erp_budget_posting_ready()

    def _erp_finance_lines(self):
        # Do not silently omit lines hidden by accounting record rules.
        lines = self.sudo().mapped('invoice_line_ids').filtered(lambda row: row._erp_purchase_budget_source().erp_request_line_id).with_env(self.env)
        if lines:
            lines.check_access('read')
        return lines

    def _erp_finance_requests(self):
        controlled = self.env['erp.procurement.request.line']
        for line in self._erp_finance_lines():
            controlled |= line._erp_purchase_budget_source().erp_request_line_id
        if controlled:
            controlled.check_access('read')
        return controlled

    def _check_erp_finance_sources(self):
        for line in self._erp_finance_lines():
            po = line._erp_purchase_budget_source()
            po.check_access('read')
            if po.order_id.state not in ('purchase', 'done') or not po.erp_request_line_id.request_id._is_budget_approved():
                raise ValidationError(_('The linked purchase order and request must be approved.'))

    def _post(self, soft=True):
        affected = self._erp_finance_requests()
        if not affected:
            return super()._post(soft=soft)
        self.check_access('write')
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()):
            self._check_erp_finance_sources()
            self._prelock_budget_sources()
            affected.mapped('request_id')._lock_budget_rows()
            self._capture_budget_amount_policy()
            token = _finance_posting.set(True)
            try:
                posted = super()._post(soft=soft)
            finally:
                _finance_posting.reset(token)
            posted._check_erp_finance_sources()
            posted._finalize_budget_amounts()
            for line in posted._erp_finance_requests():
                line._reconcile_budget(pr_eligible=True)
            return posted

    def button_draft(self):
        token = _finance_unposting.set(True)
        try:
            with self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()):
                return super().button_draft()
        finally:
            _finance_unposting.reset(token)

    def button_cancel(self):
        token = _finance_unposting.set(True)
        try:
            with self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()):
                return super().button_cancel()
        finally:
            _finance_unposting.reset(token)

    def write(self, vals):
        if vals.get('state') in ('draft', 'cancel') and not _finance_unposting.get() and self.filtered(lambda move: move.state == 'posted')._erp_finance_requests():
            raise UserError(_('Use the native accounting actions to reset or cancel a controlled bill.'))
        if not _finance_posting.get() and {'date', 'invoice_date', 'company_id', 'currency_id', 'move_type', 'reversed_entry_id', 'invoice_currency_rate', 'taxable_supply_date', 'partner_id', 'journal_id'}.intersection(vals) and self.filtered(lambda move: move.state == 'posted')._erp_finance_requests():
            raise UserError(_('Reset the controlled bill to draft before changing its budget source or date.'))
        affected = self._erp_finance_requests() if vals.get('state') in ('draft', 'cancel') else self.env['erp.procurement.request.line']
        if not affected:
            return super().write(vals)
        with self.env.cr.savepoint():
            affected.mapped('request_id')._lock_budget_rows()
            result = super().write(vals)
            for line in affected:
                line._reconcile_budget(pr_eligible=True)
            return result


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    erp_budget_activity_id = fields.Many2one('erp.budget.activity', compute='_compute_budget_activity')

    @api.depends('purchase_line_id.erp_budget_activity_id')
    def _compute_budget_activity(self):
        for line in self:
            line.erp_budget_activity_id = line.purchase_line_id.erp_budget_activity_id

    def _erp_purchase_budget_source(self):
        self.ensure_one()
        return self.purchase_line_id

    def write(self, vals):
        sensitive = {'purchase_line_id', 'move_id', 'quantity', 'price_unit', 'discount', 'product_id', 'product_uom_id', 'account_id', 'analytic_distribution', 'tax_ids', 'balance', 'debit', 'credit', 'amount_currency', 'currency_id', 'company_id', 'tax_repartition_line_id', 'tax_line_id', 'display_type', 'partner_id'}
        if sensitive.intersection(vals) and any(line.move_id.state == 'posted' and not line.move_id._budget_financial_transition() and line.move_id._erp_budget_amount_lines() for line in self):
            raise UserError(_('Reset the controlled bill to draft before changing its budget source or amount.'))
        return super().write(vals)

    def unlink(self):
        if any(line.move_id.state == 'posted' and not line.move_id._budget_financial_transition() and line.move_id._erp_budget_amount_lines() for line in self):
            raise UserError(_('Reset the controlled bill to draft before deleting its budget source.'))
        return super().unlink()


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def write(self, vals):
        if vals.get('state') not in ('draft', 'cancel'):
            return super().write(vals)
        linked = self.mapped('order_line').filtered('erp_request_line_id')
        if linked:
            bills = self.env['account.move.line'].sudo().search([('purchase_line_id', 'in', linked.ids), ('move_id.state', '=', 'posted')]).with_env(self.env)
            if bills:
                bills.check_access('read')
                raise UserError(_('Reset or reverse controlled posted bills before cancelling the purchase order.'))
        return super().write(vals)
