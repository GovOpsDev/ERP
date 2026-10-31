from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPurchaseGuarantee(TransactionCase):
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


    def setup_guarantee(self, requisition=False, cash=True):
        request = self.make_request(50)
        request.action_submit()
        request.action_approve()
        if requisition:
            source = self.test_env['purchase.requisition'].browse(request.action_create_requisition()['res_id'])
            source.action_confirm()
        else:
            source = self.make_po(request, 50)
        account = self.env['account.account'].create({'name': 'Guarantee liability', 'code': 'GUAL', 'account_type': 'liability_current', 'company_ids': [(6, 0, self.company.ids)]})
        method = self.env['erp.contract.guarantee.method'].create({'name': 'Bid security', 'company_id': self.company.id, 'default_for': 'requisition' if requisition else 'rfq', 'account_id': account.id})
        instrument = self.env['erp.contract.guarantee.type'].create({'name': 'Cash' if cash else 'Bank letter', 'is_create_invoice': cash})
        receivable = self.env['account.account'].create({'name': 'Guarantee receivable', 'code': 'GUAR', 'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        payable = self.env['account.account'].create({'name': 'Guarantee payable', 'code': 'GUAP', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        self.vendor.with_company(self.company).write({'property_account_receivable_id': receivable.id, 'property_account_payable_id': payable.id})
        self.env['account.journal'].create({'name': 'Guarantee sales', 'code': 'GUAS', 'type': 'sale', 'company_id': self.company.id})
        self.env['account.journal'].create({'name': 'Guarantee purchases', 'code': 'GUAP', 'type': 'purchase', 'company_id': self.company.id})
        bank_account = self.env['account.account'].create({'name': 'Guarantee bank', 'code': 'GUAB', 'account_type': 'asset_cash', 'company_ids': [(6, 0, self.company.ids)]})
        outstanding = self.env['account.account'].create({'name': 'Guarantee outstanding', 'code': 'GUAO', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        self.bank = self.env['account.journal'].create({'name': 'Guarantee bank', 'code': 'GUAB', 'type': 'bank', 'company_id': self.company.id, 'default_account_id': bank_account.id})
        (self.bank.inbound_payment_method_line_ids | self.bank.outbound_payment_method_line_ids).payment_account_id = outstanding
        values = {'type_id': instrument.id, 'amount': 10, 'document_ref': 'Bank reference', 'date_guarantee_receive': '2026-06-01', 'partner_id': self.vendor.id}
        values['requisition_id' if requisition else 'purchase_order_id'] = source.id
        guarantee = self.test_env['erp.contract.guarantee'].create(values)
        self.assertEqual(guarantee.method_id, method)
        self.assertEqual((guarantee.fund_id, guarantee.organization_id), (self.fund, self.unit))
        return guarantee

    def pay_guarantee(self, move, amount=None):
        wizard = self.test_env['account.payment.register'].with_context(active_model='account.move', active_ids=move.ids).create({'journal_id': self.bank.id, 'payment_date': '2026-06-02', 'amount': amount if amount is not None else move.amount_residual})
        return wizard._create_payments()

    def test_guarantee_native_receipt_partial_return_and_budget(self):
        guarantee = self.setup_guarantee()
        receipt = self.test_env['account.move'].browse(guarantee.action_create_receipt()['res_id'])
        self.assertEqual(guarantee.action_create_receipt()['res_id'], receipt.id)
        self.assertEqual(guarantee.amount_received, 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            guarantee.action_create_return()
        receipt.action_post()
        self.pay_guarantee(receipt, 4)
        self.assertEqual(guarantee.amount_received, 4)
        returned = self.test_env['account.move'].browse(guarantee.action_create_return()['res_id'])
        self.assertEqual(returned.amount_total, 4)
        self.assertEqual(guarantee.action_create_return()['res_id'], returned.id)
        returned.action_post()
        self.pay_guarantee(returned)
        self.assertEqual((guarantee.amount_returned, str(guarantee.date_return)), (4, '2026-06-02'))
        self.assertEqual(self.active('pr_commitment'), 50)
        self.assertEqual(self.active('actual'), 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            guarantee.action_create_return()
        self.pay_guarantee(receipt)
        final = self.test_env['account.move'].browse(guarantee.action_create_return()['res_id'])
        self.assertEqual(final.amount_total, 6)
        final.action_post()
        self.pay_guarantee(final)
        self.assertEqual((guarantee.amount_received, guarantee.amount_returned), (10, 10))
        self.assertAlmostEqual(sum((receipt | returned | final).line_ids.filtered(lambda l: l.account_id == guarantee.method_id.account_id).mapped('balance')), 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            guarantee.action_create_receipt()

    def test_guarantee_requisition_non_cash_and_scope(self):
        guarantee = self.setup_guarantee(requisition=True, cash=False)
        with self.assertRaises(UserError), self.cr.savepoint():
            guarantee.action_create_receipt()
        guarantee.document_return_date = '2026-07-01'
        self.assertEqual(str(guarantee.date_return), '2026-07-01')
        other = self.env['res.company'].create({'name': 'Foreign guarantee company'})
        self.user.company_ids = [(4, other.id)]
        foreign = self.env(user=self.user, context={'allowed_company_ids': other.ids})
        self.assertFalse(foreign['erp.contract.guarantee'].search([('id', '=', guarantee.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            guarantee.with_env(foreign).action_create_return()
        other_unit = self.env['erp.organization.unit'].create({'name': 'Other guarantee unit', 'code': 'GUAO', 'company_id': self.company.id})
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            guarantee.organization_id = other_unit

    def test_guarantee_history_and_unreconcile_are_guarded(self):
        guarantee = self.setup_guarantee()
        receipt = self.test_env['account.move'].browse(guarantee.action_create_receipt()['res_id'])
        receipt.action_post()
        self.pay_guarantee(receipt)
        returned = self.test_env['account.move'].browse(guarantee.action_create_return()['res_id'])
        returned.action_post()
        self.pay_guarantee(returned)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            receipt.button_draft()
        self.assertEqual((receipt.state, guarantee.amount_received, guarantee.amount_returned), ('posted', 10, 10))
        with self.assertRaises(AccessError), self.cr.savepoint():
            returned.invoice_line_ids.price_unit = 100
        with self.assertRaises(AccessError), self.cr.savepoint():
            returned.erp_guarantee_id = False
        with self.assertRaises(UserError), self.cr.savepoint():
            guarantee.amount = 1
        with self.assertRaises(UserError), self.cr.savepoint():
            receipt.unlink()
        with self.assertRaises(UserError), self.cr.savepoint():
            guarantee.type_id.is_create_invoice = False
        returned.button_draft()
        returned.button_cancel()
        receipt.button_draft()
        receipt.button_cancel()
        self.assertEqual((guarantee.amount_received, guarantee.amount_returned, len(guarantee.move_ids)), (0, 0, 2))

    def test_guarantee_ou_revocation_covers_payment_and_reconcile(self):
        guarantee = self.setup_guarantee()
        receipt = self.test_env['account.move'].browse(guarantee.action_create_receipt()['res_id'])
        receipt.action_post()
        payment = self.pay_guarantee(receipt)
        lines = receipt.line_ids | payment.move_id.line_ids
        partials = lines.matched_debit_ids | lines.matched_credit_ids
        full = lines.full_reconcile_id
        self.assertTrue(payment and partials and full)
        records = [guarantee, receipt, payment, payment.move_id, lines, partials, full]
        identities = [(record._name, record.ids) for record in records]
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id), ('unit_id', '=', self.unit.id)]).unlink()
        for model, ids in identities:
            self.assertFalse(self.test_env[model].search([('id', 'in', ids)]), model)
        with self.assertRaises(AccessError), self.cr.savepoint():
            guarantee.action_create_return()

    def test_guarantee_rpc_cannot_forge_financial_links(self):
        guarantee = self.setup_guarantee()
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['account.move'].with_context(default_erp_guarantee_id=guarantee.id).create({'move_type': 'out_invoice'})
        receipt = self.test_env['account.move'].browse(guarantee.action_create_receipt()['res_id'])
        with self.assertRaises(AccessError), self.cr.savepoint():
            receipt.write({'state': 'posted'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            receipt.invoice_line_ids.write({'price_unit': 20})
        with self.assertRaises(AccessError), self.cr.savepoint():
            guarantee.write({'amount_received': 100})
        self.assertEqual((receipt.state, receipt.amount_total, guarantee.amount_received), ('draft', 10, 0))

    def test_guarantee_partial_reconcile_cannot_rewrite_or_overpay(self):
        guarantee = self.setup_guarantee()
        receipt = self.test_env['account.move'].browse(guarantee.action_create_receipt()['res_id'])
        receipt.action_post()
        payment = self.pay_guarantee(receipt, 4)
        partial = receipt.line_ids.matched_credit_ids
        with self.assertRaises(AccessError), self.cr.savepoint():
            partial.amount = 1
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.test_env['account.partial.reconcile'].create({'debit_move_id': partial.debit_move_id.id, 'credit_move_id': partial.credit_move_id.id, 'amount': 7, 'debit_amount_currency': 7, 'credit_amount_currency': 7})
        self.assertEqual((guarantee.amount_received, receipt.amount_residual), (4, 6))

    def test_guarantee_payment_reset_cannot_orphan_return(self):
        guarantee = self.setup_guarantee()
        receipt = self.test_env['account.move'].browse(guarantee.action_create_receipt()['res_id'])
        receipt.action_post()
        payment = self.pay_guarantee(receipt)
        returned = self.test_env['account.move'].browse(guarantee.action_create_return()['res_id'])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.move_id.button_draft()
        self.assertEqual((payment.move_id.state, guarantee.amount_received), ('posted', 10))
        returned.button_cancel()
        payment.move_id.button_draft()
        self.assertEqual((receipt.amount_residual, guarantee.amount_received), (10, 0))
