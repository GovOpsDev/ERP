from odoo import api, models


class OrganizationAssignment(models.Model):
    _inherit = 'erp.organization.assignment'

    @api.model_create_multi
    def create(self, vals_list):
        assignments = super().create(vals_list)
        assignments.sudo().user_id._role_reconcile()
        return assignments

    def write(self, vals):
        users = self.sudo().user_id
        result = super().write(vals)
        (users | self.sudo().user_id)._role_reconcile()
        return result

    def unlink(self):
        users = self.sudo().user_id
        result = super().unlink()
        users._role_reconcile()
        return result


class OrganizationUnit(models.Model):
    _inherit = 'erp.organization.unit'

    def write(self, vals):
        users = self.env['res.users']
        if 'active' in vals:
            users = self.env['erp.user.role.assignment'].sudo().with_context(active_test=False).search([('unit_id', 'in', self.ids)]).user_id
        result = super().write(vals)
        users._role_reconcile()
        return result
