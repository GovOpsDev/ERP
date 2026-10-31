from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .security_cache import invalidate_employee_scope


class EmployeeOrganizationAssignment(models.Model):
    _name = 'erp.employee.organization.assignment'
    _description = 'Additional Employee Organization'
    _order = 'employee_id, organization_id, date_from, id'

    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='cascade')
    organization_id = fields.Many2one('erp.organization.unit', required=True, index=True, ondelete='restrict')
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    assignment_type = fields.Selection([('additional', 'Additional')], required=True, default='additional', readonly=True)
    active = fields.Boolean(default=True)
    date_from = fields.Date()
    date_to = fields.Date()
    effective = fields.Boolean(compute='_compute_effective')

    @api.depends('active', 'date_from', 'date_to', 'organization_id.active')
    def _compute_effective(self):
        today = fields.Date.today()
        for rec in self:
            rec.effective = bool(rec.active and rec.organization_id.active and (not rec.date_from or rec.date_from <= today) and (not rec.date_to or rec.date_to >= today))

    @api.constrains('employee_id', 'organization_id', 'date_from', 'date_to')
    def _check_assignment(self):
        for rec in self.sudo():
            if rec.employee_id.company_id != rec.organization_id.company_id:
                raise ValidationError(_('Employee and organization must belong to the same company.'))
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_('Start date must precede or equal end date.'))

    @api.model
    def _check_destination(self, vals):
        if vals.get('employee_id'):
            self.env['hr.employee'].browse(vals['employee_id']).check_access('write')
        if vals.get('organization_id'):
            unit = self.env['erp.organization.unit'].browse(vals['organization_id'])
            unit.check_access('read')
            if not unit.active:
                raise ValidationError(_('An archived organization cannot be assigned.'))
            if not self.env.su and unit.company_id not in self.env.companies:
                raise AccessError(_('The destination company must be active.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_destination(vals)
        records = super().create(vals_list)
        records.sudo().employee_id._mark_organization_scope_history()
        invalidate_employee_scope(self.env)
        return records

    def write(self, vals):
        self.mapped('employee_id').check_access('write')
        self._check_destination(vals)
        result = super().write(vals)
        self.sudo().employee_id._mark_organization_scope_history()
        invalidate_employee_scope(self.env)
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_except_employee_organization_history(self):
        raise UserError(_('Employee organization history cannot be deleted. Archive the assignment instead.'))
