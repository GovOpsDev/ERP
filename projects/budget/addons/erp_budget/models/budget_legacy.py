"""Explicit capture of target history; captured facts are not past approvals."""
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_allocation import _allocation_internal
from .budget_control import BudgetControl
from .budget_plan import BudgetPlanLine
from .budget_release import _planning_internal

_legacy_capture = ContextVar('budget_legacy_capture', default=False)


class BudgetLegacyPlan(models.Model):
    _inherit = 'erp.budget.plan'

    def action_capture_legacy_allocation(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        controls = self.env['erp.budget.control'].sudo().with_context(active_test=False).search([('period_id', '=', self.period_id.id)])
        controls.with_env(self.env).check_access('write')
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        existing = self.env['erp.budget.allocation'].search([('period_id', '=', self.period_id.id)])
        if existing:
            if existing.plan_id != self:
                raise UserError(_('Another allocation already owns this period.'))
            return {'type': 'ir.actions.act_window', 'res_model': existing._name, 'view_mode': 'form', 'res_id': existing.id}
        if self.state not in ('confirm', 'done'):
            raise UserError(_('Only a confirmed existing plan can be captured.'))
        all_plan_lines = self.env['erp.budget.plan.line'].sudo().search([('plan_id', '=', self.id)])
        all_plan_lines.with_env(self.env).check_access('write')
        if set(all_plan_lines.ids) != set(self.line_ids.ids):
            raise AccessError(_('Access to every plan line is required.'))
        current = controls.filtered(lambda row: row.active and not row.erp_release_reversed and row.state in ('open', 'closed')).with_env(self.env)
        funds = current.filtered(lambda row: row.level == 'fund')
        if not funds or any(control.allocation_line_id for control in funds):
            raise UserError(_('Unanchored effective fund controls are required.'))
        keys = {(row.organization_id.id, row.analytic_id.id, row.fund_id.id, tuple(sorted(row.dimension_ids.ids))) for row in funds}
        if len(keys) != len(funds):
            raise UserError(_('Duplicate legacy fund keys must be explicitly consolidated before capture.'))
        plan_analytics = set(self.line_ids.analytic_id.ids)
        if set(current.analytic_id.ids) != plan_analytics or any(len(self.line_ids.filtered(lambda line: line.analytic_id == control.analytic_id and line.organization_id == control.organization_id)) != 1 for control in current):
            raise ValidationError(_('Every effective control must match one owning plan line.'))
        for line in self.line_ids:
            if not funds.filtered(lambda control: control.analytic_id == line.analytic_id) or not current.filtered(lambda control: control.level == 'analytic' and control.analytic_id == line.analytic_id):
                raise UserError(_('Each analytic requires existing fund and analytic controls.'))
            line._check_all_control_access()
        allocation_token = _allocation_internal.set(True)
        planning_token = _planning_internal.set(True)
        capture_token = _legacy_capture.set(True)
        try:
            with self.env.cr.savepoint():
                allocation = self.env['erp.budget.allocation'].create({'name': _('Captured target baseline: %s') % self.name, 'company_id': self.company_id.id, 'period_id': self.period_id.id, 'legacy_baseline': True, 'captured_by_id': self.env.user.id, 'captured_at': fields.Datetime.now()})
                for control in funds:
                    line = self.env['erp.budget.allocation.line'].create({'allocation_id': allocation.id, 'organization_id': control.organization_id.id, 'analytic_id': control.analytic_id.id, 'fund_id': control.fund_id.id, 'dimension_ids': [(6, 0, control.dimension_ids.ids)], 'allocated_amount': control.amount, 'released_amount': control.amount, 'control_id': control.id})
                    control._capture_allocation_link(line)
                allocation.write({'plan_id': self.id, 'state': 'done'})
                for line in self.line_ids:
                    analytic_controls = current.filtered(lambda control: control.level == 'analytic' and control.analytic_id == line.analytic_id)
                    releases = self.env['erp.budget.kpi.release'].search([('plan_line_id', '=', line.id), ('state', '=', 'done')])
                    if len(releases) == 1 and set(releases.line_ids.control_id.ids) == set(analytic_controls.ids):
                        continue
                    baseline = self.env['erp.budget.kpi.release'].create({'name': _('Captured target controls: %s') % line.analytic_id.name, 'plan_line_id': line.id, 'released_amount': sum(analytic_controls.mapped('amount')), 'legacy_baseline': True, 'captured_by_id': self.env.user.id, 'captured_at': fields.Datetime.now(), 'legacy_release_ids': [(6, 0, releases.ids)], 'line_ids': [(0, 0, {'control_id': control.id, 'planning_ids': []}) for control in analytic_controls]})
                    baseline.write({'planning_snapshot': False, 'state': 'done'})
                    # This is a present-day consolidation of captured target facts.
                    # The original amounts, reviews and approval dates stay intact.
                    releases.write({'state': 'superseded'})
        finally:
            _legacy_capture.reset(capture_token)
            _planning_internal.reset(planning_token)
            _allocation_internal.reset(allocation_token)
        return {'type': 'ir.actions.act_window', 'res_model': allocation._name, 'view_mode': 'form', 'res_id': allocation.id}


class BudgetLegacyAllocation(models.Model):
    _inherit = 'erp.budget.allocation'

    legacy_baseline = fields.Boolean(readonly=True, help='Captured current target facts, not a historical upstream allocation approval.')
    captured_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    captured_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'legacy_baseline', 'captured_by_id', 'captured_at'}
        if not _legacy_capture.get() and (any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected)):
            raise AccessError(_('Legacy baselines must be explicitly captured from existing controls.'))
        return super().create(vals_list)


class BudgetLegacyControl(models.Model):
    _inherit = 'erp.budget.control'

    def _capture_allocation_link(self, line):
        self.ensure_one()
        if not _legacy_capture.get() or self.level != 'fund' or self.allocation_line_id or line.control_id != self or not line.allocation_id.legacy_baseline:
            raise AccessError(_('Legacy allocation links are internal to explicit capture.'))
        return super(BudgetControl, self).write({'allocation_line_id': line.id})


class BudgetLegacyPlanning(models.Model):
    _inherit = 'erp.budget.kpi.release'

    legacy_baseline = fields.Boolean(readonly=True, help='Derived current target snapshot with no invented historical reviewer or date ranges.')
    captured_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    captured_at = fields.Datetime(readonly=True)
    legacy_release_ids = fields.Many2many('erp.budget.kpi.release', 'erp_budget_legacy_release_rel', 'baseline_id', 'release_id', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'legacy_baseline', 'captured_by_id', 'captured_at', 'legacy_release_ids'}
        if not _legacy_capture.get() and (any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected)):
            raise AccessError(_('Legacy planning facts must be captured explicitly.'))
        return super().create(vals_list)

    def action_prepare_revision(self, allocation_revision_id=None):
        action = super().action_prepare_revision(allocation_revision_id)
        # Successors record actual new planning, not another derived baseline.
        successor = self.browse(action['res_id'])
        token = _planning_internal.set(True)
        try:
            successor.write({'legacy_baseline': False, 'captured_by_id': False, 'captured_at': False, 'legacy_release_ids': [(5, 0, 0)]})
        finally:
            _planning_internal.reset(token)
        return action


class BudgetLegacyPlanLine(models.Model):
    _inherit = 'erp.budget.plan.line'

    def _requires_source_planning_reconciliation(self):
        self.ensure_one()
        return super()._requires_source_planning_reconciliation() or bool(self.env['erp.budget.allocation'].sudo().search_count([('plan_id', '=', self.plan_id.id), ('legacy_baseline', '=', True)]))

    def _activate_canonical_policy(self):
        if not _allocation_internal.get():
            raise AccessError(_('Canonical policy activation is internal.'))
        return super(BudgetPlanLine, self).write({'allocation_mode': 'allocated', 'release_required': True})
