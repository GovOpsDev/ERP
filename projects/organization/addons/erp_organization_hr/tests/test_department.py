from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDepartmentOrganization(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env["res.company"]
        cls.a = company.create({"name": "HR Organization Company A"})
        cls.b = company.create({"name": "HR Organization Company B"})
        unit = cls.env["erp.organization.unit"]
        cls.a1 = unit.create({"name": "HR Unit A1", "code": "HR-A1", "company_id": cls.a.id})
        cls.a2 = unit.create({"name": "HR Unit A2", "code": "HR-A2", "company_id": cls.a.id})
        cls.b1 = unit.create({"name": "HR Unit B1", "code": "HR-B1", "company_id": cls.b.id})
        groups = cls.env.ref("hr.group_hr_user")
        org_manager = cls.env.ref("erp_organization.group_organization_manager")
        user = cls.env["res.users"]
        cls.officer = user.create({"name": "Department Officer", "login": "department_officer", "company_id": cls.a.id, "company_ids": [(6, 0, [cls.a.id, cls.b.id])], "group_ids": [(6, 0, [groups.id])]})
        cls.reader = user.create({"name": "Department Reader", "login": "department_reader", "company_id": cls.a.id, "company_ids": [(6, 0, [cls.a.id])], "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])]})
        cls.manager = user.create({"name": "Department Manager", "login": "department_manager", "company_id": cls.a.id, "company_ids": [(6, 0, [cls.a.id, cls.b.id])], "group_ids": [(6, 0, [groups.id, org_manager.id])]})
        assignments = cls.env["erp.organization.assignment"]
        cls.officer_a = assignments.create({"user_id": cls.officer.id, "unit_id": cls.a1.id, "is_default": True})
        assignments.create({"user_id": cls.officer.id, "unit_id": cls.b1.id, "is_default": True})
        assignments.create({"user_id": cls.reader.id, "unit_id": cls.a1.id})
        departments = cls.env["hr.department"]
        cls.dept_a1 = departments.create({"name": "Department A1", "company_id": cls.a.id, "organization_unit_id": cls.a1.id})
        cls.dept_a2 = departments.create({"name": "Department A2", "company_id": cls.a.id, "organization_unit_id": cls.a2.id})
        cls.dept_b1 = departments.create({"name": "Department B1", "company_id": cls.b.id, "organization_unit_id": cls.b1.id})
        cls.unlinked = departments.create({"name": "Department Unlinked", "company_id": cls.a.id, "organization_unit_id": False})

    def test_department_read_and_company_switch(self):
        ids = [self.dept_a1.id, self.dept_a2.id, self.dept_b1.id, self.unlinked.id]
        dept = self.env["hr.department"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(set(dept.search([("id", "in", ids)]).ids), {self.dept_a1.id, self.unlinked.id})
        with self.assertRaises(AccessError):
            dept.browse(self.dept_a2.id).read(["name"])
        with self.assertRaises(AccessError):
            dept.browse(self.dept_b1.id).read(["name"])
        both = dept.with_user(self.officer).with_context(allowed_company_ids=[self.a.id, self.b.id])
        self.assertEqual(set(both.search([("id", "in", ids)]).ids), {self.dept_a1.id, self.dept_b1.id, self.unlinked.id})
        manager = dept.with_user(self.manager)
        self.assertEqual(set(manager.search([("id", "in", ids)]).ids), {self.dept_a1.id, self.dept_a2.id, self.unlinked.id})

    def test_hr_officer_cannot_link_unassigned_or_cross_active_company(self):
        dept = self.env["hr.department"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        with self.assertRaises(AccessError), self.cr.savepoint():
            dept.create({"name": "Forbidden A", "company_id": self.a.id, "organization_unit_id": self.a2.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            dept.browse(self.dept_a1.id).write({"organization_unit_id": self.a2.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            dept.create({"name": "Forbidden B", "company_id": self.b.id, "organization_unit_id": self.b1.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            dept.browse(self.dept_a2.id).write({"name": "Forbidden"})
        with self.assertRaises(AccessError), self.cr.savepoint():
            dept.browse(self.unlinked.id).write({"company_id": self.b.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            dept.browse(self.unlinked.id).write({"parent_id": self.dept_b1.id})

    def test_default_respects_company_and_explicit_empty(self):
        dept = self.env["hr.department"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id, self.b.id])
        created = dept.create({"name": "Default A", "company_id": self.a.id})
        self.assertEqual(created.organization_unit_id, self.a1)
        explicit = dept.create({"name": "No Unit", "company_id": self.a.id, "organization_unit_id": False})
        self.assertFalse(explicit.organization_unit_id)
        other = dept.create({"name": "Other Company", "company_id": self.b.id})
        self.assertFalse(other.organization_unit_id)
        b_current = dept.with_context(allowed_company_ids=[self.b.id, self.a.id]).create({"name": "Default B", "company_id": self.b.id})
        self.assertEqual(b_current.organization_unit_id, self.b1)

    def test_company_mismatch_and_descendant_change(self):
        dept = self.env["hr.department"]
        with self.assertRaises(ValidationError), self.cr.savepoint():
            dept.create({"name": "Mismatch", "company_id": self.a.id, "organization_unit_id": self.b1.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.dept_a1.write({"company_id": self.b.id})
        parent = dept.create({"name": "Parent A", "company_id": self.a.id, "organization_unit_id": False})
        child = dept.create({"name": "Child A", "parent_id": parent.id, "organization_unit_id": self.a1.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            parent.write({"company_id": self.b.id})
        self.assertEqual(child.company_id, self.a)

    def test_revoke_unit_and_archived_link(self):
        dept = self.env["hr.department"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertTrue(dept.search([("id", "=", self.dept_a1.id)]))
        self.a1.active = False
        self.assertFalse(dept.search([("id", "=", self.dept_a1.id)]))
        self.a1.active = True
        self.assertTrue(dept.search([("id", "=", self.dept_a1.id)]))
        self.officer_a.unlink()
        self.assertFalse(dept.search([("id", "=", self.dept_a1.id)]))
        self.a1.active = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["hr.department"].create({"name": "Archived link", "company_id": self.a.id, "organization_unit_id": self.a1.id})

    def test_organization_manager_does_not_gain_hr_write(self):
        org_only = self.env["res.users"].create({
            "name": "Organization Only", "login": "organization_only_hr",
            "company_id": self.a.id, "company_ids": [(6, 0, [self.a.id])],
            "group_ids": [(6, 0, [self.env.ref("erp_organization.group_organization_manager").id])],
        })
        departments = self.env["hr.department"].with_user(org_only).with_context(allowed_company_ids=[self.a.id])
        self.assertTrue(departments.search([("id", "=", self.dept_a2.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            departments.browse(self.dept_a2.id).write({"name": "Forbidden"})
        with self.assertRaises(AccessError), self.cr.savepoint():
            departments.create({"name": "Forbidden", "company_id": self.a.id})
        with self.assertRaises(AccessError):
            self.env["hr.department"].with_user(self.env.ref("base.public_user")).search([])
