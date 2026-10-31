from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPurchaseInvoicePlan(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Procurement Company'})
        cls.unit = cls.env['erp.organization.unit'].create({'name': 'Procurement Unit', 'code': 'PUR', 'company_id': cls.company.id})
        cls.user = cls.env['res.users'].create({'name': 'Procurement Approver', 'login': 'erp_pr_approver', 'company_id': cls.company.id, 'company_ids': [(6, 0, [cls.company.id])], 'group_ids': [(6, 0, [cls.env.ref('erp_procurement.group_procurement_manager').id])]})
        cls.user.write({'group_ids': [(4, cls.env.ref('account.group_account_invoice').id)]})
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

    def make_po(self, request, amount, date_order='2026-06-01 12:00:00', date_planned='2026-06-05 12:00:00', budget_account=None):
        return self.test_env['purchase.order'].create({'company_id': self.company.id, 'partner_id': self.vendor.id, 'date_order': date_order, 'order_line': [(0, 0, {'name': 'Ordered service', 'product_id': self.product.id, 'product_qty': 1, 'price_unit': amount, 'date_planned': date_planned, 'tax_ids': [(5, 0, 0)], 'erp_request_line_id': request.line_ids.id, 'erp_budget_fund_id': self.fund.id, 'erp_budget_analytic_id': self.analytic.id, 'erp_budget_account_id': (budget_account or self.account).id, 'analytic_distribution': {str(self.analytic.id): 100}})]})

    def make_bill(self, po, quantity, price, kind='in_invoice', reversed_entry=None):
        payable = self.vendor.with_company(self.company).property_account_payable_id
        if not payable:
            payable = self.env['account.account'].create({'name': 'Finance payable', 'code': 'FINPAY', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, [self.company.id])]})
            self.vendor.with_company(self.company).property_account_payable_id = payable
        journal = self.env['account.journal'].search([('code', '=', 'FINT'), ('company_id', '=', self.company.id)], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({'name': 'Finance purchases', 'code': 'FINT', 'type': 'purchase', 'company_id': self.company.id})
        vals = {'move_type': kind, 'company_id': self.company.id, 'partner_id': self.vendor.id, 'journal_id': journal.id, 'invoice_date': fields.Date.today(), 'date': fields.Date.today(), 'invoice_line_ids': [(0, 0, {'name': 'Controlled bill', 'product_id': self.product.id, 'product_uom_id': po.order_line.uom_id.id, 'account_id': self.account.id, 'quantity': quantity, 'price_unit': price, 'tax_ids': [(5, 0, 0)], 'purchase_line_id': po.order_line.id, 'analytic_distribution': {str(self.analytic.id): 100}})]}
        if reversed_entry:
            vals['reversed_entry_id'] = reversed_entry.id
        return self.test_env['account.move'].with_company(self.company).create(vals)

    def active(self, kind):
        moves = self.env['erp.budget.move'].sudo().search([('control_id', '=', self.ac.id), ('move_type', '=', kind), ('reversal_of_id', '=', False)])
        reversed_ids = self.env['erp.budget.move'].sudo().search([('reversal_of_id', 'in', moves.ids)]).mapped('reversal_of_id').ids
        return sum(moves.filtered(lambda m: m.id not in reversed_ids).mapped('amount'))

    def scenario(self):
        self.env.cr.execute('UPDATE erp_budget_control SET amount=120 WHERE id IN %s', [tuple((self.ac | self.fc).ids)])
        (self.ac | self.fc).invalidate_recordset(['amount'])
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.order_line.product_qty = 10
        po.button_confirm()
        return request, po


    def planned_order(self):
        request, po = self.scenario()
        self.make_bill(po, 1, 1).unlink()  # Configure native purchase journal/payable.
        self.product.purchase_method = 'purchase'
        po.create_invoice_plan(3, '2026-06-01', 1, 'month')
        return request, po

    def test_purchase_plans_rounding_idempotency_and_budget(self):
        request, po = self.planned_order()
        plans = po.erp_invoice_plan_ids.sorted('installment')
        self.assertAlmostEqual(sum(plans.mapped('percent')), 100)
        self.assertEqual(str(plans[-1].plan_date), '2026-08-01')
        with self.assertRaises(UserError), self.cr.savepoint():
            plans[1].action_create_invoice()
        moves = self.test_env['account.move']
        for plan in plans:
            move = self.test_env['account.move'].browse(plan.action_create_invoice()['res_id'])
            self.assertEqual(plan.action_create_invoice()['res_id'], move.id)
            move.action_post()
            moves |= move
        self.assertEqual(sum(moves.invoice_line_ids.mapped('quantity')), 10)
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (100, 0))
        self.assertEqual(sum(plans.mapped('amount')), 100)
        with self.assertRaises(UserError), self.cr.savepoint():
            po.create_invoice_plan(2, '2026-06-01')
        with self.assertRaises(AccessError), self.cr.savepoint():
            moves[0].erp_purchase_invoice_plan_id = plans[1]
        moves[-1].button_draft()
        moves[-1].button_cancel()
        replacement = self.test_env['account.move'].browse(plans[-1].action_create_invoice()['res_id'])
        self.assertNotEqual(replacement, moves[-1])
        replacement.action_post()
        self.assertEqual(self.active('actual'), 100)
        self.assertEqual(len(plans[-1].invoice_ids), 2)

    def test_planned_deposit_deduction_and_retention_terms(self):
        request, po = self.planned_order()
        po.create_invoice_plan(2, '2026-07-01')
        po.write({'erp_payment_retention': 'percent', 'erp_retention_value': 10})
        deposit_plan = self.test_env['erp.procurement.invoice.plan'].create({'purchase_id': po.id, 'invoice_type': 'advance', 'installment': 0, 'percent': 30, 'plan_date': '2026-06-01', 'deposit_origin_id': po.order_line.id})
        deposit = self.test_env['account.move'].browse(deposit_plan.action_create_invoice()['res_id'])
        deposit.action_post()
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (30, 70))
        regular = po.erp_invoice_plan_ids.filtered(lambda p: p.invoice_type == 'installment').sorted('installment')
        for index, plan in enumerate(regular):
            bill = self.test_env['account.move'].browse(plan.action_create_invoice()['res_id'])
            self.assertEqual(bill.amount_untaxed, 35)
            self.assertEqual(bill.erp_retention_amount, 5)  # Positive work base excludes deposit deduction.
            bill.action_post()
            self.assertEqual(self.active('actual'), 65 if index == 0 else 100)
        self.assertEqual(sum(regular.mapped('amount')), 100)
        self.assertEqual(self.active('po_commitment'), 0)

    def test_purchase_plan_receipt_scope_and_rpc(self):
        request, po = self.planned_order()
        self.product.purchase_method = 'receive'
        plan = po.erp_invoice_plan_ids.sorted('installment')[0]
        with self.assertRaises(ValidationError), self.cr.savepoint():
            plan.action_create_invoice()
        other = self.env['res.company'].create({'name': 'Foreign plan company'})
        self.user.company_ids = [(4, other.id)]
        self.assertFalse(plan.with_context(allowed_company_ids=other.ids).search([('id', '=', plan.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['account.move'].with_context(default_erp_purchase_invoice_plan_id=plan.id).create({'move_type': 'in_invoice'})
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        self.assertFalse(self.test_env['erp.procurement.invoice.plan'].search([('id', '=', plan.id)]))
