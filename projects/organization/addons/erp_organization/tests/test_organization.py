from psycopg2.errors import UniqueViolation

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrganization(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env["res.company"].create({"name": "Organization Test A"})
        cls.company_b = cls.env["res.company"].create({"name": "Organization Test B"})
        cls.unit_a = cls.env["erp.organization.unit"].create({"name": "Unit A", "code": "A", "company_id": cls.company_a.id})
        cls.unit_b = cls.env["erp.organization.unit"].create({"name": "Unit B", "code": "B", "company_id": cls.company_b.id})
        cls.manager = cls.env["res.users"].create({
            "name": "Organization Manager", "login": "org_manager_test",
            "company_id": cls.company_a.id,
            "company_ids": [(6, 0, [cls.company_a.id, cls.company_b.id])],
            "group_ids": [(6, 0, [cls.env.ref("erp_organization.group_organization_manager").id])],
        })
        cls.reader = cls.env["res.users"].create({
            "name": "Organization Reader", "login": "org_reader_test",
            "company_id": cls.company_a.id, "company_ids": [(6, 0, [cls.company_a.id])],
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })

    def test_company_visibility_and_crud(self):
        units = self.env["erp.organization.unit"].with_user(self.manager).with_context(allowed_company_ids=[self.company_a.id])
        self.assertEqual(units.search([("id", "in", [self.unit_a.id, self.unit_b.id])]), self.unit_a)
        with self.assertRaises(AccessError):
            units.browse(self.unit_b.id).write({"name": "Forbidden"})
        with self.assertRaises(AccessError), self.cr.savepoint():
            units.create({"name": "Forbidden", "code": "X", "company_id": self.company_b.id})
        child = units.create({"name": "Child", "code": "C", "company_id": self.company_a.id, "parent_id": self.unit_a.id})
        child.write({"name": "Updated Child"})
        child.unlink()
        both = units.with_context(allowed_company_ids=[self.company_a.id, self.company_b.id])
        self.assertEqual(set(both.search([("id", "in", [self.unit_a.id, self.unit_b.id])]).ids), {self.unit_a.id, self.unit_b.id})

    def test_reader_and_public_denied_writes(self):
        with self.assertRaises(AccessError):
            self.unit_a.with_user(self.reader).write({"name": "Forbidden"})
        with self.assertRaises(AccessError):
            self.env["erp.organization.unit"].with_user(self.env.ref("base.public_user")).search([])

    def test_hierarchy_and_company_constraints(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self.unit_a.write({"parent_id": self.unit_b.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.unit_a.write({"parent_id": self.unit_a.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.unit_a.write({"company_id": self.company_b.id})
        with self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env["erp.organization.unit"].create({"name": "Duplicate", "code": "A", "company_id": self.company_a.id})
        self.env["erp.organization.unit"].create({"name": "Same code elsewhere", "code": "A", "company_id": self.company_b.id})

    def test_inactive_units_hidden_by_default(self):
        units = self.env["erp.organization.unit"].with_user(self.manager).with_context(allowed_company_ids=[self.company_a.id])
        self.unit_a.write({"active": False})
        self.assertFalse(units.search([("id", "=", self.unit_a.id)]))
        self.assertEqual(units.with_context(active_test=False).search([("id", "=", self.unit_a.id)]).id, self.unit_a.id)

    def test_name_unique_per_company(self):
        with self.assertRaises(UniqueViolation), self.cr.savepoint():
            self.env["erp.organization.unit"].create({"name": "Unit A", "code": "NEW", "company_id": self.company_a.id})
        self.env["erp.organization.unit"].create({"name": "Unit A", "code": "OTHER", "company_id": self.company_b.id})

    def test_partner_defaults_and_cross_company_boundary(self):
        self.assertEqual(self.unit_a.partner_id, self.company_a.partner_id)
        shared = self.env['res.partner'].create({'name': 'Shared unit contact'})
        self.unit_a.partner_id = shared
        own = self.env['res.partner'].create({'name': 'Local unit contact', 'company_id': self.company_a.id})
        self.unit_a.partner_id = own
        foreign = self.env['res.partner'].create({'name': 'Foreign unit contact', 'company_id': self.company_b.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.unit_a.partner_id = foreign
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.unit_a.partner_id = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['erp.organization.unit'].create({'name': 'Missing partner', 'code': 'MISSING', 'company_id': self.company_a.id, 'partner_id': False})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            own.company_id = self.company_b
