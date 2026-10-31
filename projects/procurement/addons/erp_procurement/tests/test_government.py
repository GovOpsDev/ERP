from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGovernmentProcurement(TransactionCase):
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



    def government_type(self, route='purchase_agreement'):
        method = self.test_env['erp.procurement.method'].create({'name': 'Specific selection', 'company_id': self.company.id})
        kind = self.test_env['erp.procurement.purchase.type'].create({'name': 'Government purchase', 'company_id': self.company.id, 'to_create': route, 'method_ids': [(6, 0, method.ids)]})
        return kind, method

    def reviewer(self):
        user = self.env['res.users'].create({'name': 'Second reviewer', 'login': 'gov_second_review', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, [self.env.ref('erp_procurement.group_procurement_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': self.unit.id})
        return user

    def test_done_reset_retains_reviews_terms_and_commitment(self):
        request = self.make_request(80)
        request.action_submit()
        request.action_approve()
        old = request.review_ids
        request.action_done()
        self.assertEqual((request.state, self.total()), ('done', 80))
        request.line_ids._reconcile_budget(pr_eligible=request._is_budget_approved())
        self.assertEqual(self.total(), 80)
        request.action_reset()
        self.assertEqual((request.state, self.total(), old.state, old.decided_by_id), ('draft', 0, 'approved', self.user))
        request.line_ids.estimated_cost = 50
        request.action_submit()
        self.assertEqual(request.review_round, 2)
        request.action_reject()
        request.action_reset()
        request.action_submit()
        request.action_approve()
        self.assertEqual((request.review_round, len(request.review_ids), self.total()), (3, 3, 50))
        self.assertEqual(old.request_snapshot['lines'][0]['estimate'], 80)
        with self.assertRaises(AccessError), self.cr.savepoint():
            old.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.with_context(default_review_round=44).copy()
        po = self.make_po(request, 50)
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_reset()
        po.button_confirm()
        request.action_done()
        po.button_cancel()
        self.assertEqual(self.total(), 50)
        request.action_reset()
        self.assertEqual(self.total(), 0)

    def test_government_verification_method_committee_and_route(self):
        kind, method = self.government_type()
        request = self.make_request(50)
        request.write({'purchase_type_id': kind.id, 'procurement_method_id': method.id})
        member = self.test_env['erp.procurement.committee'].create({'request_id': request.id, 'name': 'External committee member', 'kind': 'work_acceptance', 'approve_role': 'chairman'})
        request.action_submit()
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_approve()
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.write({'verified_by_id': self.user.id})
        request.action_verify()
        request.action_approve()
        self.assertEqual((request.verified_by_id, request.approved_by_id), (self.user, self.user))
        review = request._current_reviews()
        with self.assertRaises(UserError), self.cr.savepoint():
            member.name = 'Different member'
        with self.assertRaises(UserError), self.cr.savepoint():
            kind.to_create = 'expense'
        request.action_reset()
        self.assertFalse(request.verified_by_id)
        self.assertEqual(review.verified_by_id, self.user)
        self.assertEqual(review.request_snapshot['committees'][0]['name'], member.name)
        expense_type, expense_method = self.government_type('expense')
        request.write({'purchase_type_id': expense_type.id, 'procurement_method_id': expense_method.id})
        request.action_submit()
        request.action_verify()
        request.action_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_create_requisition()
        wrong = self.test_env['erp.procurement.method'].create({'name': 'Unlisted method', 'company_id': self.company.id})
        request.action_reset()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            request.procurement_method_id = wrong

    def test_purchase_ordered_tiers_reject_reset_and_no_force_bypass(self):
        second = self.reviewer()
        self.test_env['erp.procurement.tier'].create([{'name': 'PO first', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'kind': 'purchase', 'sequence': 10}, {'name': 'PO second', 'company_id': self.company.id, 'reviewer_id': second.id, 'kind': 'purchase', 'sequence': 20}])
        request = self.make_request(80)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 50)
        po.button_confirm()
        self.assertEqual((po.state, po.erp_review_status, self.total()), ('draft', 'pending', 80))
        with self.assertRaises(AccessError), self.cr.savepoint():
            po.button_approve(force=True)
        with self.assertRaises(AccessError), self.cr.savepoint():
            po.with_user(second).action_approve_tier()
        with self.assertRaises(UserError), self.cr.savepoint():
            po.order_line.price_unit = 70
        po.action_approve_tier()
        po.action_approve_tier()
        po.with_user(second).action_reject_tier()
        po.action_reset_tier_review()
        po.order_line.price_unit = 60
        po.button_confirm()
        po.action_approve_tier()
        po.with_user(second).action_approve_tier()
        self.assertEqual((po.state, po.erp_review_status, len(po.erp_review_ids), self.total()), ('purchase', 'approved', 4, 60))
        with self.assertRaises(AccessError), self.cr.savepoint():
            po.erp_review_ids.sudo().write({'state': 'approved'})
        po.button_cancel()
        po.button_draft()
        po.button_confirm()
        self.assertEqual((po.state, len(po.erp_review_ids), self.total()), ('draft', 6, 80))

    def test_review_company_unit_and_default_state_guards(self):
        request = self.make_request(30)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['erp.procurement.request'].with_context(default_state='approved').create({'organization_id': self.unit.id})
        second = self.reviewer()
        self.env['erp.organization.assignment'].search([('user_id', '=', second.id)]).unlink()
        self.env['erp.procurement.tier'].create({'name': 'Unavailable reviewer', 'company_id': self.company.id, 'reviewer_id': second.id, 'sequence': 20})
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.action_submit()
        self.assertFalse(request.review_ids)
        kind, method = self.government_type()
        company = self.env['res.company'].create({'name': 'Other government company'})
        foreign = self.env['erp.procurement.method'].create({'name': 'Other company method', 'company_id': company.id})
        with self.assertRaises((AccessError, UserError, ValidationError)), self.cr.savepoint():
            kind.method_ids = foreign

    def test_final_purchase_review_capacity_and_revoked_scope_are_atomic(self):
        second = self.reviewer()
        self.test_env['erp.procurement.tier'].create({'name': 'PO reviewer', 'company_id': self.company.id, 'reviewer_id': second.id, 'kind': 'purchase'})
        request = self.make_request(80)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 110)
        po.button_confirm()
        with self.assertRaises(UserError), self.cr.savepoint():
            po.with_user(second).action_approve_tier()
        self.assertEqual((po.state, po.erp_review_status, self.total()), ('draft', 'pending', 80))
        self.assertFalse(po.erp_review_ids.decided_at)
        po.action_reset_tier_review()
        po.order_line.price_unit = 60
        po.button_confirm()
        assignment = self.env['erp.organization.assignment'].search([('user_id', '=', second.id)])
        assignment.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            po.with_user(second).action_approve_tier()
        self.assertEqual((po.state, po.erp_review_status, self.total()), ('draft', 'pending', 80))
        self.env['erp.organization.assignment'].create({'user_id': second.id, 'unit_id': self.unit.id})
        po.with_user(second).action_approve_tier()
        self.assertEqual((po.state, self.total()), ('purchase', 60))

    def test_same_reviewer_can_decide_later_purchase_tier(self):
        self.test_env['erp.procurement.tier'].create([{'name': 'PO first', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'kind': 'purchase', 'sequence': 10}, {'name': 'PO second', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'kind': 'purchase', 'sequence': 20}])
        request = self.make_request(80)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 60)
        po.button_confirm()
        po.action_approve_tier()
        self.assertEqual(po.state, 'draft')
        po.action_approve_tier()
        po.action_approve_tier()
        self.assertEqual((po.state, self.total()), ('purchase', 60))
