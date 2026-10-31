from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestContractInvoicePlan(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Contract budget company'})
        cls.unit = cls.env['erp.organization.unit'].create({'name': 'Contract budget OU', 'code': 'CB', 'company_id': cls.company.id})
        cls.user = cls.env['res.users'].create({'name': 'Contract budget reviewer', 'login': 'contract_budget_reviewer', 'company_id': cls.company.id, 'company_ids': [(6, 0, [cls.company.id])], 'group_ids': [(6, 0, [cls.env.ref('erp_contract.group_contract_manager').id, cls.env.ref('account.group_account_invoice').id])]})
        cls.env['erp.organization.assignment'].create({'user_id': cls.user.id, 'unit_id': cls.unit.id})
        group = cls.env['erp.budget.fund.group'].create({'name': 'Contract fund group', 'company_id': cls.company.id})
        cls.fund = cls.env['erp.budget.fund'].create({'name': 'Contract fund', 'group_id': group.id, 'company_id': cls.company.id})
        cls.period = cls.env['erp.budget.period'].create({'name': 'Contract period', 'company_id': cls.company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        plan = cls.env['account.analytic.plan'].create({'name': 'Contract analytics'})
        cls.analytic = cls.env['account.analytic.account'].create({'name': 'Contract analytic', 'plan_id': plan.id, 'company_id': cls.company.id})
        cls.account = cls.env['account.account'].create({'name': 'Contract expense', 'code': 'CNT001', 'account_type': 'expense', 'company_ids': [(6, 0, [cls.company.id])]})
        payable = cls.env['account.account'].create({'name': 'Contract payable', 'code': 'CNTPAY', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, [cls.company.id])]})
        cls.product = cls.env['product.product'].create({'name': 'Contract service', 'type': 'service', 'purchase_ok': True})
        cls.product.with_company(cls.company).product_tmpl_id.property_account_expense_id = cls.account
        cls.vendor = cls.env['res.partner'].create({'name': 'Contract supplier', 'supplier_rank': 1})
        cls.vendor.with_company(cls.company).property_account_payable_id = payable
        cls.journal = cls.env['account.journal'].create({'name': 'Contract purchases', 'code': 'CTST', 'type': 'purchase', 'company_id': cls.company.id})
        vals = {'company_id': cls.company.id, 'period_id': cls.period.id, 'organization_id': cls.unit.id, 'analytic_id': cls.analytic.id, 'amount': 120}
        cls.ac = cls.env['erp.budget.control'].create(dict(vals, name='Contract analytic limit', level='analytic'))
        cls.fc = cls.env['erp.budget.control'].create(dict(vals, name='Contract fund limit', level='fund', fund_id=cls.fund.id))
        (cls.ac | cls.fc).action_open()
        cls.e = cls.env(user=cls.user, context={'allowed_company_ids': [cls.company.id]})

    def make_contract(self):
        contract = self.e['erp.contract.contract'].create({'name': 'Service contract', 'company_id': self.company.id, 'organization_id': self.unit.id, 'partner_id': self.vendor.id, 'journal_id': self.journal.id})
        line = self.e['erp.contract.line'].create({'contract_id': contract.id, 'name': 'Service', 'product_id': self.product.id, 'uom_id': self.product.uom_id.id, 'quantity': 10, 'price_unit': 10, 'date_start': '2026-01-01', 'date_end': '2026-12-31', 'period_id': self.period.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id, 'account_id': self.account.id})
        return contract, line

    def make_bill(self, line, quantity, price, kind='in_invoice', original=None):
        values = {'move_type': kind, 'company_id': self.company.id, 'partner_id': self.vendor.id, 'journal_id': self.journal.id, 'date': fields.Date.today(), 'invoice_date': fields.Date.today(), 'invoice_line_ids': [(0, 0, {'name': 'Contract bill', 'product_id': self.product.id, 'product_uom_id': line.uom_id.id, 'account_id': self.account.id, 'quantity': quantity, 'price_unit': price, 'tax_ids': [(5, 0, 0)], 'erp_contract_line_id': line.id, 'analytic_distribution': {str(self.analytic.id): 100}})]}
        if original:
            values['reversed_entry_id'] = original.id
        return self.e['account.move'].with_company(self.company).create(values)

    def active_amount(self, kind):
        moves = self.env['erp.budget.move'].sudo().search([('control_id', '=', self.ac.id), ('move_type', '=', kind), ('reversal_of_id', '=', False)])
        reversed_ids = self.env['erp.budget.move'].sudo().search([('reversal_of_id', 'in', moves.ids)]).mapped('reversal_of_id').ids
        return sum(moves.filtered(lambda m: m.id not in reversed_ids).mapped('amount'))

    def test_contract_plans_preserve_quantity_and_commitment(self):
        contract, line = self.make_contract()
        contract.action_commit_budget()
        contract.create_invoice_plan(3, '2026-06-01')
        plans = contract.erp_invoice_plan_ids.sorted('installment')
        invoices = self.e['account.move']
        for plan in plans:
            bill = self.e['account.move'].browse(plan.action_create_invoice()['res_id'])
            self.assertEqual(plan.action_create_invoice()['res_id'], bill.id)
            bill.action_post()
            invoices |= bill
        self.assertEqual(sum(invoices.invoice_line_ids.mapped('quantity')), 10)
        self.assertEqual((self.active_amount('actual'), self.active_amount('contract_commitment')), (100, 0))
        with self.assertRaises(UserError), self.cr.savepoint():
            plans[0].percent = 10
        with self.assertRaises(AccessError), self.cr.savepoint():
            invoices[0].erp_contract_invoice_plan_id = plans[1]

    def test_contract_manual_plan_selection_and_scope(self):
        contract, line = self.make_contract()
        contract.erp_plan_manual_selection = True
        contract.create_invoice_plan(2, '2026-06-01')
        contract.action_commit_budget()
        plans = contract.erp_invoice_plan_ids.sorted('installment')
        selected = self.e['erp.contract.invoice.plan.selection'].create({'plan_id': plans[1].id, 'contract_line_id': line.id, 'quantity': 4})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            plans[1].action_create_invoice()
        selected.quantity = 5
        bill = self.e['account.move'].browse(plans[1].action_create_invoice()['res_id'])
        bill.action_post()
        self.assertEqual((bill.amount_total, self.active_amount('actual')), (50, 50))
        with self.assertRaises(UserError), self.cr.savepoint():
            selected.quantity = 6
        bill2 = self.e['account.move'].browse(plans[0].action_create_invoice()['res_id'])
        bill2.action_post()
        self.assertEqual(self.active_amount('actual'), 100)
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        self.assertFalse(self.e['erp.contract.invoice.plan'].search([('id', 'in', plans.ids)]))
        self.assertFalse(self.e['erp.contract.invoice.plan.selection'].search([('id', '=', selected.id)]))

    def test_contract_foreign_currency_plan_uses_native_actuals(self):
        self.company.erp_budget_amount_mode = 'net'
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 1})
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 2})
        self.journal.currency_id = foreign
        contract, line = self.make_contract()
        contract.action_commit_budget()
        contract.create_invoice_plan(2, '2026-06-01')
        self.assertEqual((contract.currency_id, self.active_amount('contract_commitment')), (foreign, 50))
        for plan in contract.erp_invoice_plan_ids.sorted('installment'):
            bill = self.e['account.move'].browse(plan.action_create_invoice()['res_id'])
            self.assertEqual((bill.currency_id, bill.amount_total), (foreign, 50))
            bill.action_post()
        self.assertEqual((self.active_amount('actual'), self.active_amount('contract_commitment')), (50, 0))
