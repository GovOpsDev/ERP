from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class OrganizationAssignment(models.Model):
    _name = "erp.organization.assignment"
    _description = "User Organization Assignment"
    _order = "user_id, company_id, unit_id"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    unit_id = fields.Many2one("erp.organization.unit", required=True, index=True, ondelete="cascade")
    company_id = fields.Many2one(related="unit_id.company_id", store=True, index=True)
    is_default = fields.Boolean(string="Default in Company")

    _user_unit_unique = models.Constraint(
        "UNIQUE (user_id, unit_id)", "A user can only be assigned to a unit once."
    )
    _user_company_default_unique = models.UniqueIndex(
        "(user_id, company_id) WHERE is_default IS TRUE",
        "A user can only have one default organization per company.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "company_id" in vals:
                raise AccessError(_("Assignment company is derived from the organization."))
            if vals.get("unit_id"):
                unit = self.env["erp.organization.unit"].browse(vals["unit_id"])
                unit.check_access("read")
                if not unit.active:
                    raise ValidationError(_("An archived organization cannot be assigned."))
        return super().create(vals_list)

    def write(self, vals):
        if "company_id" in vals:
            raise AccessError(_("Assignment company is derived from the organization."))
        if vals.get("unit_id"):
            unit = self.env["erp.organization.unit"].browse(vals["unit_id"])
            unit.check_access("read")
            if not unit.active:
                raise ValidationError(_("An archived organization cannot be assigned."))
        if (vals.get("is_default") or vals.get("user_id")) and not vals.get("unit_id") and any(not a.unit_id.active for a in self.sudo()):
            raise ValidationError(_("An archived organization cannot be assigned or set as a default."))
        result = super().write(vals)
        if "is_default" in vals:
            self.flush_recordset(["is_default"])
        return result

    @api.constrains("user_id", "unit_id", "is_default")
    def _check_assignment(self):
        for assignment in self.sudo():
            if assignment.unit_id.company_id not in assignment.user_id.company_ids:
                raise ValidationError(_("The user must be allowed in the unit's company."))
            if assignment.user_id.share:
                raise ValidationError(_("Assignments are only available to internal users."))

    @api.model
    def default_unit_for_current_user(self):
        """Return the active assigned default in the current active company, if any."""
        company = self.env.company
        assignment = self.sudo().search([
            ("user_id", "=", self.env.uid),
            ("company_id", "=", company.id),
            ("unit_id.active", "=", True),
            ("is_default", "=", True),
        ], limit=1)
        return self.env["erp.organization.unit"].browse(assignment.unit_id.id)
