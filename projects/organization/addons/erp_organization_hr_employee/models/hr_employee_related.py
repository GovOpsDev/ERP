from odoo import api, models


def check_employee_target(env, vals):
    if vals.get("employee_id"):
        env["hr.employee"].browse(vals["employee_id"]).check_access("read")


class HrEmployeeLocation(models.Model):
    _inherit = "hr.employee.location"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            check_employee_target(self.env, vals)
        return super().create(vals_list)

    def write(self, vals):
        check_employee_target(self.env, vals)
        return super().write(vals)


class HrEmployeeDeparture(models.Model):
    _inherit = "hr.employee.departure"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            check_employee_target(self.env, vals)
        return super().create(vals_list)

    def write(self, vals):
        check_employee_target(self.env, vals)
        return super().write(vals)
