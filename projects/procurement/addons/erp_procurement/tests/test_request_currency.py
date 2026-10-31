from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRequestCurrency(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Procurement Company'})
        cls.unit = cls.env['erp.organization.unit'].create({'name': 'Procurement Unit', 'code': 'PUR', 'company_id': cls.company.id})
        cls.user = cls.env['res.users'].create({'name': 'Procurement Approver', 'login': 'erp_pr_approver', 'company_id': cls.company.id, 'company_ids': [(6, 0, [cls.company.id])], 'group_ids': [(6, 0, [cls.env.ref('erp_procurement.group_procurement_manager').id])]})
        cls.env['erp.organization.assignment'].create({'user_id': cls.user.id, 'unit_id': cls.unit.id})
        cls.env['erp.procurement.tier'].create({'name': 'Standard review', 'company_id': cls.company.id, 'reviewer_id': cls.user.id, 'minimum_amount': 0, 'sequence': 10})
        cls.group = cls.env['erp.budget.fund.group'].create({'name': 'PR group', 'company_id': cls.company.id})
        cls.fund = cls.env['erp.budget.fund'].create({'name': 'PR fund', 'company_id': cls.company.id, 'group_id': cls.group.id})
        cls.period = cls.env['erp.budget.period'].create({'name': 'PR period', 'company_id': cls.company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        plan = cls.env['account.analytic.plan'].create({'name': 'PR plan'})
        cls.analytic = cls.env['account.analytic.account'].create({'name': 'PR analytic', 'plan_id': plan.id, 'company_id': cls.company.id})
        cls.account = cls.env['account.account'].create({'name': 'PR expense', 'code': 'PR100', 'account_type': 'expense', 'company_ids': [(6, 0, [cls.company.id])]})
        cls.product = cls.env['product.product'].create({'name': 'Test service', 'type': 'service', 'purchase_ok': True})
        cls.product.with_company(cls.company).product_tmpl_id.property_account_expense_id = cls.account
        cls.vendor = cls.env['res.partner'].create({'name': 'Test vendor', 'supplier_rank': 1})
        env = cls.env(user=cls.user, context={'allowed_company_ids': [cls.company.id]})
        vals = {'company_id': cls.company.id, 'period_id': cls.period.id, 'organization_id': cls.unit.id, 'analytic_id': cls.analytic.id, 'amount': 100}
        cls.ac = cls.env['erp.budget.control'].create(dict(vals, name='Analytic limit', level='analytic'))
        cls.fc = cls.env['erp.budget.control'].create(dict(vals, name='Fund limit', level='fund', fund_id=cls.fund.id))
        (cls.ac | cls.fc).action_open()
        cls.test_env = env


    def make_request(self, amount):
        request = self.test_env['erp.procurement.request'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'date_start': '2026-06-01'})
        self.test_env['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Requested service', 'product_id': self.product.id, 'product_qty': 1, 'estimated_cost': amount, 'period_id': self.period.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id, 'account_id': self.account.id})
        return request


    def total(self):
        return sum(self.env['erp.budget.move'].search([('control_id', '=', self.ac.id)]).mapped('amount'))


    def make_po(self, request, amount):
        return self.test_env['purchase.order'].create({'company_id': self.company.id, 'partner_id': self.vendor.id, 'date_order': '2026-06-01 12:00:00', 'order_line': [(0, 0, {'name': 'Ordered service', 'product_id': self.product.id, 'product_qty': 1, 'price_unit': amount, 'date_planned': '2026-06-05 12:00:00', 'tax_ids': [(5, 0, 0)], 'erp_request_line_id': request.line_ids.id, 'erp_budget_fund_id': self.fund.id, 'erp_budget_analytic_id': self.analytic.id, 'erp_budget_account_id': self.account.id, 'analytic_distribution': {str(self.analytic.id): 100}})]})


    def foreign(self):
        self.company.erp_budget_amount_mode = 'net'
        currency = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        currency.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 1})
        self.rate = self.env['res.currency.rate'].create({'currency_id': currency.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 2})
        return currency

    def test_pr_currency_threshold_and_frozen_commitment(self):
        currency = self.foreign()
        self.env['erp.procurement.tier'].create({'name': 'Over sixty', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'minimum_amount': 60, 'sequence': 20})
        request = self.make_request(100)
        request.currency_id = currency
        self.assertEqual(request.total_company_currency, 50)
        request.action_submit()
        self.assertEqual(len(request.review_ids), 1)
        self.rate.rate = 4
        request.action_approve()
        self.assertEqual((self.total(), request.total_company_currency), (50, 50))
        with self.assertRaises(UserError), self.cr.savepoint():
            request.currency_id = self.company.currency_id
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.erp_budget_fx_rate = 0.1
        po = self.make_po(request, 40)
        po.button_confirm()
        self.assertEqual(self.total(), 40)
        po.button_cancel()
        self.assertEqual(self.total(), 50)

    def test_manual_rate_requisition_and_po_provenance(self):
        currency = self.foreign()
        request = self.make_request(100)
        request.currency_id = currency
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.erp_budget_manual_rate = .4
        request.sudo().erp_budget_manual_rate = .4
        request.action_submit()
        request.action_approve()
        self.assertEqual(self.total(), 40)
        agreement = self.test_env['purchase.requisition'].browse(request.action_create_requisition()['res_id'])
        self.assertEqual((agreement.currency_id, agreement.erp_budget_manual_rate), (currency, .4))
        agreement.vendor_id = self.vendor
        agreement.action_confirm()
        po = self.test_env['purchase.order'].browse(agreement.action_create_rfq()['res_id'])
        self.assertEqual((po.currency_id, po.erp_budget_manual_rate), (currency, .4))
        po.button_confirm()
        self.assertEqual((po.erp_budget_fx_rate, self.total()), (.4, 40))
        po.button_cancel()
        request.action_reject()
        self.assertEqual(self.total(), 0)

    def test_invalid_rates_budget_failure_and_company_defaults(self):
        currency = self.foreign()
        request = self.make_request(100)
        request.currency_id = currency
        for invalid in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                request.sudo().erp_budget_manual_rate = invalid
        request.sudo().erp_budget_manual_rate = 2
        with self.assertRaisesRegex(UserError, 'Insufficient budget'), self.cr.savepoint():
            request.action_submit()
        self.assertEqual((request.state, request.erp_budget_rate_captured, self.total()), ('draft', False, 0))
        company = self.env['res.company'].create({'name': 'Foreign base request company', 'currency_id': currency.id})
        unit = self.env['erp.organization.unit'].create({'name': 'Foreign base unit', 'code': 'FXB', 'company_id': company.id})
        other = self.env['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id})
        self.assertEqual(other.currency_id, currency)
        self.assertFalse(self.test_env['erp.procurement.request'].search([('id', '=', other.id)]))
