from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class BudgetActivity(models.Model):
    _name = 'erp.budget.activity'
    _inherit = 'erp.budget.company.mixin'
    _description = 'Budget Activity'
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    account_id = fields.Many2one('account.account', required=True, check_company=True, ondelete='restrict')
    kpi_id = fields.Many2one('erp.budget.kpi', check_company=True, ondelete='restrict', help='Default KPI for new template mappings; the period template selects the effective KPI.')
    lock_version = fields.Integer(default=0, readonly=True)
    _name_company_unique = models.Constraint('unique(name, company_id)', 'Activity names must be unique in their company.')

    @api.constrains('company_id', 'account_id', 'kpi_id')
    def _check_dimensions(self):
        for activity in self:
            activity.account_id.check_access('read')
            if activity.company_id not in activity.account_id.company_ids or (activity.kpi_id and activity.kpi_id.company_id != activity.company_id):
                raise ValidationError(_('Activity account and KPI must belong to the activity company.'))

    def _has_document_usage(self):
        return False

    @api.model_create_multi
    def create(self, vals_list):
        if any('lock_version' in vals for vals in vals_list) or 'default_lock_version' in self.env.context:
            raise AccessError(_('Activity locking is internal.'))
        return super().create(vals_list)

    def _lock_activity_key(self):
        self.check_access('read')
        if self:
            ids = tuple(sorted(self.ids))
            self.env.cr.execute('SELECT id FROM erp_budget_activity WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
            self.env.cr.execute('UPDATE erp_budget_activity SET lock_version = COALESCE(lock_version, 0) + 1 WHERE id IN %s', [ids])
            self.invalidate_recordset()

    def _is_used(self):
        mappings = self.env['erp.budget.template.activity'].sudo().search([('activity_id', 'in', self.ids)])
        return any(template._has_effective_period() for template in mappings.mapped('template_id')) or self._has_document_usage()

    def write(self, vals):
        self.check_access('write')
        if 'lock_version' in vals:
            raise AccessError(_('Activity locking is internal.'))
        self._lock_activity_key()
        if 'company_id' in vals and any(activity.company_id.id != vals['company_id'] for activity in self):
            raise ValidationError(_('Activity company is immutable.'))
        if 'account_id' in vals and any(activity.account_id.id != vals['account_id'] for activity in self) and self._is_used():
            raise UserError(_('A used activity account cannot change; create a new activity.'))
        return super().write(vals)


class BudgetActivityTemplate(models.Model):
    _inherit = 'erp.budget.template'

    activity_line_ids = fields.One2many('erp.budget.template.activity', 'template_id')
    period_ids = fields.One2many('erp.budget.period', 'template_id', readonly=True)

    def _has_effective_period(self):
        periods = self.sudo().mapped('period_ids')
        return any(period.plan_enforced for period in periods) or bool(self.env['erp.budget.control'].sudo().with_context(active_test=False).search_count([('period_id', 'in', periods.ids), ('state', 'in', ('open', 'closed'))]))

    def _kpi_for_account(self, account, activity=None):
        self.ensure_one()
        self.check_access('read')
        account.ensure_one()
        account.check_access('read')
        if not self.activity_line_ids:
            if activity:
                raise ValidationError(_('The activity must be mapped in this period template.'))
            return super()._kpi_for_account(account)
        if not activity:
            raise ValidationError(_('This period template requires an explicit budget activity.'))
        activity = activity.with_env(self.env)
        activity.ensure_one()
        activity.check_access('read')
        if not activity.active or activity.company_id != self.company_id or activity.account_id != account or self.company_id not in account.company_ids:
            raise ValidationError(_('Activity, budget account and template company must match.'))
        rows = self.activity_line_ids.filtered(lambda row: row.activity_id == activity)
        if len(rows) != 1 or not rows.kpi_id.active or rows.kpi_id.company_id != self.company_id:
            raise ValidationError(_('The activity must select exactly one active KPI in the template.'))
        return rows.kpi_id


class BudgetTemplateActivity(models.Model):
    _name = 'erp.budget.template.activity'
    _description = 'Budget Template Activity Mapping'
    _check_company_auto = True

    template_id = fields.Many2one('erp.budget.template', required=True, check_company=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='template_id.company_id', store=True, index=True)
    activity_id = fields.Many2one('erp.budget.activity', required=True, check_company=True, ondelete='restrict')
    kpi_id = fields.Many2one('erp.budget.kpi', required=True, check_company=True, ondelete='restrict')
    _activity_unique = models.Constraint('unique(template_id, activity_id)', 'An activity may select only one KPI in a template.')

    @api.onchange('activity_id')
    def _onchange_activity(self):
        self.kpi_id = self.activity_id.kpi_id

    @api.constrains('template_id', 'activity_id', 'kpi_id')
    def _check_mapping(self):
        for row in self:
            if not row.activity_id.active or not row.kpi_id.active or row.activity_id.company_id != row.company_id or row.kpi_id.company_id != row.company_id:
                raise ValidationError(_('Activity mappings require active activity and KPI in the template company.'))

    @api.model_create_multi
    def create(self, vals_list):
        derived = {'company_id'}
        if any(derived & vals.keys() for vals in vals_list) or 'default_company_id' in self.env.context:
            raise AccessError(_('Mapping company derives from the template.'))
        for vals in vals_list:
            template = self.env['erp.budget.template'].browse(vals.get('template_id')).exists()
            template.check_access('write')
            template.period_ids._lock_plan_periods()
            if template._has_effective_period() and not template.activity_line_ids:
                raise UserError(_('An effective legacy template needs explicit conversion before enabling activity mapping.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.mapped('template_id.period_ids')._lock_plan_periods()
        if any(template._has_effective_period() for template in self.mapped('template_id')):
            raise UserError(_('Effective activity mappings are immutable; add a new activity instead.'))
        if 'template_id' in vals or 'company_id' in vals:
            raise AccessError(_('Activity mapping ownership is immutable.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.mapped('template_id.period_ids')._lock_plan_periods()
        if any(template._has_effective_period() for template in self.mapped('template_id')):
            raise UserError(_('Effective activity mappings cannot be deleted.'))
        return super().unlink()


class BudgetActivityPeriod(models.Model):
    _inherit = 'erp.budget.period'

    def write(self, vals):
        if 'template_id' in vals:
            self.check_access('write')
            new_template = self.env['erp.budget.template'].browse(vals['template_id']).exists()
            new_template.check_access('read')
            for period in self:
                if new_template != period.template_id and (new_template.activity_line_ids or period.template_id.activity_line_ids):
                    controls = self.env['erp.budget.control'].sudo().with_context(active_test=False).search_count([('period_id', '=', period.id), ('state', 'in', ('open', 'closed'))])
                    if period.plan_enforced or controls:
                        raise UserError(_('Changing an effective activity key requires explicit legacy conversion.'))
        return super().write(vals)
