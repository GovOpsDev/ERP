from odoo import api, fields, models


class HrEmployeePublic(models.Model):
    _inherit = "hr.employee.public"

    organization_unit_id = fields.Many2one("erp.organization.unit", readonly=True)
    organization_scope_history = fields.Boolean(readonly=True, groups='base.group_no_one')
    erp_security_organization_assignment_ids = fields.One2many(
        'erp.employee.organization.assignment', 'employee_id', bypass_search_access=True,
        groups='base.group_no_one', context={'active_test': False},
    )

    @api.depends_context("uid", "company", "allowed_company_ids")
    def _compute_child_count(self):
        public = self.env["hr.employee.public"]
        for employee in self:
            employee.child_count = public.search_count([("parent_id", "=", employee.id), ("id", "!=", employee.id)])

    @api.depends_context("uid", "company", "allowed_company_ids")
    def _compute_child_all_count(self):
        public = self.env["hr.employee.public"]
        for employee in self:
            employee.child_all_count = public.search_count([("id", "child_of", employee.id), ("id", "!=", employee.id)])
