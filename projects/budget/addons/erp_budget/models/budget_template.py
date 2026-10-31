from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class BudgetTemplate(models.Model):
    _name = 'erp.budget.template'
    _inherit = 'erp.budget.company.mixin'
    _description = 'Budget KPI Template'

    name = fields.Char(required=True)
    line_ids = fields.One2many('erp.budget.template.line', 'template_id')
    _name_company_unique = models.Constraint('UNIQUE(name, company_id)', 'The template name must be unique in its company.')

    def write(self, vals):
        self.check_access('write')
        if 'company_id' in vals and any(r.company_id.id != vals['company_id'] for r in self):
            raise ValidationError(_('The company of a budget template cannot be changed.'))
        return super().write(vals)

    def _kpi_for_account(self, account):
        self.ensure_one()
        self.check_access('read')
        account.ensure_one()
        account.check_access('read')
        if self.company_id not in account.company_ids:
            raise ValidationError(_('The account is not available in the template company.'))
        lines = self.line_ids.filtered(lambda line: line.account_id == account)
        if len(lines) != 1 or not lines.kpi_id.active or lines.kpi_id.company_id != self.company_id:
            raise ValidationError(_('The account must map to one active KPI in the template company.'))
        return lines.kpi_id


class BudgetTemplateLine(models.Model):
    _name = 'erp.budget.template.line'
    _description = 'Budget KPI Account Mapping'
    _check_company_auto = True

    template_id = fields.Many2one('erp.budget.template', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one(related='template_id.company_id', store=True, index=True)
    kpi_id = fields.Many2one('erp.budget.kpi', required=True, ondelete='restrict', check_company=True)
    account_id = fields.Many2one('account.account', required=True, ondelete='restrict', check_company=True)
    _template_account_unique = models.Constraint('UNIQUE(template_id, account_id)', 'An account may map to only one KPI per template.')

    @api.constrains('template_id', 'kpi_id', 'account_id')
    def _check_mapping(self):
        for line in self:
            if line.company_id not in line.account_id.company_ids:
                raise ValidationError(_('The account must belong to the template company.'))
            if not line.kpi_id.active:
                raise ValidationError(_('An archived KPI cannot be mapped.'))
