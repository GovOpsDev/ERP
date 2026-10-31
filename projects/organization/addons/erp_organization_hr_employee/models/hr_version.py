from odoo import api, models


class HrVersion(models.Model):
    _inherit = "hr.version"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_employee_target(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._check_employee_target(vals)
        return super().write(vals)

    @api.model
    def _check_employee_target(self, vals):
        if vals.get("employee_id"):
            self.env["hr.employee"].browse(vals["employee_id"]).check_access("read")
