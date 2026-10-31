from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFoundation(TransactionCase):
    def test_module_installed(self):
        module = self.env["ir.module.module"].search([("name", "=", "erp_core")])
        self.assertEqual(module.state, "installed")

    def test_partner_crud_as_internal_user(self):
        user = self.env["res.users"].create({
            "name": "ERP Foundation Test",
            "login": "erp_foundation_test",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.env.ref("base.group_partner_manager").id])],
        })
        partner = self.env["res.partner"].with_user(user).create({"name": "Foundation Test"})
        partner.write({"name": "Foundation Updated"})
        self.assertEqual(partner.name, "Foundation Updated")
        partner.unlink()

    def test_public_cannot_create_users(self):
        public = self.env.ref("base.public_user")
        with self.assertRaises(AccessError):
            self.env["res.users"].with_user(public).create({"name": "Forbidden", "login": "forbidden"})
