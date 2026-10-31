from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmployeeOrganizationAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env["res.company"]
        cls.a = company.create({"name": "Employee Scope Company A"})
        cls.b = company.create({"name": "Employee Scope Company B"})
        units = cls.env["erp.organization.unit"]
        cls.a1 = units.create({"name": "Employee Unit A1", "code": "EA1", "company_id": cls.a.id})
        cls.a2 = units.create({"name": "Employee Unit A2", "code": "EA2", "company_id": cls.a.id})
        cls.b1 = units.create({"name": "Employee Unit B1", "code": "EB1", "company_id": cls.b.id})
        users = cls.env["res.users"]
        def user(name, login, group_ids, company_ids):
            return users.create({"name": name, "login": login, "company_id": cls.a.id, "company_ids": [(6, 0, company_ids)], "group_ids": [(6, 0, group_ids)]})
        cls.reader = user("Employee Reader", "employee_scope_reader", [cls.env.ref("base.group_user").id], [cls.a.id, cls.b.id])
        cls.officer = user("Employee HR Officer", "employee_scope_officer", [cls.env.ref("hr.group_hr_user").id], [cls.a.id, cls.b.id])
        cls.manager = user("Employee Organization Manager", "employee_scope_manager", [cls.env.ref("hr.group_hr_user").id, cls.env.ref("erp_organization.group_organization_manager").id], [cls.a.id, cls.b.id])
        cls.org_only = user("Employee Organization Only", "employee_scope_org_only", [cls.env.ref("erp_organization.group_organization_manager").id], [cls.a.id])
        assignment = cls.env["erp.organization.assignment"]
        for current in (cls.reader, cls.officer):
            assignment.create({"user_id": current.id, "unit_id": cls.a1.id, "is_default": True})
            assignment.create({"user_id": current.id, "unit_id": cls.b1.id, "is_default": True})
        assignment.create({"user_id": cls.manager.id, "unit_id": cls.a1.id})
        assignment.create({"user_id": cls.org_only.id, "unit_id": cls.a2.id})
        employee = cls.env["hr.employee"]
        cls.ea1 = employee.create({"name": "Employee A1", "company_id": cls.a.id, "organization_unit_id": cls.a1.id})
        cls.ea2 = employee.create({"name": "Employee A2", "company_id": cls.a.id, "organization_unit_id": cls.a2.id})
        cls.eb1 = employee.create({"name": "Employee B1", "company_id": cls.b.id, "organization_unit_id": cls.b1.id})
        cls.unlinked = employee.create({"name": "Employee Unlinked", "company_id": cls.a.id, "organization_unit_id": False})

    def test_private_and_public_visibility(self):
        ids = [self.ea1.id, self.ea2.id, self.eb1.id, self.unlinked.id]
        for model in ("hr.employee", "hr.employee.public"):
            records = self.env[model].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
            self.assertEqual(set(records.search([("id", "in", ids)]).ids), {self.ea1.id, self.unlinked.id}, model)
            with self.assertRaises(AccessError):
                records.browse(self.ea2.id).read(["name"])
            with self.assertRaises(AccessError):
                records.browse(self.eb1.id).read(["name"])
            both = records.with_context(allowed_company_ids=[self.a.id, self.b.id])
            self.assertEqual(set(both.search([("id", "in", ids)]).ids), {self.ea1.id, self.eb1.id, self.unlinked.id}, model)
        via_employee = self.env["hr.employee"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual({r["id"] for r in via_employee.search_read([("id", "in", ids)], ["name"])}, {self.ea1.id, self.unlinked.id})
        public = self.env["hr.employee.public"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual({r["id"] for r in public.search_read([("id", "in", ids)], ["name"])}, {self.ea1.id, self.unlinked.id})
        self.assertEqual(sum(count for _, count in public._read_group([("id", "in", ids)], ["company_id"], ["__count"])), 2)
        hr = self.env["hr.employee"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(set(hr.search([("id", "in", ids)]).ids), {self.ea1.id, self.unlinked.id})
        with self.assertRaises(AccessError):
            hr.browse(self.ea2.id).read(["name"])
        manager = hr.with_user(self.manager)
        self.assertEqual(set(manager.search([("id", "in", ids)]).ids), {self.ea1.id, self.unlinked.id})

    def test_version_and_direct_access(self):
        versions = self.env["hr.version"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        targets = [self.ea1.current_version_id.id, self.ea2.current_version_id.id, self.eb1.current_version_id.id]
        self.assertEqual(versions.search([("id", "in", targets)]).ids, [self.ea1.current_version_id.id])
        with self.assertRaises(AccessError):
            versions.browse(self.ea2.current_version_id.id).read(["employee_id"])
        with self.assertRaises(AccessError), self.cr.savepoint():
            versions.browse(self.ea1.current_version_id.id).write({"employee_id": self.ea2.id})

    def test_employee_write_create_and_company(self):
        employees = self.env["hr.employee"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        with self.assertRaises(AccessError), self.cr.savepoint():
            employees.create({"name": "Forbidden Unit", "company_id": self.a.id, "organization_unit_id": self.a2.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            employees.browse(self.ea1.id).write({"organization_unit_id": self.a2.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            employees.browse(self.unlinked.id).write({"company_id": self.b.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            employees.browse(self.ea2.id).write({"name": "Forbidden"})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env["hr.employee"].create({"name": "Wrong Company", "company_id": self.a.id, "organization_unit_id": self.b1.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.ea1.write({"company_id": self.b.id})
        created = employees.create({"name": "Default Employee", "company_id": self.a.id})
        self.assertEqual(created.organization_unit_id, self.a1)
        explicit = employees.create({"name": "No Unit Employee", "company_id": self.a.id, "organization_unit_id": False})
        self.assertFalse(explicit.organization_unit_id)

    def test_revoked_and_archived_unit(self):
        records = self.env["hr.employee.public"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        self.assertTrue(records.search([("id", "=", self.ea1.id)]))
        self.a1.active = False
        self.assertFalse(records.search([("id", "=", self.ea1.id)]))
        self.a1.active = True
        assignment = self.env["erp.organization.assignment"].search([("user_id", "=", self.reader.id), ("unit_id", "=", self.a1.id)])
        assignment.unlink()
        self.assertFalse(records.search([("id", "=", self.ea1.id)]))

    def test_no_new_hr_rights_and_public_user(self):
        records = self.env["hr.employee"].with_user(self.org_only).with_context(allowed_company_ids=[self.a.id])
        self.assertTrue(records.search([("id", "=", self.ea2.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            records.browse(self.ea2.id).write({"name": "Forbidden"})
        with self.assertRaises(AccessError):
            self.env["hr.employee.public"].with_user(self.env.ref("base.public_user")).search([])

    def test_autocomplete_archived_and_company_switch(self):
        for model in ("hr.employee", "hr.employee.public"):
            employees = self.env[model].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
            names = dict(employees.name_search("Employee"))
            self.assertIn(self.ea1.id, names)
            self.assertIn(self.unlinked.id, names)
            self.assertNotIn(self.ea2.id, names)
            self.assertNotIn(self.eb1.id, names)
            switched = employees.with_context(allowed_company_ids=[self.b.id])
            self.assertIn(self.eb1.id, dict(switched.name_search("Employee")))
            self.assertNotIn(self.ea1.id, dict(switched.name_search("Employee")))
            self.ea1.active = False
            self.ea1.flush_recordset(["active"])
            self.assertNotIn(self.ea1.id, dict(employees.name_search("Employee")))
            self.ea1.active = True
            self.ea1.flush_recordset(["active"])

    def test_version_reassignment_and_revocation(self):
        versions = self.env["hr.version"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        version_id = self.ea1.current_version_id.id
        self.assertTrue(versions.search([("id", "=", version_id)]))
        self.ea1.write({"organization_unit_id": self.a2.id})
        self.assertFalse(versions.search([("id", "=", version_id)]))
        self.ea1.write({"organization_unit_id": self.a1.id})
        assignment = self.env["erp.organization.assignment"].search([("user_id", "=", self.officer.id), ("unit_id", "=", self.a1.id)])
        assignment.unlink()
        self.assertFalse(versions.search([("id", "=", version_id)]))

    def test_export_direct_and_mixed_records(self):
        self.officer.group_ids = [(4, self.env.ref("base.group_allow_export").id)]
        records = self.env["hr.employee"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(records.browse(self.ea1.id).export_data(["name"])["datas"][0][0], "Employee A1")
        with self.assertRaises(AccessError):
            records.browse(self.ea2.id).export_data(["name"])
        with self.assertRaises(AccessError):
            records.browse([self.ea1.id, self.ea2.id]).export_data(["name"])

    def test_employee_attachment_and_image_access(self):
        attachment = self.env["ir.attachment"]
        allowed = attachment.create({"name": "allowed-test.txt", "raw": b"allowed synthetic", "res_model": "hr.employee", "res_id": self.ea1.id})
        denied = attachment.create({"name": "denied-test.txt", "raw": b"forbidden synthetic", "res_model": "hr.employee", "res_id": self.ea2.id})
        attachments = attachment.with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(attachments.browse(allowed.id).read(["file_size"])[0]["file_size"], 17)
        with self.assertRaises(AccessError):
            attachments.browse(denied.id).read(["raw"])
        employee = self.env["hr.employee.public"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        with self.assertRaises(AccessError):
            employee.browse(self.ea2.id).read(["avatar_128"])
        assignment = self.env["erp.organization.assignment"].search([("user_id", "=", self.officer.id), ("unit_id", "=", self.a1.id)])
        assignment.unlink()
        with self.assertRaises(AccessError):
            attachments.browse(allowed.id).read(["raw"])

    def test_badge_report_denies_forbidden_employee(self):
        report = self.env["ir.actions.report"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        content, _ = report._render_qweb_html("hr.hr_employee_print_badge", [self.ea1.id])
        self.assertIn(b"Employee A1", content)
        with self.assertRaises(AccessError):
            report._render_qweb_html("hr.hr_employee_print_badge", [self.ea2.id])
        with self.assertRaises(AccessError):
            report._render_qweb_html("hr.hr_employee_print_badge", [self.ea1.id, self.ea2.id])

    def test_org_chart_does_not_leak_forbidden_hierarchy(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from odoo.addons.erp_organization_hr_employee.controllers.hr_org_chart import ScopedHrOrgChartController
        self.ea1.parent_id = self.ea2
        employee_below = self.env["hr.employee"].create({"name": "Hidden subordinate", "company_id": self.a.id, "organization_unit_id": self.a2.id, "parent_id": self.ea1.id})
        env = self.env(user=self.reader.id, context={"allowed_company_ids": [self.a.id]})
        controller = ScopedHrOrgChartController()
        with patch("odoo.addons.hr.controllers.hr_org_chart.request", SimpleNamespace(env=env)), patch("odoo.addons.erp_organization_hr_employee.controllers.hr_org_chart.request", SimpleNamespace(env=env)):
            result = ScopedHrOrgChartController.get_org_chart.original_endpoint(controller, self.ea1.id, context={"allowed_company_ids": [self.a.id], "max_level": 5})
            self.assertNotIn(self.ea2.id, [item["id"] for item in result["managers"]])
            self.assertNotIn(employee_below.id, [item["id"] for item in result["children"]])
            self.assertEqual(result["self"]["direct_sub_count"], 0)
            self.assertEqual(result["self"]["indirect_sub_count"], 0)
            ids = ScopedHrOrgChartController.get_subordinates.original_endpoint(controller, self.ea1.id, context={"allowed_company_ids": [self.a.id]})
            self.assertNotIn(employee_below.id, ids)

    def test_chatter_employee_record_visibility(self):
        message_a = self.ea1.message_post(body="Allowed synthetic chatter")
        message_b = self.ea2.message_post(body="Forbidden synthetic chatter")
        messages = self.env["mail.message"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertTrue(messages.search([("id", "=", message_a.id)]))
        self.assertFalse(messages.search([("id", "=", message_b.id)]))
        with self.assertRaises(AccessError):
            messages.browse(message_b.id).read(["body"])

    def test_related_employee_location_and_departure(self):
        location = self.env["hr.work.location"].create({"name": "Synthetic Workplace", "company_id": self.a.id})
        locations = self.env["hr.employee.location"]
        good = locations.create({"employee_id": self.ea1.id, "work_location_id": location.id})
        bad = locations.create({"employee_id": self.ea2.id, "work_location_id": location.id})
        restricted = locations.with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertTrue(restricted.search([("id", "=", good.id)]))
        self.assertFalse(restricted.search([("id", "=", bad.id)]))
        with self.assertRaises(AccessError):
            restricted.browse(bad.id).read(["employee_name"])
        with self.assertRaises(AccessError), self.cr.savepoint():
            restricted.browse(good.id).write({"employee_id": self.ea2.id})
        reason = self.env.ref("hr.departure_resigned")
        departures = self.env["hr.employee.departure"]
        future = fields.Date.add(fields.Date.today(), days=7)
        dgood = departures.create({"employee_id": self.ea1.id, "departure_reason_id": reason.id, "dismissal_date": future})
        dbad = departures.create({"employee_id": self.ea2.id, "departure_reason_id": reason.id, "dismissal_date": future})
        scoped = departures.with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertTrue(scoped.search([("id", "=", dgood.id)]))
        self.assertFalse(scoped.search([("id", "=", dbad.id)]))
        with self.assertRaises(AccessError):
            scoped.browse(dbad.id).read(["departure_description"])
        with self.assertRaises(AccessError), self.cr.savepoint():
            scoped.browse(dgood.id).write({"employee_id": self.ea2.id})

    def test_hidden_manager_not_disclosed_by_relational_read(self):
        self.ea1.parent_id = self.ea2
        public = self.env["hr.employee.public"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        try:
            parent = public.browse(self.ea1.id).read(["parent_id"])[0]["parent_id"]
        except AccessError:
            return
        self.assertTrue(not parent or parent[0] != self.ea2.id)

    def test_archived_employee_explicit_context(self):
        records = self.env["hr.employee.public"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        self.ea1.active = False
        self.ea1.flush_recordset(["active"])
        self.assertFalse(records.search([("id", "=", self.ea1.id)]))
        self.assertTrue(records.with_context(active_test=False).search([("id", "=", self.ea1.id)]))
        self.a1.active = False
        self.assertFalse(records.with_context(active_test=False).search([("id", "=", self.ea1.id)]))

    def test_public_subordinates_field_does_not_leak_ids(self):
        hidden = self.env["hr.employee"].create({"name": "Hidden Public Descendant", "company_id": self.a.id, "organization_unit_id": self.a2.id, "parent_id": self.ea1.id})
        public = self.env["hr.employee.public"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        try:
            ids = public.browse(self.ea1.id).read(["subordinate_ids"])[0]["subordinate_ids"]
        except AccessError:
            return
        self.assertNotIn(hidden.id, ids)

    def test_employee_resource_name_does_not_leak(self):
        resources = self.env["resource.resource"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(resources.browse(self.ea1.resource_id.id).read(["name"])[0]["name"], "Employee A1")
        self.assertEqual(resources.browse(self.unlinked.resource_id.id).read(["name"])[0]["name"], "Employee Unlinked")
        with self.assertRaises(AccessError):
            resources.browse(self.ea2.resource_id.id).read(["name"])
        generic = self.env["resource.resource"].create({"name": "Unrelated generic resource", "company_id": self.a.id})
        self.assertEqual(resources.browse(generic.id).read(["name"])[0]["name"], "Unrelated generic resource")
        with self.assertRaises(AccessError):
            resources.browse(generic.id).read(["erp_security_employee_ids"])
        self.ea2.active = False
        self.ea2.flush_recordset(["active"])
        with self.assertRaises(AccessError):
            resources.browse(self.ea2.resource_id.id).read(["name"])
        assignment = self.env["erp.organization.assignment"].search([("user_id", "=", self.reader.id), ("unit_id", "=", self.a1.id)])
        assignment.unlink()
        with self.assertRaises(AccessError):
            resources.browse(self.ea1.resource_id.id).read(["name"])

    def test_employee_bank_scope_and_unrelated_bank(self):
        banks = self.env["res.partner.bank"]
        allowed = banks.create({"account_number": "AUDIT000000111", "partner_id": self.ea1.work_contact_id.id, "company_id": self.a.id})
        denied = banks.create({"account_number": "AUDIT000000222", "partner_id": self.ea2.work_contact_id.id, "company_id": self.a.id})
        contact_only = banks.create({"account_number": "AUDIT000000444", "partner_id": self.ea2.work_contact_id.id, "company_id": self.a.id})
        self.ea1.write({"bank_account_ids": [(4, allowed.id)]})
        self.ea2.write({"bank_account_ids": [(4, denied.id)]})
        partner = self.env["res.partner"].create({"name": "Unrelated supplier"})
        unrelated = banks.create({"account_number": "AUDIT000000333", "partner_id": partner.id, "company_id": self.a.id})
        scoped = banks.with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(scoped.browse(allowed.id).read(["account_number"])[0]["account_number"], "AUDIT000000111")
        with self.assertRaises(AccessError):
            scoped.browse(denied.id).read(["account_number"])
        with self.assertRaises(AccessError):
            scoped.browse(contact_only.id).read(["account_number"])
        self.assertEqual(scoped.browse(unrelated.id).read(["account_number"])[0]["account_number"], "AUDIT000000333")
        assignment = self.env["erp.organization.assignment"].search([("user_id", "=", self.officer.id), ("unit_id", "=", self.a1.id)])
        assignment.unlink()
        with self.assertRaises(AccessError):
            scoped.browse(allowed.id).read(["account_number"])

    def test_employee_work_contact_scope(self):
        partners = self.env["res.partner"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id])
        self.assertEqual(partners.browse(self.ea1.work_contact_id.id).read(["name"])[0]["name"], "Employee A1")
        self.assertEqual(partners.browse(self.unlinked.work_contact_id.id).read(["name"])[0]["name"], "Employee Unlinked")
        with self.assertRaises(AccessError):
            partners.browse(self.ea2.work_contact_id.id).read(["name"])
        unrelated = self.env["res.partner"].create({"name": "Unrelated partner"})
        self.assertEqual(partners.browse(unrelated.id).read(["name"])[0]["name"], "Unrelated partner")

    def test_public_subordinate_counts_exclude_hidden(self):
        self.env["hr.employee"].create({"name": "Hidden Count Descendant", "company_id": self.a.id, "organization_unit_id": self.a2.id, "parent_id": self.ea1.id})
        public = self.env["hr.employee.public"].with_user(self.reader).with_context(allowed_company_ids=[self.a.id])
        counts = public.browse(self.ea1.id).read(["child_count", "child_all_count"])[0]
        self.assertEqual(counts["child_count"], 0)
        self.assertEqual(counts["child_all_count"], 0)

    def test_hr_private_subordinate_ids_and_counts_exclude_hidden(self):
        hidden = self.env["hr.employee"].create({"name": "Hidden Private Descendant", "company_id": self.a.id, "organization_unit_id": self.a2.id, "parent_id": self.ea1.id})
        employee = self.env["hr.employee"].with_user(self.officer).with_context(allowed_company_ids=[self.a.id]).browse(self.ea1.id)
        result = employee.read(["subordinate_ids", "child_count", "child_all_count"])[0]
        self.assertNotIn(hidden.id, result["subordinate_ids"])
        self.assertEqual(result["child_count"], 0)
        self.assertEqual(result["child_all_count"], 0)

    def test_hierarchy_counts_refresh_after_company_and_assignment_changes(self):
        child = self.env["hr.employee"].create({"name": "Visible Cross Company Child", "company_id": self.b.id, "organization_unit_id": self.b1.id, "parent_id": self.ea1.id})
        public = self.env["hr.employee.public"].with_user(self.reader)
        both = public.with_context(allowed_company_ids=[self.a.id, self.b.id]).browse(self.ea1.id)
        only_a = public.with_context(allowed_company_ids=[self.a.id]).browse(self.ea1.id)
        self.assertEqual(both.read(["child_count"])[0]["child_count"], 1)
        self.assertEqual(only_a.read(["child_count"])[0]["child_count"], 0)
        assignment = self.env["erp.organization.assignment"].search([("user_id", "=", self.reader.id), ("unit_id", "=", self.b1.id)])
        assignment.unlink()
        self.assertEqual(both.read(["child_count"])[0]["child_count"], 0)
