"""Source read-only/restricted-model policies on Odoo 20 access domains.

Odoo 20 global ir.access rows restrict access; they are not Odoo 15 global
ACL grants. Technical write exceptions therefore use explicit model metadata.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain


class RoleRestriction(models.Model):
    _inherit = 'erp.user.role'

    is_readonly_user = fields.Boolean(copy=False, groups='base.group_system', string='Read-only Role')
    unrestrict_model_update = fields.Boolean(copy=False, groups='base.group_system', string='Allow Restricted Model Updates')

    def write(self, vals):
        users = self.sudo().assignment_ids.user_id
        result = super().write(vals)
        if {'is_readonly_user', 'unrestrict_model_update'} & vals.keys():
            users._role_reconcile()
        return result


class UserRestriction(models.Model):
    _inherit = 'res.users'

    is_readonly_user = fields.Boolean(groups='base.group_system', string='Read-only User')
    unrestrict_model_update = fields.Boolean(groups='base.group_system', string='Allow Restricted Model Updates')
    erp_role_assignment_ids = fields.One2many('erp.user.role.assignment', 'user_id', groups='base.group_system')
    erp_role_update_policy = fields.Json(compute='_compute_role_update_policy', compute_sudo=True, groups='base.group_system')

    @api.depends('erp_role_assignment_ids.active', 'erp_role_assignment_ids.date_from', 'erp_role_assignment_ids.date_to',
                 'erp_role_assignment_ids.role_id.active', 'erp_role_assignment_ids.role_id.is_readonly_user',
                 'erp_role_assignment_ids.role_id.unrestrict_model_update', 'company_ids', 'active')
    def _compute_role_update_policy(self):
        today = fields.Date.today()
        for user in self:
            assignments = user.erp_role_assignment_ids.filtered(lambda assignment: assignment._is_effective(today))
            user.erp_role_update_policy = {
                'readonly': assignments.filtered('role_id.is_readonly_user').company_id.ids,
                'unrestricted': assignments.filtered('role_id.unrestrict_model_update').company_id.ids,
            }

    def _role_reconcile(self):
        result = super()._role_reconcile()
        self.sudo().invalidate_recordset(['erp_role_update_policy'])
        self.sudo()._check_readonly_administrator()
        return result

    @api.constrains('is_readonly_user', 'group_ids')
    def _check_readonly_administrator(self):
        for user in self:
            if (user.is_readonly_user or user.erp_role_update_policy.get('readonly')) and user.has_group('base.group_system'):
                raise ValidationError(_('A settings administrator cannot be a read-only user.'))


class ModelRestriction(models.Model):
    _inherit = 'ir.model'

    restrict_update = fields.Boolean(groups='base.group_system', string='Restrict Updates')
    erp_readonly_exempt = fields.Boolean(groups='base.group_system', string='Technical Read-only Exception',
                                       help='Allows read-only users to use normal write permissions on this technical model. It never grants an ACL or bypasses record rules.')


class BaseRestriction(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def _access_domain(self, operation):
        domain = super()._access_domain(operation)
        if self.env.su or operation == 'read' or domain.is_false():
            return domain
        user = self.env.user.sudo()
        policy = user.erp_role_update_policy or {}
        companies = set(self.env.companies.ids)
        readonly = user.is_readonly_user or companies.intersection(policy.get('readonly', []))
        unrestricted = user.unrestrict_model_update or companies.issubset(policy.get('unrestricted', []))
        model = self.env['ir.model'].sudo()._get(self._name)
        if readonly and not model.erp_readonly_exempt or model.restrict_update and not unrestricted:
            return Domain.FALSE
        return domain
