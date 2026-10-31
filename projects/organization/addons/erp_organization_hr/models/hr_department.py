from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class HrDepartment(models.Model):
    _inherit = "hr.department"

    organization_unit_id = fields.Many2one(
        "erp.organization.unit", string="Organization Unit", index=True,
        ondelete="restrict", domain="[('company_id', '=', company_id)]",
    )

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            self._check_company_destination(vals)
            company_id = vals.get("company_id")
            if vals.get("parent_id"):
                parent = self.browse(vals["parent_id"])
                if "company_id" not in vals and parent.company_id:
                    company_id = parent.company_id.id
                    vals["company_id"] = company_id
            if "organization_unit_id" not in vals:
                if company_id is None:
                    company_id = self.env.context.get("default_company_id", self.env.company.id)
                if company_id == self.env.company.id:
                    default = self.env["erp.organization.assignment"].default_unit_for_current_user()
                    if default:
                        vals["organization_unit_id"] = default.id
            self._check_unit_destination(vals)
        records = super().create(vals_list)
        records._validate_organization_company()
        return records

    def write(self, vals):
        self._check_company_destination(vals)
        self._check_unit_destination(vals)
        result = super().write(vals)
        if {"organization_unit_id", "company_id", "parent_id"} & vals.keys():
            self._validate_organization_company(include_descendants=True)
        return result

    @api.model
    def _check_company_destination(self, vals):
        if not self.env.su and vals.get("company_id") and vals["company_id"] not in self.env.companies.ids:
            raise AccessError(_("The destination company must be active."))
        if vals.get("parent_id"):
            self.browse(vals["parent_id"]).check_access("read")

    @api.model
    def _check_unit_destination(self, vals):
        if vals.get("organization_unit_id"):
            unit = self.env["erp.organization.unit"].browse(vals["organization_unit_id"])
            unit.check_access("read")
            if not unit.active:
                raise ValidationError(_("An archived organization unit cannot be linked."))

    def _validate_organization_company(self, include_descendants=False):
        self.env["hr.department"].flush_model(["company_id", "organization_unit_id", "parent_id"])
        departments = self.sudo().with_context(active_test=False)
        if include_descendants:
            departments = departments.search([("id", "child_of", self.ids)])
        for department in departments:
            if department.organization_unit_id and department.company_id != department.organization_unit_id.company_id:
                raise ValidationError(_("A department and its organization unit must belong to the same company."))
