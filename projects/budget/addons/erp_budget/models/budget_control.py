import hashlib
import json
import math
from contextlib import contextmanager
from contextvars import ContextVar

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

_accounting_batch = ContextVar('erp_budget_accounting_batch', default=None)

_release_open = ContextVar('budget_release_open', default=False)
_release_close = ContextVar('budget_release_close', default=False)


class BudgetControl(models.Model):
    _name = 'erp.budget.control'
    _description = 'Budget Control Allocation'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict', index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict', index=True)
    analytic_id = fields.Many2one('account.analytic.account', required=True, check_company=True, ondelete='restrict', index=True)
    level = fields.Selection([('analytic', 'Analytic / KPI'), ('fund', 'Fund / Dimensions')], required=True)
    kpi_id = fields.Many2one('erp.budget.kpi', check_company=True, ondelete='restrict')
    fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict')
    dimension_ids = fields.Many2many('account.analytic.account', 'erp_budget_control_dimension_rel', 'control_id', 'analytic_id', check_company=True)
    amount = fields.Monetary(required=True)
    state = fields.Selection([('draft', 'Draft'), ('open', 'Open'), ('closed', 'Closed')], required=True, default='draft')
    active = fields.Boolean(default=True)
    lock_version = fields.Integer(default=0, readonly=True)
    allocation_line_id = fields.Many2one('erp.budget.allocation.line', readonly=True, ondelete='restrict', check_company=True, index=True)
    erp_release_reversed = fields.Boolean(default=False, readonly=True, copy=False)
    move_ids = fields.One2many('erp.budget.move', 'control_id', readonly=True)
    available_amount = fields.Monetary(compute='_compute_available_amount', string='Available (display only)')

    def _has_child_capacity_limit(self):
        self.ensure_one()
        return not (self.level == 'analytic' and self.period_id.control_level == 'analytic_kpi' and self.kpi_id.advance_reservation)

    @api.depends('amount', 'move_ids.amount')
    def _compute_available_amount(self):
        for row in self:
            row.available_amount = row.amount - sum(row.move_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        from .budget_allocation import _allocation_internal
        for vals in vals_list:
            if (vals.get('allocation_line_id') or 'default_allocation_line_id' in self.env.context) and not _allocation_internal.get():
                raise AccessError(_('Allocation links are generated internally.'))
            if 'erp_release_reversed' in vals or 'default_erp_release_reversed' in self.env.context:
                raise AccessError(_('Release status is internal.'))
            if vals.get('state', 'draft') != 'draft':
                raise AccessError(_('A budget allocation must begin in draft.'))
            company_id = vals.get('company_id', self.env.company.id)
            if not self.env.su and company_id not in self.env.companies.ids:
                raise AccessError(_('The company must be active.'))
            unit = self.env['erp.organization.unit'].browse(vals.get('organization_id')).exists()
            if not unit:
                raise ValidationError(_('An active organization is required.'))
            unit.check_access('read')
            if not unit.active:
                raise ValidationError(_('An active organization is required.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        from .budget_release import _planning_internal
        if _planning_internal.get() and set(vals) == {'amount'} and all(row.level == 'analytic' for row in self):
            return super().write(vals)
        if 'allocation_line_id' in vals or any(row.allocation_line_id for row in self):
            raise AccessError(_('Allocation-backed controls are immutable.'))
        if {'state', 'erp_release_reversed'} & vals.keys():
            raise AccessError(_('Use the budget allocation actions to change state.'))
        if {'name', 'company_id', 'period_id', 'organization_id', 'analytic_id', 'level', 'kpi_id', 'fund_id', 'dimension_ids', 'amount', 'active'} & vals.keys() and self:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.mapped('period_id')._lock_plan_periods()
            if self.env['erp.budget.kpi.release.line'].sudo().search_count([('control_id', 'in', self.ids), ('release_id.state', 'in', ('submit', 'done'))]):
                raise UserError(_('Controls in a submitted or released allocation cannot be changed.'))
        if any(row.state != 'draft' for row in self):
            raise UserError(_('Only draft allocations may be edited.'))
        if vals.get('organization_id'):
            unit = self.env['erp.organization.unit'].browse(vals['organization_id']).exists()
            if not unit:
                raise ValidationError(_('An active organization is required.'))
            unit.check_access('read')
            if not unit.active:
                raise ValidationError(_('An active organization is required.'))
        if 'company_id' in vals and not self.env.su and vals['company_id'] not in self.env.companies.ids:
            raise AccessError(_('The company must be active.'))
        return super().write(vals)

    def unlink(self):
        if any(row.allocation_line_id for row in self):
            raise AccessError(_('Allocation-backed controls cannot be deleted.'))
        if any(row.state != 'draft' for row in self):
            raise UserError(_('Only draft allocations may be deleted.'))
        return super().unlink()

    @api.constrains('amount', 'level', 'fund_id', 'kpi_id', 'dimension_ids', 'analytic_id')
    def _check_allocation(self):
        for row in self:
            if not math.isfinite(row.amount) or row.amount < 0:
                raise ValidationError(_('Allocated amount must be nonnegative.'))
            if row.level == 'analytic' and (row.fund_id or row.dimension_ids):
                raise ValidationError(_('Analytic control does not contain fund dimensions.'))
            if row.level == 'fund' and (not row.fund_id or row.kpi_id):
                raise ValidationError(_('Fund control requires a fund and no KPI.'))
            plans = row.dimension_ids.mapped('root_plan_id')
            if len(plans) != len(row.dimension_ids):
                raise ValidationError(_('Each dimension must belong to a different analytic root plan.'))
            if row.analytic_id.root_plan_id in plans:
                raise ValidationError(_('The primary analytic account and dimensions must belong to different root plans.'))

    def _set_allocation_revision_amount(self, amount):
        from .budget_allocation import _allocation_internal
        if not _allocation_internal.get() or any(not row.allocation_line_id for row in self):
            raise AccessError(_('Allocation revision amount is internal.'))
        return super(BudgetControl, self).write({'amount': amount})

    def _prepare_control_restoration(self):
        from .budget_allocation import _allocation_internal
        from .budget_release import _planning_internal
        if not _allocation_internal.get() or any(row.state != 'closed' or (row.level == 'fund' and not row.allocation_line_id) or (row.level == 'analytic' and not _planning_internal.get()) for row in self):
            raise AccessError(_('Control restoration is internal to an allocation successor.'))
        return super(BudgetControl, self).write({'state': 'draft'})

    def action_open(self):
        self.check_access('write')
        if self:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.mapped('period_id')._lock_plan_periods()
        for period in self.mapped('period_id'):
            allocation = self.env['erp.budget.allocation'].sudo().search([('period_id', '=', period.id), ('plan_id', '!=', False)], limit=1)
            if allocation.state == 'cancel':
                raise UserError(_('A cancelled allocation must be restored through its revision workflow.'))
            if allocation and allocation.plan_id.state not in ('confirm', 'done'):
                raise UserError(_('Confirm the allocation-generated plan before opening controls.'))
        plan_lines = self.env['erp.budget.control.service']._plan_lines_for_controls(self)
        for line in {line.id: line for line in plan_lines.values()}.values():
            if line.release_required and not _release_open.get():
                raise AccessError(_('Open these controls through an approved KPI release.'))
            if line.allocation_mode == 'allocated' and float_compare(line._allocated(self.ids), line._ceiling(), precision_rounding=line.currency_id.rounding) > 0:
                raise UserError(_('Child allocations exceed the plan ceiling.'))
        for row in self:
            if row.level == 'fund':
                allocations = self.env['erp.budget.allocation'].sudo().search([('period_id', '=', row.period_id.id), ('plan_id', '!=', False)])
                if allocations and (not row.allocation_line_id or row.allocation_line_id.allocation_id not in allocations):
                    raise AccessError(_('Fund controls in an allocated period must be backed by its allocation.'))
            if row.erp_release_reversed or row.state != 'draft' or not row.active or not row.organization_id.active:
                raise UserError(_('Only active draft allocations can be opened.'))
            if not row.analytic_id.active or (row.fund_id and not row.fund_id.active) or (row.kpi_id and not row.kpi_id.active) or any(not d.active for d in row.dimension_ids):
                raise ValidationError(_('Allocation references must be active.'))
        return super(BudgetControl, self).write({'state': 'open'})

    def action_close(self):
        self.check_access('write')
        if self:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.mapped('period_id')._lock_plan_periods()
        if not _release_close.get() and self.env['erp.budget.kpi.release.line'].sudo().search_count([('control_id', 'in', self.ids), ('release_id.state', '=', 'done')]):
            raise AccessError(_('Close released controls through release reversal.'))
        if any(row.state != 'open' for row in self):
            raise UserError(_('Only open allocations can be closed.'))
        return super(BudgetControl, self).write({'state': 'closed'})


class BudgetMove(models.Model):
    _name = 'erp.budget.move'
    _description = 'Budget Commitment Ledger'
    _order = 'id'

    control_id = fields.Many2one('erp.budget.control', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='control_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='control_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    origin_key = fields.Char(required=True, index=True)
    amount = fields.Monetary(required=True)
    reversal_of_id = fields.Many2one('erp.budget.move', ondelete='restrict', index=True)
    family_key = fields.Char(index=True)
    source_key = fields.Char(index=True)
    document_key = fields.Char(index=True, readonly=True)
    purchase_source_key = fields.Char(index=True, readonly=True)
    move_type = fields.Selection([('pr_commitment', 'PR Commitment'), ('pr_reversal', 'PR Reversal'), ('po_commitment', 'PO Commitment'), ('po_reversal', 'PO Reversal'), ('actual', 'Actual Expenditure'), ('actual_reversal', 'Actual Reversal'), ('contract_commitment', 'Contract Commitment'), ('contract_reversal', 'Contract Reversal'), ('expense_commitment', 'Expense Commitment'), ('expense_reversal', 'Expense Reversal'), ('advance_commitment', 'Advance Commitment'), ('advance_reversal', 'Advance Reversal')])
    _origin_unique = models.Constraint('UNIQUE(control_id, origin_key)', 'This budget operation already exists for this control.')
    _reversal_unique = models.Constraint('UNIQUE(reversal_of_id)', 'This budget commitment has already been reversed.')

    def _planning_source(self):
        """Domain adapters return the immutable source line, account and activity."""
        self.ensure_one()
        return False

    def _planning_fallback_key(self):
        """Adapters expose an original primary key restored by source cancellation."""
        self.ensure_one()
        return False

    def _planning_kpi(self):
        self.ensure_one()
        if self.control_id.kpi_id:
            return self.control_id.kpi_id
        source = self._planning_source()
        if not source or not self.control_id.period_id.template_id:
            raise UserError(_('KPI planning initialization requires identifiable source commitments.'))
        line, account, activity = source
        line.check_access('read')
        if line.company_id != self.company_id:
            raise ValidationError(_('The commitment source company does not match.'))
        return self.control_id.period_id.template_id._kpi_for_account(account, activity=activity)


class BudgetControlService(models.AbstractModel):
    _name = 'erp.budget.control.service'
    _description = 'Budget Control Internal Service'

    def _resolve(self, period, organization, analytic, fund, account, dimensions, activity=None):
        period, organization, analytic, fund, account, dimensions = (r.with_env(self.env) for r in (period, organization, analytic, fund, account, dimensions))
        for record in (period, organization, analytic, fund, account):
            record.ensure_one()
            record.check_access('read')
        dimensions.check_access('read')
        if period.company_id not in self.env.companies or organization.company_id != period.company_id or fund.company_id != period.company_id:
            raise AccessError(_('The budget key is outside the active company.'))
        if not organization.active or not fund.active or not analytic.active or any(not d.active for d in dimensions):
            raise ValidationError(_('Budget key records must be active.'))
        if period.company_id not in account.company_ids:
            raise ValidationError(_('Account company does not match budget company.'))
        if analytic.company_id and analytic.company_id != period.company_id:
            raise ValidationError(_('Analytic company does not match budget company.'))
        if any(d.company_id and d.company_id != period.company_id for d in dimensions):
            raise ValidationError(_('Dimension company does not match budget company.'))
        domain = [('company_id', '=', period.company_id.id), ('period_id', '=', period.id), ('organization_id', '=', organization.id), ('analytic_id', '=', analytic.id), ('state', '=', 'open')]
        candidates = self.env['erp.budget.control'].search(domain)
        if activity:
            activity = activity.with_env(self.env)
            activity.ensure_one()
            activity.check_access('read')
            activity._lock_activity_key()
            if not activity.active or activity.company_id != period.company_id or activity.account_id != account:
                raise ValidationError(_('Budget activity must match the company and budget account.'))
        kpi = period.template_id._kpi_for_account(account, activity=activity) if period.template_id else self.env['erp.budget.kpi']
        analytic_controls = candidates.filtered(lambda r: r.level == 'analytic' and (not r.kpi_id or r.kpi_id == kpi))
        if period.control_level == 'analytic':
            analytic_controls = candidates.filtered(lambda r: r.level == 'analytic' and not r.kpi_id)
        elif period.control_level == 'analytic_kpi':
            if not kpi:
                raise ValidationError(_('KPI-level control requires a mapped KPI.'))
            analytic_controls = candidates.filtered(lambda r: r.level == 'analytic' and r.kpi_id == kpi)
        fund_controls = candidates.filtered(lambda r: r.level == 'fund' and r.fund_id == fund and set(r.dimension_ids.ids) == set(dimensions.ids))
        if len(analytic_controls) != 1 or len(fund_controls) != 1:
            raise ValidationError(_('Exactly one matching open control is required at each budget level.'))
        return analytic_controls | fund_controls

    def _check_key(self, period, organization, analytic, fund, account, dimensions, amount, date, activity=None):
        controls = self._resolve(period, organization, analytic, fund, account, dimensions, activity=activity)
        return self._check_available(controls, amount, date)

    def _commit_key(self, period, organization, analytic, fund, account, dimensions, amount, date, origin_key, activity=None):
        controls = self._resolve(period, organization, analytic, fund, account, dimensions, activity=activity)
        return self._commit(controls, amount, date, origin_key)

    def _plan_lines_for_controls(self, controls):
        result = {}
        for row in controls.filtered(lambda row: row.level == 'analytic'):
            if not row.period_id.plan_enforced:
                continue
            lines = self.env['erp.budget.plan.line'].sudo().search([('period_id', '=', row.period_id.id), ('company_id', '=', row.company_id.id), ('analytic_id', '=', row.analytic_id.id), ('plan_id.state', 'in', ('confirm', 'done'))])
            if len(lines) != 1:
                raise ValidationError(_('Exactly one confirmed plan ceiling is required for this budget key.'))
            result[row.id] = lines
        return result

    def _in_accounting_batch(self, controls):
        scope = _accounting_batch.get()
        return bool(scope and scope[0] == self.env.cr.dbname and scope[1] == self.env.uid and set(controls.ids) <= scope[2])

    @contextmanager
    def _accounting_transaction(self, controls):
        """Check a native document's combined final expenditure under common locks."""
        if not controls:
            yield
            return
        if _accounting_batch.get():
            if not self._in_accounting_batch(controls):
                raise ValidationError(_('All accounting budget sources must be locked before posting.'))
            yield
            return
        if not self.env.user.has_group('erp_budget.group_budget_user'):
            raise AccessError(_('Budget capability is required.'))
        controls.check_access('read')
        self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        controls.period_id._lock_plan_periods()
        with self.env.cr.savepoint():
            token = _accounting_batch.set((self.env.cr.dbname, self.env.uid, set(controls.ids)))
            try:
                yield
            finally:
                _accounting_batch.reset(token)
            self._validate_accounting_totals(controls)

    def _validate_accounting_totals(self, controls):
        """Validate final or simulated totals even inside a deferred atomic batch."""
        controls.check_access('read')
        for line in self._plan_lines_for_controls(controls).values():
            if float_compare(line._consumed(), line._ceiling(), precision_rounding=line.currency_id.rounding) > 0:
                raise UserError(_('Insufficient shared plan capacity.'))
        for control in controls:
            self.env.cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [control.id])
            consumed = self.env.cr.fetchone()[0]
            if control._has_child_capacity_limit() and float_compare(consumed, control.amount, precision_rounding=control.currency_id.rounding) > 0:
                raise UserError(_('Insufficient budget for %s.') % control.display_name)

    def _check_plan_deltas(self, controls, deltas):
        if self._in_accounting_batch(controls):
            return
        lines = self._plan_lines_for_controls(controls)
        totals = {}
        for control_id, line in lines.items():
            totals[line.id] = totals.get(line.id, 0) + deltas.get(control_id, 0)
        for line_id, delta in totals.items():
            line = self.env['erp.budget.plan.line'].sudo().browse(line_id)
            if float_compare(line._consumed() + delta, line._ceiling(), precision_rounding=line.currency_id.rounding) > 0:
                raise UserError(_('Insufficient shared plan capacity.'))

    def _lock_and_check(self, controls, amount, date):
        controls = controls.with_env(self.env)
        date = fields.Date.to_date(date)
        if not date:
            raise ValidationError(_('A budget date is required.'))
        if not self.env.user.has_group('erp_budget.group_budget_user'):
            raise AccessError(_('Budget capability is required.'))
        controls.check_access('read')
        if len(controls.exists()) != len(controls) or len(controls) != 2 or set(controls.mapped('level')) != {'analytic', 'fund'} or not math.isfinite(amount) or amount <= 0:
            raise ValidationError(_('A positive amount and exactly one control for each level are required.'))
        if len(controls.mapped('company_id')) != 1 or len(controls.mapped('period_id')) != 1 or len(controls.mapped('organization_id')) != 1 or len(controls.mapped('analytic_id')) != 1:
            raise ValidationError(_('The budget controls must have the same company, period, organization and analytic account.'))
        self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        controls.invalidate_recordset()
        controls.mapped('period_id')._lock_plan_periods()
        self._plan_lines_for_controls(controls)
        for row in controls:
            if not row._has_child_capacity_limit() and not row.period_id.plan_enforced:
                raise ValidationError(_('Advance KPI reservations require a confirmed shared plan ceiling.'))
            if row.period_id.company_id != row.company_id or row.organization_id.company_id != row.company_id or (row.fund_id and row.fund_id.company_id != row.company_id) or (row.kpi_id and row.kpi_id.company_id != row.company_id) or (row.analytic_id.company_id and row.analytic_id.company_id != row.company_id) or any(d.company_id and d.company_id != row.company_id for d in row.dimension_ids):
                raise ValidationError(_('A budget control reference no longer belongs to its company.'))
            if row.state != 'open' or not row.active or not row.organization_id.active:
                raise ValidationError(_('The budget allocation is not open.'))
            if not row.period_id.date_from <= date <= row.period_id.date_to:
                raise ValidationError(_('The date is outside the budget period.'))
            if row.level == 'fund' and (not row.fund_id.active or any(not d.active for d in row.dimension_ids)):
                raise ValidationError(_('The fund or dimension is inactive.'))
            if not row.analytic_id.active or (row.kpi_id and not row.kpi_id.active):
                raise ValidationError(_('The analytic account or KPI is inactive.'))
        return controls

    def _check_available(self, controls, amount, date):
        controls = self._lock_and_check(controls, amount, date)
        self._check_plan_deltas(controls, {row.id: amount for row in controls if row.level == 'analytic'})
        for row in controls:
            self.env.cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [row.id])
            consumed = self.env.cr.fetchone()[0]
            if row._has_child_capacity_limit() and float_compare(row.amount - consumed, amount, precision_rounding=row.currency_id.rounding) < 0:
                raise UserError(_('Insufficient budget for %s.') % row.display_name)
        return True

    def _commit(self, controls, amount, date, origin_key):
        if not origin_key:
            raise ValidationError(_('A stable origin key is required.'))
        controls = self._lock_and_check(controls, amount, date)
        existing = self.env['erp.budget.move'].sudo().search([('control_id', 'in', controls.ids), ('origin_key', '=', origin_key)])
        if existing:
            if self.env['erp.budget.move'].sudo().search_count([('reversal_of_id', 'in', existing.ids)]):
                raise ValidationError(_('A reversed commitment cannot be reused.'))
            if set(existing.mapped('control_id').ids) != set(controls.ids) or any(float_compare(m.amount, amount, precision_rounding=m.currency_id.rounding) for m in existing):
                raise ValidationError(_('The origin already has a different budget commitment.'))
            return True
        # Odoo uses repeatable-read transactions: update the locked rows so a
        # concurrent transaction with an older snapshot gets a serialization
        # failure instead of authorizing against a stale ledger snapshot.
        self.env.cr.execute('UPDATE erp_budget_control SET lock_version = lock_version + 1 WHERE id IN %s', [tuple(sorted(controls.ids))])
        self._check_available(controls, amount, date)
        self.env['erp.budget.move'].sudo().create([{'control_id': row.id, 'amount': amount, 'origin_key': origin_key} for row in controls])
        return True

    def _reverse(self, controls, origin_key):
        controls = controls.with_env(self.env)
        if not self.env.user.has_group('erp_budget.group_budget_user'):
            raise AccessError(_('Budget capability is required.'))
        controls.check_access('read')
        if len(controls.exists()) != len(controls) or len(controls) != 2 or set(controls.mapped('level')) != {'analytic', 'fund'} or not origin_key:
            raise ValidationError(_('A valid commitment and both controls are required.'))
        self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        controls.mapped('period_id')._lock_plan_periods()
        moves = self.env['erp.budget.move'].sudo().search([('control_id', 'in', controls.ids), ('origin_key', '=', origin_key), ('reversal_of_id', '=', False)])
        if set(moves.mapped('control_id').ids) != set(controls.ids):
            raise ValidationError(_('The budget commitment does not match the requested controls.'))
        self.env.cr.execute('UPDATE erp_budget_control SET lock_version = lock_version + 1 WHERE id IN %s', [tuple(sorted(controls.ids))])
        existing = self.env['erp.budget.move'].sudo().search([('reversal_of_id', 'in', moves.ids)])
        reversed_ids = set(existing.mapped('reversal_of_id').ids)
        self.env['erp.budget.move'].sudo().create([{'control_id': move.control_id.id, 'origin_key': 'reverse:' + origin_key, 'amount': -move.amount, 'reversal_of_id': move.id} for move in moves if move.id not in reversed_ids])
        return True

    def _reconcile_purchase(self, controls, date, family_key, pr_key, pr_amount, pr_eligible, purchase_orders):
        """Reconcile one PR line and its linked confirmed PO lines on the same key.

        Private provisional helper; the caller must authorize the source documents.
        purchase_orders is a list of (stable source key, positive amount) pairs.
        """
        if not family_key or not pr_key or not math.isfinite(pr_amount) or pr_amount <= 0:
            raise ValidationError(_('A PR identity and positive amount are required.'))
        po_keys = [key for key, amount in purchase_orders]
        if len(set(po_keys)) != len(po_keys) or pr_key in po_keys or any(not key or not math.isfinite(amount) or amount <= 0 for key, amount in purchase_orders):
            raise ValidationError(_('Purchase order identities and amounts must be valid and unique.'))
        controls = self._lock_and_check(controls, pr_amount, date)
        targets = {key: ('po_commitment', amount) for key, amount in purchase_orders}
        if pr_eligible and not purchase_orders:
            targets[pr_key] = ('pr_commitment', pr_amount)
        Move = self.env['erp.budget.move'].sudo()
        with self.env.cr.savepoint():
            self.env.cr.execute('UPDATE erp_budget_control SET lock_version = lock_version + 1 WHERE id IN %s', [tuple(sorted(controls.ids))])
            previous = Move.search([('control_id', 'in', controls.ids), ('family_key', '=', family_key)])
            reversed_ids = set(previous.mapped('reversal_of_id').ids)
            current = previous.filtered(lambda m: m.move_type in ('pr_commitment', 'po_commitment') and not m.reversal_of_id and m.id not in reversed_ids)
            signatures = [sorted((m.source_key, m.move_type, m.amount) for m in current.filtered(lambda m: m.control_id == row)) for row in controls]
            if signatures[0] != signatures[1]:
                raise ValidationError(_('Inconsistent budget ledger levels require repair.'))
            delta = sum(amount for _, amount in targets.values()) - sum(current.filtered(lambda m: m.control_id.level == 'analytic').mapped('amount'))
            self._check_plan_deltas(controls, {row.id: delta for row in controls if row.level == 'analytic'})
            for row in controls:
                current_row = current.filtered(lambda m: m.control_id == row)
                if len(current_row.mapped('source_key')) != len(current_row):
                    raise ValidationError(_('Duplicate active source commitments require repair.'))
                existing = {m.source_key: (m.move_type, m.amount) for m in current_row}
                target_delta = sum(amount for _, amount in targets.values()) - sum(m.amount for m in current_row)
                self.env.cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [row.id])
                total = self.env.cr.fetchone()[0]
                if row._has_child_capacity_limit() and float_compare(total + target_delta, row.amount, precision_rounding=row.currency_id.rounding) > 0:
                    raise UserError(_('Insufficient budget for %s.') % row.display_name)
                for move in current_row:
                    expected = targets.get(move.source_key)
                    if expected and expected[0] == move.move_type and not float_compare(move.amount, expected[1], precision_rounding=row.currency_id.rounding):
                        continue
                    Move.create({'control_id': row.id, 'origin_key': 'reconcile-reverse:%s' % move.id, 'family_key': family_key, 'source_key': move.source_key, 'move_type': 'pr_reversal' if move.move_type == 'pr_commitment' else 'po_reversal', 'amount': -move.amount, 'reversal_of_id': move.id})
                for source_key, (move_type, amount) in targets.items():
                    old = existing.get(source_key)
                    if old and old[0] == move_type and not float_compare(old[1], amount, precision_rounding=row.currency_id.rounding):
                        continue
                    # The control row lock serializes sequence allocation per level.
                    seq = Move.search_count([('control_id', '=', row.id), ('family_key', '=', family_key), ('source_key', '=', source_key), ('reversal_of_id', '=', False)]) + 1
                    origin = hashlib.sha256(json.dumps([family_key, source_key, seq], separators=(',', ':')).encode()).hexdigest()
                    Move.create({'control_id': row.id, 'origin_key': 'reconcile:' + origin, 'family_key': family_key, 'source_key': source_key, 'move_type': move_type, 'amount': amount})
        return True

    def _reconcile_purchase_multi(self, pr_controls, pr_date, family_key, pr_key, pr_amount, pr_eligible, purchase_orders, actuals=None, actual_provenance=None, primary_type='pr_commitment'):
        """Reconcile one authorized PR line and PO lines, allowing distinct keys.

        purchase_orders contains (source_key, controls, amount, date). The
        caller is responsible for authenticating document identities and state.
        """
        pr_controls = pr_controls.with_env(self.env)
        purchase_orders = [(key, controls.with_env(self.env), amount, date) for key, controls, amount, date in purchase_orders]
        actuals_owned = actuals is not None
        actual_provenance = actual_provenance or {}
        actuals = [(key, controls.with_env(self.env), amount, date) for key, controls, amount, date in (actuals or [])]
        po_keys = [key for key, controls, amount, po_date in purchase_orders]
        actual_keys = [key for key, controls, amount, date in actuals]
        if primary_type not in ('pr_commitment', 'contract_commitment', 'expense_commitment', 'advance_commitment', 'actual'):
            raise ValidationError(_('Unsupported budget source type.'))
        if primary_type == 'actual' and (pr_amount or pr_eligible or purchase_orders):
            raise ValidationError(_('Direct actual reconciliation cannot create commitments.'))
        if len(pr_controls) != 2:
            raise ValidationError(_('Both PR budget controls are required.'))
        if not family_key or not pr_key or not math.isfinite(pr_amount) or pr_amount < 0 or (not pr_amount and primary_type == 'pr_commitment') or len(po_keys) != len(set(po_keys)) or pr_key in po_keys or any(not key or not math.isfinite(amount) or amount < 0 for key, _, amount, _ in purchase_orders) or len(actual_keys) != len(set(actual_keys)) or set(actual_keys) & (set(po_keys) | {pr_key}) or any(not key or not math.isfinite(amount) or not amount for key, _, amount, _ in actuals):
            raise ValidationError(_('Purchase commitment identities and amounts must be valid and unique.'))
        if not self.env.user.has_group('erp_budget.group_budget_user'):
            raise AccessError(_('Budget capability is required.'))
        Move = self.env['erp.budget.move'].sudo()
        previous = Move.search([('family_key', '=', family_key)])
        historic_controls = previous.mapped('control_id').with_env(self.env)
        all_controls = pr_controls | historic_controls
        for source_key, controls, amount, po_date in purchase_orders:
            all_controls |= controls
        for source_key, controls, amount, date in actuals:
            all_controls |= controls
        all_controls.check_access('read')
        if len(all_controls.exists()) != len(all_controls):
            raise ValidationError(_('A referenced budget control no longer exists.'))
        self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(all_controls.ids))])
        all_controls.mapped('period_id')._lock_plan_periods()
        pr_controls = self._lock_and_check(pr_controls, max(pr_amount, pr_controls[:1].currency_id.rounding), pr_date)
        common_company = pr_controls[0].company_id
        common_org = pr_controls[0].organization_id
        if any(row.company_id != common_company or row.organization_id != common_org for row in all_controls):
            raise ValidationError(_('All historical budget controls must match the source company and organization.'))
        for source_key, controls, amount, date in purchase_orders:
            self._lock_and_check(controls, max(amount, controls[:1].currency_id.rounding), date)
            if any(row.company_id != common_company or row.organization_id != common_org for row in controls):
                raise ValidationError(_('PR and PO controls must belong to the same company and organization.'))
        for source_key, controls, amount, date in actuals:
            self._lock_and_check(controls, abs(amount), date)
            if any(row.company_id != common_company or row.organization_id != common_org for row in controls):
                raise ValidationError(_('Actual controls must belong to the source company and organization.'))
        targets = {}
        if pr_eligible and not purchase_orders and pr_amount:
            for row in pr_controls:
                targets[(row.id, pr_key)] = (primary_type, pr_amount)
        for key, controls, amount, po_date in purchase_orders:
            if amount:
                for row in controls:
                    targets[(row.id, key)] = ('po_commitment', amount)
        for key, controls, amount, date in actuals:
            for row in controls:
                targets[(row.id, key)] = ('actual', amount)
        with self.env.cr.savepoint():
            self.env.cr.execute('UPDATE erp_budget_control SET lock_version = lock_version + 1 WHERE id IN %s', [tuple(sorted(all_controls.ids))])
            previous = Move.search([('family_key', '=', family_key)])
            reversed_ids = set(previous.mapped('reversal_of_id').ids)
            owned_types = (primary_type, 'po_commitment', 'actual') if actuals_owned else (primary_type, 'po_commitment')
            current = previous.filtered(lambda m: m.move_type in owned_types and not m.reversal_of_id and m.id not in reversed_ids)
            by_source = {}
            for move in current:
                by_source.setdefault(move.source_key, []).append(move)
            for entries in by_source.values():
                if len(entries) != 2 or {m.control_id.level for m in entries} != {'analytic', 'fund'} or entries[0].amount != entries[1].amount or entries[0].move_type != entries[1].move_type:
                    raise ValidationError(_('Inconsistent budget ledger levels require repair.'))
            plan_deltas = {}
            for row in all_controls.filtered(lambda c: c.level == 'analytic'):
                expected = sum(amount for (control_id, source_key), (move_type, amount) in targets.items() if control_id == row.id)
                plan_deltas[row.id] = expected - sum(current.filtered(lambda m: m.control_id.id == row.id).mapped('amount'))
            self._check_plan_deltas(all_controls, plan_deltas)
            for row in all_controls:
                current_row = current.filtered(lambda m: m.control_id.id == row.id)
                expected_total = sum(amount for (control_id, source_key), (move_type, amount) in targets.items() if control_id == row.id)
                delta = expected_total - sum(current_row.mapped('amount'))
                self.env.cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [row.id])
                consumed = self.env.cr.fetchone()[0]
                if row._has_child_capacity_limit() and not self._in_accounting_batch(all_controls) and float_compare(consumed + delta, row.amount, precision_rounding=row.currency_id.rounding) > 0:
                    raise UserError(_('Insufficient budget for %s.') % row.display_name)
            existing = {(m.control_id.id, m.source_key): m for m in current}
            for move in current.filtered(lambda m: m.move_type == 'actual' and m.source_key in actual_provenance):
                if (move.document_key, move.purchase_source_key) != tuple(actual_provenance[move.source_key]):
                    raise ValidationError(_('Actual source provenance changed and requires repair.'))
            for key, move in existing.items():
                target = targets.get(key)
                if target and move.move_type == target[0] and not float_compare(move.amount, target[1], precision_rounding=move.currency_id.rounding):
                    continue
                Move.create({'control_id': move.control_id.id, 'origin_key': 'reconcile-reverse:%s' % move.id, 'family_key': family_key, 'source_key': move.source_key, 'move_type': {'pr_commitment': 'pr_reversal', 'po_commitment': 'po_reversal', 'actual': 'actual_reversal', 'contract_commitment': 'contract_reversal', 'expense_commitment': 'expense_reversal', 'advance_commitment': 'advance_reversal'}[move.move_type], 'document_key': move.document_key, 'purchase_source_key': move.purchase_source_key, 'amount': -move.amount, 'reversal_of_id': move.id})
            for (control_id, source_key), (move_type, amount) in targets.items():
                move = existing.get((control_id, source_key))
                if move and move.move_type == move_type and not float_compare(move.amount, amount, precision_rounding=move.currency_id.rounding):
                    continue
                seq = Move.search_count([('control_id', '=', control_id), ('family_key', '=', family_key), ('source_key', '=', source_key), ('reversal_of_id', '=', False)]) + 1
                origin = hashlib.sha256(json.dumps([family_key, source_key, seq], separators=(',', ':')).encode()).hexdigest()
                provenance = actual_provenance.get(source_key, (False, False))
                Move.create({'control_id': control_id, 'origin_key': 'reconcile:' + origin, 'family_key': family_key, 'source_key': source_key, 'document_key': provenance[0], 'purchase_source_key': provenance[1], 'move_type': move_type, 'amount': amount})
        return True
