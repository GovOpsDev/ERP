import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_allocation import _allocation_internal


class BudgetAllocationRevisionMixin(models.Model):
    _inherit = 'erp.budget.allocation'

    def _lock_revision_scope(self):
        self.ensure_one()
        all_lines = self.env['erp.budget.allocation.line'].sudo().search([('allocation_id', '=', self.id)])
        lines = self.line_ids
        if set(all_lines.ids) != set(lines.ids):
            raise AccessError(_('Access to every allocation line is required.'))
        # Pending dimensions have no economic effect until their revision activates.
        lines = lines.filtered('control_id')
        published_lines = all_lines.filtered('control_id')
        controls = lines.mapped('control_id')
        controls.check_access('write')
        if len(controls) != len(lines):
            raise ValidationError(_('Every allocation line must have a distinct fund control.'))
        scope_controls = self.env['erp.budget.control'].sudo().with_context(active_test=False).search([('company_id', '=', self.company_id.id), ('period_id', '=', self.period_id.id)])
        scope_controls.with_env(self.env).check_access('read')
        if scope_controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(scope_controls.ids))])
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        scope_controls.invalidate_recordset()
        effective = self.env['erp.budget.allocation.revision'].sudo().search([('allocation_id', '=', self.id), ('state', '=', 'effective')])
        if len(effective) > 1:
            raise ValidationError(_('Multiple effective allocation revisions require repair.'))
        effective_lines = effective.line_ids if effective else self.env['erp.budget.allocation.revision.line'].sudo()
        if effective and (len(effective_lines) != len(published_lines) or set(effective_lines.mapped('allocation_line_id').ids) != set(published_lines.ids)):
            raise ValidationError(_('The effective allocation snapshot is incomplete.'))
        values = {row.allocation_line_id.id: row.amount for row in effective_lines}
        for line in lines:
            line.check_access('read')
            line._validate_dimensions()
            if float_compare(line.control_id.amount, values.get(line.id, line.released_amount), precision_rounding=line.currency_id.rounding):
                raise ValidationError(_('The fund control differs from the effective allocation; repair is required.'))
        return lines

    def action_prepare_allocation_revision(self):
        return self._prepare_allocation_revision('revision')

    def _prepare_allocation_revision(self, kind):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        lines = self._lock_revision_scope()
        if self.state != ('cancel' if kind == 'restore' else 'done') or self.plan_id.state not in ('confirm', 'done'):
            raise UserError(_('A completed allocation and confirmed plan are required.'))
        revisions = self.env['erp.budget.allocation.revision'].sudo().search([('allocation_id', '=', self.id)], order='number desc')
        effective = revisions.filtered(lambda r: r.state == 'effective')
        if len(effective) > 1:
            raise ValidationError(_('Multiple effective allocation revisions require repair.'))
        historical = effective.previous_id if kind == 'restore' else self.env['erp.budget.allocation.revision']
        while historical and not any(historical.line_ids.mapped('amount')):
            historical = historical.previous_id
        restored = {row.allocation_line_id.id: row.amount for row in historical.line_ids}
        token = _allocation_internal.set(True)
        try:
            with self.env.cr.savepoint():
                action = self.plan_id.action_prepare_revision()
                excluded = set(effective.line_ids.filtered('excluded').mapped('allocation_line_id').ids)
                amounts = {line.id: 0 if kind == 'cancel' else restored.get(line.id, line.released_amount) if kind == 'restore' else line.control_id.amount for line in lines}
                revision = self.env['erp.budget.allocation.revision'].sudo().create({'allocation_id': self.id, 'number': max(revisions.mapped('number') or [0]) + 1, 'state': 'draft', 'revision_kind': kind, 'cancelled_control_ids': [], 'previous_id': effective.id or False, 'plan_version_id': action['res_id'], 'reason': _('Cancel allocation') if kind == 'cancel' else _('Restore allocation') if kind == 'restore' else False, 'effective_at': False, 'activated_by_id': False, 'line_ids': [(0, 0, {'allocation_line_id': line.id, 'base_amount': line.control_id.amount, 'amount': amounts[line.id], 'excluded': not amounts[line.id] if kind in ('cancel', 'restore') else line.id in excluded}) for line in lines]})
        finally:
            _allocation_internal.reset(token)
        return {'type': 'ir.actions.act_window', 'name': _('Allocation revision'), 'res_model': 'erp.budget.allocation.revision', 'view_mode': 'form', 'res_id': revision.id, 'target': 'current'}

    def _check_cancel_consumption(self):
        self.ensure_one()
        self.env['erp.budget.move'].flush_model(['control_id', 'amount'])
        self.env.cr.execute('SELECT m.control_id, SUM(m.amount) FROM erp_budget_move m JOIN erp_budget_control c ON c.id=m.control_id WHERE c.company_id=%s AND c.period_id=%s GROUP BY m.control_id', [self.company_id.id, self.period_id.id])
        if any(float_compare(amount, 0, precision_rounding=self.currency_id.rounding) for _, amount in self.env.cr.fetchall()):
            raise UserError(_('Allocation cancellation requires zero net consumption on every control.'))

    def action_cancel(self):
        self.ensure_one()
        if self.state != 'done':
            return super().action_cancel()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self._lock_revision_scope()
        self._check_cancel_consumption()
        return self._prepare_allocation_revision('cancel')

    def action_draft(self):
        self.ensure_one()
        if self.state == 'cancel' and self.plan_id:
            return self._prepare_allocation_revision('restore')
        return super().action_draft()


class BudgetAllocationRevision(models.Model):
    _name = 'erp.budget.allocation.revision'
    _description = 'Budget Allocation Revision'
    _check_company_auto = True
    _order = 'number desc, id desc'

    allocation_id = fields.Many2one('erp.budget.allocation', required=True, readonly=True, check_company=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='allocation_id.company_id', store=True, index=True)
    period_id = fields.Many2one(related='allocation_id.period_id', store=True, index=True)
    number = fields.Integer(required=True, readonly=True)
    previous_id = fields.Many2one('erp.budget.allocation.revision', readonly=True, ondelete='restrict')
    plan_version_id = fields.Many2one('erp.budget.plan.version', required=True, readonly=True, check_company=True, ondelete='restrict')
    state = fields.Selection([('draft', 'Draft'), ('effective', 'Effective'), ('superseded', 'Superseded'), ('cancel', 'Cancelled')], required=True, readonly=True)
    reason = fields.Char()
    revision_kind = fields.Selection([('revision', 'Revision'), ('cancel', 'Allocation cancellation'), ('restore', 'Allocation restoration')], required=True, default='revision', readonly=True)
    cancelled_control_ids = fields.Many2many('erp.budget.control', 'erp_budget_cancelled_control_rel', 'revision_id', 'control_id', readonly=True)
    effective_at = fields.Datetime(readonly=True)
    activated_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    line_ids = fields.One2many('erp.budget.allocation.revision.line', 'revision_id')
    _number_unique = models.Constraint('unique(allocation_id, number)', 'Allocation revision numbers must be unique.')

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute("CREATE UNIQUE INDEX IF NOT EXISTS erp_budget_one_effective_allocation_revision ON erp_budget_allocation_revision (allocation_id) WHERE state = 'effective'")
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if not _allocation_internal.get():
            raise AccessError(_('Use the allocation revision action.'))
        return super().create(vals_list)

    def _check_scope(self):
        for revision in self:
            revision.allocation_id.check_access('write')
            revision.allocation_id._lock_revision_scope()
            rows = self.env['erp.budget.allocation.revision.line'].sudo().search([('revision_id', '=', revision.id)])
            rows.with_env(self.env).check_access('read')
            if set(rows.ids) != set(revision.line_ids.ids):
                raise AccessError(_('Access to every revision line is required.'))

    def write(self, vals):
        self.check_access('write')
        self._check_scope()
        commands = vals.get('line_ids', [])
        if set(vals) - {'reason', 'line_ids'} or any(r.state != 'draft' for r in self) or any(command[0] != 1 or set(command[2]) - {'amount', 'excluded'} for command in commands):
            raise AccessError(_('Only draft revision amounts, exclusions and reason may be edited.'))
        allowed = set(self.mapped('line_ids').ids)
        if any(command[1] not in allowed for command in commands):
            raise AccessError(_('Revision line does not belong to this revision.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Allocation revisions cannot be deleted.'))

    def action_add_dimension(self, organization_id, analytic_id, fund_id, amount, dimension_ids=None):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self._check_scope()
        self.invalidate_recordset()
        if self.state != 'draft':
            raise UserError(_('Dimensions may only be added to a draft revision.'))
        if self.revision_kind != 'revision':
            raise UserError(_('Cancellation and restoration retain the existing dimensions.'))
        if not math.isfinite(amount) or amount <= 0 or abs(amount - self.company_id.currency_id.round(amount)) > 1e-9:
            raise ValidationError(_('A new dimension needs a positive amount in company currency precision.'))
        dimensions = self.env['account.analytic.account'].browse(dimension_ids or []).exists()
        dimensions.check_access('read')
        if len(dimensions) != len(set(dimension_ids or [])):
            raise ValidationError(_('Every additional dimension must exist.'))
        values = {'allocation_id': self.allocation_id.id, 'organization_id': organization_id, 'analytic_id': analytic_id, 'fund_id': fund_id, 'dimension_ids': [(6, 0, dimensions.ids)], 'allocated_amount': amount, 'introduced_revision_id': self.id}
        existing = self.allocation_id.line_ids.filtered(lambda line: line.organization_id.id == organization_id and line.analytic_id.id == analytic_id and line.fund_id.id == fund_id and set(line.dimension_ids.ids) == set(dimensions.ids))
        if existing and (existing.control_id or existing.introduced_revision_id.state != 'cancel'):
            raise ValidationError(_('This allocation dimension already exists; revise its existing snapshot.'))
        token = _allocation_internal.set(True)
        try:
            with self.env.cr.savepoint():
                if existing:
                    line = existing
                    line.write({'introduced_revision_id': self.id})
                else:
                    line = self.env['erp.budget.allocation.line'].create(values)
                row = self.env['erp.budget.allocation.revision.line'].create({'revision_id': self.id, 'allocation_line_id': line.id, 'base_amount': 0, 'amount': amount})
        finally:
            _allocation_internal.reset(token)
        return row.id

    def action_add_dimension_form(self):
        self.ensure_one()
        self.check_access('write')
        return {'type': 'ir.actions.act_window', 'name': _('Add allocation dimension'), 'res_model': 'erp.budget.allocation.dimension', 'view_mode': 'form', 'target': 'new', 'context': {'default_revision_id': self.id}}

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self._check_scope()
        self.invalidate_recordset()
        if self.state != 'draft':
            raise UserError(_('Only a draft revision may be cancelled.'))
        with self.env.cr.savepoint():
            from .budget_release import _planning_internal
            planning = self.env['erp.budget.kpi.release'].search([('allocation_revision_id', '=', self.id), ('state', 'in', ('draft', 'submit', 'approved'))])
            planning_token = _planning_internal.set(True)
            try:
                for release in planning:
                    release._lock_controls()
                    release.write({'state': 'cancel'})
            finally:
                _planning_internal.reset(planning_token)
            self.plan_version_id.action_cancel()
            return super(BudgetAllocationRevision, self).write({'state': 'cancel'})

    def action_activate(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self._check_scope()
        self.invalidate_recordset()
        if self.state != 'draft' or not self.reason:
            raise UserError(_('A draft revision with a reason is required.'))
        if self.revision_kind == 'cancel':
            self.allocation_id._check_cancel_consumption()
            if any(self.line_ids.mapped('amount')):
                raise ValidationError(_('Cancellation must remove every dimension capacity.'))
        current = self.env['erp.budget.allocation.revision'].sudo().search([('allocation_id', '=', self.allocation_id.id), ('state', '=', 'effective')])
        if len(current) > 1 or (current.id if current else False) != self.previous_id.id:
            raise UserError(_('This allocation revision is stale.'))
        allocation_lines = self.allocation_id.line_ids.filtered('control_id')
        rows = self.line_ids
        new_lines = rows.mapped('allocation_line_id').filtered(lambda line: not line.control_id)
        if set(rows.mapped('allocation_line_id').ids) != set((allocation_lines | new_lines).ids) or len(rows) != len(allocation_lines | new_lines) or any(line.allocation_id != self.allocation_id or line.introduced_revision_id != self for line in new_lines):
            raise ValidationError(_('The revision must contain every allocation line.'))
        grouped = {}
        self.env['erp.budget.move'].flush_model(['control_id', 'amount'])
        for row in rows:
            source = row.allocation_line_id
            source._validate_dimensions()
            control = source.control_id
            if row.excluded and row.amount:
                raise ValidationError(_('An excluded dimension must have zero capacity.'))
            if not control:
                if row.excluded or row.amount <= 0:
                    raise ValidationError(_('A new dimension requires positive capacity.'))
                key = source.analytic_id.id
                grouped[key] = grouped.get(key, 0) + row.amount
                continue
            control.invalidate_recordset(['amount'])
            if float_compare(control.amount, row.base_amount, precision_rounding=self.company_id.currency_id.rounding):
                raise UserError(_('Released fund capacity changed; prepare a new revision.'))
            if control.state not in (('draft', 'open', 'closed') if self.revision_kind == 'restore' or self.allocation_id.legacy_baseline else ('draft', 'open')) or not control.active:
                raise UserError(_('Fund controls must be active and not closed.'))
            self.env.cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [control.id])
            if float_compare(row.amount, self.env.cr.fetchone()[0], precision_rounding=self.company_id.currency_id.rounding) < 0:
                raise UserError(_('Fund capacity cannot be reduced below consumption.'))
            key = source.analytic_id.id
            grouped[key] = grouped.get(key, 0) + row.amount
        version = self.plan_version_id
        planning_revisions = self.env['erp.budget.kpi.release'].search([('allocation_revision_id', '=', self.id), ('state', '=', 'approved')])
        for planning in planning_revisions:
            planning._validate_planning_revision()
        for analytic_id in grouped:
            if len(rows.mapped('allocation_line_id').filtered(lambda line: line.analytic_id.id == analytic_id).mapped('organization_id')) != 1:
                raise ValidationError(_('One organization must own each analytic plan line.'))
        for plan_row in version.line_ids:
            plan_line = plan_row.plan_line_id
            planned = plan_line._allocated()
            revisions = planning_revisions.filtered(lambda release: release.plan_line_id == plan_line)
            has_effective_planning = self.env['erp.budget.kpi.release'].search_count([('plan_line_id', '=', plan_line.id), ('state', '=', 'done')])
            if plan_line._requires_source_planning_reconciliation() and (planned or (self.revision_kind == 'restore' and has_effective_planning)):
                if len(revisions) != 1 or float_compare(revisions._proposed_planning_total(), grouped[plan_row.analytic_id.id], precision_rounding=plan_line.currency_id.rounding):
                    raise UserError(_('Approve one coordinated KPI planning revision for each released analytic.'))
        with self.env.cr.savepoint():
            token = _allocation_internal.set(True)
            try:
                from .budget_revision import _revision_create
                version_token = _revision_create.set(True)
                try:
                    for analytic_id in set(grouped) - set(version.line_ids.mapped('analytic_id').ids):
                        sources = rows.mapped('allocation_line_id').filtered(lambda line: line.analytic_id.id == analytic_id)
                        if len(sources.mapped('organization_id')) != 1:
                            raise ValidationError(_('One organization must own each analytic plan line.'))
                        plan_line = self.env['erp.budget.plan.line'].create({'plan_id': self.allocation_id.plan_id.id, 'organization_id': sources[0].organization_id.id, 'analytic_id': analytic_id, 'initial_amount': 0, 'introduced_revision_id': self.id, 'allocation_mode': 'allocated' if self.period_id.release_policy == 'formal' else 'limits', 'release_required': self.period_id.release_policy == 'formal'})
                        self.env['erp.budget.plan.version.line'].create({'version_id': version.id, 'plan_line_id': plan_line.id, 'base_amount': 0, 'amount': grouped[analytic_id]})
                finally:
                    _revision_create.reset(version_token)
                version.write({'reason': self.reason})
                plan_rows = version.line_ids
                if set(plan_rows.mapped('analytic_id').ids) != set(grouped):
                    raise ValidationError(_('Allocation and plan dimensions do not match.'))
                for plan_row in plan_rows:
                    plan_row.write({'amount': grouped[plan_row.analytic_id.id]})
                from .budget_release import _planning_internal
                planning_token = _planning_internal.set(True)
                try:
                    for planning in planning_revisions:
                        planning._apply_planning_revision(defer_open=True)
                finally:
                    _planning_internal.reset(planning_token)
                if self.allocation_id.legacy_baseline:
                    self.allocation_id.plan_id.line_ids._activate_canonical_policy()
                version.action_activate()
                if self.revision_kind == 'restore':
                    self.allocation_id.write({'state': 'done'})
                for row in rows:
                    source = row.allocation_line_id
                    if source.control_id:
                        source.control_id._set_allocation_revision_amount(row.amount)
                    else:
                        control = self.env['erp.budget.control'].create({'name': self.allocation_id.name, 'company_id': self.company_id.id, 'period_id': self.period_id.id, 'organization_id': source.organization_id.id, 'analytic_id': source.analytic_id.id, 'level': 'fund', 'fund_id': source.fund_id.id, 'dimension_ids': [(6, 0, source.dimension_ids.ids)], 'amount': row.amount, 'allocation_line_id': source.id})
                        source.write({'control_id': control.id})
                        control.action_open()
                if self.revision_kind == 'restore':
                    restored_controls = self.previous_id.cancelled_control_ids.with_env(self.env)
                    planning_controls = planning_revisions.line_ids.control_id
                    legacy_controls = restored_controls.filtered(lambda control: control.level == 'analytic') - planning_controls
                    from .budget_release import _planning_internal
                    restore_token = _planning_internal.set(True)
                    try:
                        (restored_controls.filtered(lambda control: control.level == 'fund') | legacy_controls).filtered(lambda control: control.state == 'closed')._prepare_control_restoration()
                    finally:
                        _planning_internal.reset(restore_token)
                    restored_controls.filtered(lambda control: control.state == 'draft' and control not in planning_controls).action_open()
                from .budget_control import _release_open
                release_token = _release_open.set(True)
                try:
                    planning_revisions.line_ids.control_id.filtered(lambda control: control.state == 'draft').action_open()
                finally:
                    _release_open.reset(release_token)
                if current:
                    super(BudgetAllocationRevision, current).write({'state': 'superseded'})
                    current.flush_recordset(['state'])
                super(BudgetAllocationRevision, self).write({'state': 'effective', 'effective_at': fields.Datetime.now(), 'activated_by_id': self.env.user.id})
                if self.revision_kind == 'cancel':
                    controls = self.env['erp.budget.control'].search([('period_id', '=', self.period_id.id), ('company_id', '=', self.company_id.id), ('state', '=', 'open')])
                    super(BudgetAllocationRevision, self).write({'cancelled_control_ids': [(6, 0, controls.ids)]})
                    from .budget_control import _release_close
                    close_token = _release_close.set(True)
                    try:
                        controls.action_close()
                    finally:
                        _release_close.reset(close_token)
                    self.allocation_id.write({'state': 'cancel'})
            finally:
                _allocation_internal.reset(token)
        return True


class BudgetAllocationRevisionLine(models.Model):
    _name = 'erp.budget.allocation.revision.line'
    _description = 'Budget Allocation Revision Snapshot'
    _check_company_auto = True

    revision_id = fields.Many2one('erp.budget.allocation.revision', required=True, check_company=True, ondelete='restrict', index=True)
    allocation_line_id = fields.Many2one('erp.budget.allocation.line', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='revision_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='allocation_line_id.organization_id', store=True, index=True)
    analytic_id = fields.Many2one(related='allocation_line_id.analytic_id')
    fund_id = fields.Many2one(related='allocation_line_id.fund_id')
    dimension_ids = fields.Many2many(related='allocation_line_id.dimension_ids')
    excluded = fields.Boolean(default=False, help='Retain the dimension and its history with zero effective capacity.')
    currency_id = fields.Many2one(related='company_id.currency_id')
    base_amount = fields.Monetary(required=True, readonly=True)
    amount = fields.Monetary(required=True)
    _line_unique = models.Constraint('unique(revision_id, allocation_line_id)', 'Each allocation line occurs once per revision.')

    @api.model_create_multi
    def create(self, vals_list):
        if not _allocation_internal.get():
            raise AccessError(_('Revision lines are generated from the allocation.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.mapped('revision_id')._check_scope()
        self.invalidate_recordset()
        if set(vals) - {'amount', 'excluded'} or any(row.revision_id.state != 'draft' for row in self):
            raise AccessError(_('Only draft revision amounts may be edited.'))
        if 'amount' in vals and any(not math.isfinite(vals['amount']) or vals['amount'] < 0 or abs(vals['amount'] - row.currency_id.round(vals['amount'])) > 1e-9 for row in self):
            raise ValidationError(_('Revision amounts must be nonnegative and use company currency precision.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Revision snapshots cannot be deleted.'))


class BudgetAllocationDimension(models.TransientModel):
    _name = 'erp.budget.allocation.dimension'
    _description = 'Add Allocation Revision Dimension'

    revision_id = fields.Many2one('erp.budget.allocation.revision', required=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True)
    analytic_id = fields.Many2one('account.analytic.account', required=True)
    fund_id = fields.Many2one('erp.budget.fund', required=True)
    dimension_ids = fields.Many2many('account.analytic.account')
    currency_id = fields.Many2one(related='revision_id.company_id.currency_id')
    amount = fields.Monetary(required=True)

    def action_add(self):
        self.ensure_one()
        self.revision_id.action_add_dimension(self.organization_id.id, self.analytic_id.id, self.fund_id.id, self.amount, self.dimension_ids.ids)
        return {'type': 'ir.actions.act_window_close'}
