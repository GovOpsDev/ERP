from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from .fixture import InventoryFixture

@tagged('post_install', '-at_install')
class TestAcceptanceFines(InventoryFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user.write({'group_ids': [(4, cls.env.ref('erp_inventory.group_acceptance_manager').id)]})
        cls.revenue = cls.env['account.account'].create({'name': 'Fine revenue', 'code': 'FINEINC', 'account_type': 'income_other', 'company_ids': [(6, 0, cls.company.ids)]})
        receivable = cls.env['account.account'].create({'name': 'Fine receivable', 'code': 'FINEREC', 'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [(6, 0, cls.company.ids)]})
        payable = cls.env['account.account'].create({'name': 'Fine payable', 'code': 'FINEPAY', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, cls.company.ids)]})
        cls.vendor.with_company(cls.company).write({'property_account_receivable_id': receivable.id, 'property_account_payable_id': payable.id})
        cls.company.write({'erp_wa_fines_account_id': cls.revenue.id, 'erp_wa_fines_rate': 3})
        cls.env['account.journal'].create([{'name': 'Fine sales', 'code': 'FINS', 'type': 'sale', 'company_id': cls.company.id}, {'name': 'Fine purchases', 'code': 'FINP', 'type': 'purchase', 'company_id': cls.company.id}])

    def fine(self, po, amount=6):
        wa = self.test_env['erp.inventory.acceptance'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'purchase_order_id': po.id, 'date_due': '2026-06-01', 'date_receive': '2026-06-03', 'late_days': 2, 'fines_late': amount, 'line_ids': [(0, 0, {'purchase_line_id': po.order_line.id, 'quantity': 1})]})
        wa.action_accept()
        return wa

    def test_fine_native_invoice_and_credit_without_budget_actual(self):
        request, po = self.scenario()
        wa = self.fine(po)
        action = wa.action_create_fines_invoice()
        bill = self.test_env['account.move'].browse(action['res_id'])
        self.assertEqual(wa.action_create_fines_invoice()['res_id'], bill.id)
        self.assertEqual((bill.amount_total, bill.erp_budget_exempt, bill.currency_id), (6, True, po.currency_id))
        bill.action_post()
        self.assertEqual((self.active('actual'), self.total()), (0, 100))
        self.assertEqual(sum(bill.line_ids.filtered(lambda l: l.account_id == self.revenue).mapped('balance')), -6)
        refund = bill._reverse_moves(default_values_list=[{'invoice_date': fields.Date.today()}])
        refund.invoice_line_ids.price_unit = 4
        refund.action_post()
        excess = bill._reverse_moves(default_values_list=[{'invoice_date': fields.Date.today()}])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            excess.action_post()
        excess.invoice_line_ids.price_unit = 2
        excess.action_post()
        self.assertEqual(self.active('actual'), 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.button_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            wa.fines_late = 7

    def test_fine_supplier_credit_cancel_recreate_and_provenance(self):
        request, po = self.scenario()
        wa = self.fine(po, 7)
        bill = self.test_env['account.move'].browse(wa.action_create_fines_invoice('in_refund')['res_id'])
        bill.button_cancel()
        replacement = self.test_env['account.move'].browse(wa.action_create_fines_invoice('in_refund')['res_id'])
        self.assertNotEqual(bill, replacement)
        replacement.action_post()
        self.assertEqual((replacement.move_type, self.active('actual'), len(wa.fines_invoice_ids)), ('in_refund', 0, 2))
        with self.assertRaises(AccessError), self.cr.savepoint():
            replacement.erp_late_acceptance_id = False
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['account.move'].with_context(default_erp_late_acceptance_id=wa.id).create({'move_type': 'out_invoice'})
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.unlink()
        replacement.button_draft()
        replacement.invoice_line_ids.price_unit = 8
        with self.assertRaises(ValidationError), self.cr.savepoint():
            replacement.action_post()
        replacement.invoice_line_ids.price_unit = 7
        replacement.invoice_line_ids.account_id = self.account
        with self.assertRaises(ValidationError), self.cr.savepoint():
            replacement.action_post()

    def test_fine_company_unit_visibility_and_configuration(self):
        request, po = self.scenario()
        wa = self.fine(po)
        bill = self.test_env['account.move'].browse(wa.action_create_fines_invoice()['res_id'])
        other = self.env['erp.organization.unit'].create({'name': 'Other fine OU', 'code': 'FINE2', 'company_id': self.company.id})
        outsider = self.env['res.users'].create({'name': 'Other accountant', 'login': 'fine_outsider', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, [self.env.ref('account.group_account_invoice').id, self.env.ref('erp_inventory.group_acceptance_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': outsider.id, 'unit_id': other.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            wa.with_user(outsider).action_create_fines_invoice()
        self.assertFalse(self.test_env['account.move'].with_user(outsider).search([('id', '=', bill.id)]))
        self.assertFalse(self.test_env['account.move.line'].with_user(outsider).search([('move_id', '=', bill.id)]))
        company = self.env['res.company'].create({'name': 'Foreign fine company'})
        wrong = self.env['account.account'].create({'name': 'Foreign revenue', 'code': 'FOREIGN', 'account_type': 'income', 'company_ids': [(6, 0, company.ids)]})
        with self.assertRaises((ValidationError, UserError)), self.cr.savepoint():
            self.company.erp_wa_fines_account_id = wrong

    def test_foreign_fine_keeps_document_currency_and_budget_exemption(self):
        self.company.erp_budget_amount_mode = 'net'
        currency = self.env['res.currency'].create({'name': 'FNF', 'symbol': 'F', 'rounding': .01, 'active': True})
        self.env['res.currency.rate'].create({'name': '2026-01-01', 'currency_id': currency.id, 'company_id': self.company.id, 'rate': .5})
        request = self.make_request(40)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.write({'currency_id': currency.id})
        po.button_confirm()
        wa = self.fine(po, 6)
        bill = self.test_env['account.move'].browse(wa.action_create_fines_invoice()['res_id'])
        bill.action_post()
        self.assertEqual((bill.currency_id, bill.amount_total, self.active('actual')), (currency, 6, 0))
        self.assertEqual(sum(bill.line_ids.filtered(lambda l: l.account_id == self.revenue).mapped('balance')), -12)
