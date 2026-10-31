import math
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_control import _release_open, _release_close
from .budget_release import _planning_internal, _tier_approved


class BudgetPlanningVersion(models.Model):
    _inherit = 'erp.budget.kpi.release'

    previous_id = fields.Many2one('erp.budget.kpi.release', readonly=True, ondelete='restrict')
    root_id = fields.Many2one('erp.budget.kpi.release', readonly=True, ondelete='restrict')
    version_number = fields.Integer(default=0, readonly=True)
    _planning_number_unique = models.Constraint('unique(root_id, version_number)', 'Planning version numbers must be unique in their origin chain.')
    plan_version_id = fields.Many2one('erp.budget.plan.version', readonly=True, check_company=True, ondelete='restrict')
    allocation_revision_id = fields.Many2one('erp.budget.allocation.revision', readonly=True, check_company=True, ondelete='restrict')
    planning_snapshot = fields.Boolean(default=False, readonly=True, help='New versions persist date-range planning; old target releases retain compatibility until explicitly revised.')
    state = fields.Selection(selection_add=[('approved', 'Approved / awaiting allocation'), ('superseded', 'Superseded')], ondelete={'approved': 'set default', 'superseded': 'set default'})

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'previous_id', 'root_id', 'version_number', 'plan_version_id', 'allocation_revision_id', 'planning_snapshot'}
        if not _planning_internal.get() and (any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected)):
            raise AccessError(_('Planning versions are prepared from the effective release.'))
        for vals in vals_list:
            vals['planning_snapshot'] = True
        records = super().create(vals_list)
        token = _planning_internal.set(True)
        try:
            for record in records.filtered(lambda item: not item.previous_id):
                record.write({'root_id': record.id})
        finally:
            _planning_internal.reset(token)
        return records

    def action_prepare_revision(self, allocation_revision_id=None):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self._lock_controls()
        if self.state != 'done':
            raise UserError(_('Only effective planning may be revised.'))
        allocation_revision = self.env['erp.budget.allocation.revision'].browse(allocation_revision_id).exists() if allocation_revision_id else self.env['erp.budget.allocation.revision']
        if allocation_revision:
            allocation_revision.check_access('write')
            if allocation_revision.state != 'draft' or allocation_revision.allocation_id.plan_id != self.plan_line_id.plan_id:
                raise ValidationError(_('The allocation revision must be a draft for this plan.'))
            plan_version = allocation_revision.plan_version_id
        else:
            plan_version = self.env['erp.budget.plan.version'].search([('plan_id', '=', self.plan_line_id.plan_id.id), ('state', '=', 'effective')], limit=1)
        root = self.root_id or self
        versions = self.search([('root_id', '=', root.id)])
        next_number = max(versions.mapped('version_number') + [self.version_number]) + 1
        token = _planning_internal.set(True)
        try:
            with self.env.cr.savepoint():
                revision = self.create({'name': self.name, 'state': 'draft', 'review_round': 0, 'review_ids': [], 'submitted_by_id': False, 'released_by_id': False, 'released_at': False, 'reversed_by_id': False, 'reversed_at': False, 'plan_line_id': self.plan_line_id.id, 'released_amount': self.released_amount, 'previous_id': self.id, 'root_id': root.id, 'version_number': next_number, 'plan_version_id': plan_version.id, 'allocation_revision_id': allocation_revision.id, 'line_ids': [(0, 0, {'control_id': line.control_id.id, 'amount': line.amount, 'planning_ids': [(0, 0, {'date_from': item.date_from, 'date_to': item.date_to, 'amount': item.amount, 'kpi_id': item.kpi_id.id or line.control_id.kpi_id.id}) for item in line.planning_ids] or [(0, 0, {'date_from': self.period_id.date_from, 'date_to': self.period_id.date_to, 'amount': line.amount})]}) for line in self.line_ids]})
        finally:
            _planning_internal.reset(token)
        return {'type': 'ir.actions.act_window', 'name': _('Planning revision'), 'res_model': self._name, 'view_mode': 'form', 'res_id': revision.id, 'target': 'current'}

    def action_prepare_revision_form(self):
        self.ensure_one()
        self.check_access('write')
        return {'type': 'ir.actions.act_window', 'name': _('Prepare planning revision'), 'res_model': 'erp.budget.planning.revision', 'view_mode': 'form', 'target': 'new', 'context': {'default_release_id': self.id}}

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'approved' and self.allocation_revision_id:
            self.check_access('write')
            self._lock_controls()
            token = _planning_internal.set(True)
            try:
                return self.write({'state': 'cancel'})
            finally:
                _planning_internal.reset(token)
        return super().action_cancel()

    def _expected_planning_ceiling(self):
        self.ensure_one()
        if self.allocation_revision_id:
            return sum(self.allocation_revision_id.line_ids.filtered(lambda row: row.analytic_id == self.plan_line_id.analytic_id).mapped('amount'))
        return self.plan_line_id._ceiling()

    def _proposed_planning_total(self):
        self.ensure_one()
        amount = self.plan_line_id._allocated()
        if self.previous_id:
            amount -= sum(self.previous_id.line_ids.mapped('control_id').filtered(lambda control: control.active and not control.erp_release_reversed and control.state in ('open', 'closed')).mapped('amount'))
        return amount + sum(self.line_ids.filtered(lambda row: self.previous_id or row.control_id.state == 'draft').mapped('amount'))

    def _validate_planning(self):
        self.ensure_one()
        keys = {(row.control_id.organization_id.id, row.control_id.kpi_id.id) for row in self.line_ids}
        if not self.line_ids or len(keys) != len(self.line_ids):
            raise ValidationError(_('Each planning control must have a distinct organization and KPI key.'))
        for organization_id in {key[0] for key in keys}:
            selected = {key[1] for key in keys if key[0] == organization_id}
            if (False in selected and len(selected) > 1) or (self.period_id.control_level == 'analytic_kpi' and False in selected) or (self.period_id.control_level == 'analytic' and selected != {False}):
                raise ValidationError(_('Planning controls must match the period control granularity.'))
        rounding = self.currency_id.rounding
        if not math.isfinite(self.released_amount) or float_compare(sum(self.line_ids.mapped('amount')), self.released_amount, precision_rounding=rounding):
            raise ValidationError(_('Planning totals must equal the declared release.'))
        for row in self.line_ids:
            if not math.isfinite(row.amount) or row.amount < 0 or abs(row.amount - self.currency_id.round(row.amount)) > 1e-9:
                raise ValidationError(_('Planning amounts must be nonnegative and use company currency precision.'))
            slices = row.planning_ids.sorted(lambda item: (item.date_from, item.id))
            if not slices and self.planning_snapshot:
                raise ValidationError(_('Canonical planning must include date ranges for every KPI.'))
            # Legacy releases without stored slices retain compatibility until an
            # explicit successor is prepared. New lines always get a full-year slice.
            if slices and float_compare(sum(slices.mapped('amount')), row.amount, precision_rounding=rounding):
                raise ValidationError(_('Date-range planning must sum to its KPI amount.'))
            last_ends = {}
            for item in slices:
                item._check_slice()
                key = item.kpi_id.id or row.control_id.kpi_id.id
                last_end = last_ends.get(key)
                if last_end and item.date_from <= last_end:
                    raise ValidationError(_('Date ranges for one KPI must not overlap.'))
                last_ends[key] = item.date_to

    def _validate_planning_revision(self):
        self.ensure_one()
        previous = self.previous_id
        if not previous or previous.state != 'done' or previous.plan_line_id != self.plan_line_id:
            raise UserError(_('This planning revision is stale.'))
        if self.allocation_revision_id and self.allocation_revision_id.state != 'draft':
            raise UserError(_('The linked allocation revision is no longer draft.'))
        previous_controls = previous.line_ids.mapped('control_id')
        proposed_controls = self.line_ids.mapped('control_id')
        controls = previous_controls | proposed_controls
        controls.check_access('write')
        for row in previous.line_ids:
            if float_compare(row.control_id.amount, row.amount, precision_rounding=self.currency_id.rounding):
                raise UserError(_('Effective control amounts no longer match their planning version.'))
        proposed = {row.control_id.id: row.amount for row in self.line_ids}
        self.env['erp.budget.move'].flush_model(['control_id', 'amount'])
        for control in controls:
            if control.company_id != self.company_id or control.period_id != self.period_id or control.analytic_id != self.plan_line_id.analytic_id or control.level != 'analytic' or (self.period_id.control_level == 'analytic_kpi' and not control.kpi_id) or not control.active or control.erp_release_reversed:
                raise ValidationError(_('Planning controls must match the company, period, organization and analytic.'))
            restoring = self.allocation_revision_id.revision_kind == 'restore'
            if control in previous_controls and control.state not in (('open', 'closed') if restoring or previous.legacy_baseline else ('open',)):
                raise UserError(_('The preceding planning controls must remain open.'))
            if control not in previous_controls and control.state != 'draft':
                raise UserError(_('New planning controls must be draft.'))
            if float_compare(proposed.get(control.id, 0), self._planning_consumed(control), precision_rounding=self.currency_id.rounding) < 0:
                raise UserError(_('A KPI revision cannot remove consumed capacity.'))
        total = self._proposed_planning_total()
        self._check_planning_opening(total)
        if float_compare(total, self._expected_planning_ceiling(), precision_rounding=self.currency_id.rounding):
            raise UserError(_('Revised KPI planning must equal its effective or proposed allocation.'))
        self._validate_planning()

    def _planning_consumed(self, control):
        if not control._has_child_capacity_limit() and control in self.line_ids.control_id:
            return 0
        self.env.cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [control.id])
        return self.env.cr.fetchone()[0]

    def _check_planning_opening(self, amount):
        return self.plan_line_id._check_opening_minimum(amount)

    def _activate_planning_revision(self):
        self.ensure_one()
        if not _tier_approved.get():
            raise AccessError(_('The configured review tiers must approve planning revisions.'))
        self._lock_controls()
        self._validate_planning_revision()
        if self.allocation_revision_id:
            token = _planning_internal.set(True)
            try:
                return self.write({'state': 'approved'})
            finally:
                _planning_internal.reset(token)
        with self.env.cr.savepoint():
            self._apply_planning_revision()
        return True

    def _apply_planning_revision(self, defer_open=False):
        self.ensure_one()
        if not _planning_internal.get() and not _tier_approved.get():
            raise AccessError(_('Planning activation is internal to approved workflows.'))
        self._validate_planning_revision()
        controls = self.line_ids.mapped('control_id')
        omitted = self.previous_id.line_ids.mapped('control_id') - controls
        token = _planning_internal.set(True)
        try:
            for row in self.line_ids:
                row.control_id._set_planning_revision_amount(row.amount)
            if self.allocation_revision_id.revision_kind == 'restore':
                controls.filtered(lambda control: control.state == 'closed')._prepare_control_restoration()
            for control in omitted:
                control._set_planning_revision_amount(0)
            if omitted:
                closing = _release_close.set(True)
                try:
                    omitted.filtered(lambda control: control.state == 'open').action_close()
                finally:
                    _release_close.reset(closing)
            opening = _release_open.set(True)
            try:
                if not defer_open:
                    controls.filtered(lambda control: control.state == 'draft').action_open()
            finally:
                _release_open.reset(opening)
            self.previous_id.write({'state': 'superseded'})
            self.write({'state': 'done', 'released_by_id': self.env.user.id, 'released_at': fields.Datetime.now()})
        finally:
            _planning_internal.reset(token)
        return True

    def action_initialize_commitments(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_controls()
        if self.state != 'draft':
            raise UserError(_('Only draft planning may be initialized.'))
        self.env['erp.budget.move'].flush_model(['control_id', 'amount', 'move_type'])
        for row in self.line_ids:
            if row.control_id.kpi_id.advance_reservation:
                continue
            moves = self.env['erp.budget.move'].search([('control_id', '=', row.control_id.id), '|', ('move_type', '=', False), ('move_type', 'not in', ('actual', 'actual_reversal'))])
            amounts = {}
            split_kpis = row.planning_ids.mapped('kpi_id')
            for move in moves:
                if move.move_type in ('advance_commitment', 'advance_reversal'):
                    continue
                key = move._planning_kpi().id if split_kpis else False
                amounts[key] = amounts.get(key, 0) + move.amount
            if set(amounts) - (set(split_kpis.ids) if split_kpis else {False}):
                raise UserError(_('Every outstanding commitment KPI must occur in draft planning.'))
            amount = abs(sum(amounts.values()))
            token = _planning_internal.set(True)
            try:
                if row.planning_ids:
                    for key in split_kpis.ids or [False]:
                        slices = row.planning_ids.filtered(lambda item: item.kpi_id.id == key)
                        first = slices.sorted(lambda item: (item.date_from, item.id))[:1]
                        first.write({'amount': abs(amounts.get(key, 0))})
                    amount = sum(row.planning_ids.mapped('amount'))
                if not self.previous_id:
                    row.control_id.write({'amount': amount})
                row.write({'amount': amount})
            finally:
                _planning_internal.reset(token)
        self.write({'released_amount': sum(self.line_ids.mapped('amount'))})
        return True


class BudgetPlanningControl(models.Model):
    _inherit = 'erp.budget.control'

    def _set_planning_revision_amount(self, amount):
        if not _planning_internal.get() or any(control.level != 'analytic' for control in self):
            raise AccessError(_('Planning revision amounts are internal.'))
        return super(BudgetPlanningControl, self).write({'amount': amount})


class BudgetPlanningVersionLine(models.Model):
    _inherit = 'erp.budget.kpi.release.line'

    planning_ids = fields.One2many('erp.budget.planning.line', 'release_line_id')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            release = self.env['erp.budget.kpi.release'].browse(vals.get('release_id'))
            if 'planning_ids' not in vals:
                control = self.env['erp.budget.control'].browse(vals.get('control_id'))
                vals['planning_ids'] = [(0, 0, {'date_from': release.period_id.date_from, 'date_to': release.period_id.date_to, 'amount': vals.get('amount', control.amount)})]
        return super().create(vals_list)

    def write(self, vals):
        if 'control_id' in vals:
            self.mapped('planning_ids')._check_editable()
        result = super().write(vals)
        if 'amount' in vals:
            for row in self:
                if len(row.planning_ids) == 1 and row.planning_ids.date_from == row.release_id.period_id.date_from and row.planning_ids.date_to == row.release_id.period_id.date_to:
                    row.planning_ids.write({'amount': vals['amount']})
        return result

    def unlink(self):
        self.mapped('planning_ids')._check_editable()
        return super().unlink()

class BudgetPlanningLine(models.Model):
    _name = 'erp.budget.planning.line'
    _description = 'Budget KPI Date-range Planning Snapshot'
    _check_company_auto = True

    release_line_id = fields.Many2one('erp.budget.kpi.release.line', required=True, check_company=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='release_line_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='release_line_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    amount = fields.Monetary(required=True)
    kpi_id = fields.Many2one('erp.budget.kpi', check_company=True, ondelete='restrict')

    @api.constrains('date_from', 'date_to', 'amount', 'release_line_id', 'kpi_id')
    def _check_slice(self):
        for item in self:
            period = item.release_line_id.release_id.period_id
            control = item.release_line_id.control_id
            if item.kpi_id and (not item.kpi_id.active or item.kpi_id.company_id != item.company_id or (control.kpi_id and item.kpi_id != control.kpi_id)):
                raise ValidationError(_('Planning KPI must be active and match the control/company.'))
            if period.control_level == 'analytic' and period.template_id:
                allowed = period.template_id.line_ids.mapped('kpi_id') | period.template_id.activity_line_ids.mapped('kpi_id')
                if not item.kpi_id or item.kpi_id not in allowed:
                    raise ValidationError(_('Analytic-total planning must identify its template KPI.'))
            if not item.date_from or not item.date_to or not period.date_from <= item.date_from <= item.date_to <= period.date_to:
                raise ValidationError(_('Planning dates must be within the fiscal period.'))
            if not math.isfinite(item.amount) or item.amount < 0 or abs(item.amount - item.currency_id.round(item.amount)) > 1e-9:
                raise ValidationError(_('Planning amounts must use nonnegative company currency precision.'))

    def _check_editable(self):
        releases = self.mapped('release_line_id.release_id')
        releases._lock_controls()
        if any(release.state != 'draft' for release in releases):
            raise AccessError(_('Only draft planning dates may be edited.'))
        for item in self:
            if _planning_internal.get() or not item.release_line_id.release_id.previous_id:
                continue
            policy = item.company_id.sudo().erp_budget_planning_lock
            today = fields.Date.context_today(item)
            cutoff = today.replace(day=1) - timedelta(days=1) if policy == 'last' else today
            if policy != 'none' and item.date_from <= cutoff:
                raise UserError(_('Past planning amounts are locked by company policy.'))

    @api.model_create_multi
    def create(self, vals_list):
        derived = {'company_id', 'organization_id', 'currency_id'}
        if any(derived & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in derived):
            raise AccessError(_('Planning scope derives from its release line.'))
        for vals in vals_list:
            line = self.env['erp.budget.kpi.release.line'].browse(vals.get('release_line_id'))
            vals.setdefault('kpi_id', line.control_id.kpi_id.id)
        lines = self.env['erp.budget.kpi.release.line'].browse([vals.get('release_line_id') for vals in vals_list])
        lines.check_access('write')
        for release in lines.mapped('release_id'):
            release._lock_controls()
        if any(line.release_id.state != 'draft' for line in lines):
            raise AccessError(_('Only draft planning dates may be added.'))
        result = super().create(vals_list)
        result._check_editable()
        return result

    def write(self, vals):
        self.check_access('write')
        self._check_editable()
        if set(vals) - {'date_from', 'date_to', 'amount', 'kpi_id'}:
            raise AccessError(_('Planning ownership is immutable.'))
        result = super().write(vals)
        self._check_editable()
        return result

    def unlink(self):
        self.check_access('unlink')
        self._check_editable()
        return super().unlink()


class BudgetPlanningCompany(models.Model):
    _inherit = 'res.company'

    erp_budget_planning_lock = fields.Selection([('none', 'No past-date lock'), ('current', 'Through today'), ('last', 'Through last month')], required=True, default='none', groups='base.group_system')


class BudgetPlanningSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    erp_budget_planning_lock = fields.Selection(related='company_id.erp_budget_planning_lock', readonly=False, groups='base.group_system')


class BudgetPlanningRevisionWizard(models.TransientModel):
    _name = 'erp.budget.planning.revision'
    _description = 'Prepare Coordinated Budget Planning Revision'

    release_id = fields.Many2one('erp.budget.kpi.release', required=True)
    allocation_revision_id = fields.Many2one('erp.budget.allocation.revision')

    def action_prepare(self):
        self.ensure_one()
        return self.release_id.action_prepare_revision(self.allocation_revision_id.id or None)
