from psycopg2.errors import UniqueViolation
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOrganizationAssignments(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a = cls.env["res.company"].create({"name": "Assignment Company A"})
        cls.b = cls.env["res.company"].create({"name": "Assignment Company B"})
        unit = cls.env["erp.organization.unit"]
        cls.a1 = unit.create({"name": "Assignment A1", "code": "A1", "company_id": cls.a.id})
        cls.a2 = unit.create({"name": "Assignment A2", "code": "A2", "company_id": cls.a.id})
        cls.b1 = unit.create({"name": "Assignment B1", "code": "B1", "company_id": cls.b.id})
        user = cls.env["res.users"]
        base = cls.env.ref("base.group_user").id
        manager_group = cls.env.ref("erp_organization.group_organization_manager").id
        cls.user = user.create({"name": "Assigned User", "login": "assignment_user", "company_id": cls.a.id, "company_ids": [(6, 0, [cls.a.id, cls.b.id])], "group_ids": [(6, 0, [base])]})
        cls.other = user.create({"name": "Other User", "login": "assignment_other", "company_id": cls.a.id, "company_ids": [(6, 0, [cls.a.id])], "group_ids": [(6, 0, [base])]})
        cls.manager = user.create({"name": "Assignment Manager", "login": "assignment_manager", "company_id": cls.a.id, "company_ids": [(6, 0, [cls.a.id, cls.b.id])], "group_ids": [(6, 0, [manager_group])]})
        assignments = cls.env["erp.organization.assignment"]
        cls.assign_a = assignments.create({"user_id": cls.user.id, "unit_id": cls.a1.id, "is_default": True})
        cls.assign_b = assignments.create({"user_id": cls.user.id, "unit_id": cls.b1.id, "is_default": True})
        cls.other_assignment = assignments.create({"user_id": cls.other.id, "unit_id": cls.a2.id})

    def test_assigned_units_only_and_company_switch(self):
        units = self.env["erp.organization.unit"].with_user(self.user).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(set(units.search([("id", "in", [self.a1.id, self.a2.id, self.b1.id])]).ids), {self.a1.id})
        with self.assertRaises(AccessError):
            units.browse(self.a2.id).read(["name"])
        both = units.with_context(allowed_company_ids=[self.b.id, self.a.id])
        self.assertEqual(set(both.search([("id", "in", [self.a1.id, self.a2.id, self.b1.id])]).ids), {self.a1.id, self.b1.id})
        assignments = self.env["erp.organization.assignment"].with_user(self.user).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(assignments.default_unit_for_current_user().id, self.a1.id)
        self.assertEqual(assignments.with_context(allowed_company_ids=[self.b.id]).default_unit_for_current_user().id, self.b1.id)
        self.assertEqual(assignments.search([("id", "in", [self.assign_a.id, self.assign_b.id, self.other_assignment.id])]).ids, [self.assign_a.id])

    def test_user_cannot_change_assignments_or_see_others(self):
        assignments = self.env["erp.organization.assignment"].with_user(self.user).with_context(allowed_company_ids=[self.a.id])
        with self.assertRaises(AccessError), self.cr.savepoint():
            assignments.create({"user_id": self.user.id, "unit_id": self.a2.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            assignments.browse(self.assign_a.id).write({"unit_id": self.a2.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            assignments.browse(self.other_assignment.id).read(["user_id"])
        with self.assertRaises(AccessError), self.cr.savepoint():
            assignments.browse(self.assign_a.id).write({"is_default": False})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.a2.with_user(self.user).write({"assignment_ids": [(0, 0, {"user_id": self.user.id})]})

    def test_manager_scope_and_invalid_membership(self):
        assignments = self.env["erp.organization.assignment"].with_user(self.manager).with_context(allowed_company_ids=[self.a.id])
        with self.assertRaises(AccessError), self.cr.savepoint():
            assignments.create({"user_id": self.user.id, "unit_id": self.a2.id, "company_id": self.a.id})
        created = assignments.create({"user_id": self.user.id, "unit_id": self.a2.id})
        self.assertEqual(created.company_id, self.a)
        b2 = self.env["erp.organization.unit"].create({"name": "Assignment B2", "code": "B2", "company_id": self.b.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            created.write({"unit_id": b2.id})
        created.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            assignments.create({"user_id": self.manager.id, "unit_id": self.b1.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            assignments.with_context(allowed_company_ids=[self.a.id, self.b.id]).create({"user_id": self.other.id, "unit_id": self.b1.id})

    def test_default_unique_and_duplicate(self):
        assignments = self.env["erp.organization.assignment"]
        with self.assertRaises(UniqueViolation), self.cr.savepoint():
            assignments.create({"user_id": self.user.id, "unit_id": self.a1.id})
        with self.assertRaises(UniqueViolation), self.cr.savepoint():
            assignments.create({"user_id": self.user.id, "unit_id": self.a2.id, "is_default": True})
        self.assertTrue(self.assign_b.is_default)

    def test_revoke_and_archived_default(self):
        units = self.env["erp.organization.unit"].with_user(self.user).with_context(allowed_company_ids=[self.a.id])
        assignments = self.env["erp.organization.assignment"].with_user(self.user).with_context(allowed_company_ids=[self.a.id])
        self.assertTrue(units.search([("id", "=", self.a1.id)]))
        self.assign_a.unlink()
        self.assertFalse(units.search([("id", "=", self.a1.id)]))
        self.assertFalse(assignments.default_unit_for_current_user())
        assignment = self.env["erp.organization.assignment"].create({"user_id": self.user.id, "unit_id": self.a1.id, "is_default": True})
        self.a1.active = False
        self.assertFalse(assignments.default_unit_for_current_user())
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["erp.organization.assignment"].create({"user_id": self.other.id, "unit_id": self.a1.id})
        assignment.write({"is_default": False})
        self.env["erp.organization.assignment"].create({"user_id": self.user.id, "unit_id": self.a2.id, "is_default": True})
        self.assertEqual(assignments.default_unit_for_current_user().id, self.a2.id)
        assignment.unlink()

    def test_removed_company_does_not_grant_access(self):
        self.user.write({"company_ids": [(3, self.b.id)]})
        units = self.env["erp.organization.unit"].with_user(self.user).with_context(allowed_company_ids=[self.a.id])
        self.assertFalse(units.search([("id", "=", self.b1.id)]))
        with self.assertRaises(AccessError):
            units.with_context(allowed_company_ids=[self.b.id]).search([])
