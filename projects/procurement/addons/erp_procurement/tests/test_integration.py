from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProcurementBudget(TransactionCase):
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

    def test_check_approval_po_replacement_and_restore(self):
        request = self.make_request(30)
        request.action_submit()
        self.assertEqual(request.state, 'to_approve')
        self.assertEqual(self.total(), 0)
        request.action_approve()
        request.action_approve()
        self.assertEqual(self.total(), 30)
        po = self.make_po(request, 50)
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        self.assertEqual(self.total(), 50)
        po.button_cancel()
        self.assertEqual(self.total(), 30)
        request.action_reject()
        request.action_reject()
        self.assertEqual(self.total(), 0)

    def test_insufficient_and_multiline_atomic(self):
        first = self.make_request(80)
        first.action_submit()
        first.action_approve()
        request = self.make_request(30)
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_submit()
        self.assertEqual(request.state, 'draft')
        self.assertEqual(self.total(), 80)
        first.action_reject()
        request.line_ids.estimated_cost = 60
        self.test_env['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Second', 'product_qty': 1, 'estimated_cost': 50, 'period_id': self.period.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id, 'account_id': self.account.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_submit()
        self.assertEqual(request.state, 'draft')
        self.assertEqual(self.total(), 0)

    def test_company_and_organization_access(self):
        outsider = self.env['res.users'].create({'name': 'Other procurement user', 'login': 'erp_pr_outsider', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_procurement.group_procurement_user').id, self.env.ref('purchase.group_purchase_user').id])]})
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 50)
        other_env = self.env(user=outsider, context={'allowed_company_ids': [self.company.id]})
        self.assertFalse(other_env['erp.procurement.request'].search([('id', '=', request.id)]))
        self.assertFalse(other_env['purchase.order'].search([('id', '=', po.id)]))
        self.assertFalse(other_env['purchase.order.line'].search([('id', 'in', po.order_line.ids)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            other_env['purchase.order'].browse(po.id).write({'partner_ref': 'Forbidden'})
        self.assertEqual(other_env['res.partner'].browse(self.vendor.id).name, 'Test vendor')
        unrelated = self.test_env['purchase.order'].create({'company_id': self.company.id, 'partner_id': self.vendor.id, 'date_order': '2026-06-01 12:00:00'})
        self.assertEqual(other_env['purchase.order'].search([('id', '=', unrelated.id)]).id, unrelated.id)

    def test_approval_requires_capability_and_other_dimensions_rejected(self):
        reader = self.env['res.users'].create({'name': 'Requester', 'login': 'erp_pr_reader', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_procurement.group_procurement_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reader.id, 'unit_id': self.unit.id})
        request = self.make_request(30)
        request.action_submit()
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.with_user(reader).action_approve()
        request.action_approve()
        other_fund = self.env['erp.budget.fund'].create({'name': 'Other fund', 'company_id': self.company.id, 'group_id': self.group.id})
        po = self.make_po(request, 50)
        po.order_line.write({'erp_budget_fund_id': other_fund.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            po.button_confirm()
        self.assertEqual(self.total(), 30)

    def test_sequential_tiers_and_retry(self):
        reviewer = self.env['res.users'].create({'name': 'Second reviewer', 'login': 'erp_pr_second', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_procurement.group_procurement_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.procurement.tier'].create({'name': 'Second tier', 'company_id': self.company.id, 'reviewer_id': reviewer.id, 'minimum_amount': 20, 'sequence': 20})
        request = self.make_request(30)
        request.action_submit()
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.with_user(reviewer).action_approve()
        request.action_approve()
        request.action_approve()
        self.assertEqual(request.state, 'to_approve')
        self.assertEqual(self.total(), 0)
        request.with_user(reviewer).action_approve()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(self.total(), 30)

    def test_linked_order_state_cannot_be_written_directly(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 50)
        with self.assertRaises(AccessError), self.cr.savepoint():
            po.write({'state': 'purchase'})
        self.assertEqual(po.state, 'draft')
        self.assertEqual(self.total(), 30)
        po.button_confirm()
        self.assertEqual(self.total(), 50)

    def test_po_insufficient_does_not_advance(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 120)
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_confirm()
        self.assertEqual(po.state, 'draft')
        self.assertEqual(self.total(), 30)

    def test_cross_company_request_rejected(self):
        company_b = self.env['res.company'].create({'name': 'Other PR company'})
        unit_b = self.env['erp.organization.unit'].create({'name': 'Other PR unit', 'code': 'PRB', 'company_id': company_b.id})
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            self.test_env['erp.procurement.request'].create({'company_id': self.company.id, 'organization_id': unit_b.id})

    def test_pending_reviewer_can_reject_without_purchase_role(self):
        reviewer = self.env['res.users'].create({'name': 'Reject reviewer', 'login': 'erp_pr_rejector', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_procurement.group_procurement_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.procurement.tier'].search([('company_id', '=', self.company.id)]).write({'reviewer_id': reviewer.id})
        request = self.make_request(30)
        request.action_submit()
        request.with_user(reviewer).action_reject()
        self.assertEqual(request.state, 'rejected')
        self.assertEqual(self.total(), 0)

    def test_multiline_approval_is_atomic_if_budget_changes(self):
        request = self.make_request(40)
        self.test_env['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Second line', 'product_qty': 1, 'estimated_cost': 40, 'period_id': self.period.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id, 'account_id': self.account.id})
        request.action_submit()
        other = self.make_request(30)
        other.action_submit()
        other.action_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_approve()
        self.assertEqual(request.state, 'to_approve')
        self.assertEqual(request.review_ids.state, 'pending')
        self.assertEqual(self.total(), 30)

    def test_po_different_fund_and_cancellation(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        other_fund = self.env['erp.budget.fund'].create({'name': 'PO alternate fund', 'company_id': self.company.id, 'group_id': self.group.id})
        control = self.env['erp.budget.control'].create({'name': 'Alternate fund limit', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 70, 'level': 'fund', 'fund_id': other_fund.id})
        control.action_open()
        po = self.make_po(request, 50)
        po.order_line.write({'erp_budget_fund_id': other_fund.id})
        po.button_confirm()
        self.assertEqual(self.total(), 50)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', self.fc.id)]).mapped('amount')), 0)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', control.id)]).mapped('amount')), 50)
        po.button_cancel()
        self.assertEqual(self.total(), 30)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', self.fc.id)]).mapped('amount')), 30)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', control.id)]).mapped('amount')), 0)

    def test_other_fund_insufficient_preserves_pr_commitment(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        other_fund = self.env['erp.budget.fund'].create({'name': 'Insufficient alternate', 'company_id': self.company.id, 'group_id': self.group.id})
        control = self.env['erp.budget.control'].create({'name': 'Insufficient alternate limit', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 40, 'level': 'fund', 'fund_id': other_fund.id})
        control.action_open()
        po = self.make_po(request, 50)
        po.order_line.write({'erp_budget_fund_id': other_fund.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_confirm()
        self.assertEqual(po.state, 'draft')
        self.assertEqual(self.total(), 30)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', self.fc.id)]).mapped('amount')), 30)
        self.assertFalse(self.env['erp.budget.move'].search([('control_id', '=', control.id)]))

    def test_po_different_analytic_and_cancellation(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        other_analytic = self.env['account.analytic.account'].create({'name': 'PO analytic', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        base = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': other_analytic.id, 'amount': 100}
        analytic_control = self.env['erp.budget.control'].create(dict(base, name='PO analytic limit', level='analytic'))
        fund_control = self.env['erp.budget.control'].create(dict(base, name='PO analytic fund limit', level='fund', fund_id=self.fund.id))
        (analytic_control | fund_control).action_open()
        po = self.make_po(request, 50)
        po.order_line.write({'erp_budget_analytic_id': other_analytic.id, 'analytic_distribution': {str(other_analytic.id): 100}})
        po.button_confirm()
        self.assertEqual(self.total(), 0)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', analytic_control.id)]).mapped('amount')), 50)
        po.button_cancel()
        self.assertEqual(self.total(), 30)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', analytic_control.id)]).mapped('amount')), 0)

    def test_po_different_dimension_and_cancellation(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        plan = self.env['account.analytic.plan'].create({'name': 'PO dimension'})
        dimension = self.env['account.analytic.account'].create({'name': 'PO dimension value', 'plan_id': plan.id, 'company_id': self.company.id})
        alternate = self.env['erp.budget.control'].create({'name': 'Dimension limit', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 100, 'level': 'fund', 'fund_id': self.fund.id, 'dimension_ids': [(6, 0, [dimension.id])]})
        alternate.action_open()
        po = self.make_po(request, 50)
        key = ','.join(map(str, sorted([self.analytic.id, dimension.id])))
        po.order_line.write({'erp_budget_dimension_ids': [(6, 0, [dimension.id])], 'analytic_distribution': {key: 100}})
        po.button_confirm()
        self.assertEqual(self.total(), 50)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', self.fc.id)]).mapped('amount')), 0)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', alternate.id)]).mapped('amount')), 50)
        po.button_cancel()
        self.assertEqual(self.total(), 30)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', alternate.id)]).mapped('amount')), 0)

    def test_po_different_account_and_kpi(self):
        kpi_a = self.env['erp.budget.kpi'].create({'name': 'PR KPI', 'company_id': self.company.id})
        kpi_b = self.env['erp.budget.kpi'].create({'name': 'PO KPI', 'company_id': self.company.id})
        account_b = self.env['account.account'].create({'name': 'PO expense', 'code': 'PR200', 'account_type': 'expense', 'company_ids': [(6, 0, [self.company.id])]})
        product_b = self.env['product.product'].create({'name': 'Other PO service', 'type': 'service', 'purchase_ok': True})
        product_b.with_company(self.company).product_tmpl_id.property_account_expense_id = account_b
        template = self.env['erp.budget.template'].create({'name': 'PR and PO KPI', 'company_id': self.company.id})
        self.env['erp.budget.template.line'].create([{'template_id': template.id, 'account_id': self.account.id, 'kpi_id': kpi_a.id}, {'template_id': template.id, 'account_id': account_b.id, 'kpi_id': kpi_b.id}])
        self.period.template_id = template
        self.ac.action_close()
        base = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 100, 'level': 'analytic'}
        a = self.env['erp.budget.control'].create(dict(base, name='PR KPI limit', kpi_id=kpi_a.id))
        b = self.env['erp.budget.control'].create(dict(base, name='PO KPI limit', kpi_id=kpi_b.id))
        (a | b).action_open()
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 50)
        po.order_line.write({'product_id': product_b.id, 'erp_budget_account_id': account_b.id, 'price_unit': 50})
        po.button_confirm()
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', a.id)]).mapped('amount')), 0)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', b.id)]).mapped('amount')), 50)
        po.button_cancel()
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', a.id)]).mapped('amount')), 30)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', b.id)]).mapped('amount')), 0)

    def test_po_cancel_draft_amend_and_reconfirm(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 50)
        po.button_confirm()
        self.assertEqual(self.total(), 50)
        po.button_cancel()
        self.assertEqual(self.total(), 30)
        po.button_draft()
        po.order_line.write({'price_unit': 70})
        po.button_confirm()
        self.assertEqual(self.total(), 70)
        po.button_cancel()
        self.assertEqual(self.total(), 30)

    def test_multiple_pos_with_different_funds(self):
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        alternate_fund = self.env['erp.budget.fund'].create({'name': 'Second PO fund', 'company_id': self.company.id, 'group_id': self.group.id})
        alternate = self.env['erp.budget.control'].create({'name': 'Second PO fund limit', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 100, 'level': 'fund', 'fund_id': alternate_fund.id})
        alternate.action_open()
        po1 = self.make_po(request, 40)
        po2 = self.make_po(request, 60)
        po2.order_line.write({'erp_budget_fund_id': alternate_fund.id})
        def total(control):
            return sum(self.env['erp.budget.move'].search([('control_id', '=', control.id)]).mapped('amount'))
        po1.button_confirm()
        po2.button_confirm()
        self.assertEqual((total(self.ac), total(self.fc), total(alternate)), (100, 40, 60))
        po1.button_cancel()
        self.assertEqual((total(self.ac), total(self.fc), total(alternate)), (60, 0, 60))
        po2.button_cancel()
        self.assertEqual((total(self.ac), total(self.fc), total(alternate)), (100, 100, 0))

    def test_vendor_bill_posting_fails_closed_until_finance_integration(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 50)
        po.button_confirm()
        payable = self.env['account.account'].create({'name': 'Payable test', 'code': 'PTPAY', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, [self.company.id])]})
        self.vendor.with_company(self.company).property_account_payable_id = payable
        journal = self.env['account.journal'].create({'name': 'Purchase test', 'code': 'PTST', 'type': 'purchase', 'company_id': self.company.id})
        bill = self.env['account.move'].with_company(self.company).create({'move_type': 'in_invoice', 'company_id': self.company.id, 'partner_id': self.vendor.id, 'journal_id': journal.id, 'invoice_line_ids': [(0, 0, {'name': 'Linked bill line', 'account_id': self.account.id, 'quantity': 1, 'price_unit': 50, 'purchase_line_id': po.order_line.id})]})
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.write({'state': 'posted'})
        self.assertEqual(bill.state, 'draft')
        self.assertEqual(self.total(), 50)
        unrelated = self.env['account.move'].with_company(self.company).create({'move_type': 'in_invoice', 'company_id': self.company.id, 'partner_id': self.vendor.id, 'journal_id': journal.id, 'invoice_date': fields.Date.today(), 'invoice_line_ids': [(0, 0, {'name': 'Unrelated bill line', 'account_id': self.account.id, 'quantity': 1, 'price_unit': 10})]})
        unrelated.action_post()
        self.assertEqual(unrelated.state, 'posted')

    def test_multi_po(self):
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        po1 = self.make_po(request, 40)
        po2 = self.make_po(request, 60)
        po1.button_confirm()
        self.assertEqual(self.total(), 40)
        po2.button_confirm()
        self.assertEqual(self.total(), 100)
        po1.button_cancel()
        self.assertEqual(self.total(), 60)
        po2.button_cancel()
        self.assertEqual(self.total(), 100)

    def test_native_requisition_preserves_single_budget_authority(self):
        request = self.make_request(50)
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_create_requisition()
        request.action_submit()
        request.action_approve()
        action = request.action_create_requisition()
        requisition = self.test_env['purchase.requisition'].browse(action['res_id'])
        self.assertEqual(request.action_create_requisition()['res_id'], requisition.id)
        self.assertEqual(self.total(), 50)
        self.assertEqual((requisition.erp_organization_id, requisition.line_ids.erp_request_line_id), (self.unit, request.line_ids))
        requisition.vendor_id = self.vendor
        requisition.action_confirm()
        action = requisition.action_create_rfq()
        po = self.test_env['purchase.order'].browse(action['res_id'])
        self.assertEqual(requisition.action_create_rfq()['res_id'], po.id)
        self.assertEqual((po.order_line.erp_request_line_id, po.order_line.erp_requisition_line_id), (request.line_ids, requisition.line_ids))
        po.order_line.price_unit = 70
        po.button_confirm()
        self.assertEqual((self.total(), po.state), (70, 'purchase'))
        po.button_cancel()
        self.assertEqual(self.total(), 50)
        self.assertEqual(request.state, 'approved')

    def test_requisition_scope_and_source_forgery(self):
        request = self.make_request(50)
        request.action_submit()
        request.action_approve()
        requisition = self.test_env['purchase.requisition'].browse(request.action_create_requisition()['res_id'])
        other = self.env['res.company'].create({'name': 'Other requisition company'})
        self.user.company_ids = [(4, other.id)]
        foreign_env = self.env(user=self.user, context={'allowed_company_ids': other.ids})
        self.assertFalse(foreign_env['purchase.requisition'].search([('id', '=', requisition.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            requisition.with_env(foreign_env).action_confirm()
        with self.assertRaises(UserError), self.cr.savepoint():
            requisition.write({'erp_organization_id': False})
        requisition.vendor_id = self.vendor
        requisition.action_confirm()
        po = self.test_env['purchase.order'].browse(requisition.action_create_rfq()['res_id'])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            po.order_line.erp_request_line_id = False
        requisition.action_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_confirm()
        self.assertEqual(self.total(), 50)
