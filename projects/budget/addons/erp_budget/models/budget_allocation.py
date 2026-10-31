import math
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_allocation_internal = ContextVar('erp_budget_allocation_internal', default=False)


class BudgetAllocation(models.Model):
    _name = 'erp.budget.allocation'
    _description = 'Budget Fund and Analytic Allocation'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict')
    period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict', index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done'), ('cancel', 'Cancelled')], required=True, default='draft', readonly=True)
    plan_id = fields.Many2one('erp.budget.plan', readonly=True, check_company=True, ondelete='restrict')
    line_ids = fields.One2many('erp.budget.allocation.line', 'allocation_id')
    _one_allocation = models.Constraint('unique(period_id)', 'Only one initial allocation is allowed per period.')

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('state', 'draft') != 'draft' or 'plan_id' in v for v in vals_list) or any('default_' + x in self.env.context for x in ('state', 'plan_id')):
            raise AccessError(_('An allocation starts in draft.'))
        for vals in vals_list:
            company = vals.get('company_id', self.env.company.id)
            if not self.env.su and company not in self.env.companies.ids:
                raise AccessError(_('The company must be active.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.mapped('period_id')._lock_plan_periods()
        if not _allocation_internal.get() and (set(vals) - {'name', 'line_ids'} or any(a.state != 'draft' for a in self)):
            raise AccessError(_('Only draft allocations can be edited.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.mapped('period_id')._lock_plan_periods()
        if any(a.state != 'draft' for a in self):
            raise AccessError(_('Only draft allocations can be deleted.'))
        return super().unlink()

    def action_done(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        if self.state != 'draft' or not self.line_ids or self.company_id != self.period_id.company_id:
            raise ValidationError(_('A nonempty draft allocation in the period company is required.'))
        all_lines = self.env['erp.budget.allocation.line'].sudo().search([('allocation_id', '=', self.id)])
        if set(all_lines.ids) != set(self.line_ids.ids):
            raise AccessError(_('Access to every allocation line is required.'))
        if self.env['erp.budget.plan'].sudo().search_count([('period_id', '=', self.period_id.id)]) or self.env['erp.budget.control'].sudo().with_context(active_test=False).search_count([('period_id', '=', self.period_id.id)]):
            raise UserError(_('Initial allocation requires a period without an existing plan or controls.'))
        grouped = {}
        for line in self.line_ids:
            line.check_access('write')
            line._validate_dimensions()
            key = line.analytic_id.id
            if key in grouped and grouped[key][0] != line.organization_id.id:
                raise ValidationError(_('One organization must own each analytic plan line.'))
            previous = grouped.get(key, (line.organization_id.id, 0))
            grouped[key] = (previous[0], previous[1] + line.allocated_amount)
        formal = self.period_id.release_policy == 'formal'
        with self.env.cr.savepoint():
            token = _allocation_internal.set(True)
            try:
                plan = self.env['erp.budget.plan'].create({'name': self.name, 'company_id': self.company_id.id, 'period_id': self.period_id.id, 'line_ids': [(0, 0, {'organization_id': unit, 'analytic_id': analytic, 'initial_amount': amount, 'allocation_mode': 'allocated' if formal else 'limits', 'release_required': formal}) for analytic, (unit, amount) in grouped.items()]})
                for line in self.line_ids:
                    control = self.env['erp.budget.control'].create({'name': self.name, 'company_id': self.company_id.id, 'period_id': self.period_id.id, 'organization_id': line.organization_id.id, 'analytic_id': line.analytic_id.id, 'level': 'fund', 'fund_id': line.fund_id.id, 'dimension_ids': [(6, 0, line.dimension_ids.ids)], 'amount': line.allocated_amount, 'allocation_line_id': line.id})
                    line.write({'control_id': control.id, 'released_amount': line.allocated_amount})
                self.write({'plan_id': plan.id, 'state': 'done'})
            finally:
                _allocation_internal.reset(token)
        return True

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self.period_id._lock_plan_periods()
        if self.state != 'draft':
            raise UserError(_('Only a draft allocation can be cancelled.'))
        token = _allocation_internal.set(True)
        try:
            return self.write({'state': 'cancel'})
        finally:
            _allocation_internal.reset(token)

    def action_draft(self):
        self.ensure_one()
        self.check_access('write')
        self.period_id._lock_plan_periods()
        if self.state != 'cancel':
            raise UserError(_('Only a cancelled draft allocation can be reset.'))
        token = _allocation_internal.set(True)
        try:
            return self.write({'state': 'draft'})
        finally:
            _allocation_internal.reset(token)


class BudgetAllocationLine(models.Model):
    _name = 'erp.budget.allocation.line'
    _description = 'Budget Fund and Analytic Allocation Line'
    _check_company_auto = True

    allocation_id = fields.Many2one('erp.budget.allocation', required=True, ondelete='cascade', check_company=True, index=True)
    company_id = fields.Many2one(related='allocation_id.company_id', store=True, index=True)
    period_id = fields.Many2one(related='allocation_id.period_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict', index=True)
    analytic_id = fields.Many2one('account.analytic.account', required=True, check_company=True, ondelete='restrict')
    fund_id = fields.Many2one('erp.budget.fund', required=True, check_company=True, ondelete='restrict')
    dimension_ids = fields.Many2many('account.analytic.account', 'erp_budget_allocation_dimension_rel', 'line_id', 'analytic_id', check_company=True)
    dimension_key = fields.Char(compute='_compute_dimension_key', store=True)
    introduced_revision_id = fields.Many2one('erp.budget.allocation.revision', readonly=True, ondelete='restrict')
    allocated_amount = fields.Monetary(required=True)
    released_amount = fields.Monetary(readonly=True, default=0)
    control_id = fields.Many2one('erp.budget.control', readonly=True, ondelete='restrict', check_company=True)
    _line_unique = models.Constraint('unique(allocation_id, organization_id, analytic_id, fund_id, dimension_key)', 'Duplicate allocation dimensions.')

    def _auto_init(self):
        self.env.cr.execute("SELECT to_regclass('erp_budget_allocation_line'), EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'erp_budget_allocation_line' AND column_name = 'dimension_key')")
        table, has_key = self.env.cr.fetchone()
        if table and not has_key:
            # SQL backfill avoids treating a derived uniqueness key as a new
            # business edit of historical released allocation lines.
            self.env.cr.execute('ALTER TABLE erp_budget_allocation_line ADD COLUMN dimension_key VARCHAR')
            self.env.cr.execute("SELECT to_regclass('erp_budget_allocation_dimension_rel')")
            if self.env.cr.fetchone()[0]:
                self.env.cr.execute("UPDATE erp_budget_allocation_line l SET dimension_key = COALESCE((SELECT string_agg(d.analytic_id::text, ',' ORDER BY d.analytic_id) FROM erp_budget_allocation_dimension_rel d WHERE d.line_id = l.id), '-')")
            else:
                self.env.cr.execute("UPDATE erp_budget_allocation_line SET dimension_key = '-'")
        return super()._auto_init()

    @api.depends('dimension_ids')
    def _compute_dimension_key(self):
        for line in self:
            line.dimension_key = ','.join(map(str, sorted(line.dimension_ids.ids))) or '-'

    def _validate_dimensions(self):
        for line in self:
            line.organization_id.check_access('read')
            line.analytic_id.check_access('read')
            line.fund_id.check_access('read')
            line.dimension_ids.check_access('read')
            if not line.organization_id.active or not line.analytic_id.active or not line.fund_id.active or line.organization_id.company_id != line.company_id or line.fund_id.company_id != line.company_id or (line.analytic_id.company_id and line.analytic_id.company_id != line.company_id):
                raise ValidationError(_('Allocation dimensions must be active and match the company.'))
            if any(not dimension.active or (dimension.company_id and dimension.company_id != line.company_id) for dimension in line.dimension_ids):
                raise ValidationError(_('Additional dimensions must be active and match the company.'))
            roots = line.dimension_ids.mapped('root_plan_id')
            if len(roots) != len(line.dimension_ids) or line.analytic_id.root_plan_id in roots:
                raise ValidationError(_('Each allocation dimension must use a distinct analytic root plan.'))
            if not math.isfinite(line.allocated_amount) or (line.allocated_amount < 0 if line.allocation_id.legacy_baseline else line.allocated_amount <= 0) or abs(line.allocated_amount - line.currency_id.round(line.allocated_amount)) > 1e-9:
                raise ValidationError(_('Allocation must be positive and use company currency precision.'))

    @api.constrains('organization_id', 'analytic_id', 'fund_id', 'dimension_ids', 'allocated_amount')
    def _check_dimensions(self):
        self._validate_dimensions()

    @api.model_create_multi
    def create(self, vals_list):
        if not _allocation_internal.get() and (any({'released_amount', 'control_id', 'introduced_revision_id', 'dimension_key'} & v.keys() for v in vals_list) or any('default_' + x in self.env.context for x in ('released_amount', 'control_id', 'introduced_revision_id', 'dimension_key'))):
            raise AccessError(_('Released amount and control are generated internally.'))
        for vals in vals_list:
            allocation = self.env['erp.budget.allocation'].browse(vals.get('allocation_id')).exists()
            allocation.ensure_one()
            allocation.check_access('write')
            allocation.period_id._lock_plan_periods()
            if allocation.state != 'draft' and not _allocation_internal.get():
                raise AccessError(_('Allocation lines require a draft document.'))
            self.env['erp.organization.unit'].browse(vals.get('organization_id')).check_access('read')
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.mapped('period_id')._lock_plan_periods()
        if not _allocation_internal.get() and (set(vals) - {'organization_id', 'analytic_id', 'fund_id', 'dimension_ids', 'allocated_amount'} or any(line.allocation_id.state != 'draft' for line in self)):
            raise AccessError(_('Only draft allocation dimensions may be edited.'))
        if vals.get('organization_id'):
            self.env['erp.organization.unit'].browse(vals['organization_id']).check_access('read')
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.mapped('period_id')._lock_plan_periods()
        if any(line.allocation_id.state != 'draft' for line in self):
            raise AccessError(_('Completed allocation lines cannot be deleted.'))
        return super().unlink()
