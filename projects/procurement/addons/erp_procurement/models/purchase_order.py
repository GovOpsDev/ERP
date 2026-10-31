from contextvars import ContextVar

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


_purchase_transition = ContextVar('erp_purchase_transition', default=False)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    erp_request_line_id = fields.Many2one('erp.procurement.request.line', ondelete='restrict', check_company=True, copy=False, index=True)
    erp_budget_period_id = fields.Many2one('erp.budget.period', ondelete='restrict', check_company=True)
    erp_budget_fund_id = fields.Many2one('erp.budget.fund', ondelete='restrict', check_company=True)
    erp_budget_analytic_id = fields.Many2one('account.analytic.account', ondelete='restrict', check_company=True)
    erp_budget_account_id = fields.Many2one('account.account', ondelete='restrict', check_company=True)
    erp_budget_activity_id = fields.Many2one('erp.budget.activity', ondelete='restrict', check_company=True)
    erp_budget_dimension_ids = fields.Many2many('account.analytic.account', 'erp_po_line_dimension_rel', 'line_id', 'analytic_id', check_company=True)

    @api.onchange('erp_request_line_id')
    def _onchange_erp_request_line(self):
        for line in self:
            request_line = line.erp_request_line_id
            if request_line:
                line.erp_budget_period_id = request_line.period_id
                line.erp_budget_fund_id = request_line.fund_id
                line.erp_budget_analytic_id = request_line.analytic_id
                line.erp_budget_account_id = request_line.account_id
                line.erp_budget_activity_id = request_line.activity_id
                line.erp_budget_dimension_ids = request_line.dimension_ids
                ids = sorted([request_line.analytic_id.id] + request_line.dimension_ids.ids)
                line.analytic_distribution = {','.join(map(str, ids)): 100}

    @api.onchange('erp_budget_activity_id')
    def _onchange_budget_activity(self):
        if self.erp_budget_activity_id:
            self.erp_budget_account_id = self.erp_budget_activity_id.account_id

    def _validate_request_budget_key(self):
        for line in self.filtered('erp_request_line_id'):
            pr = line.erp_request_line_id
            if line.is_downpayment:
                raise ValidationError(_('Use the deposit adapter to link a down payment to an approved purchase line.'))
            pr.check_access('read')
            if not pr.request_id._is_budget_approved():
                raise ValidationError(_('The linked purchase request must be approved.'))
            expense = line.product_id.with_company(line.company_id).product_tmpl_id.get_product_accounts(line.order_id.fiscal_position_id).get('expense')
            if line.erp_budget_activity_id and line.erp_budget_activity_id.account_id != line.erp_budget_account_id:
                raise ValidationError(_('The purchase budget account must match its activity.'))
            if not line.erp_budget_activity_id and (not expense or expense != line.erp_budget_account_id):
                raise ValidationError(_('The purchase order account must match the product expense account.'))
            line._erp_budget_amount()
            if line.company_id != pr.company_id:
                raise ValidationError(_('Purchase order and request companies must match.'))
            if not line.erp_budget_fund_id or not line.erp_budget_analytic_id or not line.erp_budget_account_id:
                raise ValidationError(_('Purchase order budget dimensions are required.'))
            expected_ids = {line.erp_budget_analytic_id.id, *line.erp_budget_dimension_ids.ids}
            distribution = line.analytic_distribution or {}
            if len(distribution) != 1 or any(set(map(int, key.split(','))) != expected_ids or value != 100 for key, value in distribution.items()):
                raise ValidationError(_('The PO analytic distribution must match the request at 100 percent.'))
            unit_ids = self.sudo().search([('order_id', '=', line.order_id.id)]).mapped('erp_request_line_id.organization_id').ids
            if len(set(unit_ids)) > 1:
                raise ValidationError(_('Linked purchase request lines on an order must belong to one organization.'))
            po_date = fields.Date.to_date(line.order_id.date_order)
            period = line.erp_budget_period_id or pr.period_id
            if period.company_id != line.company_id or not period.date_from <= po_date <= period.date_to:
                raise ValidationError(_('Purchase order date must fall in its company budget period.'))
            if line.price_subtotal <= 0:
                raise ValidationError(_('A linked purchase order line must have a positive subtotal.'))

    def _erp_budget_controls(self):
        self.ensure_one()
        self.check_access('read')
        self._validate_request_budget_key()
        request_line = self.erp_request_line_id
        period = self.erp_budget_period_id or request_line.period_id
        return self.env['erp.budget.control.service']._resolve(period, request_line.organization_id, self.erp_budget_analytic_id, self.erp_budget_fund_id, self.erp_budget_account_id, self.erp_budget_dimension_ids, activity=self.erp_budget_activity_id)

    @api.constrains('erp_request_line_id', 'erp_budget_period_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_account_id', 'erp_budget_activity_id', 'erp_budget_dimension_ids', 'company_id', 'order_id')
    def _check_request_budget_key(self):
        self._validate_request_budget_key()

    @api.model_create_multi
    def create(self, vals_list):
        order_ids = sorted({v.get('order_id') for v in vals_list if v.get('order_id') and v.get('erp_request_line_id')})
        if order_ids:
            self.env['purchase.order'].browse(order_ids)._lock_request_scope()
        for vals in vals_list:
            request = self.env['erp.procurement.request.line'].browse(vals.get('erp_request_line_id')).exists()
            if request:
                request.check_access('read')
                vals.setdefault('erp_budget_activity_id', request.activity_id.id)
            if vals.get('erp_budget_activity_id'):
                activity = self.env['erp.budget.activity'].browse(vals['erp_budget_activity_id'])
                activity.check_access('read')
                vals.setdefault('erp_budget_account_id', activity.account_id.id)
            if vals.get('erp_request_line_id') and vals.get('order_id'):
                order = self.env['purchase.order'].browse(vals['order_id'])
                if order.state in ('purchase', 'done'):
                    raise UserError(_('Linked lines cannot be added to a confirmed purchase order.'))
        return super().create(vals_list)

    def unlink(self):
        linked_orders = self.filtered('erp_request_line_id').mapped('order_id')
        if linked_orders:
            linked_orders._lock_request_scope()
        if any(line.erp_request_line_id and line.order_id.state in ('purchase', 'done') for line in self):
            raise UserError(_('Cancel the linked purchase order before deleting its line.'))
        return super().unlink()

    def write(self, vals):
        sensitive = {'is_downpayment', 'erp_request_line_id', 'erp_budget_period_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_account_id', 'erp_budget_activity_id', 'erp_budget_dimension_ids', 'price_unit', 'product_qty', 'product_id', 'uom_id', 'discount', 'tax_ids', 'analytic_distribution', 'order_id'}
        forward_keys = {'erp_request_line_id', 'erp_budget_period_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_account_id', 'erp_budget_activity_id', 'erp_budget_dimension_ids', 'order_id'}
        if forward_keys & vals.keys() and self.env['erp.budget.commit.forward.line'].sudo().search_count([('source_key', 'in', ['purchase.order.line:%s' % line.id for line in self]), ('reserved', '=', True), ('forward_id.state', '=', 'done')]):
            raise UserError(_('Forwarded purchase budget keys are immutable.'))
        if {'erp_request_line_id', 'order_id'} & vals.keys():
            orders = self.mapped('order_id') | self.env['purchase.order'].browse(vals.get('order_id'))
            orders._lock_request_scope()
        if sensitive & vals.keys() and any((line.erp_request_line_id or vals.get('erp_request_line_id')) and line.order_id.state in ('purchase', 'done') for line in self):
            raise UserError(_('Cancel the linked purchase order before changing its budget or amount.'))
        if vals.get('erp_budget_activity_id') and 'erp_budget_account_id' not in vals:
            activity = self.env['erp.budget.activity'].browse(vals['erp_budget_activity_id'])
            activity.check_access('read')
            vals = dict(vals, erp_budget_account_id=activity.account_id.id)
        return super().write(vals)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    erp_request_organization_id = fields.Many2one('erp.organization.unit', compute='_compute_request_organization', store=True, compute_sudo=True, index=True)
    erp_scope_version = fields.Integer(default=0, readonly=True)

    @api.depends('order_line.erp_request_line_id.organization_id')
    def _compute_request_organization(self):
        for order in self:
            units = order.order_line.mapped('erp_request_line_id.organization_id')
            order.erp_request_organization_id = units[:1]

    def _lock_request_scope(self):
        self.check_access('write')
        if not self:
            return
        ids = tuple(sorted(self.ids))
        self.env.cr.execute('SELECT id FROM purchase_order WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
        self.env.cr.execute('UPDATE purchase_order SET erp_scope_version = COALESCE(erp_scope_version, 0) + 1 WHERE id IN %s', [ids])

    @api.model_create_multi
    def create(self, vals_list):
        if any({'erp_request_organization_id', 'erp_scope_version'} & vals.keys() for vals in vals_list):
            raise AccessError(_('Purchase order scope is derived from its request lines.'))
        return super().create(vals_list)

    def _erp_native_transition(self, method, *args, **kwargs):
        token = _purchase_transition.set(True)
        try:
            return method(*args, **kwargs)
        finally:
            _purchase_transition.reset(token)

    def button_confirm(self):
        return self._erp_native_transition(super().button_confirm)

    def button_approve(self, force=False):
        return self._erp_native_transition(super().button_approve, force=force)

    def button_cancel(self):
        return self._erp_native_transition(super().button_cancel)

    def button_draft(self):
        return self._erp_native_transition(super().button_draft)

    def write(self, vals):
        if vals.get('state') in ('purchase', 'cancel', 'draft', 'to approve') and not _purchase_transition.get() and any(order.erp_request_organization_id for order in self):
            raise AccessError(_('Use the native purchase order workflow actions.'))
        if {'company_id', 'currency_id', 'date_order', 'fiscal_position_id'} & vals.keys() and any(order.erp_request_organization_id and order.state in ('purchase', 'done') for order in self):
            raise UserError(_('Cancel the linked purchase order before changing its budget dates or company.'))
        if {'erp_request_organization_id', 'erp_scope_version'} & vals.keys():
            raise AccessError(_('Purchase order scope is derived from its request lines.'))
        affected = self.mapped('order_line.erp_request_line_id') if vals.get('state') in ('purchase', 'cancel', 'draft') else self.env['erp.procurement.request.line']
        if affected:
            affected.check_access('read')
            affected.mapped('request_id')._lock_budget_rows(extra_po_lines=self.mapped('order_line').filtered('erp_request_line_id'))
        with self.env.cr.savepoint():
            result = super().write(vals)
            if affected:
                for line in affected:
                    line._reconcile_budget(pr_eligible=line.request_id._is_budget_approved())
            return result
