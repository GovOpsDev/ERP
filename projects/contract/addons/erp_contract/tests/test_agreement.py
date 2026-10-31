from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPurchaseAgreement(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Procurement Company'})
        cls.unit = cls.env['erp.organization.unit'].create({'name': 'Procurement Unit', 'code': 'PUR', 'company_id': cls.company.id})
        cls.user = cls.env['res.users'].create({'name': 'Procurement Approver', 'login': 'erp_pr_approver', 'company_id': cls.company.id, 'company_ids': [(6, 0, [cls.company.id])], 'group_ids': [(6, 0, [cls.env.ref('erp_procurement.group_procurement_manager').id])]})
        cls.user.write({'group_ids': [(4, cls.env.ref('account.group_account_invoice').id), (4, cls.env.ref('erp_contract.group_contract_manager').id)]})
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

    def make_agreement(self, po, **extra):
        values = {'name': 'Purchase agreement', 'company_id': self.company.id, 'organization_id': self.unit.id, 'partner_id': self.vendor.id, 'purchase_order_id': po.id, 'start_date': '2026-01-01', 'end_date': '2026-12-31', 'signature_date': fields.Date.today()}
        values.update(extra)
        return self.test_env['erp.contract.agreement'].create(values)

    def prepare_po(self, pr_amount=30, po_amount=50):
        request = self.make_request(pr_amount)
        request.action_submit()
        request.action_approve()
        return request, self.make_po(request, po_amount)

    def test_real_request_po_agreement_bill_and_termination(self):
        request, po = self.prepare_po()
        po.erp_agreement_required = True
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_confirm()
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_approve()
        first = self.make_agreement(po)
        second = self.make_agreement(po, name='Additional agreement')
        self.assertNotEqual(first.code, second.code)
        first.action_activate()
        self.assertEqual(first.state, 'active')
        self.assertEqual(len(po.erp_agreement_ids), 2)
        po.button_confirm()
        self.assertEqual(self.active('pr_commitment'), 0)
        self.assertEqual(self.active('po_commitment'), 50)
        bill = self.make_bill(po, 0.4, 50)
        bill.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (30, 20))
        before = self.env['erp.budget.move'].sudo().search_count([])
        first.action_terminate()
        self.assertEqual(first.state, 'inactive')
        self.assertEqual(po.state, 'purchase')
        self.assertEqual(self.env['erp.budget.move'].sudo().search_count([]), before)
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (30, 20))

    def test_versions_and_expiration(self):
        request, po = self.prepare_po()
        agreement = self.make_agreement(po)
        agreement.action_activate()
        with self.assertRaises(UserError), self.cr.savepoint():
            po.order_line.price_unit = 60
        agreement.action_new_version()
        po.order_line.price_unit = 60
        self.assertEqual(agreement.amount_untaxed, 60)
        self.assertEqual((agreement.version, agreement.state, len(agreement.revision_ids)), (2, 'draft', 1))
        old = agreement.revision_ids
        self.assertEqual((old.version, old.amount_untaxed), (1, 50))
        agreement.write({'end_date': '2027-12-31', 'signature_date': fields.Date.today()})
        agreement.action_activate()
        self.assertEqual(old.end_date, fields.Date.from_string('2026-12-31'))
        with self.assertRaises(AccessError), self.cr.savepoint():
            old.write({'name': 'tampered'})
        expired = self.make_agreement(po, end_date='2020-12-31', start_date='2020-01-01')
        self.assertTrue(expired.is_expired)
        with self.assertRaises(UserError), self.cr.savepoint():
            expired.action_activate()

    def test_company_partner_and_organization_enforced(self):
        request, po = self.prepare_po()
        other_company = self.env['res.company'].create({'name': 'Other agreement company'})
        other_unit = self.env['erp.organization.unit'].create({'name': 'Other agreement OU', 'code': 'OTH', 'company_id': self.company.id})
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': other_unit.id})
        with self.assertRaises((ValidationError, AccessError, UserError)), self.cr.savepoint():
            self.make_agreement(po, company_id=other_company.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.make_agreement(po, organization_id=other_unit.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.make_agreement(po, partner_id=self.env['res.partner'].create({'name': 'Other vendor'}).id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.make_agreement(po, start_date='2026-12-01', end_date='2026-01-01')
        agreement = self.make_agreement(po)
        outsider = self.env['res.users'].create({'name': 'Other OU agreement user', 'login': 'contract_other_unit', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_contract.group_contract_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': outsider.id, 'unit_id': other_unit.id})
        self.assertFalse(self.env['erp.contract.agreement'].with_user(outsider).with_context(allowed_company_ids=[self.company.id]).search([('id', '=', agreement.id)]))
        self.assertTrue(self.env['res.partner'].with_user(outsider).browse(self.vendor.id).name)

    def test_authorization_and_source_identity(self):
        request, po = self.prepare_po()
        agreement = self.make_agreement(po)
        nonmanager = self.env['res.users'].create({'name': 'Agreement user', 'login': 'contract_user_only', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_contract.group_contract_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': nonmanager.id, 'unit_id': self.unit.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            agreement.with_user(nonmanager).action_activate()
        with self.assertRaises(AccessError), self.cr.savepoint():
            agreement.write({'state': 'active'})
        with self.assertRaises(UserError), self.cr.savepoint():
            po.write({'partner_id': self.env['res.partner'].create({'name': 'Different vendor'}).id})
        with self.assertRaises(UserError), self.cr.savepoint():
            po.order_line.write({'erp_request_line_id': False})
        po.button_confirm()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.make_agreement(po)

    def test_multi_company_switch_hides_other_company_agreements(self):
        request_a, po_a = self.prepare_po()
        agreement_a = self.make_agreement(po_a)
        company_b = self.env['res.company'].create({'name': 'Agreement second company'})
        unit_b = self.env['erp.organization.unit'].create({'name': 'Agreement second OU', 'code': 'ACB', 'company_id': company_b.id})
        self.user.write({'company_ids': [(4, company_b.id)]})
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': unit_b.id})
        self.env['erp.procurement.tier'].create({'name': 'Company B reviewer', 'company_id': company_b.id, 'reviewer_id': self.user.id})
        group_b = self.env['erp.budget.fund.group'].create({'name': 'Company B fund group', 'company_id': company_b.id})
        fund_b = self.env['erp.budget.fund'].create({'name': 'Company B fund', 'company_id': company_b.id, 'group_id': group_b.id})
        period_b = self.env['erp.budget.period'].create({'name': 'Company B period', 'company_id': company_b.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        plan_b = self.env['account.analytic.plan'].create({'name': 'Company B analytic plan'})
        analytic_b = self.env['account.analytic.account'].create({'name': 'Company B analytic', 'plan_id': plan_b.id, 'company_id': company_b.id})
        account_b = self.env['account.account'].create({'name': 'Company B expense', 'code': 'CBEXP', 'account_type': 'expense', 'company_ids': [(6, 0, [company_b.id])]})
        product_b = self.env['product.product'].create({'name': 'Company B service', 'type': 'service', 'purchase_ok': True})
        product_b.with_company(company_b).product_tmpl_id.property_account_expense_id = account_b
        vals = {'company_id': company_b.id, 'period_id': period_b.id, 'organization_id': unit_b.id, 'analytic_id': analytic_b.id, 'amount': 100}
        controls = self.env['erp.budget.control'].create([dict(vals, name='B analytic control', level='analytic'), dict(vals, name='B fund control', level='fund', fund_id=fund_b.id)])
        controls.action_open()
        e_b = self.env(user=self.user, context={'allowed_company_ids': [company_b.id]})
        request_b = e_b['erp.procurement.request'].create({'company_id': company_b.id, 'organization_id': unit_b.id, 'date_start': '2026-06-01'})
        e_b['erp.procurement.request.line'].create({'request_id': request_b.id, 'name': 'B request', 'product_id': product_b.id, 'product_qty': 1, 'estimated_cost': 25, 'period_id': period_b.id, 'fund_id': fund_b.id, 'analytic_id': analytic_b.id, 'account_id': account_b.id})
        request_b.action_submit()
        request_b.action_approve()
        po_b = e_b['purchase.order'].create({'company_id': company_b.id, 'partner_id': self.vendor.id, 'date_order': '2026-06-01 12:00:00', 'order_line': [(0, 0, {'name': 'B order', 'product_id': product_b.id, 'product_qty': 1, 'price_unit': 25, 'date_planned': '2026-06-05 12:00:00', 'tax_ids': [(5, 0, 0)], 'erp_request_line_id': request_b.line_ids.id, 'erp_budget_fund_id': fund_b.id, 'erp_budget_analytic_id': analytic_b.id, 'erp_budget_account_id': account_b.id, 'analytic_distribution': {str(analytic_b.id): 100}})]})
        agreement_b = e_b['erp.contract.agreement'].create({'name': 'Company B agreement', 'company_id': company_b.id, 'organization_id': unit_b.id, 'partner_id': self.vendor.id, 'purchase_order_id': po_b.id, 'start_date': '2026-01-01', 'end_date': '2026-12-31'})
        self.assertEqual(self.test_env['erp.contract.agreement'].search([('id', 'in', [agreement_a.id, agreement_b.id])]).ids, [agreement_a.id])
        self.assertEqual(e_b['erp.contract.agreement'].search([('id', 'in', [agreement_a.id, agreement_b.id])]).ids, [agreement_b.id])

    def test_government_requisition_type_activates_agreement_gate(self):
        request = self.make_request(50)
        request.action_submit()
        request.action_approve()
        requisition = self.test_env['purchase.requisition'].browse(request.action_create_requisition()['res_id'])
        requisition.write({'vendor_id': self.vendor.id, 'erp_po_type': 'agreement'})
        requisition.action_confirm()
        po = self.test_env['purchase.order'].browse(requisition.action_create_rfq()['res_id'])
        self.assertFalse(po.erp_agreement_required)
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_confirm()
        agreement = self.make_agreement(po)
        po.button_confirm()
        self.assertEqual(po.state, 'purchase')
        self.assertEqual(agreement.purchase_order_id, po)
