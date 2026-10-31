from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRetention(TransactionCase):
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


    def retention_scenario(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 10, 10)
        bill.write({'erp_payment_retention': 'percent', 'erp_retention_value': 10})
        account = self.env['account.account'].create({'name': 'Retention liability', 'code': 'RET', 'account_type': 'liability_current', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        self.company.erp_retention_payable_account_id = account
        bank_account = self.env['account.account'].create({'name': 'Bank', 'code': 'RETB', 'account_type': 'asset_cash', 'company_ids': [(6, 0, self.company.ids)]})
        outstanding = self.env['account.account'].create({'name': 'Outstanding', 'code': 'RETO', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        self.bank = self.env['account.journal'].create({'name': 'Retention bank', 'code': 'RETB', 'type': 'bank', 'company_id': self.company.id, 'default_account_id': bank_account.id})
        self.bank.outbound_payment_method_line_ids.payment_account_id = outstanding
        bill.action_post()
        return bill

    def payment_wizard(self, bill, apply=False, enforce=True):
        return self.test_env['account.payment.register'].with_context(active_model='account.move', active_ids=bill.ids).create({'journal_id': self.bank.id, 'payment_date': fields.Date.today(), 'erp_apply_retention': apply, 'erp_enforce_retention': enforce})

    def test_retention_native_payment_release_no_double_actual(self):
        bill = self.retention_scenario()
        self.assertEqual(bill.erp_retention_amount, 10)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.payment_wizard(bill)._create_payments()
        payment = self.payment_wizard(bill, apply=True)._create_payments()
        self.assertEqual((payment.amount, bill.amount_residual, self.active('actual')), (90, 0, 100))
        retention = bill.erp_retention_ids
        self.assertEqual((retention.amount, retention.amount_remaining, retention.organization_id), (10, 10, self.unit))
        release = self.test_env['account.move'].browse(retention.action_release()['res_id'])
        self.assertEqual(retention.action_release()['res_id'], release.id)
        release.action_post()
        self.assertEqual((retention.amount_remaining, release.amount_total, self.active('actual')), (0, 10, 100))
        self.payment_wizard(release)._create_payments()
        self.assertEqual((release.amount_residual, self.active('actual')), (0, 100))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.move_id.button_draft()
        release.button_draft()
        release.button_cancel()
        self.assertEqual(retention.amount_remaining, 10)
        payment.move_id.button_draft()
        self.assertEqual((retention.amount_remaining, bill.amount_residual, self.active('actual')), (0, 100, 100))

    def test_purchase_payment_without_retention_preserves_source_scope(self):
        bill = self.retention_scenario()
        bill.button_draft()
        bill.write({'erp_payment_retention': False, 'erp_retention_value': 0})
        bill.action_post()
        payment = self.payment_wizard(bill, enforce=False)._create_payments()
        self.assertFalse(bill.erp_retention_ids)
        lines = payment.move_id.line_ids | bill.line_ids
        partials = lines.matched_debit_ids | lines.matched_credit_ids
        full = lines.full_reconcile_id
        self.assertTrue(partials)
        protected = [bill, payment, payment.move_id, lines, partials, full]
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        for records in protected:
            if records:
                self.assertFalse(self.test_env[records._name].search([('id', 'in', records.ids)]), records._name)
                with self.assertRaises(AccessError), self.cr.savepoint():
                    records.with_env(self.test_env).check_access('write')

    def test_retention_opt_out_and_ou_scope(self):
        bill = self.retention_scenario()
        payment = self.payment_wizard(bill, enforce=False)._create_payments()
        self.assertEqual(payment.amount, 100)
        self.assertFalse(bill.erp_retention_ids)
        payment.move_id.line_ids.remove_move_reconcile()
        payment.move_id.button_draft()
        payment = self.payment_wizard(bill, apply=True)._create_payments()
        retention = bill.erp_retention_ids
        release = self.test_env['account.move'].browse(retention.action_release()['res_id'])
        protected = [retention, release, payment, payment.move_id, payment.move_id.line_ids]
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        for records in protected:
            self.assertFalse(self.test_env[records._name].search([('id', 'in', records.ids)]), records._name)

    def test_retention_rpc_and_invalid_terms(self):
        bill = self.retention_scenario()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.erp_retention_value = 20
        payment = self.payment_wizard(bill, apply=True)._create_payments()
        retention = bill.erp_retention_ids
        with self.assertRaises(AccessError), self.cr.savepoint():
            retention.amount = 100
        release = self.test_env['account.move'].browse(retention.action_release()['res_id'])
        with self.assertRaises(AccessError), self.cr.savepoint():
            release.invoice_line_ids.price_unit = 100
        with self.assertRaises(AccessError), self.cr.savepoint():
            release.erp_retention_release_id = False
        with self.assertRaises(AccessError), self.cr.savepoint():
            release.state = 'posted'
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['account.move'].with_context(default_erp_retention_release_id=retention.id).create({'move_type': 'in_invoice'})

    def test_retention_full_amount_and_foreign_currency(self):
        self.company.erp_budget_amount_mode = 'net'
        bill = self.retention_scenario()
        bill.button_draft()
        self.company.erp_budget_amount_mode = 'net'
        foreign = self.env['res.currency'].with_context(active_test=False).search([('id', '!=', self.company.currency_id.id)], limit=1)
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 1})
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 2})
        bill.write({'currency_id': foreign.id, 'erp_payment_retention': 'amount', 'erp_retention_value': 100})
        bill.action_post()
        self.assertEqual(self.active('actual'), 50)
        payment = self.payment_wizard(bill, apply=True)._create_payments()
        self.assertEqual(payment.amount, 0)
        retention = bill.erp_retention_ids
        self.assertEqual((retention.amount, bill.amount_residual), (50, 0))
        release = self.test_env['account.move'].browse(retention.action_release()['res_id'])
        release.action_post()
        self.assertEqual((release.currency_id, release.amount_total, retention.amount_remaining, self.active('actual')), (self.company.currency_id, 50, 0, 50))

    def test_retention_payment_with_native_withholding(self):
        self.company.erp_budget_amount_mode = 'net'
        bill = self.retention_scenario()
        bill.button_draft()
        self.company.write({'erp_budget_amount_mode': 'net', 'country_id': self.env.ref('base.th').id})
        base = self.env['account.account'].create({'name': 'WHT base', 'code': 'RETWBASE', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        liability = self.env['account.account'].create({'name': 'WHT payable', 'code': 'RETWPAY', 'account_type': 'liability_current', 'company_ids': [(6, 0, self.company.ids)]})
        self.company.withholding_tax_base_account_id = base
        group = self.env['account.tax.group'].create({'name': 'WHT', 'company_id': self.company.id})
        tax = self.env['account.tax'].create({'tax_group_id': group.id, 'name': 'WHT 3%', 'amount': -3, 'amount_type': 'percent', 'type_tax_use': 'purchase', 'is_withholding_tax': True, 'company_id': self.company.id, 'invoice_repartition_line_ids': [(0, 0, {'repartition_type': 'base'}), (0, 0, {'repartition_type': 'tax', 'account_id': liability.id})], 'refund_repartition_line_ids': [(0, 0, {'repartition_type': 'base'}), (0, 0, {'repartition_type': 'tax', 'account_id': liability.id})]})
        self.env['account.journal'].create({'name': 'WHT retention', 'code': 'RETWH', 'type': 'general', 'company_id': self.company.id})
        bill.invoice_line_ids.tax_ids = tax
        bill.action_post()
        payment = self.payment_wizard(bill, apply=True)._create_payments()
        self.assertEqual((sum(payment.mapped('withholding_amount')), sum(payment.mapped('withholding_net_amount')), bill.amount_residual, bill.erp_retention_ids.amount, self.active('actual')), (3, 87, 0, 10, 100))

    def test_retention_reconciliation_and_company_are_guarded(self):
        bill = self.retention_scenario()
        payment = self.payment_wizard(bill, apply=True)._create_payments()
        retention = bill.erp_retention_ids
        partial = bill.line_ids.matched_debit_ids
        with self.assertRaises(AccessError), self.cr.savepoint():
            partial.amount = 1
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.test_env['account.partial.reconcile'].create({'debit_move_id': partial.debit_move_id.id, 'credit_move_id': partial.credit_move_id.id, 'amount': 1, 'debit_amount_currency': 1, 'credit_amount_currency': 1})
        other = self.env['res.company'].create({'name': 'Foreign retention company'})
        self.user.company_ids = [(4, other.id)]
        foreign = self.test_env(context={'allowed_company_ids': other.ids})
        self.assertFalse(foreign['erp.finance.retention'].search([('id', '=', retention.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            retention.with_env(foreign).action_release()
