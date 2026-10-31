"""Source expense commitments on Odoo 20's native per-expense approval."""
from contextlib import contextmanager
from contextvars import ContextVar
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

_expense_workflow = ContextVar('erp_expense_workflow', default=False)
_expense_posting = ContextVar('erp_expense_posting', default=False)
_KEYS = {'erp_budget_period_id', 'erp_budget_organization_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_activity_id', 'erp_budget_dimension_ids'}
_CAPTURE = {'erp_budget_amount', 'erp_budget_snapshot', 'erp_budget_captured'}
_FINANCIAL = _KEYS | {'date', 'company_id', 'employee_id', 'account_id', 'analytic_distribution', 'product_id', 'quantity', 'price_unit', 'total_amount', 'total_amount_currency', 'currency_id', 'tax_ids', 'payment_mode', 'has_existing_bill', 'existing_bill_id'}


def _expense_access(uid):
    invalid = Domain('active', '=', False) | Domain('assignment_ids', 'not any!', Domain('user_id', '=', uid))
    return Domain('erp_budget_organization_id', 'not any!', invalid)


class BudgetExpense(models.Model):
    _inherit = 'hr.expense'

    erp_budget_period_id = fields.Many2one('erp.budget.period', check_company=True, ondelete='restrict')
    erp_budget_organization_id = fields.Many2one('erp.organization.unit', check_company=True, ondelete='restrict', index=True)
    erp_budget_fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict')
    erp_budget_analytic_id = fields.Many2one('account.analytic.account', check_company=True, ondelete='restrict')
    erp_budget_activity_id = fields.Many2one('erp.budget.activity', check_company=True, ondelete='restrict')
    erp_budget_dimension_ids = fields.Many2many('account.analytic.account', 'erp_expense_dimension_rel', 'expense_id', 'analytic_id', check_company=True)
    erp_budget_amount = fields.Monetary(currency_field='company_currency_id', readonly=True, copy=False)
    erp_budget_snapshot = fields.Json(readonly=True, copy=False)
    erp_budget_captured = fields.Boolean(readonly=True, copy=False)
    erp_budget_lock_version = fields.Integer(readonly=True, copy=False)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & _expense_access(self.env.uid)

    def _budget_expenses(self):
        records = self.sudo().filtered(lambda expense: any(expense[key] for key in _KEYS)).with_env(self.env)
        records.check_access('read')
        return records

    def _budget_spec(self):
        self.ensure_one()
        self.check_access('read')
        if not all((self.erp_budget_period_id, self.erp_budget_organization_id, self.erp_budget_fund_id, self.erp_budget_analytic_id, self.account_id)):
            raise ValidationError(_('A controlled expense requires period, organization, fund, analytic and account.'))
        if self.has_existing_bill:
            raise ValidationError(_('Set budget dimensions on the existing bill, not its reimbursement payment.'))
        if self.erp_budget_period_id.company_id != self.company_id:
            raise ValidationError(_('Expense and budget period must belong to the same company.'))
        ids = {self.erp_budget_analytic_id.id, *self.erp_budget_dimension_ids.ids}
        distribution = self.analytic_distribution or {}
        if len(distribution) != 1 or any(set(map(int, key.split(','))) != ids or amount != 100 for key, amount in distribution.items()):
            raise ValidationError(_('Expense budget dimensions must match its native analytic distribution at 100 percent.'))
        return (self.erp_budget_period_id, self.erp_budget_organization_id, self.erp_budget_analytic_id, self.erp_budget_fund_id, self.erp_budget_activity_id.account_id or self.account_id, self.erp_budget_dimension_ids, self.erp_budget_activity_id)

    def _budget_controls(self):
        period, unit, analytic, fund, account, dimensions, activity = self._budget_spec()
        return self.env['erp.budget.control.service']._resolve(period, unit, analytic, fund, account, dimensions, activity=activity)

    def _budget_family(self):
        self.ensure_one()
        return 'hr.expense:%s' % self.id

    def _budget_related_expenses(self):
        return self._budget_expenses()

    def _lock_budget_expenses(self):
        expenses = self._budget_related_expenses()
        if not expenses:
            return self.env['erp.budget.control']
        specs, families = expenses._budget_lock_specs()
        activities = self.env['erp.budget.activity']
        for spec in specs:
            activities |= spec[6]
        if activities:
            activities._lock_activity_key()
        controls = self.env['erp.budget.control']
        for period, unit, analytic, fund, account, dimensions, activity in specs:
            controls |= self.env['erp.budget.control.service']._resolve(period, unit, analytic, fund, account, dimensions, activity=activity)
        if families:
            service = self.env['erp.budget.control.service']
            historic = self.env['erp.budget.move'].sudo().search([('family_key', 'in', families)]).control_id.with_env(self.env)
            controls |= historic | service._carry_lock_controls(families)
        controls.check_access('read')
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
            controls.period_id._lock_plan_periods()
        expenses._lock_expense_identity()
        return controls

    def _budget_lock_specs(self):
        return [expense._budget_spec() for expense in self], [expense._budget_family() for expense in self]

    def _lock_expense_identity(self):
        self.check_access('write')
        if self:
            self.env.cr.execute('SELECT id FROM hr_expense WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE hr_expense SET erp_budget_lock_version = COALESCE(erp_budget_lock_version, 0) + 1 WHERE id IN %s', [tuple(sorted(self.ids))])

    @contextmanager
    def _budget_workflow(self):
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._lock_budget_expenses()):
            token = _expense_workflow.set(True)
            try:
                yield
                self._budget_related_expenses()._reconcile_expense_budget()
            finally:
                _expense_workflow.reset(token)

    def _capture_expense_budget(self):
        service = self.env['erp.budget.control.service']
        for expense in self._budget_expenses():
            mode, taxes = service._amount_policy(expense.company_id, 'expense')
            service._amount_currency(0, 0, expense.currency_id, expense.company_id, expense.tax_ids, mode, taxes)
            rate = expense.total_amount_currency / expense.total_amount if expense.total_amount else 1
            base = expense._prepare_base_line_for_taxes_computation(price_unit=expense.total_amount_currency, quantity=1, rate=rate)
            tax_model = self.env['account.tax']
            tax_model._add_tax_details_in_base_lines([base], expense.company_id)
            tax_model._round_base_lines_tax_details([base], expense.company_id)
            selected = set(taxes.flatten_taxes_hierarchy().ids)
            amount = expense.untaxed_amount + sum(tax['tax_amount'] for tax in base['tax_details']['taxes_data'] if mode == 'all' or (mode == 'specific' and tax['tax'].id in selected))
            amount = expense.company_currency_id.round(amount)
            if not math.isfinite(amount) or amount <= 0:
                raise ValidationError(_('A controlled expense must have a positive company-currency amount.'))
            expense.write({'erp_budget_amount': amount, 'erp_budget_captured': True, 'erp_budget_snapshot': {'scope': 'expense', 'mode': mode, 'selected_tax_ids': sorted(taxes.ids), 'tax_ids': sorted(expense.tax_ids.ids), 'currency_id': expense.currency_id.id, 'rate': rate, 'unit': expense.price_unit, 'quantity': expense.quantity, 'budget_company_amount': amount}})

    def _reconcile_expense_budget(self, simulate=False):
        service = self.env['erp.budget.control.service']
        for expense in self._budget_expenses():
            controls = expense._budget_controls()
            key = expense._budget_family()
            actuals, provenance = [], {}
            lines = self.env['account.move.line'].sudo().search([('expense_id', '=', expense.id), ('move_id.state', '=', 'posted'), ('tax_line_id', '=', False), ('display_type', 'not in', ['tax', 'payment_term', 'rounding'])]).with_env(self.env)
            lines.check_access('read')
            lines.move_id.check_access('read')
            for line in lines:
                if line.company_id != expense.company_id or line.account_id != expense.account_id:
                    raise ValidationError(_('Expense accounting must retain its company and source account.'))
                expected = service._source_distribution(key, controls, expense.analytic_distribution, line.date)
                if line.analytic_distribution != expected:
                    raise ValidationError(_('Expense accounting must retain its budget analytic dimensions.'))
                amount = line._erp_actual_budget_amount()
                if not line.company_currency_id.is_zero(amount):
                    source = 'account.move.line:%s' % line.id
                    actuals.append((source, controls, amount, line.date))
                    provenance[source] = ('account.move:%s' % line.move_id.id, key)
            # Source uncommits the whole expense when its accounting entry posts.
            remaining = 0 if lines else expense.erp_budget_amount
            eligible = simulate or expense.approval_state == 'approved'
            service._reconcile_purchase_multi(controls, expense.date, key, key, remaining, eligible, [], actuals, provenance, primary_type='expense_commitment')

    def action_submit(self):
        controlled = self._budget_expenses()
        if not controlled:
            return super().action_submit()
        with self._budget_workflow():
            controlled._capture_expense_budget()
            # Submission checks capacity without reserving it.
            with self.env.cr.savepoint() as check:
                controlled._reconcile_expense_budget(simulate=True)
                self.env['erp.budget.control.service']._validate_accounting_totals(controlled._lock_budget_expenses())
                check.rollback()
            return super().action_submit()

    def _do_approve(self):
        if not self._budget_expenses():
            return super()._do_approve()
        with self._budget_workflow():
            self._capture_expense_budget()
            return super()._do_approve()

    def _retain_historical_draft_moves(self):
        moves = self.sudo().account_move_id.filtered(lambda move: move.state == 'draft' and move.line_ids._has_actual_budget_history())
        if moves:
            moves.button_cancel()
            self.filtered(lambda expense: expense.account_move_id in moves).sudo().write({'account_move_id': False})

    def action_reset(self):
        with self._budget_workflow():
            self._check_can_reset_approval()
            self._retain_historical_draft_moves()
            return super().action_reset()

    def _do_refuse(self, reason):
        with self._budget_workflow():
            self._retain_historical_draft_moves()
            return super()._do_refuse(reason)

    @api.model_create_multi
    def create(self, vals_list):
        protected = _CAPTURE | {'erp_budget_lock_version'}
        if any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected):
            raise AccessError(_('Expense budget amounts are captured by the approval workflow.'))
        if any(any(vals.get(key) or self.env.context.get('default_' + key) for key in _KEYS) and (vals.get('approval_state') or self.env.context.get('default_approval_state') or vals.get('account_move_id') or self.env.context.get('default_account_move_id')) for vals in vals_list):
            raise AccessError(_('A controlled expense must begin in draft.'))
        return super().create(vals_list)

    def write(self, vals):
        if (_CAPTURE | {'erp_budget_lock_version'}) & vals.keys() and not _expense_workflow.get():
            raise AccessError(_('Expense budget amounts are captured by the approval workflow.'))
        controlled = self._budget_expenses()
        if controlled or _KEYS & vals.keys():
            self._lock_expense_identity()
            if {'approval_state', 'approval_date', 'account_move_id'} & vals.keys() and not _expense_workflow.get() and not _expense_posting.get():
                raise AccessError(_('Use native expense approval and accounting actions.'))
            if _FINANCIAL & vals.keys() and any(expense.approval_state == 'approved' for expense in self):
                raise UserError(_('Reset the expense before changing its budget source or amount.'))
            if {'company_id', 'employee_id', 'erp_budget_organization_id'} & vals.keys() and self._has_budget_history():
                raise UserError(_('Expense company and employee identity with budget history cannot be changed.'))
        return super().write(vals)

    def _has_budget_history(self):
        return bool(self and self.env['erp.budget.move'].sudo().search_count([('family_key', 'in', [expense._budget_family() for expense in self])], limit=1))

    def unlink(self):
        self._lock_expense_identity()
        if self._has_budget_history():
            raise UserError(_('Expenses with budget history cannot be deleted.'))
        return super().unlink()

    @api.onchange('erp_budget_analytic_id', 'erp_budget_dimension_ids')
    def _onchange_budget_distribution(self):
        for expense in self.filtered('erp_budget_analytic_id'):
            expense.analytic_distribution = {','.join(map(str, sorted({expense.erp_budget_analytic_id.id, *expense.erp_budget_dimension_ids.ids}))): 100}

    def _prepare_payments_vals(self):
        move_vals, payment_vals = super()._prepare_payments_vals()
        if self._budget_expenses():
            distribution = self.env['erp.budget.control.service']._source_distribution(self._budget_family(), self._budget_controls(), self.analytic_distribution, self.date, actual=False)
            for command in move_vals['line_ids']:
                if command[0] == 0 and command[2].get('expense_id') == self.id:
                    command[2]['analytic_distribution'] = distribution
        return move_vals, payment_vals

    def _prepare_move_lines_vals(self):
        values = super()._prepare_move_lines_vals()
        if self._budget_expenses():
            values['analytic_distribution'] = self.env['erp.budget.control.service']._source_distribution(self._budget_family(), self._budget_controls(), self.analytic_distribution, self.date, actual=False)
        return values


class ExpenseBudgetMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _access_domain(self, operation):
        invalid = ~_expense_access(self.env.uid)
        return super()._access_domain(operation) & Domain('line_ids', 'not any!', Domain('expense_id', 'any!', invalid))

    def _erp_expense_lines(self):
        lines = self.sudo().line_ids.filtered(lambda line: not line.tax_line_id and line.display_type not in ('tax', 'payment_term', 'rounding') and line.expense_id and any(line.expense_id[key] for key in _KEYS)).with_env(self.env)
        lines.check_access('read')
        lines.expense_id.check_access('read')
        return lines

    def _erp_budget_amount_lines(self):
        return super()._erp_budget_amount_lines() | self._erp_expense_lines()

    def _budget_scope_specs(self):
        specs, families = super()._budget_scope_specs()
        extra_specs, extra_families = self._erp_expense_lines().expense_id._budget_related_expenses()._budget_lock_specs()
        specs.extend(extra_specs)
        families.extend(extra_families)
        return specs, families

    def _budget_financial_transition(self):
        return super()._budget_financial_transition() or _expense_posting.get()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        expenses = self._erp_expense_lines().expense_id
        if not expenses:
            return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)
        origins = {expense.id: expense.account_move_id.id for expense in expenses}
        token = _expense_posting.set(True)
        try:
            with self.env.cr.savepoint():
                result = super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)
                for expense in expenses:
                    expense.sudo().write({'account_move_id': origins[expense.id]})
                return result
        finally:
            _expense_posting.reset(token)

    def button_cancel(self):
        token = _expense_posting.set(True)
        try:
            return super().button_cancel()
        finally:
            _expense_posting.reset(token)

    def _post(self, soft=True):
        expenses = self._erp_expense_lines().expense_id
        if not expenses:
            return super()._post(soft=soft)
        self.check_access('write')
        if any(expense.approval_state != 'approved' for expense in expenses) or self.filtered('erp_budget_exempt'):
            raise ValidationError(_('Controlled expense accounting requires approved expenses and cannot be exempted.'))
        for line in self._erp_expense_lines():
            if line.move_id != line.expense_id.account_move_id and not line.move_id.reversed_entry_id:
                raise ValidationError(_('Only the current expense accounting document or its native reversal may post.'))
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()):
            expenses._lock_expense_identity()
            self._capture_budget_amount_policy()
            token = _expense_posting.set(True)
            try:
                posted = super()._post(soft=soft)
                posted._finalize_budget_amounts()
                expenses._budget_related_expenses()._reconcile_expense_budget()
                return posted
            finally:
                _expense_posting.reset(token)

    def write(self, vals):
        expenses = self._erp_expense_lines().expense_id
        if expenses and self.filtered(lambda move: move.state == 'posted') and not self._budget_financial_transition():
            if {'state', 'date', 'invoice_date', 'company_id', 'currency_id', 'move_type', 'reversed_entry_id', 'invoice_currency_rate', 'partner_id', 'journal_id'} & vals.keys():
                raise UserError(_('Use native accounting reset before changing expense actuals.'))
        if expenses and vals.get('state') in ('draft', 'cancel'):
            with self.env.cr.savepoint():
                result = super().write(vals)
                expenses._budget_related_expenses()._reconcile_expense_budget()
                return result
        return super().write(vals)


class ExpenseBudgetMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model
    def _access_domain(self, operation):
        invalid = ~_expense_access(self.env.uid)
        return super()._access_domain(operation) & Domain('move_id', 'any!', Domain('line_ids', 'not any!', Domain('expense_id', 'any!', invalid)))

    def _copy_data_extend_business_fields(self, values):
        super()._copy_data_extend_business_fields(values)
        if self.expense_id._budget_expenses():
            values['expense_id'] = self.expense_id.id

    def write(self, vals):
        if 'expense_id' in vals and any(line.move_id.state == 'posted' or line._has_actual_budget_history() for line in self):
            raise UserError(_('An expense accounting source with budget history cannot be reassigned.'))
        return super().write(vals)


class ExpenseBudgetLedger(models.Model):
    _inherit = 'erp.budget.move'

    def _planning_source(self):
        self.ensure_one()
        model, separator, identifier = (self.source_key or '').partition(':')
        if model == 'hr.expense' and separator and identifier.isdigit():
            expense = self.env[model].browse(int(identifier)).exists()
            if expense:
                return expense, expense.erp_budget_activity_id.account_id or expense.account_id, expense.erp_budget_activity_id
        return super()._planning_source()

    def _source_amount_snapshot(self, values):
        model, separator, identifier = (values.get('source_key') or '').partition(':')
        if model == 'hr.expense' and separator and identifier.isdigit():
            return self.env[model].browse(int(identifier)).erp_budget_snapshot
        return super()._source_amount_snapshot(values)


class ExpenseBudgetActivity(models.Model):
    _inherit = 'erp.budget.activity'

    def _has_document_usage(self):
        return super()._has_document_usage() or bool(self.env['hr.expense'].sudo().search_count([('erp_budget_activity_id', 'in', self.ids)], limit=1))
