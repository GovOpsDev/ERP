"""Employee advances, ordered clearing and bank returns on native accounting."""
from contextvars import ContextVar
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from .expense import _expense_access, _expense_workflow

_advance_internal = ContextVar('erp_advance_internal', default=False)
_ADVANCE_FIELDS = {'erp_is_advance', 'erp_advance_ids', 'erp_clearing_product_id', 'erp_clearing_activity_id'}


class AdvanceCompany(models.Model):
    _inherit = 'res.company'

    erp_employee_advance_account_id = fields.Many2one('account.account', check_company=True, groups='account.group_account_manager', string='Employee Advance Account')
    erp_employee_advance_journal_id = fields.Many2one('account.journal', check_company=True, groups='account.group_account_manager', string='Advance Settlement Journal')

    def write(self, vals):
        if 'erp_employee_advance_account_id' in vals:
            for company in self:
                if company.erp_employee_advance_account_id.id != vals['erp_employee_advance_account_id'] and self.env['hr.expense'].sudo().search_count([('company_id', '=', company.id), ('erp_is_advance', '=', True)], limit=1):
                    raise UserError(_('The employee advance account cannot change while advance documents retain that source identity.'))
        return super().write(vals)


class AdvanceSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    erp_employee_advance_account_id = fields.Many2one(related='company_id.erp_employee_advance_account_id', readonly=False, groups='account.group_account_manager')
    erp_employee_advance_journal_id = fields.Many2one(related='company_id.erp_employee_advance_journal_id', readonly=False, groups='account.group_account_manager')


class AdvanceExpense(models.Model):
    _inherit = 'hr.expense'

    erp_is_advance = fields.Boolean(string='Employee Advance')
    erp_clearing_product_id = fields.Many2one('product.product', check_company=True, ondelete='restrict', string='Default Clearing Product')
    erp_clearing_activity_id = fields.Many2one('erp.budget.activity', check_company=True, ondelete='restrict', string='Default Clearing Activity')
    erp_advance_ids = fields.Many2many('hr.expense', 'erp_expense_advance_rel', 'clearing_id', 'advance_id', check_company=True, string='Clear Advances', copy=False)
    erp_advance_settlement_ids = fields.One2many('account.move', 'erp_advance_clearing_expense_id', string='Advance Settlements', readonly=True)
    erp_advance_remaining = fields.Monetary(currency_field='company_currency_id', compute='_compute_advance_remaining')

    @api.onchange('erp_is_advance')
    def _onchange_employee_advance(self):
        for expense in self.filtered('erp_is_advance'):
            expense.account_id = expense.company_id.sudo().erp_employee_advance_account_id
            expense.tax_ids = False
            expense.payment_mode = 'own_account'
            expense.erp_advance_ids = False

    def action_prepare_clearing(self):
        self.ensure_one()
        self.check_access('read')
        if not self.erp_is_advance or self.account_move_id.state != 'posted':
            raise UserError(_('A posted employee advance is required.'))
        remaining, allocations = self._advance_allocations()
        if remaining[self.id] <= 0:
            raise UserError(_('No advance remains after approved clearings and returns.'))
        service = self.env['erp.budget.control.service']
        controls, date = service._forward_route(self._budget_family(), self._budget_controls(), self.date)
        analytic = controls.filtered(lambda control: control.level == 'analytic').analytic_id
        product = self.erp_clearing_product_id
        activity = self.erp_clearing_activity_id
        values = {'default_name': self.name, 'default_company_id': self.company_id.id, 'default_employee_id': self.employee_id.id, 'default_erp_advance_ids': [(6, 0, self.ids)], 'default_payment_mode': 'own_account', 'default_product_id': product.id, 'default_account_id': (activity.account_id or product.with_company(self.company_id).property_account_expense_id).id, 'default_currency_id': self.company_currency_id.id, 'default_total_amount_currency': remaining[self.id], 'default_quantity': 1, 'default_date': max(fields.Date.context_today(self), controls.period_id.date_from), 'default_erp_budget_period_id': controls.period_id.id, 'default_erp_budget_organization_id': self.erp_budget_organization_id.id, 'default_erp_budget_fund_id': self.erp_budget_fund_id.id, 'default_erp_budget_analytic_id': analytic.id, 'default_erp_budget_activity_id': activity.id, 'default_erp_budget_dimension_ids': [(6, 0, self.erp_budget_dimension_ids.ids)], 'default_analytic_distribution': service._source_distribution(self._budget_family(), self._budget_controls(), self.analytic_distribution, self.date, actual=False)}
        return {'type': 'ir.actions.act_window', 'name': _('Clear Employee Advance'), 'res_model': 'hr.expense', 'view_mode': 'form', 'context': values}

    def action_prepare_advance_return(self):
        self.ensure_one()
        self.check_access('read')
        remaining, allocations = self._advance_allocations()
        if not self.erp_is_advance or self.account_move_id.state != 'posted' or remaining.get(self.id, 0) <= 0:
            raise UserError(_('A posted advance with remaining funds is required.'))
        return {'type': 'ir.actions.act_window', 'name': _('Return Employee Advance'), 'res_model': 'erp.finance.advance.return', 'view_mode': 'form', 'context': {'default_name': self.name, 'default_advance_id': self.id, 'default_amount': remaining[self.id], 'default_currency_id': self.company_currency_id.id}}

    def _expense_tier_kind(self):
        return 'advance' if self.erp_is_advance else super()._expense_tier_kind()

    @api.depends('erp_is_advance', 'account_move_id.line_ids.amount_residual')
    def _compute_advance_remaining(self):
        for expense in self:
            expense.erp_advance_remaining = sum(expense.account_move_id.line_ids.filtered(lambda line: line.account_id == expense.account_id).mapped('amount_residual')) if expense.erp_is_advance else 0

    @api.constrains('erp_is_advance', 'erp_advance_ids', 'account_id', 'tax_ids', 'payment_mode', 'company_id', 'employee_id', 'erp_budget_organization_id')
    def _check_advance_sources(self):
        for expense in self:
            if expense.erp_is_advance:
                account = expense.company_id.sudo().erp_employee_advance_account_id.with_env(self.env)
                if not account or expense.account_id != account or not account.reconcile or account.account_type != 'asset_current':
                    raise ValidationError(_('An advance requires the configured reconcilable current-asset employee advance account.'))
                if expense.tax_ids or expense.payment_mode != 'own_account' or expense.erp_advance_ids:
                    raise ValidationError(_('Advances are employee-paid, tax-free and cannot clear other advances.'))
            if expense.erp_advance_ids:
                if expense.payment_mode != 'own_account' or any(not advance.erp_is_advance or advance.company_id != expense.company_id or advance.employee_id != expense.employee_id or advance.erp_budget_organization_id != expense.erp_budget_organization_id for advance in expense.erp_advance_ids):
                    raise ValidationError(_('Clearing requires employee-paid expenses and advances for the same company, employee and organization.'))

    def _budget_spec(self):
        spec = super()._budget_spec()
        self._check_advance_sources()
        if self.erp_budget_period_id.template_id:
            kpi = self.erp_budget_period_id.template_id._kpi_for_account(spec[4], activity=spec[6])
            if bool(kpi.advance_reservation) != bool(self.erp_is_advance):
                raise ValidationError(_('Use the advance-reservation KPI only for employee advances; clearing uses its expense KPI.'))
        return spec

    def _budget_related_expenses(self):
        records = super()._budget_related_expenses()
        # Lock the complete connected set before touching any common advance.
        while records:
            advances = records.filtered('erp_is_advance') | records.erp_advance_ids
            linked = self.sudo().search([('erp_advance_ids', 'in', advances.ids)]).with_env(self.env) if advances else self.browse()
            combined = records | advances | linked
            combined.check_access('read')
            if combined == records:
                break
            records = combined
        return records

    def _advance_clearing_amount(self):
        self.ensure_one()
        return self.total_amount

    def _advance_allocations(self, budget=False, simulated=None):
        """FIFO distribution across source advances and approved clearings."""
        related = self._budget_related_expenses()
        advances = related.filtered('erp_is_advance').sorted(lambda item: (item.approval_date or fields.Datetime.from_string('1970-01-01'), item.id))
        returns = self.env['account.move.line'].sudo().search([('erp_advance_origin_id', 'in', advances.ids), ('move_id.erp_advance_return_id', '!=', False), ('move_id.state', '=', 'posted')]).with_env(self.env)
        returns.check_access('read')
        remaining = {advance.id: (advance.erp_budget_amount if budget else advance.total_amount) + sum(returns.filtered(lambda line: line.erp_advance_origin_id == advance).mapped('balance')) for advance in advances}
        allocations = {}
        clearing = related.filtered(lambda expense: expense.erp_advance_ids and (expense.approval_state == 'approved' or expense in (simulated or self.browse())))
        for expense in clearing.sorted(lambda item: (item.approval_date or fields.Datetime.now(), item.id)):
            amount = expense.erp_budget_amount if budget else expense._advance_clearing_amount()
            allocations[expense.id] = {}
            for advance in advances & expense.erp_advance_ids:
                taken = min(max(0, remaining[advance.id]), amount)
                if taken:
                    allocations[expense.id][advance.id] = taken
                    remaining[advance.id] -= taken
                    amount -= taken
        return remaining, allocations

    def _validate_clearing_approval(self):
        for expense in self.filtered('erp_advance_ids'):
            expense.erp_advance_ids.check_access('read')
            if any(advance.approval_state != 'approved' or advance.account_move_id.state != 'posted' for advance in expense.erp_advance_ids):
                raise UserError(_('Post the approved advance before submitting its clearing.'))
            _, allocations = expense._advance_allocations(simulated=expense)
            if not allocations.get(expense.id):
                raise UserError(_('The advances have no amount remaining after approved clearings and returns.'))

    def action_submit(self):
        if self.filtered(lambda expense: expense.erp_is_advance or expense.erp_advance_ids) - self._budget_expenses():
            raise ValidationError(_('Select the full Budget key for an employee advance or clearing.'))
        with self._budget_workflow():
            self._validate_clearing_approval()
            return super().action_submit()

    def _do_approve(self):
        with self._budget_workflow():
            self._validate_clearing_approval()
            return super()._do_approve()

    def _reconcile_expense_budget(self, simulate=False):
        related = self._budget_related_expenses()
        ordinary = related - related.filtered('erp_is_advance')
        for expense in ordinary:
            super(AdvanceExpense, expense)._reconcile_expense_budget(simulate=simulate and expense in self)
        remaining, allocations = related._advance_allocations(budget=True, simulated=self if simulate else None) if related.filtered('erp_is_advance') else ({}, {})
        service = self.env['erp.budget.control.service']
        for advance in related.filtered('erp_is_advance'):
            controls = advance._budget_controls()
            key = advance._budget_family()
            amount = max(0, remaining[advance.id])
            eligible = advance.approval_state == 'approved' or (simulate and advance in self)
            service._reconcile_purchase_multi(controls, advance.date, key, key, amount, eligible, [], [], {}, primary_type='advance_commitment')

    def write(self, vals):
        if _ADVANCE_FIELDS & vals.keys():
            self._lock_expense_identity()
            if any(expense.approval_state in ('approved', 'submitted') or expense._has_budget_history() for expense in self):
                raise UserError(_('Advance and clearing source identities with approval history cannot be changed.'))
        if 'erp_advance_settlement_ids' in vals and not _advance_internal.get():
            raise AccessError(_('Advance settlements are created only by native posting.'))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if any('erp_advance_settlement_ids' in vals for vals in vals_list) or 'default_erp_advance_settlement_ids' in self.env.context:
            raise AccessError(_('Advance settlement history cannot be supplied by clients.'))
        return super().create(vals_list)

    def _create_advance_settlement(self):
        self.ensure_one()
        if self.erp_advance_settlement_ids.filtered(lambda move: move.state == 'posted'):
            return
        remaining, allocations = self._advance_allocations()
        amounts = allocations.get(self.id, {})
        if not amounts:
            raise UserError(_('The advance is already fully cleared or returned.'))
        bill = self.account_move_id
        journal = self.company_id.sudo().erp_employee_advance_journal_id.with_env(self.env)
        if not journal or journal.company_id != self.company_id or journal.type != 'general':
            raise ValidationError(_('Configure a general journal for employee advance settlement.'))
        payable = bill.line_ids.filtered(lambda line: line.account_type == 'liability_payable')
        if len(payable.account_id) != 1:
            raise ValidationError(_('A clearing receipt must have one employee payable account.'))
        total = sum(amounts.values())
        lines = [{'name': self.name, 'account_id': payable.account_id.id, 'partner_id': payable.partner_id.id, 'balance': total}]
        for advance in self.erp_advance_ids:
            amount = amounts.get(advance.id, 0)
            if amount:
                lines.append({'name': self.name, 'account_id': advance.account_id.id, 'partner_id': advance.employee_id.work_contact_id.id, 'balance': -amount, 'erp_advance_origin_id': advance.id})
        token = _advance_internal.set(True)
        try:
            entry = self.env['account.move'].create({'move_type': 'entry', 'date': bill.date, 'journal_id': journal.id, 'company_id': self.company_id.id, 'ref': self.name, 'erp_advance_clearing_expense_id': self.id, 'line_ids': [(0, 0, line) for line in lines]})
            entry.action_post()
            (payable | entry.line_ids.filtered(lambda line: line.account_id == payable.account_id)).filtered(lambda line: not line.reconciled).reconcile()
            for advance in self.erp_advance_ids:
                native = advance.account_move_id.line_ids.filtered(lambda line: line.account_id == advance.account_id)
                clearing = entry.line_ids.filtered(lambda line: line.erp_advance_origin_id == advance)
                if clearing:
                    (native | clearing).filtered(lambda line: not line.reconciled).reconcile()
        finally:
            _advance_internal.reset(token)


class AdvanceAccountingMove(models.Model):
    _inherit = 'account.move'

    erp_advance_clearing_expense_id = fields.Many2one('hr.expense', check_company=True, ondelete='restrict', readonly=True, copy=False)
    erp_advance_return_id = fields.Many2one('erp.finance.advance.return', check_company=True, ondelete='restrict', readonly=True, copy=False)

    @api.model
    def _access_domain(self, operation):
        invalid = ~_expense_access(self.env.uid)
        return super()._access_domain(operation) & Domain('line_ids', 'not any!', Domain('erp_advance_origin_id', 'any!', invalid))

    def _advance_sources(self):
        expenses = self.sudo().line_ids.erp_advance_origin_id.with_env(self.env)
        expenses.check_access('read')
        return expenses

    def _budget_scope_specs(self):
        specs, families = super()._budget_scope_specs()
        extra_specs, extra_families = self._advance_sources()._budget_related_expenses()._budget_lock_specs()
        specs.extend(extra_specs)
        families.extend(extra_families)
        return specs, families

    def _post(self, soft=True):
        clearing = self._erp_expense_lines().expense_id.filtered('erp_advance_ids')
        sources = self._advance_sources()
        if not clearing and not sources:
            return super()._post(soft=soft)
        if sources and not _advance_internal.get():
            raise AccessError(_('Post an advance settlement or return through its source workflow.'))
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()):
            related = (clearing | sources)._budget_related_expenses()
            related._lock_expense_identity()
            posted = super()._post(soft=soft)
            for expense in clearing.filtered(lambda expense: expense.account_move_id in posted):
                expense._create_advance_settlement()
            related._reconcile_expense_budget()
            return posted

    def _check_advance_reversal(self):
        for advance in self._erp_expense_lines().expense_id.filtered('erp_is_advance'):
            entries = self.env['account.move.line'].sudo().search_count([('erp_advance_origin_id', '=', advance.id), ('move_id.state', '=', 'posted')], limit=1)
            if entries or advance.account_move_id.line_ids.filtered(lambda line: line.account_id == advance.account_id and (line.matched_debit_ids or line.matched_credit_ids)):
                raise UserError(_('Cancel advance clearings and returns before resetting or reversing the advance.'))

    def _cancel_advance_settlements(self):
        settlements = self._erp_expense_lines().expense_id.erp_advance_settlement_ids.filtered(lambda move: move.state == 'posted')
        token = _advance_internal.set(True)
        try:
            if settlements:
                settlements.button_draft()
                settlements.button_cancel()
        finally:
            _advance_internal.reset(token)

    def button_draft(self):
        if self.filtered(lambda move: move.erp_advance_clearing_expense_id or move.erp_advance_return_id) and not _advance_internal.get():
            raise AccessError(_('Reset the original clearing or return document.'))
        self._check_advance_reversal()
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()):
            self._cancel_advance_settlements()
            return super().button_draft()

    def button_cancel(self):
        if self.filtered(lambda move: move.erp_advance_clearing_expense_id or move.erp_advance_return_id) and not _advance_internal.get():
            raise AccessError(_('Cancel the original clearing or return document.'))
        self._check_advance_reversal()
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()):
            self._cancel_advance_settlements()
            return super().button_cancel()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        self._check_advance_reversal()
        if self._advance_sources() or self._erp_expense_lines().expense_id.filtered('erp_advance_ids'):
            raise UserError(_('Reset and cancel the original advance clearing or return to reverse its accounting and budget together.'))
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'erp_advance_clearing_expense_id', 'erp_advance_return_id'}
        if not _advance_internal.get() and (any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected)):
            raise AccessError(_('Advance accounting origins are created only by the source workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'erp_advance_clearing_expense_id', 'erp_advance_return_id'} & vals.keys() and not _advance_internal.get():
            raise AccessError(_('Advance accounting origins are immutable.'))
        sources = self._advance_sources()
        if sources and not _advance_internal.get() and {'state', 'line_ids', 'date', 'company_id', 'currency_id', 'journal_id'} & vals.keys():
            raise AccessError(_('Advance accounting is managed by its source workflow.'))
        result = super().write(vals)
        if sources and vals.get('state') in ('draft', 'cancel'):
            sources._budget_related_expenses()._reconcile_expense_budget()
        return result

    def unlink(self):
        if self.filtered(lambda move: move.erp_advance_clearing_expense_id or move.erp_advance_return_id):
            raise UserError(_('Advance settlement and return accounting history cannot be deleted.'))
        return super().unlink()


class AdvanceAccountingLine(models.Model):
    _inherit = 'account.move.line'

    erp_advance_origin_id = fields.Many2one('hr.expense', check_company=True, ondelete='restrict', readonly=True, copy=False, index=True)

    @api.model
    def _access_domain(self, operation):
        invalid = ~_expense_access(self.env.uid)
        return super()._access_domain(operation) & Domain('move_id', 'any!', Domain('line_ids', 'not any!', Domain('erp_advance_origin_id', 'any!', invalid)))

    @api.model_create_multi
    def create(self, vals_list):
        if not _advance_internal.get() and (any('erp_advance_origin_id' in vals for vals in vals_list) or 'default_erp_advance_origin_id' in self.env.context):
            raise AccessError(_('Advance accounting lines are created by source workflows.'))
        return super().create(vals_list)

    def write(self, vals):
        controlled = self.filtered(lambda line: line.move_id.erp_advance_clearing_expense_id or line.move_id.erp_advance_return_id)
        sensitive = {'erp_advance_origin_id', 'move_id', 'account_id', 'balance', 'debit', 'credit', 'amount_currency', 'currency_id', 'company_id', 'partner_id', 'tax_ids', 'analytic_distribution', 'expense_id', 'purchase_line_id', 'erp_contract_line_id', 'erp_budget_period_id', 'erp_budget_organization_id', 'erp_budget_analytic_id', 'erp_budget_fund_id', 'erp_budget_direct_activity_id', 'erp_budget_dimension_ids', 'quantity', 'price_unit', 'discount', 'display_type'}
        if (controlled and sensitive & vals.keys() or 'erp_advance_origin_id' in vals) and not _advance_internal.get():
            raise AccessError(_('Advance settlement amounts and origins are immutable.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda line: line.move_id.erp_advance_clearing_expense_id or line.move_id.erp_advance_return_id):
            raise UserError(_('Advance accounting lines are retained for audit.'))
        return super().unlink()


class AdvanceReturn(models.Model):
    _name = 'erp.finance.advance.return'
    _description = 'Employee Advance Return'
    _check_company_auto = True

    name = fields.Char(required=True, string='Reference')
    advance_id = fields.Many2one('hr.expense', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='advance_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='advance_id.erp_budget_organization_id', store=True, index=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one('account.journal', required=True, check_company=True, ondelete='restrict')
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(required=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Returned'), ('cancel', 'Cancelled')], required=True, default='draft', readonly=True, copy=False)
    move_id = fields.Many2one('account.move', readonly=True, copy=False, check_company=True, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'state', 'move_id', 'company_id', 'organization_id'}
        if any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected):
            raise AccessError(_('Advance returns begin in draft with derived scope.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _advance_internal.get():
            if {'state', 'move_id', 'advance_id', 'company_id', 'organization_id'} & vals.keys() or any(doc.state != 'draft' or doc.move_id for doc in self):
                raise AccessError(_('Applied return history is immutable.'))
        return super().write(vals)

    def unlink(self):
        if any(doc.state != 'draft' or doc.move_id for doc in self):
            raise UserError(_('Applied advance return history cannot be deleted.'))
        return super().unlink()

    def action_post(self):
        self.ensure_one()
        self.check_access('write')
        advance = self.advance_id
        advance.check_access('read')
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(advance._lock_budget_expenses()):
            self.env.cr.execute('SELECT id FROM erp_finance_advance_return WHERE id = %s FOR UPDATE', [self.id])
            if self.state == 'done':
                return True
            if self.state != 'draft' or self.move_id or not advance.erp_is_advance or advance.account_move_id.state != 'posted':
                raise UserError(_('A new draft return for a posted advance is required.'))
            if not math.isfinite(self.amount) or self.amount <= 0 or self.journal_id.type not in ('bank', 'cash') or not self.journal_id.default_account_id:
                raise ValidationError(_('A return requires a positive amount and a configured bank or cash journal.'))
            if self.journal_id.currency_id and self.journal_id.currency_id != self.currency_id:
                raise ValidationError(_('Return currency must match the bank journal currency.'))
            amount = self.currency_id._convert(self.amount, self.company_id.currency_id, self.company_id, self.date)
            if self.currency_id.compare_amounts(self.amount, self.currency_id.round(self.amount)) or amount <= 0:
                raise ValidationError(_('Return amounts must use currency precision and a positive company amount.'))
            remaining, allocations = advance._advance_allocations()
            if self.company_id.currency_id.compare_amounts(amount, remaining[advance.id]) > 0:
                raise UserError(_('The return exceeds the remaining advance after approved clearings.'))
            token = _advance_internal.set(True)
            try:
                partner = advance.employee_id.work_contact_id
                entry = self.env['account.move'].create({'move_type': 'entry', 'company_id': self.company_id.id, 'journal_id': self.journal_id.id, 'date': self.date, 'currency_id': self.currency_id.id, 'ref': self.name, 'erp_advance_return_id': self.id, 'line_ids': [(0, 0, {'name': self.name, 'account_id': self.journal_id.default_account_id.id, 'balance': amount, 'amount_currency': self.amount, 'currency_id': self.currency_id.id, 'partner_id': partner.id}), (0, 0, {'name': self.name, 'account_id': advance.account_id.id, 'balance': -amount, 'amount_currency': -self.amount, 'currency_id': self.currency_id.id, 'partner_id': partner.id, 'erp_advance_origin_id': advance.id})]})
                entry.action_post()
                lines = advance.account_move_id.line_ids.filtered(lambda line: line.account_id == advance.account_id) | entry.line_ids.filtered('erp_advance_origin_id')
                lines.filtered(lambda line: not line.reconciled).reconcile()
                self.write({'state': 'done', 'move_id': entry.id})
            finally:
                _advance_internal.reset(token)
            return True

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self.advance_id._lock_budget_expenses()):
            self.env.cr.execute('SELECT id FROM erp_finance_advance_return WHERE id = %s FOR UPDATE', [self.id])
            if self.state == 'cancel':
                return True
            token = _advance_internal.set(True)
            try:
                if self.move_id:
                    self.move_id.button_draft()
                    self.move_id.button_cancel()
                self.write({'state': 'cancel'})
            finally:
                _advance_internal.reset(token)
            return True


class AdvanceLedgerProvenance(models.Model):
    _inherit = 'erp.budget.move'

    def _source_amount_snapshot(self, values):
        snapshot = super()._source_amount_snapshot(values)
        model, separator, identifier = (values.get('source_key') or '').partition(':')
        if model == 'hr.expense' and separator and identifier.isdigit():
            advance = self.env['hr.expense'].browse(int(identifier)).exists()
            if advance.erp_is_advance:
                remaining, allocations = advance._advance_allocations(budget=True)
                returns = self.env['account.move.line'].search([('erp_advance_origin_id', '=', advance.id), ('move_id.erp_advance_return_id', '!=', False), ('move_id.state', '=', 'posted')])
                snapshot = dict(snapshot or {}, advance_company_amount=advance.total_amount, remaining_commitment=max(0, remaining[advance.id]), clearing_allocations={str(expense_id): amounts[advance.id] for expense_id, amounts in allocations.items() if amounts.get(advance.id)}, return_line_ids=sorted(returns.ids))
        return snapshot
