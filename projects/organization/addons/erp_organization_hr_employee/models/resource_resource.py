from odoo import fields, models


class ResourceResource(models.Model):
    _inherit = "resource.resource"

    # This relation is used only by the resource access rule. Security-domain
    # evaluation must include hidden employees, otherwise their resources look
    # unlinked and are inadvertently exposed.
    erp_security_employee_ids = fields.One2many(
        "hr.employee", "resource_id", bypass_search_access=True,
        groups="base.group_no_one", context={"active_test": False},
    )
