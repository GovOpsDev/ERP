"""PR to native expense/advance commitment handoff, without duplicate authority."""
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_simulated_claims = ContextVar('erp_expense_request_claims', default=frozenset())


class RequestExpense(models.Model):
    _inherit = 'hr.expense'

    erp_request_line_id = fields.Many2one('erp.procurement.request.line', string='Purchase Request Source', copy=False, check_company=True, ondelete='restrict', index=True)
    erp_request_amount_override = fields.Boolean(string='Allow Expense Above Request', copy=False, groups='hr_expense.group_hr_expense_manager')

    def _budget_spec(self):
        spec = super()._budget_spec()
        pr = self.erp_request_line_id
        if pr:
            pr.check_access('read')
            if pr.request_id.purchase_type_id and pr.request_id.conversion_route != 'expense':
                raise ValidationError(_('This government purchase type must use the purchase agreement route.'))
            if not pr.request_id._is_budget_approved() or pr._confirmed_po_lines():
                raise ValidationError(_('Expense reimbursement requires an approved request without confirmed purchase orders.'))
            if pr.company_id != self.company_id or pr.organization_id != self.erp_budget_organization_id or self.employee_id.user_id != pr.request_id.requested_by:
                raise ValidationError(_('The request must belong to the expense employee, organization and company.'))
            if self.erp_advance_ids:
                raise ValidationError(_('Advance clearing uses its advance origin, not another purchase request.'))
            controls, date = self.env['erp.budget.control.service']._forward_route('erp.procurement.request.line:%s' % pr.id, pr._budget_controls(), pr.request_id.date_start)
            analytic = controls.filtered(lambda control: control.level == 'analytic')
            if self.erp_budget_period_id != analytic.period_id or self.erp_budget_analytic_id != analytic.analytic_id or self.erp_budget_fund_id != pr.fund_id or self.erp_budget_dimension_ids != pr.dimension_ids:
                raise ValidationError(_('Expense dimensions must match the request fiscal destination.'))
        return spec

    @api.constrains('erp_request_line_id', 'company_id', 'employee_id', 'erp_budget_organization_id', 'erp_budget_period_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_dimension_ids', 'erp_advance_ids')
    def _check_request_source(self):
        for expense in self.filtered('erp_request_line_id'):
            expense._budget_spec()

    def _budget_related_expenses(self):
        records = super()._budget_related_expenses()
        while records:
            requests = records.erp_request_line_id
            linked = self.sudo().search([('erp_request_line_id', 'in', requests.ids)]).with_env(self.env) if requests else self.browse()
            combined = super(RequestExpense, records | linked)._budget_related_expenses()
            combined.check_access('read')
            if combined == records:
                break
            records = combined
        return records

    def _budget_lock_specs(self):
        specs, families = super()._budget_lock_specs()
        for pr in self.erp_request_line_id:
            specs.append((pr.period_id, pr.organization_id, pr.analytic_id, pr.fund_id, pr.account_id, pr.dimension_ids, pr.activity_id))
            families.append('erp.procurement.request.line:%s' % pr.id)
        return specs, families

    def _capture_expense_budget(self):
        result = super()._capture_expense_budget()
        for expense in self.filtered('erp_request_line_id'):
            expense.erp_budget_snapshot = dict(expense.erp_budget_snapshot or {}, request_line_id=expense.erp_request_line_id.id, request_approved_amount=expense.erp_request_line_id._budget_estimated_cost(), request_amount_override=expense.sudo().erp_request_amount_override)
        return result

    def _reconcile_expense_budget(self, simulate=False):
        related = self._budget_related_expenses()
        claims = related.filtered(lambda row: row.approval_state == 'approved' or (simulate and row in self))
        for pr in related.erp_request_line_id:
            claimed = claims.filtered(lambda row: row.erp_request_line_id == pr)
            if len(claimed) > 1:
                raise UserError(_('A request line can be taken over by only one approved expense or advance.'))
            for expense in claimed:
                expense._budget_spec()
                if not expense.sudo().erp_request_amount_override and expense.company_currency_id.compare_amounts(expense.untaxed_amount, pr._budget_estimated_cost()) > 0:
                    raise UserError(_('Expense exceeds the approved request amount; HR management must explicitly authorize the variance.'))
        token = _simulated_claims.set(frozenset(claims.ids))
        try:
            for pr in related.erp_request_line_id:
                pr._reconcile_budget(pr_eligible=pr.request_id._is_budget_approved())
            return super()._reconcile_expense_budget(simulate=simulate)
        finally:
            _simulated_claims.reset(token)

    @api.model_create_multi
    def create(self, vals_list):
        if (any(vals.get('erp_request_amount_override') for vals in vals_list) or self.env.context.get('default_erp_request_amount_override')) and not self.env.su and not self.env.user.has_group('hr_expense.group_hr_expense_manager'):
            raise AccessError(_('Only HR expense managers may authorize a request amount variance.'))
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('erp_request_amount_override') and not self.env.su and not self.env.user.has_group('hr_expense.group_hr_expense_manager'):
            raise AccessError(_('Only HR expense managers may authorize a request amount variance.'))
        if 'erp_request_line_id' in vals and any(expense.approval_state or expense._has_budget_history() for expense in self):
            raise UserError(_('A submitted or historical expense must retain its request source.'))
        if 'erp_request_amount_override' in vals and any(expense.approval_state == 'approved' for expense in self):
            raise UserError(_('Reset the expense before changing its request variance authorization.'))
        return super().write(vals)

    @api.onchange('erp_request_line_id')
    def _onchange_request_source(self):
        for expense in self.filtered('erp_request_line_id'):
            pr = expense.erp_request_line_id
            controls, date = self.env['erp.budget.control.service']._forward_route('erp.procurement.request.line:%s' % pr.id, pr._budget_controls(), pr.request_id.date_start)
            analytic = controls.filtered(lambda control: control.level == 'analytic')
            expense.update({'erp_budget_organization_id': pr.organization_id.id, 'erp_budget_period_id': analytic.period_id.id, 'erp_budget_fund_id': pr.fund_id.id, 'erp_budget_analytic_id': analytic.analytic_id.id, 'erp_budget_dimension_ids': pr.dimension_ids, 'erp_budget_activity_id': pr.activity_id.id, 'product_id': pr.product_id.id, 'account_id': pr.account_id.id, 'quantity': pr.product_qty, 'price_unit': pr.estimated_cost / pr.product_qty if pr.product_qty else pr.estimated_cost, 'currency_id': pr.currency_id.id, 'name': pr.name, 'tax_ids': False, 'date': max(expense.date or fields.Date.context_today(expense), analytic.period_id.date_from)})
            expense._onchange_budget_distribution()


class ExpenseRequestLine(models.Model):
    _inherit = 'erp.procurement.request.line'

    def _expense_sources(self):
        rows = self.env['hr.expense'].sudo().search([('erp_request_line_id', 'in', self.ids)]).with_env(self.env)
        if rows:
            rows.check_access('read')
        return rows

    def _reconcile_budget(self, pr_eligible, simulate=False):
        claims = self._expense_sources().filtered(lambda row: row.approval_state == 'approved' or row.id in _simulated_claims.get())
        return super()._reconcile_budget(pr_eligible=pr_eligible and not claims, simulate=simulate)


class ExpenseRequest(models.Model):
    _inherit = 'erp.procurement.request'

    def _check_reset_dependencies(self):
        super()._check_reset_dependencies()
        if self.line_ids._expense_sources().filtered(lambda expense: expense.approval_state != 'refused'):
            raise UserError(_('Refuse linked expenses before resetting the purchase request.'))

    def action_create_expense(self):
        self.ensure_one()
        self.check_access('read')
        with self.env.cr.savepoint():
            self._lock_conversion()
            if self.state != 'approved' or (self.purchase_type_id and self.conversion_route != 'expense'):
                raise UserError(_('An approved request configured for expense conversion is required.'))
            employee = self.env['hr.employee'].search([('user_id', '=', self.requested_by.id), ('company_id', '=', self.company_id.id)])
            if len(employee) != 1:
                raise ValidationError(_('The requester needs one visible employee in the request company.'))
            expenses = self.env['hr.expense']
            for line in self.line_ids:
                existing = line._expense_sources().filtered(lambda e: e.approval_state != 'refused')
                if existing:
                    expenses |= existing
                    continue
                if not line.product_id.can_be_expensed or line._confirmed_po_lines():
                    raise ValidationError(_('Expense conversion requires an expense product without a confirmed purchase.'))
                controls, date = self.env['erp.budget.control.service']._forward_route('erp.procurement.request.line:%s' % line.id, line._budget_controls(), self.date_start)
                analytic = controls.filtered(lambda c: c.level == 'analytic')
                expenses |= self.env['hr.expense'].with_company(self.company_id).create({
                    'name': line.name, 'company_id': self.company_id.id, 'employee_id': employee.id, 'product_id': line.product_id.id,
                    'account_id': line.account_id.id, 'date': max(self.date_start, analytic.period_id.date_from), 'quantity': line.product_qty,
                    'total_amount_currency': line.estimated_cost, 'currency_id': self.currency_id.id, 'tax_ids': [(5, 0, 0)],
                    'analytic_distribution': {','.join(map(str, sorted({analytic.analytic_id.id, *line.dimension_ids.ids}))): 100},
                    'erp_budget_period_id': analytic.period_id.id, 'erp_budget_organization_id': self.organization_id.id, 'erp_budget_fund_id': line.fund_id.id,
                    'erp_budget_analytic_id': analytic.analytic_id.id, 'erp_budget_activity_id': line.activity_id.id, 'erp_budget_dimension_ids': [(6, 0, line.dimension_ids.ids)], 'erp_request_line_id': line.id})
            return {'type': 'ir.actions.act_window', 'res_model': 'hr.expense', 'view_mode': 'list,form', 'domain': [('id', 'in', expenses.ids)]}

    def action_reject(self):
        if self.line_ids._expense_sources().filtered(lambda expense: expense.approval_state != 'refused'):
            raise UserError(_('Refuse linked expenses before rejecting the purchase request.'))
        return super().action_reject()


class ExpensePurchaseLine(models.Model):
    _inherit = 'purchase.order.line'

    def _validate_request_budget_key(self):
        result = super()._validate_request_budget_key()
        for line in self.filtered('erp_request_line_id'):
            if line.erp_request_line_id._expense_sources().filtered(lambda expense: expense.approval_state != 'refused'):
                raise UserError(_('The request is assigned to an expense; refuse that expense before purchasing.'))
        return result
