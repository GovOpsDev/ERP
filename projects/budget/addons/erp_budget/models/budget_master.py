from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class BudgetCompanyMixin(models.AbstractModel):
    _name = 'erp.budget.company.mixin'
    _description = 'Budget Company Boundary'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            allowed = set(self.env.companies.ids)
            for vals in vals_list:
                if vals.get('company_id', self.env.company.id) not in allowed:
                    raise AccessError(_('The budget company must be an active company.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and 'company_id' in vals and vals['company_id'] not in self.env.companies.ids:
            raise AccessError(_('The budget company must be an active company.'))
        return super().write(vals)


class BudgetPeriod(models.Model):
    _name = 'erp.budget.period'
    _inherit = 'erp.budget.company.mixin'
    _description = 'Budget Period'
    _order = 'date_from desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    template_id = fields.Many2one('erp.budget.template', ondelete='restrict', check_company=True)
    _name_company_unique = models.Constraint('UNIQUE(name, company_id)', 'The budget period name must be unique within a company.')

    @api.constrains('date_from', 'date_to', 'company_id')
    def _check_dates(self):
        # Serialize changes for the same company before checking the interval.
        company_ids = sorted(self.mapped('company_id').ids)
        if company_ids:
            self.env.cr.execute('SELECT id FROM res_company WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(company_ids)])
        for period in self:
            if period.date_from > period.date_to:
                raise ValidationError(_('The period start must not be after its end.'))
            if self.sudo().search_count([
                ('id', '!=', period.id), ('company_id', '=', period.company_id.id),
                ('date_from', '<=', period.date_to), ('date_to', '>=', period.date_from),
            ]):
                raise ValidationError(_('Budget periods in the same company must not overlap.'))


class BudgetFundGroup(models.Model):
    _name = 'erp.budget.fund.group'
    _inherit = 'erp.budget.company.mixin'
    _description = 'Budget Fund Group'
    _order = 'name, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    _name_company_unique = models.Constraint('UNIQUE(name, company_id)', 'The fund group name must be unique within a company.')

    def write(self, vals):
        self.check_access('write')
        if not self.env.su and 'company_id' in vals and vals['company_id'] not in self.env.companies.ids:
            raise AccessError(_('The budget company must be an active company.'))
        if 'company_id' in vals:
            for group in self:
                if vals['company_id'] != group.company_id.id and self.env['erp.budget.fund'].sudo().with_context(active_test=False).search_count([('group_id', '=', group.id)]):
                    raise ValidationError(_('A fund group with funds cannot change company.'))
        return super().write(vals)


class BudgetFund(models.Model):
    _name = 'erp.budget.fund'
    _inherit = 'erp.budget.company.mixin'
    _description = 'Budget Fund'
    _order = 'name, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    group_id = fields.Many2one('erp.budget.fund.group', required=True, ondelete='restrict', check_company=True)
    _name_company_unique = models.Constraint('UNIQUE(name, company_id)', 'The fund name must be unique within a company.')


class BudgetKpi(models.Model):
    _name = 'erp.budget.kpi'
    _inherit = 'erp.budget.company.mixin'
    _description = 'Budget Control KPI'
    _order = 'name, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    _name_company_unique = models.Constraint(
        'UNIQUE(name, company_id)', 'The budget KPI name must be unique within a company.'
    )
