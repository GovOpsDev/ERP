from contextvars import ContextVar
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_plan import _event_create

_revision_create = ContextVar('erp_budget_revision_create', default=False)


class BudgetPlanRevisionMixin(models.Model):
    _inherit = 'erp.budget.plan'

    def _record_confirmed_snapshot(self):
        self.ensure_one()
        if self.state != 'confirm' or self.env['erp.budget.plan.version'].sudo().search_count([('plan_id', '=', self.id)]):
            raise ValidationError(_('Initial confirmation requires a plan without version history.'))
        token = _revision_create.set(True)
        try:
            self.env['erp.budget.plan.version'].sudo().create({'plan_id': self.id, 'number': 0, 'state': 'effective', 'is_baseline': True, 'effective_at': fields.Datetime.now(), 'approved_by_id': self.env.user.id, 'base_version_id': False, 'reason': False, 'snapshot_anchor': True, 'event_cutoff': self._revision_event_cutoff(), 'line_ids': [(0, 0, {'plan_line_id': line.id, 'base_amount': line.initial_amount, 'amount': line.initial_amount}) for line in self.line_ids]})
        finally:
            _revision_create.reset(token)

    def _revision_event_cutoff(self):
        self.env['erp.budget.plan.event'].flush_model(['period_id'])
        self.env.cr.execute('SELECT COALESCE(MAX(id), 0) FROM erp_budget_plan_event WHERE period_id = %s', [self.period_id.id])
        return self.env.cr.fetchone()[0]

    def action_prepare_revision(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self.period_id._lock_plan_periods()
        from .budget_allocation import _allocation_internal
        if not _allocation_internal.get() and self.env['erp.budget.allocation'].sudo().search_count([('plan_id', '=', self.id)]):
            raise UserError(_('Allocation-backed plans require an allocation revision.'))
        self.invalidate_recordset()
        if self.state not in ('confirm', 'done'):
            raise UserError(_('Only a confirmed plan may be revised.'))
        lines = self.line_ids
        all_lines = self.env['erp.budget.plan.line'].sudo().search([('plan_id', '=', self.id)])
        if set(lines.ids) != set(all_lines.ids):
            raise AccessError(_('The manager must access every plan line.'))
        for line in lines:
            line._check_all_control_access()
        versions = self.env['erp.budget.plan.version'].sudo().search([('plan_id', '=', self.id)], order='number desc')
        effective = versions.filtered(lambda v: v.state == 'effective')
        if len(effective) > 1:
            raise ValidationError(_('Multiple effective plan versions require repair.'))
        token = _revision_create.set(True)
        try:
            if not effective:
                if versions:
                    raise ValidationError(_('A missing effective version requires repair.'))
                effective = self.env['erp.budget.plan.version'].sudo().create({'plan_id': self.id, 'number': 0, 'state': 'effective', 'is_baseline': True, 'effective_at': fields.Datetime.now(), 'approved_by_id': False, 'base_version_id': False, 'reason': False, 'snapshot_anchor': True, 'event_cutoff': self._revision_event_cutoff(), 'line_ids': [(0, 0, {'plan_line_id': line.id, 'base_amount': line._ceiling(), 'amount': line._ceiling()}) for line in lines]})
            number = max(versions.mapped('number') or [0]) + 1
            draft = self.env['erp.budget.plan.version'].sudo().create({'plan_id': self.id, 'number': number, 'base_version_id': effective.id, 'state': 'draft', 'is_baseline': False, 'effective_at': False, 'approved_by_id': False, 'reason': False, 'line_ids': [(0, 0, {'plan_line_id': line.id, 'base_amount': line._ceiling(), 'amount': line._ceiling()}) for line in lines]})
        finally:
            _revision_create.reset(token)
        return {'type': 'ir.actions.act_window', 'name': _('Plan revision'), 'res_model': 'erp.budget.plan.version', 'view_mode': 'form', 'res_id': draft.id, 'target': 'current'}


class BudgetPlanVersion(models.Model):
    _name = 'erp.budget.plan.version'
    _description = 'Budget Plan Version'
    _check_company_auto = True
    _order = 'number desc, id desc'

    plan_id = fields.Many2one('erp.budget.plan', required=True, ondelete='restrict', index=True, check_company=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True, index=True)
    period_id = fields.Many2one(related='plan_id.period_id', store=True, index=True)
    number = fields.Integer(required=True, readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('effective', 'Effective'), ('superseded', 'Superseded'), ('cancel', 'Cancelled')], required=True, readonly=True)
    base_version_id = fields.Many2one('erp.budget.plan.version', readonly=True, ondelete='restrict')
    is_baseline = fields.Boolean(readonly=True)
    reason = fields.Char()
    effective_at = fields.Datetime(readonly=True)
    snapshot_anchor = fields.Boolean(readonly=True, default=False, help='This snapshot has an explicit event boundary; older versions retain legacy resolution until revised.')
    event_cutoff = fields.Integer(readonly=True, default=0)
    approved_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    line_ids = fields.One2many('erp.budget.plan.version.line', 'version_id')
    _version_unique = models.Constraint('unique(plan_id, number)', 'Version numbers must be unique per plan.')

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute("CREATE UNIQUE INDEX IF NOT EXISTS erp_budget_one_effective_version ON erp_budget_plan_version (plan_id) WHERE state = 'effective'")
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if not _revision_create.get():
            raise AccessError(_('Use the plan revision action.'))
        return super().create(vals_list)

    def _check_all_version_access(self):
        for version in self:
            rows = self.env['erp.budget.plan.version.line'].sudo().search([('version_id', '=', version.id)])
            rows.with_env(self.env).check_access('read')
            for line in rows.mapped('plan_line_id').with_env(self.env):
                line.check_access('write')
                line._check_all_control_access()

    def write(self, vals):
        self.check_access('write')
        self.mapped('period_id')._lock_plan_periods()
        self._check_all_version_access()
        commands = vals.get('line_ids', [])
        if set(vals) - {'reason', 'line_ids'} or any(version.state != 'draft' for version in self) or any(command[0] != 1 or set(command[2]) - {'amount'} for command in commands):
            raise AccessError(_('Historical versions are immutable.'))
        permitted = set(self.mapped('line_ids').ids)
        if any(command[1] not in permitted for command in commands):
            raise AccessError(_('Version line does not belong to this revision.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Plan versions cannot be deleted.'))

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        self._check_all_version_access()
        if self.state != 'draft':
            raise UserError(_('Only a draft revision can be cancelled.'))
        return super(BudgetPlanVersion, self).write({'state': 'cancel'})

    def action_activate(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self.period_id._lock_plan_periods()
        from .budget_allocation import _allocation_internal
        if not _allocation_internal.get() and self.env['erp.budget.allocation'].sudo().search_count([('plan_id', '=', self.plan_id.id)]):
            raise AccessError(_('Activate this plan through its allocation revision.'))
        self.invalidate_recordset()
        if self.state != 'draft' or not self.reason:
            raise UserError(_('A draft revision with a reason is required.'))
        base = self.base_version_id
        base.invalidate_recordset()
        if not base or base.state != 'effective' or base.plan_id != self.plan_id:
            raise UserError(_('This revision is stale; prepare a new revision.'))
        rows = self.line_ids
        all_rows = self.env['erp.budget.plan.version.line'].sudo().search([('version_id', '=', self.id)])
        expected = self.env['erp.budget.plan.line'].sudo().search([('plan_id', '=', self.plan_id.id)])
        if set(rows.ids) != set(all_rows.ids) or set(rows.mapped('plan_line_id').ids) != set(expected.ids) or len(rows) != len(expected):
            raise AccessError(_('The manager must access every plan line.'))
        for row in rows:
            line = row.plan_line_id
            line.check_access('write')
            line._check_all_control_access()
            line._check_opening_minimum(row.amount)
            if float_compare(line._ceiling(), row.base_amount, precision_rounding=line.currency_id.rounding):
                raise UserError(_('Plan capacity changed; prepare a new revision.'))
            if float_compare(row.amount, line._consumed(), precision_rounding=line.currency_id.rounding) < 0:
                raise UserError(_('A revision cannot reduce a ceiling below consumption.'))
            if line.allocation_mode == 'allocated' and float_compare(row.amount, line._allocated(), precision_rounding=line.currency_id.rounding) < 0:
                raise UserError(_('A revision cannot reduce a ceiling below allocations.'))
        with self.env.cr.savepoint():
            token = _event_create.set(True)
            try:
                values = []
                for row in rows:
                    delta = row.amount - row.base_amount
                    if not float_compare(delta, 0, precision_rounding=row.currency_id.rounding):
                        continue
                    values.append({'company_id': self.company_id.id, 'period_id': self.period_id.id, 'source_id': row.plan_line_id.id if delta < 0 else False, 'destination_id': row.plan_line_id.id if delta > 0 else False, 'kind': 'decrease' if delta < 0 else 'increase', 'amount': abs(delta), 'reference': self.reason, 'user_id': self.env.user.id, 'version_id': self.id, 'reversal_of_id': False})
                if values:
                    self.env['erp.budget.plan.event'].sudo().create(values)
            finally:
                _event_create.reset(token)
            super(BudgetPlanVersion, base.sudo()).write({'state': 'superseded'})
            base.flush_recordset(['state'])
            super(BudgetPlanVersion, self).write({'state': 'effective', 'effective_at': fields.Datetime.now(), 'approved_by_id': self.env.user.id, 'snapshot_anchor': True, 'event_cutoff': self.plan_id._revision_event_cutoff()})
        return True


class BudgetPlanVersionLine(models.Model):
    _name = 'erp.budget.plan.version.line'
    _description = 'Budget Plan Version Snapshot'
    _check_company_auto = True

    version_id = fields.Many2one('erp.budget.plan.version', required=True, ondelete='restrict', check_company=True, index=True)
    plan_line_id = fields.Many2one('erp.budget.plan.line', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='version_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='plan_line_id.organization_id', store=True, index=True)
    analytic_id = fields.Many2one(related='plan_line_id.analytic_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    base_amount = fields.Monetary(required=True, readonly=True)
    amount = fields.Monetary(required=True)
    _line_unique = models.Constraint('unique(version_id, plan_line_id)', 'Each plan line may appear only once per version.')

    @api.model_create_multi
    def create(self, vals_list):
        if not _revision_create.get():
            raise AccessError(_('Version lines are generated from the plan.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.mapped('version_id.period_id')._lock_plan_periods()
        self.invalidate_recordset()
        if set(vals) - {'amount'} or any(row.version_id.state != 'draft' for row in self):
            raise AccessError(_('Only draft revision amounts may be edited.'))
        if 'amount' in vals and any(not math.isfinite(vals['amount']) or vals['amount'] < 0 or abs(vals['amount'] - row.currency_id.round(vals['amount'])) > 1e-9 for row in self):
            raise ValidationError(_('Version amounts must be nonnegative and use company currency precision.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Version lines cannot be deleted.'))


class BudgetPlanEventRevision(models.Model):
    _inherit = 'erp.budget.plan.event'

    version_id = fields.Many2one('erp.budget.plan.version', readonly=True, ondelete='restrict', check_company=True)
