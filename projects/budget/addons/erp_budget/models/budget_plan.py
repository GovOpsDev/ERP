import math
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

_event_create = ContextVar('budget_plan_event_create', default=False)


class BudgetPeriodPlan(models.Model):
    _inherit = 'erp.budget.period'

    release_policy = fields.Selection([('legacy', 'Legacy / independent controls'), ('formal', 'Formal KPI releases')], default='legacy', required=True)
    control_level = fields.Selection([('legacy', 'Existing control keys'), ('analytic', 'Analytic total'), ('analytic_kpi', 'Analytic and KPI')], default='legacy', required=True)
    plan_enforced = fields.Boolean(default=False, readonly=True, copy=False)
    plan_lock_version = fields.Integer(default=0, readonly=True, copy=False)

    def _lock_plan_periods(self):
        if self:
            ids = tuple(sorted(self.ids))
            self.env.cr.execute('SELECT id FROM erp_budget_period WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
            self.env.cr.execute('UPDATE erp_budget_period SET plan_lock_version = COALESCE(plan_lock_version, 0) + 1 WHERE id IN %s', [ids])
            self.invalidate_recordset(['plan_enforced', 'plan_lock_version'])

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('base.group_system') and (self.env.context.get('default_control_level', 'legacy') != 'legacy' or any(vals.get('control_level', 'legacy') != 'legacy' for vals in vals_list)):
            raise AccessError(_('Only settings administrators can configure control granularity.'))
        if not self.env.su and not self.env.user.has_group('base.group_system') and (self.env.context.get('default_release_policy', 'legacy') != 'legacy' or any(vals.get('release_policy', 'legacy') != 'legacy' for vals in vals_list)):
            raise AccessError(_('Only settings administrators can configure formal release policy.'))
        if any({'plan_enforced', 'plan_lock_version'} & vals.keys() for vals in vals_list) or any('default_' + k in self.env.context for k in ('plan_enforced', 'plan_lock_version')):
            raise AccessError(_('Plan enforcement is internal.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'control_level' in vals:
            if not self.env.su and not self.env.user.has_group('base.group_system'):
                raise AccessError(_('Only settings administrators can configure control granularity.'))
            self._lock_plan_periods()
            if self.env['erp.budget.control'].sudo().with_context(active_test=False).search_count([('period_id', 'in', self.ids), ('state', 'in', ('open', 'closed'))]):
                raise UserError(_('An effective period cannot change control granularity.'))
        if {'plan_enforced', 'plan_lock_version'} & vals.keys():
            raise AccessError(_('Plan enforcement is internal.'))
        if 'release_policy' in vals and not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only settings administrators can configure formal release policy.'))
        if {'company_id', 'date_from', 'date_to', 'template_id', 'release_policy', 'control_level'} & vals.keys():
            self._lock_plan_periods()
            if any(period.plan_enforced for period in self):
                raise UserError(_('A period with a confirmed plan cannot be reconfigured.'))
        return super().write(vals)


class BudgetPlan(models.Model):
    _name = 'erp.budget.plan'
    _description = 'Budget Plan'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict')
    period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict', index=True)
    state = fields.Selection([('draft', 'Draft'), ('confirm', 'Confirmed'), ('done', 'Done'), ('cancel', 'Cancelled')], default='draft', required=True, readonly=True)
    line_ids = fields.One2many('erp.budget.plan.line', 'plan_id')
    _period_unique = models.Constraint('unique(period_id)', 'Only one budget plan is supported for a period.')

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('state', 'draft') != 'draft' for vals in vals_list) or 'default_state' in self.env.context:
            raise AccessError(_('A plan must begin in draft.'))
        if not self.env.su and any(vals.get('company_id', self.env.company.id) not in self.env.companies.ids for vals in vals_list):
            raise AccessError(_('The plan company must be active.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.mapped('period_id')._lock_plan_periods()
        if self.env['erp.budget.allocation'].sudo().search_count([('plan_id', 'in', self.ids)]):
            raise AccessError(_('Allocation-generated draft plans cannot be edited.'))
        if {'company_id', 'period_id'} & vals.keys() and self.env['erp.budget.plan.line'].sudo().search_count([('plan_id', 'in', self.ids)]):
            raise UserError(_('A plan with lines cannot change company or period.'))
        if 'state' in vals or any(plan.state != 'draft' for plan in self):
            raise AccessError(_('Confirmed plans are immutable; use plan actions.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.mapped('period_id')._lock_plan_periods()
        if any(plan.state != 'draft' for plan in self) or self.env['erp.budget.allocation'].sudo().search_count([('plan_id', 'in', self.ids)]):
            raise UserError(_('Confirmed or allocation-backed plans cannot be deleted.'))
        return super().unlink()

    def action_confirm(self):
        self.ensure_one()
        self.check_access('write')
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        if self.state != 'draft' or self.period_id.plan_enforced or not self.line_ids:
            raise ValidationError(_('A nonempty draft plan is required.'))
        lines = self.line_ids
        lines.check_access('read')
        all_lines = self.env['erp.budget.plan.line'].sudo().search([('plan_id', '=', self.id)])
        if set(lines.ids) != set(all_lines.ids):
            raise AccessError(_('The manager must have access to every plan line.'))
        controls = self.env['erp.budget.control'].sudo().with_context(active_test=False).search([('period_id', '=', self.period_id.id), ('level', '=', 'analytic')])
        controls.with_env(self.env).check_access('read')
        keys = {line.analytic_id.id: line for line in lines}
        if any(row.analytic_id.id not in keys for row in controls):
            raise ValidationError(_('The plan must cover all existing analytic controls in its period.'))
        if self.period_id.release_policy == 'formal' and any(not line.release_required or line.allocation_mode != 'allocated' for line in lines):
            raise ValidationError(_('Formal-release periods require formal allocation on every plan line.'))
        for line in lines:
            line._check_opening_minimum(line.initial_amount)
            if line.release_required and (line.allocation_mode != 'allocated' or line._allocated()):
                raise ValidationError(_('Formal release requires allocated mode and no existing open or closed analytic controls.'))
            if line.allocation_mode == 'allocated' and float_compare(line._allocated(), line.initial_amount, precision_rounding=line.currency_id.rounding) > 0:
                raise UserError(_('Child allocations exceed the plan ceiling.'))
            if float_compare(line._consumed(), line.initial_amount, precision_rounding=line.currency_id.rounding) > 0:
                raise UserError(_('The plan ceiling cannot be below existing consumption.'))
        with self.env.cr.savepoint():
            self.env.cr.execute('UPDATE erp_budget_period SET plan_enforced = TRUE WHERE id = %s', [self.period_id.id])
            self.period_id.invalidate_recordset(['plan_enforced'])
            result = super(BudgetPlan, self).write({'state': 'confirm'})
            self._record_confirmed_snapshot()
        return result

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self.period_id._lock_plan_periods()
        if self.state != 'draft':
            raise UserError(_('Only draft plans may be cancelled.'))
        return super(BudgetPlan, self).write({'state': 'cancel'})

    def action_draft(self):
        self.ensure_one()
        self.check_access('write')
        self.period_id._lock_plan_periods()
        if self.state != 'cancel' or self.period_id.plan_enforced:
            raise UserError(_('Only cancelled draft plans may be reset.'))
        return super(BudgetPlan, self).write({'state': 'draft'})

    def action_done(self):
        self.ensure_one()
        self.check_access('write')
        self.period_id._lock_plan_periods()
        if self.state != 'confirm':
            raise UserError(_('Only confirmed plans can be completed.'))
        return super(BudgetPlan, self).write({'state': 'done'})


class BudgetPlanLine(models.Model):
    _name = 'erp.budget.plan.line'
    _description = 'Budget Plan Ceiling'
    _check_company_auto = True

    plan_id = fields.Many2one('erp.budget.plan', required=True, ondelete='restrict', check_company=True, index=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True, index=True)
    period_id = fields.Many2one(related='plan_id.period_id', store=True, index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict', index=True)
    analytic_id = fields.Many2one('account.analytic.account', required=True, check_company=True, ondelete='restrict', index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    initial_amount = fields.Monetary(required=True)
    introduced_revision_id = fields.Many2one('erp.budget.allocation.revision', readonly=True, ondelete='restrict')
    effective_amount = fields.Monetary(compute='_compute_capacity')
    consumed_amount = fields.Monetary(compute='_compute_capacity')
    available_amount = fields.Monetary(compute='_compute_capacity')
    release_required = fields.Boolean(default=False, help='Require an explicit KPI release for analytic controls.')
    allocation_mode = fields.Selection([('limits', 'Independent child limits'), ('allocated', 'Allocated child budgets')], default='limits', required=True)
    _scope_unique = models.Constraint('unique(plan_id, analytic_id)', 'Duplicate plan ceiling for this analytic account.')

    @api.constrains('initial_amount', 'organization_id', 'analytic_id')
    def _check_line(self):
        for line in self:
            if not math.isfinite(line.initial_amount) or line.initial_amount < 0 or abs(line.initial_amount - line.currency_id.round(line.initial_amount)) > 1e-9 or not line.organization_id.active:
                raise ValidationError(_('The ceiling must be nonnegative and the organization active.'))
            if line.organization_id.company_id != line.company_id or (line.analytic_id.company_id and line.analytic_id.company_id != line.company_id):
                raise ValidationError(_('Plan dimensions must belong to its company.'))

    @api.model_create_multi
    def create(self, vals_list):
        from .budget_allocation import _allocation_internal
        internal = _allocation_internal.get()
        if not internal and (any('introduced_revision_id' in vals for vals in vals_list) or 'default_introduced_revision_id' in self.env.context):
            raise AccessError(_('Revision provenance is generated internally.'))
        if any({'company_id', 'period_id'} & vals.keys() for vals in vals_list) or any('default_' + field in self.env.context for field in ('company_id', 'period_id')):
            raise AccessError(_('Plan line company and period derive from the plan.'))
        plans = self.env['erp.budget.plan'].browse([v.get('plan_id') for v in vals_list if v.get('plan_id')]).exists()
        plans.check_access('write')
        plans.mapped('period_id')._lock_plan_periods()
        if not internal and self.env['erp.budget.allocation'].sudo().search_count([('plan_id', 'in', plans.ids)]):
            raise AccessError(_('Allocation-generated plan lines cannot be added.'))
        if len(plans) == 0 or (not internal and any(p.state != 'draft' for p in plans)):
            raise AccessError(_('Plan lines require a draft plan.'))
        for vals in vals_list:
            unit = self.env['erp.organization.unit'].browse(vals.get('organization_id')).exists()
            if not unit:
                raise ValidationError(_('An organization is required.'))
            unit.check_access('read')
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.mapped('period_id')._lock_plan_periods()
        if self.env['erp.budget.allocation'].sudo().search_count([('plan_id', 'in', self.mapped('plan_id').ids)]):
            raise AccessError(_('Allocation-generated plan lines are immutable.'))
        if {'plan_id', 'company_id', 'period_id'} & vals.keys() or any(line.plan_id.state != 'draft' for line in self):
            raise AccessError(_('Confirmed plan lines and plan ownership are immutable.'))
        if vals.get('organization_id'):
            self.env['erp.organization.unit'].browse(vals['organization_id']).check_access('read')
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.mapped('period_id')._lock_plan_periods()
        if any(line.plan_id.state != 'draft' for line in self) or self.env['erp.budget.allocation'].sudo().search_count([('plan_id', 'in', self.mapped('plan_id').ids)]):
            raise AccessError(_('Confirmed or allocation-generated plan lines cannot be deleted.'))
        return super().unlink()

    def _compute_capacity(self):
        for line in self:
            if not line.id:
                line.effective_amount = line.initial_amount
                line.consumed_amount = 0
            else:
                line.effective_amount = line._ceiling()
                line.consumed_amount = line._consumed()
            line.available_amount = line.effective_amount - line.consumed_amount

    def action_adjust(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        return {'type': 'ir.actions.act_window', 'name': _('Adjust plan ceiling'), 'res_model': 'erp.budget.plan.adjustment', 'view_mode': 'form', 'target': 'new', 'context': {'default_source_id': self.id}}

    def _check_all_control_access(self):
        self.ensure_one()
        if not self.env.su:
            controls = self.env['erp.budget.control'].sudo().with_context(active_test=False).search([('company_id', '=', self.company_id.id), ('period_id', '=', self.period_id.id), ('analytic_id', '=', self.analytic_id.id), ('level', '=', 'analytic')])
            controls.with_env(self.env).check_access('read')

    def _consumed(self):
        self.ensure_one()
        self._check_all_control_access()
        self.env['erp.budget.control'].flush_model(['level', 'company_id', 'period_id', 'organization_id', 'analytic_id'])
        self.env['erp.budget.move'].flush_model(['control_id', 'amount'])
        self.env.cr.execute("SELECT COALESCE(SUM(m.amount),0) FROM erp_budget_move m JOIN erp_budget_control c ON c.id=m.control_id WHERE c.level='analytic' AND c.company_id=%s AND c.period_id=%s AND c.analytic_id=%s", [self.company_id.id, self.period_id.id, self.analytic_id.id])
        return self.env.cr.fetchone()[0]

    def _requires_source_planning_reconciliation(self):
        self.ensure_one()
        return bool(self.release_required and self.env['erp.budget.allocation'].sudo().search_count([('plan_id', '=', self.plan_id.id)]))

    def _allocated(self, opening_ids=()):
        self.ensure_one()
        self._check_all_control_access()
        self.env['erp.budget.control'].flush_model(['level', 'company_id', 'period_id', 'organization_id', 'analytic_id', 'amount', 'active', 'state', 'erp_release_reversed'])
        self.env.cr.execute("SELECT COALESCE(SUM(amount),0) FROM erp_budget_control WHERE level='analytic' AND company_id=%s AND period_id=%s AND analytic_id=%s AND active AND NOT COALESCE(erp_release_reversed, FALSE) AND (state IN ('open','closed') OR id = ANY(%s))", [self.company_id.id, self.period_id.id, self.analytic_id.id, list(opening_ids)])
        return self.env.cr.fetchone()[0]

    def _ceiling(self):
        self.ensure_one()
        self.flush_recordset(['initial_amount'])
        self.env['erp.budget.plan.version'].flush_model(['plan_id', 'state', 'snapshot_anchor', 'event_cutoff'])
        self.env['erp.budget.plan.version.line'].flush_model(['version_id', 'plan_line_id', 'amount'])
        self.env['erp.budget.plan.event'].flush_model(['source_id', 'destination_id', 'amount'])
        self.env.cr.execute("SELECT l.amount, v.event_cutoff FROM erp_budget_plan_version v LEFT JOIN erp_budget_plan_version_line l ON l.version_id = v.id AND l.plan_line_id = %s WHERE v.plan_id = %s AND v.state = 'effective' AND v.snapshot_anchor", [self.id, self.plan_id.id])
        anchor = self.env.cr.fetchone()
        if anchor and anchor[0] is None and self.introduced_revision_id and self.introduced_revision_id.state == 'draft':
            return 0
        if anchor and anchor[0] is None:
            raise ValidationError(_('The effective plan snapshot is missing a line.'))
        base, cutoff = (anchor[0], anchor[1] or 0) if anchor else (self.initial_amount, 0)
        self.env.cr.execute('SELECT COALESCE(SUM(CASE WHEN destination_id=%s THEN amount ELSE 0 END),0)-COALESCE(SUM(CASE WHEN source_id=%s THEN amount ELSE 0 END),0) FROM erp_budget_plan_event WHERE id > %s AND (source_id=%s OR destination_id=%s)', [self.id, self.id, cutoff, self.id, self.id])
        return base + self.env.cr.fetchone()[0]

    def _change(self, kind, amount, destination=None, reference=None):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager') or not math.isfinite(amount) or amount <= 0:
            raise AccessError(_('A budget manager and positive amount are required.'))
        if abs(amount - self.currency_id.round(amount)) > 1e-9:
            raise ValidationError(_('The adjustment must use company currency precision.'))
        dest = self.env['erp.budget.plan.line'].browse(destination).exists() if destination else self.env['erp.budget.plan.line']
        if kind == 'transfer':
            dest.ensure_one()
            dest.check_access('write')
            if dest == self or dest.company_id != self.company_id or dest.period_id != self.period_id:
                raise ValidationError(_('Transfer must use distinct plan lines in the same company and period.'))
        self.period_id._lock_plan_periods()
        if self.env['erp.budget.allocation'].sudo().search_count([('plan_id', 'in', (self.plan_id | dest.plan_id).ids)]):
            raise UserError(_('Allocation-backed plans require an allocation revision.'))
        self.invalidate_recordset()
        dest.invalidate_recordset()
        self._check_all_control_access()
        if dest:
            dest._check_all_control_access()
        if self.plan_id.state not in ('confirm', 'done') or (dest and dest.plan_id.state not in ('confirm', 'done')):
            raise ValidationError(_('Plan must be confirmed.'))
        if kind in ('decrease', 'transfer'):
            new_ceiling = self._ceiling() - amount
            self._check_opening_minimum(new_ceiling)
            if float_compare(new_ceiling, 0, precision_rounding=self.currency_id.rounding) < 0 or float_compare(new_ceiling, self._consumed(), precision_rounding=self.currency_id.rounding) < 0:
                raise UserError(_('The ceiling cannot be reduced below zero or consumption.'))
            if self.allocation_mode == 'allocated' and float_compare(new_ceiling, self._allocated(), precision_rounding=self.currency_id.rounding) < 0:
                raise UserError(_('The ceiling cannot be reduced below child allocations.'))
        token = _event_create.set(True)
        try:
            self.env['erp.budget.plan.event'].sudo().create({'company_id': self.company_id.id, 'period_id': self.period_id.id, 'source_id': self.id if kind in ('decrease', 'transfer') else False, 'destination_id': dest.id if kind == 'transfer' else self.id if kind == 'increase' else False, 'kind': kind, 'amount': amount, 'reference': reference, 'user_id': self.env.user.id, 'reversal_of_id': False, 'version_id': False})
        finally:
            _event_create.reset(token)
        return True

    def action_increase(self, amount, reference=None):
        return self._change('increase', amount, reference=reference)

    def action_decrease(self, amount, reference=None):
        return self._change('decrease', amount, reference=reference)

    def action_transfer(self, destination, amount, reference=None):
        return self._change('transfer', amount, destination, reference)


class BudgetPlanEvent(models.Model):
    _name = 'erp.budget.plan.event'
    _description = 'Immutable Budget Plan Adjustment'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, ondelete='restrict', index=True)
    period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict')
    source_id = fields.Many2one('erp.budget.plan.line', check_company=True, ondelete='restrict')
    destination_id = fields.Many2one('erp.budget.plan.line', check_company=True, ondelete='restrict')
    currency_id = fields.Many2one(related='company_id.currency_id')
    kind = fields.Selection([('increase', 'Increase'), ('decrease', 'Decrease'), ('transfer', 'Transfer'), ('transfer_reversal', 'Transfer Reversal')], required=True)
    reversal_of_id = fields.Many2one('erp.budget.plan.event', readonly=True, copy=False, ondelete='restrict', index=True)
    _reversal_unique = models.Constraint('unique(reversal_of_id)', 'A plan transfer may only be reversed once.')
    amount = fields.Monetary(required=True)
    reference = fields.Char()
    user_id = fields.Many2one('res.users', required=True, ondelete='restrict')

    def action_reverse_transfer(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        if self.kind != 'transfer' or self.reversal_of_id:
            raise UserError(_('Only an original transfer can be reversed.'))
        source, destination = self.source_id, self.destination_id
        source.check_access('write')
        destination.check_access('write')
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        source.invalidate_recordset()
        destination.invalidate_recordset()
        source._check_all_control_access()
        destination._check_all_control_access()
        if self.env['erp.budget.plan.event'].sudo().search_count([('reversal_of_id', '=', self.id)]):
            return True
        if source.period_id != self.period_id or destination.period_id != self.period_id or source.company_id != self.company_id or destination.company_id != self.company_id:
            raise ValidationError(_('Transfer dimensions no longer match.'))
        revised = destination._ceiling() - self.amount
        destination._check_opening_minimum(revised)
        rounding = destination.currency_id.rounding
        if float_compare(revised, 0, precision_rounding=rounding) < 0 or float_compare(revised, destination._consumed(), precision_rounding=rounding) < 0:
            raise UserError(_('Transfer reversal would reduce the destination below consumption.'))
        if destination.allocation_mode == 'allocated' and float_compare(revised, destination._allocated(), precision_rounding=rounding) < 0:
            raise UserError(_('Transfer reversal would reduce the destination below allocations.'))
        token = _event_create.set(True)
        try:
            self.env['erp.budget.plan.event'].sudo().create({'company_id': self.company_id.id, 'period_id': self.period_id.id, 'source_id': destination.id, 'destination_id': source.id, 'kind': 'transfer_reversal', 'amount': self.amount, 'reference': self.reference, 'user_id': self.env.user.id, 'reversal_of_id': self.id, 'version_id': False})
        finally:
            _event_create.reset(token)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not _event_create.get():
            raise AccessError(_('Plan events are created by plan actions only.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Plan events are immutable.'))

    def unlink(self):
        raise AccessError(_('Plan events cannot be deleted.'))


class BudgetPlanAdjustment(models.TransientModel):
    _name = 'erp.budget.plan.adjustment'
    _description = 'Budget Plan Adjustment'
    _check_company_auto = True

    source_id = fields.Many2one('erp.budget.plan.line', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='source_id.company_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    kind = fields.Selection([('increase', 'Increase'), ('decrease', 'Decrease'), ('transfer', 'Transfer')], required=True, default='increase')
    destination_id = fields.Many2one('erp.budget.plan.line', check_company=True)
    amount = fields.Monetary(required=True)
    reference = fields.Char()

    def action_apply(self):
        self.ensure_one()
        self.check_access('write')
        if self.kind == 'transfer' and not self.destination_id:
            raise ValidationError(_('A destination plan line is required.'))
        self.source_id._change(self.kind, self.amount, self.destination_id.id, self.reference)
        return {'type': 'ir.actions.act_window_close'}
