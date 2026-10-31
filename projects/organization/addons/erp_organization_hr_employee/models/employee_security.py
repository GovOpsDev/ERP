from odoo import fields, models
from odoo.fields import Domain


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _employee_org_domain(self, surface='employee', company_ids=None):
        """Access-domain expression; any! includes hidden membership rows."""
        self.ensure_one()
        today = fields.Date.today()
        effective = (Domain('active', '=', True) & Domain('organization_id.active', '=', True)
                     & (Domain('date_from', '=', False) | Domain('date_from', '<=', today))
                     & (Domain('date_to', '=', False) | Domain('date_to', '>=', today)))
        overlap = effective & Domain('organization_id.assignment_ids', 'any!', [('user_id', '=', self.id)])
        additional = Domain('erp_security_organization_assignment_ids', 'any!', overlap)
        primary = (Domain('organization_unit_id.active', '=', True)
                   & Domain('organization_unit_id.assignment_ids', 'any!', [('user_id', '=', self.id)]))
        never_scoped = (Domain('organization_scope_history', '=', False)
                        & Domain('organization_unit_id', '=', False)
                        & Domain('erp_security_organization_assignment_ids', 'not any!', Domain.TRUE))
        visible = never_scoped | primary | additional
        if surface == 'employee':
            return visible
        if surface == 'version':
            return Domain('employee_id', '=', False) | Domain('employee_id', 'any!', visible)
        if surface == 'related':
            return Domain('employee_id.company_id', 'in', company_ids) & Domain('employee_id', 'any!', visible)
        denied = Domain('company_id', 'not in', company_ids) | ~visible
        if surface == 'resource' or surface == 'partner':
            return Domain('erp_security_employee_ids', 'not any!', denied)
        if surface == 'bank':
            return Domain('erp_security_employee_ids', 'not any!', denied) & Domain('partner_id.erp_security_employee_ids', 'not any!', denied)
        raise ValueError('Unknown employee access surface')
