from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRoles(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a = cls.env['res.company'].create({'name': 'Role company A'})
        cls.b = cls.env['res.company'].create({'name': 'Role company B'})
        units = cls.env['erp.organization.unit']
        cls.a1 = units.create({'name': 'Role A1', 'code': 'RA1', 'company_id': cls.a.id})
        cls.a2 = units.create({'name': 'Role A2', 'code': 'RA2', 'company_id': cls.a.id})
        cls.b1 = units.create({'name': 'Role B1', 'code': 'RB1', 'company_id': cls.b.id})
        group = cls.env['res.groups']
        cls.g = group.create({'name': 'Test role capability G'})
        cls.h = group.create({'name': 'Test role capability H'})
        cls.child = group.create({'name': 'Test role child'})
        cls.g.write({'implied_ids': [Command.link(cls.child.id)]})
        base = cls.env.ref('base.group_user')
        manager_group = cls.env.ref('erp_user_role.group_role_manager')
        cls.user = cls.env['res.users'].create({'name': 'Role target', 'login': 'role_target', 'company_id': cls.a.id, 'company_ids': [Command.set([cls.a.id, cls.b.id])], 'group_ids': [Command.set([base.id])]})
        cls.manager = cls.env['res.users'].create({'name': 'Role manager', 'login': 'role_manager_test', 'company_id': cls.a.id, 'company_ids': [Command.set([cls.a.id, cls.b.id])], 'group_ids': [Command.set([manager_group.id])]})
        cls.org = cls.env['erp.organization.assignment'].create({'user_id': cls.user.id, 'unit_id': cls.a1.id})
        cls.org_b = cls.env['erp.organization.assignment'].create({'user_id': cls.user.id, 'unit_id': cls.b1.id})
        cls.role = cls.env['erp.user.role'].create({'name': 'Test role', 'code': 'R', 'company_id': cls.a.id, 'group_ids': [Command.link(cls.g.id)]})
        cls.role_b = cls.env['erp.user.role'].create({'name': 'Test role B', 'code': 'RB', 'company_id': cls.b.id, 'group_ids': [Command.link(cls.h.id)]})

    def assignment(self, **kwargs):
        vals = {'user_id': self.user.id, 'role_id': self.role.id, 'company_id': self.a.id, 'unit_id': self.a1.id}
        vals.update(kwargs)
        return self.env['erp.user.role.assignment'].create(vals)

    def has(self, group):
        self.user.invalidate_recordset(['group_ids', 'all_group_ids'])
        return group in self.user.group_ids

    def test_lifecycle_and_implied(self):
        assignment = self.assignment()
        self.assertTrue(self.has(self.g))
        self.assertIn(self.child, self.user.all_group_ids)
        self.assertFalse(self.has(self.child))
        assignment.unlink()
        self.assertFalse(self.has(self.g))
        self.assertNotIn(self.child, self.user.all_group_ids)

    def test_manual_before_and_after_user_write(self):
        self.user.write({'group_ids': [Command.link(self.g.id)]})
        a = self.assignment()
        a.unlink()
        self.assertTrue(self.has(self.g))
        self.user.write({'group_ids': [Command.unlink(self.g.id)]})
        a = self.assignment()
        self.user.write({'group_ids': [Command.link(self.g.id)]})
        a.unlink()
        self.assertTrue(self.has(self.g))

    def test_manual_after_group_write(self):
        a = self.assignment()
        self.g.write({'user_ids': [Command.link(self.user.id)]})
        a.unlink()
        self.assertTrue(self.has(self.g))

    def test_sharing_mapping_archive(self):
        a = self.assignment()
        role2 = self.role.copy({'name': 'Other role', 'code': 'other'})
        b = self.assignment(role_id=role2.id)
        a.unlink()
        self.assertTrue(self.has(self.g))
        role2.write({'group_ids': [Command.set([self.h.id])]})
        self.assertFalse(self.has(self.g))
        self.assertTrue(self.has(self.h))
        role2.active = False
        self.assertFalse(self.has(self.h))
        role2.active = True
        self.assertTrue(self.has(self.h))
        b.unlink()
        self.assertFalse(self.has(self.h))

    def test_organization_revocation_restore(self):
        a = self.assignment()
        self.org.unlink()
        self.assertFalse(self.has(self.g))
        self.assertFalse(a._is_effective(fields.Date.today()))
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': self.a1.id})
        self.assertTrue(self.has(self.g))
        self.a1.active = False
        self.assertFalse(self.has(self.g))
        self.a1.active = True
        self.assertTrue(self.has(self.g))

    def test_dates_and_cron(self):
        today = fields.Date.today()
        a = self.assignment(date_from=today + timedelta(days=1))
        self.assertFalse(self.has(self.g))
        a.date_from = today
        self.assertTrue(self.has(self.g))
        a.date_to = today
        self.assertTrue(self.has(self.g))
        a.write({'date_from': False, 'date_to': today - timedelta(days=1)})
        self.env['erp.user.role.assignment']._cron_reconcile()
        self.env['erp.user.role.assignment']._cron_reconcile()
        self.assertFalse(self.has(self.g))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            a.write({'date_from': today, 'date_to': today - timedelta(days=1)})

    def test_scope(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.assignment(unit_id=self.a2.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.assignment(unit_id=self.b1.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.assignment(company_id=self.b.id)
        a = self.assignment()
        b = self.assignment(role_id=self.role_b.id, company_id=self.b.id, unit_id=self.b1.id)
        self.assertTrue(self.has(self.g) and self.has(self.h))
        a.unlink()
        self.assertFalse(self.has(self.g))
        self.assertTrue(self.has(self.h))
        b.unlink()

    def test_delegation(self):
        assign = self.env['erp.user.role.assignment'].with_user(self.manager).with_context(allowed_company_ids=[self.a.id])
        vals = {'user_id': self.user.id, 'role_id': self.role.id, 'company_id': self.a.id, 'unit_id': self.a1.id}
        with self.assertRaises(AccessError), self.cr.savepoint():
            assign.create(vals)
        self.env['erp.user.role.delegation'].create({'manager_id': self.manager.id, 'role_id': self.role.id, 'unit_id': self.a1.id})
        self.env['erp.organization.assignment'].create({'user_id': self.manager.id, 'unit_id': self.a1.id})
        a = assign.create(vals)
        self.assertNotIn(self.g, self.manager.all_group_ids)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.role.with_user(self.manager).write({'group_ids': [Command.link(self.env.ref('base.group_system').id)]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            assign.create(dict(vals, user_id=self.manager.id))
        with self.assertRaises(AccessError), self.cr.savepoint():
            assign.create(dict(vals, role_id=self.role_b.id, company_id=self.b.id, unit_id=self.b1.id))
        other_role = self.role.copy({'name': 'Undelegated role', 'code': 'NO-DELEGATION'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            assign.create(dict(vals, role_id=other_role.id))
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['erp.user.role.delegation'].with_user(self.manager).create({'manager_id': self.manager.id, 'role_id': self.role.id, 'unit_id': self.a1.id})
        a.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['erp.user.role.assignment'].with_user(self.user).create(vals)

    def test_direct_removal_and_retain_commands(self):
        a = self.assignment()
        self.user.write({'group_ids': [(3, self.g.id)]})
        self.assertTrue(self.has(self.g))
        self.user.write({'group_ids': [(4, self.g.id)]})
        a.unlink()
        self.assertTrue(self.has(self.g))

    def test_manual_set_from_group_and_restore(self):
        a = self.assignment()
        self.g.write({'user_ids': [Command.set(self.g.user_ids.ids)]})
        self.org.unlink()
        self.assertTrue(self.has(self.g))
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': self.a1.id})
        a.unlink()
        self.assertTrue(self.has(self.g))

    def test_company_removal_and_disable(self):
        a = self.assignment()
        a.active = False
        self.assertFalse(self.has(self.g))
        a.active = True
        self.assertTrue(self.has(self.g))
        self.user.write({'company_ids': [Command.unlink(self.b.id)]})
        self.assertTrue(self.has(self.g))
        self.user.active = False
        self.assertFalse(self.has(self.g))
        self.user.active = True
        self.assertTrue(self.has(self.g))

    def test_restrict_manager_escalation(self):
        groups = self.env.ref('base.group_system')
        manager_roles = self.env['erp.user.role'].with_user(self.manager).with_context(allowed_company_ids=[self.a.id])
        with self.assertRaises(AccessError), self.cr.savepoint():
            manager_roles.create({'name': 'Escalation', 'code': 'ESC', 'company_id': self.a.id, 'group_ids': [Command.link(groups.id)]})
        self.assertNotIn(groups, self.manager.all_group_ids)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.role.with_user(self.manager).with_context(allowed_company_ids=[self.a.id], role_sync=True).write({'group_ids': [Command.link(groups.id)]})

    def test_cron_date_boundary(self):
        from unittest.mock import patch
        today = fields.Date.today()
        self.assignment(date_from=today + timedelta(days=1), date_to=today + timedelta(days=2))
        self.assertFalse(self.has(self.g))
        with patch('odoo.addons.erp_user_role.models.membership.fields.Date.today', return_value=today + timedelta(days=1)):
            self.env['erp.user.role.assignment']._cron_reconcile()
            self.assertTrue(self.has(self.g))
        with patch('odoo.addons.erp_user_role.models.membership.fields.Date.today', return_value=today + timedelta(days=3)):
            self.env['erp.user.role.assignment']._cron_reconcile()
            self.assertFalse(self.has(self.g))

    def test_role_validation_and_assignment_retarget(self):
        from psycopg2.errors import UniqueViolation
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.role.write({'name': '  '})
        with self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env['erp.user.role'].create({'name': 'Duplicate', 'code': 'R', 'company_id': self.a.id})
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': self.a2.id})
        a = self.assignment()
        a.unit_id = self.a2
        self.assertTrue(self.has(self.g))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            a.unit_id = self.b1
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.role.company_id = self.b

    def test_company_membership_revocation(self):
        a = self.assignment()
        self.user.company_id = self.b
        self.user.write({'company_ids': [Command.unlink(self.a.id)]})
        self.assertFalse(self.has(self.g))
        self.assertFalse(a._is_effective(fields.Date.today()))
        self.user.write({'company_ids': [Command.link(self.a.id)]})
        self.assertTrue(self.has(self.g))

    def test_delegated_definition_mapping(self):
        self.env['erp.user.role.mapping.delegation'].create({
            'manager_id': self.manager.id, 'role_id': self.role.id,
            'group_ids': [Command.set([self.g.id, self.h.id])],
        })
        role = self.role.with_user(self.manager).with_context(allowed_company_ids=[self.a.id])
        role.write({'name': 'Delegated role', 'group_ids': [Command.set([self.h.id])]})
        self.assertEqual(self.role.group_ids, self.h)
        with self.assertRaises(AccessError), self.cr.savepoint():
            role.write({'group_ids': [Command.link(self.env.ref('base.group_system').id)]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            role.write({'company_id': self.b.id})
        self.assignment()
        with self.assertRaises(AccessError), self.cr.savepoint():
            role.write({'group_ids': [Command.link(self.g.id)]})
        role.write({'description': 'Delegated metadata'})

    def test_restricted_model_roles_respect_active_companies_and_revocation(self):
        self.user.write({'group_ids': [Command.link(self.env.ref('base.group_partner_manager').id)]})
        model = self.env['ir.model']._get('res.partner')
        model.restrict_update = True
        partner = self.env['res.partner'].create({'name': 'Restricted partner', 'company_id': self.a.id})
        scoped = partner.with_user(self.user).with_context(allowed_company_ids=self.a.ids)
        self.assertFalse(scoped.has_access('write'))
        with self.assertRaises(AccessError), self.cr.savepoint():
            scoped.write({'name': 'Denied'})
        self.role.unrestrict_model_update = True
        assignment = self.assignment()
        self.assertTrue(scoped.has_access('write'))
        scoped.write({'name': 'Allowed'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            scoped.with_context(allowed_company_ids=(self.a | self.b).ids).write({'name': 'Not granted in B'})
        assignment.active = False
        self.assertFalse(scoped.has_access('write'))
        with self.assertRaises(AccessError), self.cr.savepoint():
            scoped.env['res.partner'].create({'name': 'Denied create'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            scoped.unlink()
        self.user.unrestrict_model_update = True
        scoped.write({'name': 'Direct administrator grant'})
        self.assertTrue(scoped.read(['name']))

    def test_readonly_role_precedes_unrestricted_and_expires(self):
        self.user.write({'group_ids': [Command.link(self.env.ref('base.group_partner_manager').id)]})
        partner = self.env['res.partner'].create({'name': 'Read only partner'})
        scoped = partner.with_user(self.user).with_context(allowed_company_ids=self.a.ids)
        self.role.write({'is_readonly_user': True, 'unrestrict_model_update': True})
        assignment = self.assignment()
        self.assertFalse(scoped.has_access('write'))
        self.assertTrue(scoped.has_access('read'))
        with self.assertRaises(AccessError), self.cr.savepoint():
            scoped.write({'name': 'Denied'})
        assignment.date_to = fields.Date.today() - timedelta(days=1)
        self.assertTrue(scoped.has_access('write'))
        assignment.date_to = False
        self.assertFalse(scoped.has_access('write'))
        self.org.unlink()
        self.assertTrue(scoped.has_access('write'))

    def test_restriction_flags_cannot_be_self_granted_or_delegated(self):
        self.user.write({'group_ids': [Command.link(self.env.ref('base.group_partner_manager').id)]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.user.with_user(self.user).write({'unrestrict_model_update': True})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.role.with_user(self.manager).write({'unrestrict_model_update': True})
        self.user.is_readonly_user = True
        partner = self.env['res.partner'].create({'name': 'Explicit exception'})
        scoped = partner.with_user(self.user)
        self.assertFalse(scoped.has_access('write'))
        model = self.env['ir.model']._get('res.partner')
        model.erp_readonly_exempt = True
        self.assertTrue(scoped.has_access('write'))
        model.restrict_update = True
        self.assertFalse(scoped.has_access('write'))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env.user.is_readonly_user = True
