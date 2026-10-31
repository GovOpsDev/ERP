from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .security_cache import invalidate_employee_scope


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    organization_unit_id = fields.Many2one(
        "erp.organization.unit", string="Organization Unit", index=True,
        ondelete="restrict", domain="[('company_id', '=', company_id)]",
    )
    organization_scope_history = fields.Boolean(
        readonly=True, copy=False, index=True, groups='base.group_no_one',
        help='Set permanently when an employee is assigned to any organization.',
    )

    organization_assignment_ids = fields.One2many('erp.employee.organization.assignment', 'employee_id', string='Additional Organizations')
    erp_security_organization_assignment_ids = fields.One2many(
        'erp.employee.organization.assignment', 'employee_id', bypass_search_access=True,
        groups='base.group_no_one', context={'active_test': False},
    )

    child_count = fields.Integer(compute="_compute_scoped_child_count", recursive=True, compute_sudo=False)
    subordinate_ids = fields.One2many("hr.employee", compute="_compute_scoped_subordinates", compute_sudo=False)
    child_all_count = fields.Integer(compute="_compute_scoped_subordinates", recursive=True, compute_sudo=False)

    @api.depends_context("uid", "company", "allowed_company_ids")
    @api.depends("child_ids")
    def _compute_scoped_child_count(self):
        employees = self.env["hr.employee"]
        for employee in self:
            employee.child_count = employees.search_count([("parent_id", "=", employee.id), ("id", "!=", employee.id)])

    @api.depends_context("uid", "company", "allowed_company_ids")
    @api.depends("child_ids", "child_ids.child_all_count")
    def _compute_scoped_subordinates(self):
        employees = self.env["hr.employee"]
        for employee in self:
            visible = employees.search([("id", "child_of", employee.id), ("id", "!=", employee.id)])
            employee.subordinate_ids = visible
            employee.child_all_count = len(visible)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if 'organization_scope_history' in vals:
                raise AccessError(_("Organization scope history is managed automatically."))
            self._check_employee_destination(vals)
            company = vals.get("company_id", self.env.context.get("default_company_id", self.env.company.id))
            if "organization_unit_id" not in vals and company == self.env.company.id:
                unit = self.env["erp.organization.assignment"].default_unit_for_current_user()
                if unit:
                    vals["organization_unit_id"] = unit.id
        employees = super().create(vals_list)
        employees.sudo().filtered('organization_unit_id')._mark_organization_scope_history()
        employees._validate_employee_organization()
        return employees

    def write(self, vals):
        if 'organization_scope_history' in vals:
            raise AccessError(_("Organization scope history is managed automatically."))
        self._check_employee_destination(vals)
        result = super().write(vals)
        if vals.get('organization_unit_id'):
            self._mark_organization_scope_history()
        if 'organization_unit_id' in vals:
            self.flush_recordset(['organization_unit_id'])
        if 'company_id' in vals:
            self.flush_recordset(['company_id'])
            self.sudo().mapped('current_version_id').flush_recordset(['company_id'])
        if {"organization_unit_id", "company_id"} & vals.keys():
            self._validate_employee_organization()
        if {"organization_unit_id", "company_id", "active"} & vals.keys():
            invalidate_employee_scope(self.env)
        return result

    def _mark_organization_scope_history(self):
        employees = self.sudo().filtered(lambda employee: not employee.organization_scope_history)
        if employees:
            super(HrEmployee, employees).write({'organization_scope_history': True})
            employees.flush_recordset(['organization_scope_history'])

    @api.model
    def _check_employee_destination(self, vals):
        if not self.env.su and vals.get("company_id") and vals["company_id"] not in self.env.companies.ids:
            raise AccessError(_("The destination company must be active."))
        if vals.get("organization_unit_id"):
            unit = self.env["erp.organization.unit"].browse(vals["organization_unit_id"])
            unit.check_access("read")
            if not unit.active:
                raise ValidationError(_("An archived organization unit cannot be linked."))

    def _validate_employee_organization(self):
        for employee in self.sudo():
            if employee.organization_unit_id and employee.company_id != employee.organization_unit_id.company_id:
                raise ValidationError(_("An employee and organization unit must belong to the same company."))
            if any(assignment.organization_id.company_id != employee.company_id for assignment in employee.with_context(active_test=False).organization_assignment_ids):
                raise ValidationError(_("Employee organization assignments must belong to the employee company."))
