from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEmployeeMultiOrganization(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a = cls.env['res.company'].create({'name': 'Multi employee A'})
        cls.b = cls.env['res.company'].create({'name': 'Multi employee B'})
        units = cls.env['erp.organization.unit']
        def unit(name, company):
            return units.create({'name': name, 'code': name, 'company_id': company.id})
        cls.a1, cls.a2, cls.a3 = (unit(x, cls.a) for x in ('Multi A1', 'Multi A2', 'Multi A3'))
        cls.b1, cls.b2 = (unit(x, cls.b) for x in ('Multi B1', 'Multi B2'))
        base = cls.env.ref('base.group_user').id
        hr = cls.env.ref('hr.group_hr_user').id
        manager = cls.env.ref('erp_organization.group_organization_manager').id
        def user(name, groups):
            return cls.env['res.users'].create({'name': name, 'login': name, 'company_id': cls.a.id, 'company_ids': [(6, 0, [cls.a.id, cls.b.id])], 'group_ids': [(6, 0, groups)]})
        cls.reader = user('multi-employee-reader', [base])
        cls.hr_user = user('multi-employee-hr', [hr])
        cls.org_manager = user('multi-employee-org-manager', [manager])
        org = cls.env['erp.organization.assignment']
        for u in (cls.reader, cls.hr_user):
            org.create({'user_id': u.id, 'unit_id': cls.a2.id})
            org.create({'user_id': u.id, 'unit_id': cls.b1.id})
        employee = cls.env['hr.employee']
        cls.ea = employee.create({'name': 'Multi employee A', 'company_id': cls.a.id, 'organization_unit_id': cls.a1.id, 'user_id': cls.reader.id})
        cls.eb = employee.create({'name': 'Multi employee B', 'company_id': cls.b.id, 'organization_unit_id': cls.b1.id})
        cls.hidden = employee.create({'name': 'Multi hidden A', 'company_id': cls.a.id, 'organization_unit_id': cls.a3.id})
        cls.none = employee.create({'name': 'Multi unassigned A', 'company_id': cls.a.id, 'organization_unit_id': False})
        cls.extra = cls.env['erp.employee.organization.assignment'].create({'employee_id': cls.ea.id, 'organization_id': cls.a2.id})
        cls.extra_b = cls.env['erp.employee.organization.assignment'].create({'employee_id': cls.eb.id, 'organization_id': cls.b2.id})

    def scoped(self, model, user=None, company=None):
        return self.env[model].with_user(user or self.reader).with_context(allowed_company_ids=[(company or self.a).id])

    def test_visibility_public_and_private(self):
        for model in ('hr.employee', 'hr.employee.public'):
            records = self.scoped(model)
            ids = [self.ea.id, self.eb.id, self.hidden.id, self.none.id]
            expected = {self.ea.id, self.none.id}
            self.assertEqual(set(records.search([('id', 'in', ids)]).ids), expected)
            self.assertEqual({x['id'] for x in records.search_read([('id', 'in', ids)], ['name'])}, expected)
            self.assertIn(self.ea.id, dict(records.name_search('Multi employee A')))
            records.browse(self.ea.id).read(['name'])
            with self.assertRaises(AccessError):
                records.browse(self.hidden.id).read(['name'])
            b = self.scoped(model, company=self.b)
            self.assertEqual(set(b.search([('id', 'in', ids)]).ids), {self.eb.id})

    def test_revoke_restore_date_and_duplicate_search(self):
        records = self.scoped('hr.employee.public')
        extra2 = self.env['erp.employee.organization.assignment'].create({'employee_id': self.ea.id, 'organization_id': self.a2.id})
        self.assertEqual(records.search([('id', '=', self.ea.id)]).ids, [self.ea.id])
        self.extra.active = False
        self.assertTrue(records.search([('id', '=', self.ea.id)]))
        extra2.active = False
        self.assertFalse(records.search([('id', '=', self.ea.id)]))
        extra2.active = True
        self.assertTrue(records.search([('id', '=', self.ea.id)]))
        extra2.date_to = fields.Date.today() - timedelta(days=1)
        self.assertFalse(records.search([('id', '=', self.ea.id)]))
        extra2.date_to = False
        self.a2.active = False
        self.assertFalse(records.search([('id', '=', self.ea.id)]))
        self.a2.active = True
        self.assertTrue(records.search([('id', '=', self.ea.id)]))

    def test_unassigned_and_future_only(self):
        self.env['erp.employee.organization.assignment'].create({'employee_id': self.none.id, 'organization_id': self.a3.id, 'date_from': fields.Date.today() + timedelta(days=1)})
        self.assertFalse(self.scoped('hr.employee.public').search([('id', '=', self.none.id)]))

    def test_company_and_dates(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['erp.employee.organization.assignment'].create({'employee_id': self.ea.id, 'organization_id': self.b1.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.extra.write({'date_from': fields.Date.today(), 'date_to': fields.Date.today() - timedelta(days=1)})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.ea.write({'company_id': self.b.id, 'organization_unit_id': self.b1.id})
        self.ea.organization_unit_id = self.a3
        self.assertEqual(self.extra.organization_id, self.a2)
        self.assertTrue(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))

    def test_version_related_and_independence(self):
        versions = self.scoped('hr.version', self.hr_user)
        self.assertTrue(versions.search([('id', '=', self.ea.current_version_id.id)]))
        role_assignment = None
        if 'erp.user.role.assignment' in self.env:
            group = self.env['res.groups'].create({'name': 'Employee multi role test'})
            role = self.env['erp.user.role'].create({'name': 'Employee multi test', 'code': 'EMP-MULTI', 'company_id': self.a.id, 'group_ids': [(4, group.id)]})
            role_assignment = self.env['erp.user.role.assignment'].create({'user_id': self.reader.id, 'role_id': role.id, 'company_id': self.a.id, 'unit_id': self.a2.id})
        user_assignments = self.env['erp.organization.assignment'].search([('user_id', '=', self.reader.id)])
        before = set(user_assignments.ids)
        groups = set(self.reader.group_ids.ids)
        self.extra.active = False
        self.assertFalse(versions.search([('id', '=', self.ea.current_version_id.id)]))
        self.assertEqual(set(self.env['erp.organization.assignment'].search([('user_id', '=', self.reader.id)]).ids), before)
        self.assertEqual(set(self.reader.group_ids.ids), groups)
        if role_assignment:
            self.assertTrue(role_assignment.exists())

    def test_edit_requires_hr_and_employee_access(self):
        model = self.env['erp.employee.organization.assignment'].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        with self.assertRaises(AccessError), self.cr.savepoint():
            model.create({'employee_id': self.ea.id, 'organization_id': self.a2.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.extra.with_user(self.org_manager).with_context(allowed_company_ids=[self.a.id]).write({'active': False})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['erp.employee.organization.assignment'].with_user(self.hr_user).with_context(allowed_company_ids=[self.a.id]).create({'employee_id': self.hidden.id, 'organization_id': self.a2.id})
        self.extra.with_user(self.hr_user).with_context(allowed_company_ids=[self.a.id]).write({'date_from': fields.Date.today()})

    def test_organization_manager_does_not_bypass_employee_scope(self):
        public = self.scoped('hr.employee.public', self.org_manager)
        self.assertFalse(public.search([('id', '=', self.ea.id)]))
        self.assertTrue(public.search([('id', '=', self.none.id)]))

    def test_direct_read_and_counts_refresh_after_revocation(self):
        public = self.scoped('hr.employee.public')
        self.hidden.parent_id = self.ea
        self.env.flush_all()
        parent = public.browse(self.ea.id)
        self.assertEqual(parent.read(['child_count'])[0]['child_count'], 0)
        child_extra = self.env['erp.employee.organization.assignment'].create({'employee_id': self.hidden.id, 'organization_id': self.a2.id})
        self.assertEqual(parent.read(['child_count'])[0]['child_count'], 1)
        child_extra.active = False
        self.assertEqual(parent.read(['child_count'])[0]['child_count'], 0)
        self.extra.active = False
        with self.assertRaises(AccessError):
            public.browse(self.ea.id).read(['name'])

    def test_effective_date_changes_without_write(self):
        from unittest.mock import patch
        today = fields.Date.today()
        self.extra.write({'date_from': today, 'date_to': today})
        public = self.scoped('hr.employee.public')
        self.assertTrue(public.search([('id', '=', self.ea.id)]))
        with patch('odoo.addons.erp_organization_hr_employee.models.employee_security.fields.Date.today', return_value=today + timedelta(days=1)):
            self.assertFalse(public.search([('id', '=', self.ea.id)]))
            with self.assertRaises(AccessError):
                public.browse(self.ea.id).read(['name'])

    def test_multiple_distinct_overlap_is_unique(self):
        self.env['erp.organization.assignment'].create({'user_id': self.reader.id, 'unit_id': self.a3.id})
        self.env['erp.employee.organization.assignment'].create({'employee_id': self.ea.id, 'organization_id': self.a3.id})
        public = self.scoped('hr.employee.public')
        self.assertEqual(public.search([('id', '=', self.ea.id)]).ids, [self.ea.id])
        self.assertEqual(len(public.search_read([('id', '=', self.ea.id)], ['name'])), 1)
        self.assertEqual(len([item for item in public.name_search('Multi employee A') if item[0] == self.ea.id]), 1)

    def test_related_surfaces_follow_additional_membership(self):
        self.ea.organization_unit_id = False
        location = self.env['hr.work.location'].create({'name': 'Multi scope workplace', 'company_id': self.a.id})
        loc = self.env['hr.employee.location'].create({'employee_id': self.ea.id, 'work_location_id': location.id})
        bank = self.env['res.partner.bank'].create({'account_number': 'MULTISYNTHETIC001', 'partner_id': self.ea.work_contact_id.id, 'company_id': self.a.id})
        self.ea.write({'bank_account_ids': [(4, bank.id)]})
        message = self.ea.message_post(body='Multi organization synthetic message')
        attachment = self.env['ir.attachment'].create({'name': 'multi.txt', 'raw': b'multi', 'res_model': 'hr.employee', 'res_id': self.ea.id})
        self.hr_user.group_ids = [(4, self.env.ref('base.group_allow_export').id)]
        employee = self.scoped('hr.employee', self.hr_user).browse(self.ea.id)
        self.assertTrue(employee.export_data(['name'])['datas'])
        self.assertTrue(self.scoped('hr.employee.location', self.hr_user).search([('id', '=', loc.id)]))
        self.assertTrue(self.scoped('resource.resource', self.hr_user).search([('id', '=', self.ea.resource_id.id)]))
        self.assertTrue(self.scoped('res.partner', self.hr_user).search([('id', '=', self.ea.work_contact_id.id)]))
        self.assertTrue(self.scoped('res.partner.bank', self.hr_user).search([('id', '=', bank.id)]))
        self.assertTrue(self.scoped('mail.message', self.hr_user).search([('id', '=', message.id)]))
        self.assertTrue(self.scoped('ir.attachment', self.hr_user).browse(attachment.id).read(['name']))
        report = self.env['ir.actions.report'].with_user(self.hr_user).with_context(allowed_company_ids=[self.a.id])
        self.assertIn(b'Multi employee A', report._render_qweb_html('hr.hr_employee_print_badge', [self.ea.id])[0])
        self.extra.active = False
        self.assertFalse(self.scoped('hr.employee.location', self.hr_user).search([('id', '=', loc.id)]))
        self.assertFalse(self.scoped('resource.resource', self.hr_user).search([('id', '=', self.ea.resource_id.id)]))
        self.assertFalse(self.scoped('res.partner', self.hr_user).search([('id', '=', self.ea.work_contact_id.id)]))
        self.assertFalse(self.scoped('res.partner.bank', self.hr_user).search([('id', '=', bank.id)]))
        self.assertFalse(self.scoped('mail.message', self.hr_user).search([('id', '=', message.id)]))
        with self.assertRaises(AccessError):
            self.scoped('ir.attachment', self.hr_user).browse(attachment.id).read(['name'])
        with self.assertRaises(AccessError):
            employee.export_data(['name'])

    def test_last_additional_expires_fail_closed(self):
        today = fields.Date.today()
        assignment = self.env['erp.employee.organization.assignment'].create({'employee_id': self.none.id, 'organization_id': self.a2.id, 'date_from': today, 'date_to': today})
        for model in ('hr.employee', 'hr.employee.public'):
            self.assertTrue(self.scoped(model).search([('id', '=', self.none.id)]))
        version = self.scoped('hr.version', self.hr_user)
        self.assertTrue(version.search([('id', '=', self.none.current_version_id.id)]))
        assignment.write({'date_from': False, 'date_to': today - timedelta(days=1)})
        for model in ('hr.employee', 'hr.employee.public'):
            self.assertFalse(self.scoped(model).search([('id', '=', self.none.id)]))
        self.assertFalse(version.search([('id', '=', self.none.current_version_id.id)]))
        self.assertFalse(self.scoped('resource.resource', self.hr_user).search([('id', '=', self.none.resource_id.id)]))
        assignment.write({'date_to': False, 'active': False})
        self.assertFalse(self.scoped('hr.employee.public').search([('id', '=', self.none.id)]))
        assignment.active = True
        self.assertTrue(self.scoped('hr.employee.public').search([('id', '=', self.none.id)]))

    def test_primary_removed_and_assignment_deletion_cannot_widen_access(self):
        self.ea.organization_unit_id = False
        self.assertTrue(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))
        self.extra.active = False
        self.assertFalse(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))
        with self.assertRaises(UserError), self.cr.savepoint():
            self.extra.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.ea.write({'organization_scope_history': False})
        self.assertTrue(self.extra.with_context(active_test=False).exists())
        self.assertFalse(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))

    def test_archived_primary_and_remaining_extra(self):
        self.assertTrue(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))
        self.a1.active = False
        self.assertTrue(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))
        self.extra.active = False
        self.assertFalse(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))
        self.extra.active = True
        self.assertTrue(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))
        self.env['erp.organization.assignment'].search([('user_id', '=', self.reader.id), ('unit_id', '=', self.a2.id)]).unlink()
        self.assertFalse(self.scoped('hr.employee.public').search([('id', '=', self.ea.id)]))

    def test_never_scoped_company_switch(self):
        self.assertTrue(self.scoped('hr.employee.public').search([('id', '=', self.none.id)]))
        self.assertFalse(self.scoped('hr.employee.public', company=self.b).search([('id', '=', self.none.id)]))

    def test_primary_only_clearing_and_archiving_fail_closed(self):
        public = self.scoped('hr.employee.public')
        self.assertTrue(public.search([('id', '=', self.none.id)]))
        self.none.organization_unit_id = self.a2
        self.assertTrue(public.search([('id', '=', self.none.id)]))
        self.none.organization_unit_id = False
        self.assertFalse(public.search([('id', '=', self.none.id)]))
        self.none.organization_unit_id = self.a2
        self.a2.active = False
        self.assertFalse(public.search([('id', '=', self.none.id)]))

    def test_company_change_never_scoped_does_not_leak(self):
        self.assertTrue(self.scoped('hr.employee.public').search([('id', '=', self.none.id)]))
        self.none.company_id = self.b
        self.assertFalse(self.scoped('hr.employee.public').search([('id', '=', self.none.id)]))
        self.assertTrue(self.scoped('hr.employee.public', company=self.b).search([('id', '=', self.none.id)]))
