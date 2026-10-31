import math
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_control import _release_open, _release_close

_review_internal = ContextVar('budget_release_review_internal', default=False)
_tier_approved = ContextVar('budget_release_tier_approved', default=False)
_planning_internal = ContextVar('budget_planning_internal', default=False)


class BudgetKpiRelease(models.Model):
    _name = 'erp.budget.kpi.release'
    _description = 'Budget KPI Release'
    _check_company_auto = True

    name = fields.Char(required=True)
    plan_line_id = fields.Many2one('erp.budget.plan.line', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='plan_line_id.company_id', store=True, index=True)
    period_id = fields.Many2one(related='plan_line_id.period_id', store=True)
    organization_id = fields.Many2one(related='plan_line_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    released_amount = fields.Monetary(required=True)
    state = fields.Selection([('draft', 'Draft'), ('submit', 'Submitted'), ('done', 'Released'), ('cancel', 'Cancelled'), ('reversed', 'Reversed')], default='draft', required=True, readonly=True)
    line_ids = fields.One2many('erp.budget.kpi.release.line', 'release_id')
    review_ids = fields.One2many('erp.budget.kpi.review', 'release_id', readonly=True)
    review_round = fields.Integer(default=0, readonly=True)
    submitted_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    released_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    released_at = fields.Datetime(readonly=True)
    reversed_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    reversed_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        forbidden = {'company_id', 'period_id', 'organization_id', 'released_by_id', 'released_at', 'reversed_by_id', 'reversed_at', 'review_ids', 'review_round', 'submitted_by_id'}
        if not _planning_internal.get() and (any(forbidden & vals.keys() or vals.get('state', 'draft') != 'draft' for vals in vals_list) or any('default_' + key in self.env.context for key in forbidden | {'state'})):
            raise AccessError(_('A release must begin in draft with derived scope.'))
        for vals in vals_list:
            line = self.env['erp.budget.plan.line'].browse(vals.get('plan_line_id')).exists()
            if not line:
                raise ValidationError(_('A plan line is required.'))
            line.check_access('write')
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        if _planning_internal.get():
            return super().write(vals)
        if 'line_ids' in vals:
            controls = self.mapped('line_ids.control_id')
            for command in vals['line_ids']:
                if command[0] in (0, 1) and command[2].get('control_id'):
                    controls |= self.env['erp.budget.control'].browse(command[2]['control_id']).exists()
            controls.check_access('read')
            if controls:
                self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        self.mapped('period_id')._lock_plan_periods()
        if set(vals) - {'name', 'released_amount', 'line_ids'} or any(rec.state != 'draft' for rec in self):
            raise AccessError(_('Only draft releases may be edited.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.mapped('period_id')._lock_plan_periods()
        if any(rec.state != 'draft' for rec in self):
            raise AccessError(_('Only draft releases may be deleted.'))
        return super().unlink()

    def _lock_controls(self):
        self.ensure_one()
        visible_lines = self.line_ids
        all_lines = self.env['erp.budget.kpi.release.line'].sudo().search([('release_id', '=', self.id)])
        if set(visible_lines.ids) != set(all_lines.ids):
            raise AccessError(_('Access to all release lines is required.'))
        controls = visible_lines.mapped('control_id') | self.previous_id.line_ids.mapped('control_id')
        controls.check_access('write')
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        controls.invalidate_recordset()
        return controls

    def action_release(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        if self.previous_id:
            return self._activate_planning_revision()
        if self.state == 'draft' or (self.state == 'submit' and not _tier_approved.get()):
            raise AccessError(_('The configured review tiers must approve this release.'))
        controls = self._lock_controls()
        plan_line = self.plan_line_id
        plan_line.check_access('write')
        if self.state == 'done':
            return True
        plan_line._check_all_control_access()
        all_lines = self.env['erp.budget.kpi.release.line'].sudo().search([('release_id', '=', self.id)])
        if set(self.line_ids.ids) != set(all_lines.ids):
            raise AccessError(_('Access to all release lines is required.'))
        if self.state != 'submit' or not _tier_approved.get() or not controls or len(controls) != len(self.line_ids) or not plan_line.release_required or plan_line.allocation_mode != 'allocated' or plan_line.plan_id.state not in ('confirm', 'done'):
            raise ValidationError(_('A draft release for a confirmed formal-allocation plan is required.'))
        for control in controls:
            if control.company_id != self.company_id or control.period_id != self.period_id or control.analytic_id != plan_line.analytic_id or control.level != 'analytic' or (self.period_id.control_level == 'analytic_kpi' and not control.kpi_id) or control.state != 'draft' or not control.active:
                raise ValidationError(_('Release lines require draft KPI controls matching the plan.'))
        rounding = self.currency_id.rounding
        self._validate_planning()
        if not math.isfinite(self.released_amount) or abs(self.released_amount - self.currency_id.round(self.released_amount)) > 1e-9 or float_compare(self.released_amount, 0, precision_rounding=rounding) <= 0 or float_compare(sum(controls.mapped('amount')), self.released_amount, precision_rounding=rounding):
            raise ValidationError(_('The sum of KPI amounts must equal the declared released amount.'))
        planned = plan_line._allocated(controls.ids)
        plan_line._check_opening_minimum(planned)
        comparison = float_compare(planned, plan_line._ceiling(), precision_rounding=rounding)
        if comparison > 0:
            raise UserError(_('Total released KPI amounts exceed the shared plan ceiling.'))
        if plan_line._requires_source_planning_reconciliation() and comparison:
            raise UserError(_('KPI planning must equal the released allocation amount.'))
        token = _release_open.set(True)
        try:
            with self.env.cr.savepoint():
                controls.action_open()
                version = self.env['erp.budget.plan.version'].search([('plan_id', '=', plan_line.plan_id.id), ('state', '=', 'effective')], limit=1)
                return super(BudgetKpiRelease, self).write({'state': 'done', 'released_by_id': self.env.user.id, 'released_at': fields.Datetime.now(), 'plan_version_id': version.id})
        finally:
            _release_open.reset(token)

    def action_submit(self):
        self.ensure_one()
        self.check_access('write')
        controls = self._lock_controls()
        self.plan_line_id._check_all_control_access()
        self._validate_planning()
        if self.previous_id:
            self._validate_planning_revision()
        self._check_planning_opening(self._proposed_planning_total())
        if self.state != 'draft' or not self.line_ids or len(self.line_ids.mapped('control_id')) != len(self.line_ids):
            raise ValidationError(_('A draft release with KPI controls is required.'))
        if self.plan_line_id._requires_source_planning_reconciliation() and float_compare(self._proposed_planning_total(), self._expected_planning_ceiling(), precision_rounding=self.currency_id.rounding):
            raise UserError(_('KPI planning must equal the released allocation amount.'))
        tiers = self.env['erp.budget.kpi.tier'].search([('company_id', '=', self.company_id.id), ('organization_id', '=', self.organization_id.id), ('active', '=', True), ('kind', '=', 'planning')], order='sequence,id')
        return self._submit_tiers(tiers, controls)

    def _submit_tiers(self, tiers, controls):
        self.ensure_one()
        if not tiers:
            raise ValidationError(_('No budget release review tier is configured.'))
        if len(tiers.mapped('reviewer_id')) != len(tiers):
            raise ValidationError(_('Each review tier must have a distinct reviewer.'))
        for tier in tiers:
            reviewer = tier.reviewer_id
            if reviewer == self.env.user or not reviewer.has_group('erp_budget.group_budget_manager') or self.company_id not in reviewer.company_ids:
                raise ValidationError(_('Reviewers must be distinct authorized budget managers in the company.'))
            reviewer_controls = controls.with_user(reviewer).with_context(allowed_company_ids=[self.company_id.id])
            reviewer_controls.check_access('read')
            self.plan_line_id.with_user(reviewer).with_context(allowed_company_ids=[self.company_id.id]).check_access('read')
        round_number = self.review_round + 1
        token = _review_internal.set(True)
        try:
            with self.env.cr.savepoint():
                self.env['erp.budget.kpi.review'].sudo().create([{'release_id': self.id, 'reviewer_id': tier.reviewer_id.id, 'sequence': tier.sequence, 'round_number': round_number, 'state': 'pending'} for tier in tiers])
                return super(BudgetKpiRelease, self).write({'state': 'submit', 'review_round': round_number, 'submitted_by_id': self.env.user.id})
        finally:
            _review_internal.reset(token)

    def action_approve(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self._lock_controls()
        if self.state in ('done', 'approved') and self.env.user in self.review_ids.filtered(lambda row: row.round_number == self.review_round and row.state == 'approved').mapped('reviewer_id'):
            return True
        if self.state != 'submit' or self.submitted_by_id == self.env.user:
            raise AccessError(_('Only an assigned reviewer can approve a submitted release.'))
        reviews = self.review_ids.filtered(lambda row: row.round_number == self.review_round).sorted(lambda row: (row.sequence, row.id))
        pending = reviews.filtered(lambda row: row.state == 'pending')[:1]
        if pending and pending.reviewer_id != self.env.user and self.env.user in reviews.filtered(lambda row: row.state == 'approved').mapped('reviewer_id'):
            return True
        if not pending or pending.reviewer_id != self.env.user:
            raise AccessError(_('Only the next assigned reviewer may approve.'))
        self.plan_line_id._check_all_control_access()
        token = _review_internal.set(True)
        try:
            with self.env.cr.savepoint():
                pending.sudo().write({'state': 'approved'})
                if all(review.state == 'approved' for review in reviews):
                    approval = _tier_approved.set(True)
                    try:
                        return self.action_release()
                    finally:
                        _tier_approved.reset(approval)
                return True
        finally:
            _review_internal.reset(token)

    def action_reject(self):
        self.ensure_one()
        self.check_access('read')
        self._lock_controls()
        self.plan_line_id._check_all_control_access()
        if self.state != 'submit' or self.submitted_by_id == self.env.user:
            raise AccessError(_('Only the next reviewer may reject.'))
        pending = self.review_ids.filtered(lambda row: row.round_number == self.review_round and row.state == 'pending').sorted(lambda row: (row.sequence, row.id))[:1]
        if not pending or pending.reviewer_id != self.env.user or not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Only the next assigned reviewer may reject.'))
        token = _review_internal.set(True)
        try:
            with self.env.cr.savepoint():
                pending.sudo().write({'state': 'rejected'})
                return super(BudgetKpiRelease, self).write({'state': 'cancel'})
        finally:
            _review_internal.reset(token)

    def action_draft(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_controls()
        self.plan_line_id._check_all_control_access()
        if self.state != 'cancel':
            raise UserError(_('Only cancelled releases may be reset.'))
        return super(BudgetKpiRelease, self).write({'state': 'draft'})

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_controls()
        self.plan_line_id._check_all_control_access()
        if self.state != 'draft':
            raise UserError(_('Only a draft release can be cancelled.'))
        return super(BudgetKpiRelease, self).write({'state': 'cancel'})

    def action_reverse(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        controls = self._lock_controls()
        self.plan_line_id._check_all_control_access()
        if self.state == 'reversed':
            return True
        if self.state != 'done' or any(c.state != 'open' for c in controls):
            raise UserError(_('Only an open released allocation can be reversed.'))
        self.env['erp.budget.move'].flush_model(['control_id', 'amount'])
        self.env.cr.execute('SELECT control_id, COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id IN %s GROUP BY control_id', [tuple(controls.ids)])
        if any(float_compare(amount, 0, precision_rounding=self.currency_id.rounding) for _, amount in self.env.cr.fetchall()):
            raise UserError(_('A release with active consumption cannot be reversed.'))
        with self.env.cr.savepoint():
            token = _release_close.set(True)
            try:
                controls.action_close()
            finally:
                _release_close.reset(token)
            self.env.cr.execute('UPDATE erp_budget_control SET erp_release_reversed=TRUE WHERE id IN %s', [tuple(controls.ids)])
            controls.invalidate_recordset(['erp_release_reversed'])
            return super(BudgetKpiRelease, self).write({'state': 'reversed', 'reversed_by_id': self.env.user.id, 'reversed_at': fields.Datetime.now()})


class BudgetKpiReleaseLine(models.Model):
    _name = 'erp.budget.kpi.release.line'
    _description = 'Budget KPI Release Line'
    _check_company_auto = True

    release_id = fields.Many2one('erp.budget.kpi.release', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='release_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='control_id.organization_id', store=True, index=True)
    control_id = fields.Many2one('erp.budget.control', required=True, ondelete='restrict', check_company=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount = fields.Monetary(required=True)
    _control_unique = models.Constraint('unique(release_id, control_id)', 'A KPI control occurs once per release version.')

    def _auto_init(self):
        self.env.cr.execute("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'erp_budget_kpi_release_line' AND column_name = 'amount')")
        existed = self.env.cr.fetchone()[0]
        result = super()._auto_init()
        if not existed:
            # Old controls were immutable. Capture their current values without
            # manufacturing source versions or historical approval records.
            self.env.cr.execute('UPDATE erp_budget_kpi_release_line l SET amount = c.amount FROM erp_budget_control c WHERE c.id = l.control_id')
            self.env.cr.execute('ALTER TABLE erp_budget_kpi_release_line ALTER COLUMN amount SET NOT NULL')
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if any('default_' + field in self.env.context for field in ('company_id', 'organization_id', 'amount')):
            raise AccessError(_('Release scope and amount derive from the control.'))
        control_ids = [vals.get('control_id') for vals in vals_list if vals.get('control_id')]
        if control_ids:
            self.env['erp.budget.control'].browse(control_ids).check_access('read')
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(set(control_ids)))])
        releases = self.env['erp.budget.kpi.release'].browse([vals.get('release_id') for vals in vals_list if vals.get('release_id')]).exists()
        releases.mapped('period_id')._lock_plan_periods()
        releases.invalidate_recordset()
        for vals in vals_list:
            release = self.env['erp.budget.kpi.release'].browse(vals.get('release_id')).exists()
            control = self.env['erp.budget.control'].browse(vals.get('control_id')).exists()
            if not release or not control or release.state != 'draft':
                raise ValidationError(_('A draft release and control are required.'))
            release.check_access('write')
            control.check_access('read')
            if {'company_id', 'organization_id'} & vals.keys() or ('amount' in vals and not release.previous_id and not _planning_internal.get()):
                raise AccessError(_('Release scope and amount derive from the control.'))
            vals.setdefault('amount', control.amount)
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        controls = self.mapped('control_id') | self.env['erp.budget.control'].browse(vals.get('control_id')).exists()
        controls.check_access('read')
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        self.mapped('release_id.period_id')._lock_plan_periods()
        self.invalidate_recordset()
        if any(line.release_id.state != 'draft' for line in self):
            raise AccessError(_('Released allocation lines are immutable.'))
        if set(vals) - {'control_id', 'amount', 'planning_ids'} or ('amount' in vals and any(not line.release_id.previous_id for line in self) and not _planning_internal.get()):
            raise AccessError(_('Release scope and amount derive from the control.'))
        if vals.get('control_id'):
            self.env['erp.budget.control'].browse(vals['control_id']).check_access('read')
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        controls = self.mapped('control_id')
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        self.mapped('release_id.period_id')._lock_plan_periods()
        self.invalidate_recordset()
        if any(line.release_id.state != 'draft' for line in self):
            raise AccessError(_('Released allocation lines cannot be deleted.'))
        return super().unlink()


class BudgetKpiTier(models.Model):
    _name = 'erp.budget.kpi.tier'
    _description = 'Budget Release Reviewer Configuration'
    _order = 'sequence, id'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, ondelete='restrict', index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict')
    kind = fields.Selection([('planning', 'Control planning'), ('transfer', 'Budget transfer')], required=True, default='planning')
    sequence = fields.Integer(default=10, required=True)
    reviewer_id = fields.Many2one('res.users', required=True, ondelete='restrict')
    active = fields.Boolean(default=True)
    _tier_sequence_unique = models.Constraint('unique(company_id, organization_id, kind, sequence)', 'Tier order must be unique per company and organization.')
    _tier_reviewer_unique = models.Constraint('unique(company_id, organization_id, kind, reviewer_id)', 'A reviewer may have only one tier per company and organization.')

    @api.constrains('company_id', 'organization_id', 'reviewer_id')
    def _check_reviewer(self):
        for tier in self:
            if tier.organization_id.company_id != tier.company_id or tier.reviewer_id.share or tier.company_id not in tier.reviewer_id.company_ids:
                raise ValidationError(_('Reviewer and organization must belong to the tier company.'))


class BudgetKpiReview(models.Model):
    _name = 'erp.budget.kpi.review'
    _description = 'Budget Release Review'
    _order = 'round_number, sequence, id'
    _check_company_auto = True

    release_id = fields.Many2one('erp.budget.kpi.release', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='release_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='release_id.organization_id', store=True, index=True)
    reviewer_id = fields.Many2one('res.users', required=True, ondelete='restrict')
    sequence = fields.Integer(required=True)
    round_number = fields.Integer(required=True)
    state = fields.Selection([('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', required=True, readonly=True)
    _review_unique = models.Constraint('unique(release_id, round_number, sequence)', 'Review order must be unique within a submission.')

    @api.model_create_multi
    def create(self, vals_list):
        if not _review_internal.get():
            raise AccessError(_('Reviews are created on submission.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _review_internal.get() or set(vals) - {'state'}:
            raise AccessError(_('Reviews are changed by approval actions only.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Reviews are retained for audit.'))
