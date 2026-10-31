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


@tagged('post_install', '-at_install')
class TestThaiCurrencyDefaults(TransactionCase):
    def test_new_company_defaults_to_thb(self):
        company = self.env['res.company'].create({'name': 'THB default test'})
        self.assertEqual(company.currency_id, self.env.ref('base.THB'))
        self.assertTrue(company.currency_id.active)

    def test_explicit_foreign_currency_preserved(self):
        usd = self.env.ref('base.USD')
        company = self.env['res.company'].create({'name': 'Explicit USD test', 'currency_id': usd.id})
        company.write({'name': 'Explicit USD renamed'})
        self.assertEqual(company.currency_id, usd)

    def test_context_currency_choice_preserved(self):
        usd = self.env.ref('base.USD')
        company = self.env['res.company'].with_context(default_currency_id=usd.id).create({'name': 'Context USD test'})
        self.assertEqual(company.currency_id, usd)

    def test_branch_keeps_parent_currency(self):
        usd = self.env.ref('base.USD')
        parent = self.env['res.company'].create({'name': 'USD root test', 'currency_id': usd.id})
        branch = self.env['res.company'].create({'name': 'USD branch test', 'parent_id': parent.id})
        self.assertEqual(branch.currency_id, usd)
        defaults = self.env['res.company'].with_context(default_parent_id=parent.id).default_get(['currency_id'])
        self.assertEqual(defaults['currency_id'], usd.id)

    def test_batch_keeps_explicit_currency(self):
        usd = self.env.ref('base.USD')
        companies = self.env['res.company'].create([
            {'name': 'Batch THB test'},
            {'name': 'Batch USD test', 'currency_id': usd.id},
        ])
        self.assertEqual(companies[0].currency_id, self.env.ref('base.THB'))
        self.assertEqual(companies[1].currency_id, usd)

    def test_install_hook_does_not_change_named_company(self):
        from odoo.addons.erp_core.hooks import post_init_hook
        usd = self.env.ref('base.USD')
        company = self.env['res.company'].create({'name': 'Existing USD organization', 'currency_id': usd.id})
        before = {c.id: c.currency_id.id for c in self.env['res.company'].with_context(active_test=False).search([])}
        post_init_hook(self.env)
        after = {c.id: c.currency_id.id for c in self.env['res.company'].with_context(active_test=False).search([])}
        self.assertEqual(after, before)
        self.assertEqual(company.currency_id, usd)
