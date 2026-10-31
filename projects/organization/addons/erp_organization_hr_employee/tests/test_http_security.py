from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestEmployeeHttpScope(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "HTTP Scope Company"})
        units = cls.env["erp.organization.unit"]
        cls.allowed_unit = units.create({"name": "HTTP Allowed", "code": "HTTP-A", "company_id": cls.company.id})
        cls.hidden_unit = units.create({"name": "HTTP Hidden", "code": "HTTP-B", "company_id": cls.company.id})
        cls.user = cls.env["res.users"].create({
            "name": "HTTP Scope Reader", "login": "http_scope_reader", "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])], "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.env["erp.organization.assignment"].create({"user_id": cls.user.id, "unit_id": cls.allowed_unit.id})
        employee = cls.env["hr.employee"]
        cls.hidden = employee.create({"name": "HTTP Hidden Manager", "company_id": cls.company.id, "organization_unit_id": cls.hidden_unit.id})
        cls.visible = employee.create({"name": "HTTP Visible Employee", "company_id": cls.company.id, "organization_unit_id": cls.allowed_unit.id, "parent_id": cls.hidden.id})
        cls.child = employee.create({"name": "HTTP Hidden Child", "company_id": cls.company.id, "organization_unit_id": cls.hidden_unit.id, "parent_id": cls.visible.id})
        cls.allowed_attachment = cls.env["ir.attachment"].create({"name": "http-allowed.txt", "raw": b"visible synthetic payload", "res_model": "hr.employee.public", "res_id": cls.visible.id})
        cls.hidden_attachment = cls.env["ir.attachment"].create({"name": "http-hidden.txt", "raw": b"secret synthetic payload", "res_model": "hr.employee.public", "res_id": cls.hidden.id})

    def test_org_chart_and_subordinates_http(self):
        self.authenticate("http_scope_reader", "test-only")
        context = {"allowed_company_ids": [self.company.id], "max_level": 5}
        result = self.make_jsonrpc_request("/hr/get_org_chart", {"employee_id": self.visible.id, "context": context})
        self.assertEqual(result["self"]["id"], self.visible.id)
        self.assertNotIn(self.hidden.id, [x["id"] for x in result["managers"]])
        self.assertNotIn(self.child.id, [x["id"] for x in result["children"]])
        self.assertEqual(result["self"]["direct_sub_count"], 0)
        self.assertEqual(result["self"]["indirect_sub_count"], 0)
        ids = self.make_jsonrpc_request("/hr/get_subordinates", {"employee_id": self.visible.id, "context": context})
        self.assertNotIn(self.child.id, ids)
        denied = self.make_jsonrpc_request("/hr/get_org_chart", {"employee_id": self.hidden.id, "context": context})
        self.assertNotIn("self", denied)

    def test_attachment_download_http(self):
        self.authenticate("http_scope_reader", "test-only")
        allowed = self.url_open("/web/content/%s?download=1" % self.allowed_attachment.id)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.content, b"visible synthetic payload")
        hidden = self.url_open("/web/content/%s?download=1" % self.hidden_attachment.id)
        self.assertIn(hidden.status_code, (403, 404))
        self.assertNotIn(b"secret synthetic payload", hidden.content)
        assignment = self.env["erp.organization.assignment"].search([("user_id", "=", self.user.id), ("unit_id", "=", self.allowed_unit.id)])
        assignment.unlink()
        revoked = self.url_open("/web/content/%s?download=1" % self.allowed_attachment.id)
        self.assertIn(revoked.status_code, (403, 404))
        self.assertNotIn(b"visible synthetic payload", revoked.content)

    def test_employee_avatar_download_http(self):
        self.authenticate("http_scope_reader", "test-only")
        allowed = self.url_open("/web/image/hr.employee.public/%s/avatar_128?download=1" % self.visible.id)
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.content)
        hidden = self.url_open("/web/image/hr.employee.public/%s/avatar_128?download=1" % self.hidden.id)
        self.assertIn(hidden.status_code, (403, 404))

    def test_multi_organization_hierarchy_and_attachment_http(self):
        assignments = self.env['erp.employee.organization.assignment']
        self.hidden.organization_unit_id = False
        self.child.organization_unit_id = False
        manager_extra = assignments.create({'employee_id': self.hidden.id, 'organization_id': self.allowed_unit.id})
        child_extra = assignments.create({'employee_id': self.child.id, 'organization_id': self.allowed_unit.id})
        self.authenticate('http_scope_reader', 'test-only')
        context = {'allowed_company_ids': [self.company.id], 'max_level': 5}
        chart = self.make_jsonrpc_request('/hr/get_org_chart', {'employee_id': self.visible.id, 'context': context})
        self.assertIn(self.hidden.id, [item['id'] for item in chart['managers']])
        self.assertIn(self.child.id, [item['id'] for item in chart['children']])
        self.assertIn(self.child.id, self.make_jsonrpc_request('/hr/get_subordinates', {'employee_id': self.visible.id, 'subordinates_type': 'direct', 'context': context}))
        self.assertEqual(self.url_open('/web/content/%s?download=1' % self.hidden_attachment.id).status_code, 200)
        manager_extra.date_to = fields.Date.subtract(fields.Date.today(), days=1)
        child_extra.active = False
        chart = self.make_jsonrpc_request('/hr/get_org_chart', {'employee_id': self.visible.id, 'context': context})
        self.assertNotIn(self.hidden.id, [item['id'] for item in chart['managers']])
        self.assertNotIn(self.child.id, [item['id'] for item in chart['children']])
        self.assertNotIn(self.child.id, self.make_jsonrpc_request('/hr/get_subordinates', {'employee_id': self.visible.id, 'subordinates_type': 'direct', 'context': context}))
        self.assertIn(self.url_open('/web/content/%s?download=1' % self.hidden_attachment.id).status_code, (403, 404))
