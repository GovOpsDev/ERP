from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class UserRole(models.Model):
    _name = 'erp.user.role'
    _description = 'Organization User Role'
    _order = 'company_id, name, id'

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    description = fields.Text()
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True, ondelete='restrict')
    group_ids = fields.Many2many('res.groups', string='Groups')
    assignment_ids = fields.One2many('erp.user.role.assignment', 'role_id')
    _unique_code = models.Constraint('unique(company_id, code)', 'Role code must be unique in a company.')

    @api.constrains('name', 'code')
    def _check_names(self):
        if any(not r.name.strip() or not r.code.strip() for r in self):
            raise ValidationError(_('Role name and code cannot be blank.'))

    def write(self, vals):
        if not self:
            return super().write(vals)
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            self.check_access('write')
            if set(vals) - {'name', 'code', 'description', 'group_ids'}:
                raise AccessError(_('Only role metadata and delegated group mappings may be changed.'))
            # Serialize the no-assignments check against concurrent assignment inserts.
            self.env.cr.execute('SELECT id FROM erp_user_role WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            policies = self.env['erp.user.role.mapping.delegation'].sudo()
            for role in self.sudo():
                policy = policies.search([('manager_id', '=', self.env.uid), ('role_id', '=', role.id)], limit=1)
                if not policy or role.company_id.id not in self.env.companies.ids:
                    raise AccessError(_('No definition delegation for this role and active company.'))
                if 'group_ids' in vals:
                    if self.env['erp.user.role.assignment'].sudo().with_context(active_test=False).search_count([('role_id', '=', role.id)]):
                        raise AccessError(_('Only an administrator may change groups of a role with assignments.'))
                    groups = set(role.group_ids.ids)
                    for cmd in vals['group_ids']:
                        op = cmd[0]
                        if op == 4:
                            groups.add(cmd[1])
                        elif op == 3:
                            groups.discard(cmd[1])
                        elif op == 5:
                            groups.clear()
                        elif op == 6:
                            groups = set(cmd[2])
                        else:
                            raise AccessError(_('Only direct group links can be changed.'))
                    if not groups.issubset(set(policy.group_ids.ids)):
                        raise AccessError(_('The resulting groups must all be explicitly delegated.'))
        users = self.sudo().assignment_ids.user_id if {'group_ids', 'active', 'company_id'} & vals.keys() else self.env['res.users']
        if 'company_id' in vals and any(r.company_id.id != vals['company_id'] and r.assignment_ids for r in self.sudo()):
            raise ValidationError(_('A role with assignments cannot change company.'))
        result = super().write(vals)
        users._role_reconcile()
        return result

    def unlink(self):
        users = self.sudo().assignment_ids.user_id
        result = super().unlink()
        users._role_reconcile()
        return result


class RoleMappingDelegation(models.Model):
    _name = 'erp.user.role.mapping.delegation'
    _description = 'Role Definition Delegation'

    manager_id = fields.Many2one('res.users', required=True, ondelete='cascade')
    role_id = fields.Many2one('erp.user.role', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='role_id.company_id', store=True, index=True)
    group_ids = fields.Many2many('res.groups', string='Permitted Groups')
    _unique = models.Constraint('unique(manager_id, role_id)', 'Definition delegation already exists.')

    @api.constrains('manager_id', 'role_id')
    def _check_scope(self):
        for rec in self.sudo():
            if rec.company_id not in rec.manager_id.company_ids:
                raise ValidationError(_('The manager must be allowed in the role company.'))


class RoleDelegation(models.Model):
    _name = 'erp.user.role.delegation'
    _description = 'Role Assignment Delegation'
    _order = 'company_id, manager_id, role_id'

    manager_id = fields.Many2one('res.users', required=True, ondelete='cascade')
    role_id = fields.Many2one('erp.user.role', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='role_id.company_id', store=True, index=True)
    unit_id = fields.Many2one('erp.organization.unit', required=True, ondelete='cascade')
    _unique = models.Constraint('unique(manager_id, role_id, unit_id)', 'Delegation already exists.')

    @api.constrains('role_id', 'unit_id')
    def _check_scope(self):
        for rec in self.sudo():
            if rec.role_id.company_id != rec.unit_id.company_id or rec.company_id not in rec.manager_id.company_ids:
                raise ValidationError(_('Delegation must match the role company and the manager’s allowed companies.'))


class RoleAssignment(models.Model):
    _name = 'erp.user.role.assignment'
    _description = 'Organization User Role Assignment'
    _order = 'user_id, company_id, role_id, id'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    role_id = fields.Many2one('erp.user.role', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company, ondelete='restrict')
    unit_id = fields.Many2one('erp.organization.unit', index=True, ondelete='restrict')
    active = fields.Boolean(default=True)
    date_from = fields.Date()
    date_to = fields.Date()
    effective = fields.Boolean(compute='_compute_effective')

    def _is_effective(self, today):
        self.ensure_one()
        rec = self.sudo()
        if not (rec.active and rec.role_id.active and rec.user_id.active and rec.company_id in rec.user_id.company_ids and rec.role_id.company_id == rec.company_id):
            return False
        if rec.date_from and rec.date_from > today or rec.date_to and rec.date_to < today:
            return False
        if rec.unit_id:
            if not rec.unit_id.active or rec.unit_id.company_id != rec.company_id:
                return False
            return bool(self.env['erp.organization.assignment'].sudo().search_count([('user_id', '=', rec.user_id.id), ('unit_id', '=', rec.unit_id.id)]))
        return True

    @api.depends('active', 'role_id.active', 'user_id.active', 'date_from', 'date_to', 'unit_id.active', 'user_id.company_ids')
    def _compute_effective(self):
        today = fields.Date.today()
        for rec in self:
            rec.effective = rec._is_effective(today)

    def _check_delegation(self):
        if self.env.su or self.env.user.has_group('base.group_system'):
            return
        delegation = self.env['erp.user.role.delegation'].sudo()
        for rec in self.sudo():
            if (rec.company_id.id not in self.env.companies.ids or rec.user_id.id == self.env.uid or not rec.unit_id or
                not delegation.search_count([('manager_id', '=', self.env.uid), ('role_id', '=', rec.role_id.id), ('unit_id', '=', rec.unit_id.id)])):
                raise AccessError(_('No delegation for this role and organization, or self-assignment is forbidden.'))

    @api.constrains('user_id', 'role_id', 'company_id', 'unit_id', 'date_from', 'date_to')
    def _check_scope(self):
        for rec in self.sudo():
            if rec.role_id.company_id != rec.company_id or rec.company_id not in rec.user_id.company_ids:
                raise ValidationError(_('Role, user and assignment companies must match.'))
            if rec.user_id.share:
                raise ValidationError(_('Role assignments require an internal user.'))
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_('Start date must precede or equal end date.'))
            if rec.unit_id and (rec.unit_id.company_id != rec.company_id or not rec.unit_id.active or not self.env['erp.organization.assignment'].sudo().search_count([('user_id', '=', rec.user_id.id), ('unit_id', '=', rec.unit_id.id)])):
                raise ValidationError(_('The user must be assigned to the active unit in the same company.'))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._check_delegation()
        recs.sudo().user_id._role_reconcile()
        return recs

    def write(self, vals):
        self._check_delegation()
        users = self.sudo().user_id
        result = super().write(vals)
        self._check_delegation()
        (users | self.sudo().user_id)._role_reconcile()
        return result

    def unlink(self):
        self._check_delegation()
        users = self.sudo().user_id
        result = super().unlink()
        users._role_reconcile()
        return result

    @api.model
    def _cron_reconcile(self):
        assignments = self.sudo().with_context(active_test=False).search([])
        states = self.env['erp.user.role.group.state'].sudo().search([])
        (assignments.user_id | states.user_id)._role_reconcile()


class RoleGroupState(models.Model):
    _name = 'erp.user.role.group.state'
    _description = 'Role Group Membership Provenance'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    group_id = fields.Many2one('res.groups', required=True, ondelete='cascade', index=True)
    manual = fields.Boolean(default=False, help='Direct grant independently retained or explicitly requested.')
    _unique = models.Constraint('unique(user_id, group_id)', 'One provenance record per user and group.')
