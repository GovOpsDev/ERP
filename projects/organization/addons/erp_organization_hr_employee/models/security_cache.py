from odoo import api, fields, models


def invalidate_employee_scope(env):
    env.transaction.invalidate_access_cache()
    env['hr.employee'].invalidate_model(['child_count', 'child_all_count', 'subordinate_ids'])
    env['hr.employee.public'].invalidate_model(['child_count', 'child_all_count'])


class IrAccess(models.Model):
    _inherit = 'ir.access'

    def _get_access_context(self):
        yield from super()._get_access_context()
        yield fields.Date.today()


class OrganizationAssignment(models.Model):
    _inherit = 'erp.organization.assignment'

    @api.model_create_multi
    def create(self, vals_list):
        result = super().create(vals_list)
        invalidate_employee_scope(self.env)
        return result

    def write(self, vals):
        result = super().write(vals)
        invalidate_employee_scope(self.env)
        return result

    def unlink(self):
        result = super().unlink()
        invalidate_employee_scope(self.env)
        return result


class OrganizationUnit(models.Model):
    _inherit = 'erp.organization.unit'

    def write(self, vals):
        result = super().write(vals)
        if 'active' in vals:
            invalidate_employee_scope(self.env)
        return result
