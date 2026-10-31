from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFinanceBudget(TransactionCase):
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

    def test_purchase_accounting_source_scope(self):
        from odoo.tools.binary import BinaryBytes
        request, po = self.scenario()
        bill = self.make_bill(po, 4, 10)
        bill.action_post()
        attachment = self.env['ir.attachment'].create({
            'name': 'Protected purchase bill', 'res_model': 'account.move',
            'res_id': bill.id, 'raw': BinaryBytes(b'purchase accounting evidence')})
        unrelated = self.make_bill(po, 1, 10)
        unrelated.invoice_line_ids.purchase_line_id = False
        self.assertTrue(bill.read(['name']))
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        self.assertFalse(self.test_env['account.move'].search([('id', '=', bill.id)]))
        self.assertTrue(unrelated.read(['name']))
        for record in [bill, *bill.sudo().line_ids.with_env(self.test_env), attachment.with_env(self.test_env)]:
            with self.assertRaises(AccessError), self.cr.savepoint():
                record.read(['name'])
            with self.assertRaises(AccessError), self.cr.savepoint():
                record.write({'name': 'Forbidden'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            attachment.with_env(self.test_env)._to_http_stream()

    def test_partial_second_bill_and_reconcile_preserves_actual(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 4, 12)
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (100, 0))
        bill.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 48))
        actual = self.env['erp.budget.move'].sudo().search([('control_id', '=', self.ac.id), ('move_type', '=', 'actual')])
        self.assertEqual((actual.source_key, actual.document_key, actual.purchase_source_key), ('account.move.line:%s' % bill.invoice_line_ids.id, 'account.move:%s' % bill.id, 'purchase.order.line:%s' % po.order_line.id))
        second = self.make_bill(po, 6, 10)
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 48))
        second.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 108))
        count = self.env['erp.budget.move'].sudo().search_count([])
        request.line_ids._reconcile_budget(pr_eligible=True)
        self.assertEqual(self.env['erp.budget.move'].sudo().search_count([]), count)
        second.button_draft()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 48))

    def test_refund_and_overinvoice(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 10, 10)
        bill.action_post()
        refund = self.make_bill(po, 3, 10, 'in_refund', bill)
        refund.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 70))
        excessive = self.make_bill(po, 4, 10)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            excessive.action_post()
        self.assertEqual(excessive.state, 'draft')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 70))

    def test_insufficient_variance_and_bad_dimensions_are_atomic(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 4, 20)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (100, 0))
        bill.invoice_line_ids.analytic_distribution = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')

    def test_full_refund_reset_and_po_cancellation(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 10, 10)
        bill.action_post()
        refund = self.make_bill(po, 10, 10, 'in_refund', bill)
        refund.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 0))
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_cancel()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.invoice_line_ids.write({'price_unit': 1})
        refund.button_draft()
        bill.button_draft()
        po.button_cancel()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 0))
        self.assertEqual(self.active('pr_commitment'), 100)

    def test_refund_must_reference_original_and_cannot_overcredit(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 4, 10)
        bill.action_post()
        unrelated = self.make_bill(po, 1, 10, 'in_refund')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            unrelated.action_post()
        over = self.make_bill(po, 4, 11, 'in_refund', bill)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            over.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 40))

    def test_uom_conversion_and_tax_rejection(self):
        request, po = self.scenario()
        pair = self.env['uom.uom'].create({'name': 'Finance pair', 'relative_uom_id': po.order_line.uom_id.id, 'relative_factor': 2})
        bill = self.make_bill(po, 2, 24)
        bill.invoice_line_ids.write({'product_uom_id': pair.id})
        bill.invoice_line_ids.write({'quantity': 2, 'price_unit': 24})
        bill.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 48))
        bad = self.make_bill(po, 1, 10)
        self.company.country_id = self.env.ref('base.th')
        tax_group = self.env['account.tax.group'].create({'name': 'Finance tax group', 'company_id': self.company.id})
        tax = self.env['account.tax'].with_company(self.company).create({'name': 'Test tax', 'amount': 7, 'type_tax_use': 'purchase', 'company_id': self.company.id, 'tax_group_id': tax_group.id})
        bad.invoice_line_ids.tax_ids = tax
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bad.action_post()
        self.assertEqual(bad.state, 'draft')

    def test_general_bill_and_credit_note_unaffected(self):
        request, po = self.scenario()
        before = self.env['erp.budget.move'].sudo().search_count([])
        general = self.make_bill(po, 1, 10)
        general.invoice_line_ids.purchase_line_id = False
        general.action_post()
        credit = self.make_bill(po, 1, 10, 'in_refund')
        credit.invoice_line_ids.purchase_line_id = False
        credit.action_post()
        self.assertEqual(self.env['erp.budget.move'].sudo().search_count([]), before)
        self.assertEqual((general.state, credit.state), ('posted', 'posted'))

    def test_multiple_purchase_orders_and_invoices(self):
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        first = self.make_po(request, 40)
        second = self.make_po(request, 60)
        first.button_confirm()
        second.button_confirm()
        bill1 = self.make_bill(first, 1, 40)
        bill1.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 40))
        bill2 = self.make_bill(second, 1, 60)
        bill2.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 100))

    def test_accounting_permission_is_not_granted_by_procurement(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 4, 10)
        user = self.env['res.users'].create({'name': 'Procurement only', 'login': 'finance_no_account', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_procurement.group_procurement_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': self.unit.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            bill.with_user(user).action_post()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (100, 0))

    def test_request_30_order_50_and_partial_bill(self):
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.order_line.product_qty = 5
        po.button_confirm()
        bill = self.make_bill(po, 2, 10)
        bill.action_post()
        self.assertEqual((self.active('pr_commitment'), self.active('po_commitment'), self.active('actual')), (0, 30, 20))
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.write({'state': 'draft'})
        self.assertEqual(bill.state, 'posted')

    def test_posted_tax_and_currency_guards(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 1, 10)
        bill.action_post()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.write({'date': '2026-06-02'})
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.invoice_line_ids.unlink()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (90, 10))

    def test_bill_for_cancelled_order_does_not_post(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 1, 10)
        po.button_cancel()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual((self.active('pr_commitment'), self.active('actual')), (100, 0))

    def test_partial_refund_restores_when_commitment_exists(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 4, 10)
        bill.action_post()
        refund = self.make_bill(po, 3, 10, 'in_refund', bill)
        refund.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (90, 10))

    def test_hidden_invoice_line_cannot_bypass_finance(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 1, 10)
        self.env['ir.access'].create({'name': 'Hide one invoice line for finance test', 'model_id': self.env.ref('account.model_account_move_line').id, 'kind': 'restriction', 'operation': 'crud', 'domain': "[('id', '!=', %s)]" % bill.invoice_line_ids.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (100, 0))

    def test_foreign_currency_is_rejected(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 1, 10)
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        bill.currency_id = foreign
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (100, 0))

    def test_shared_plan_with_real_pr_po_bill_and_refund(self):
        plan = self.env['erp.budget.plan'].create({'name': 'Finance plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        plan.action_confirm()
        request, po = self.scenario()
        cap = plan.line_ids
        self.assertEqual(cap._consumed(), 100)
        bill = self.make_bill(po, 4, 10)
        bill.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual'), cap._consumed()), (60, 40, 100))
        expensive = self.make_bill(po, 1, 12)
        with self.assertRaises(UserError), self.cr.savepoint():
            expensive.action_post()
        self.assertEqual((expensive.state, cap._consumed()), ('draft', 100))
        refund = self.make_bill(po, 1, 10, kind='in_refund', reversed_entry=bill)
        refund.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual'), cap._consumed()), (70, 30, 100))

    def test_formal_release_real_pr_po_bill(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        original_analytic = self.analytic
        analytic_plan = original_analytic.plan_id
        new_analytic = self.env['account.analytic.account'].create({'name': 'Formal release analytic', 'plan_id': analytic_plan.id, 'company_id': self.company.id})
        kpi = self.env['erp.budget.kpi'].create({'name': 'Formal release KPI', 'company_id': self.company.id})
        template = self.env['erp.budget.template'].create({'name': 'Formal release template', 'company_id': self.company.id, 'line_ids': [(0, 0, {'account_id': self.account.id, 'kpi_id': kpi.id})]})
        self.period.template_id = template
        plan = self.env['erp.budget.plan'].create({'name': 'Formal release plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': original_analytic.id, 'initial_amount': 100}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': new_analytic.id, 'initial_amount': 100, 'allocation_mode': 'allocated', 'release_required': True})]})
        plan.action_confirm()
        cap = plan.line_ids.filtered(lambda row: row.analytic_id == new_analytic)
        vals = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': new_analytic.id, 'amount': 100}
        ac, fc = self.env['erp.budget.control'].create([dict(vals, name='Released KPI', level='analytic', kpi_id=kpi.id), dict(vals, name='Released fund', level='fund', fund_id=self.fund.id)])
        fc.action_open()
        release = self.env['erp.budget.kpi.release'].create({'name': 'Real document release', 'plan_line_id': cap.id, 'released_amount': 100, 'line_ids': [(0, 0, {'control_id': ac.id})]})
        reviewer = self.env['res.users'].create({'name': 'Budget release reviewer', 'login': 'finance_release_review', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': 10, 'reviewer_id': reviewer.id})
        release = release.with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        release.action_submit()
        release.with_user(reviewer).action_approve()
        self.analytic, self.ac, self.fc = new_analytic, ac, fc
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.order_line.product_qty = 10
        po.button_confirm()
        bill = self.make_bill(po, 4, 10)
        bill.action_post()
        self.assertEqual((release.state, cap._consumed(), self.active('po_commitment'), self.active('actual')), ('done', 100, 60, 40))
        with self.assertRaises(UserError), self.cr.savepoint():
            release.action_reverse()

    def test_real_commitment_revision_transfer_and_reversal(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        other = self.env['account.analytic.account'].create({'name': 'Transfer destination analytic', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        plan = self.env['erp.budget.plan'].create({'name': 'Real transfer plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': other.id, 'initial_amount': 100})]})
        plan.action_confirm()
        source = plan.line_ids.filtered(lambda row: row.analytic_id == self.analytic).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        destination = (plan.line_ids - source).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        request = self.make_request(60)
        request.action_submit()
        request.action_approve()
        ledger_before = self.env['erp.budget.move'].sudo().search([('control_id', 'in', (self.ac | self.fc).ids)]).ids
        revision = self.env['erp.budget.plan.version'].with_user(self.user).with_context(allowed_company_ids=[self.company.id]).browse(plan.with_user(self.user).with_context(allowed_company_ids=[self.company.id]).action_prepare_revision()['res_id'])
        revision.write({'reason': 'Increase after commitment'})
        revision.line_ids.filtered(lambda row: row.plan_line_id == source).write({'amount': 120})
        revision.action_activate()
        self.assertEqual((source._ceiling(), source._consumed(), source._ceiling() - source._consumed()), (120, 60, 60))
        self.assertEqual(self.env['erp.budget.move'].sudo().search([('control_id', 'in', (self.ac | self.fc).ids)]).ids, ledger_before)
        source.action_transfer(destination.id, 30, 'Committed source transfer')
        event = self.env['erp.budget.plan.event'].with_user(self.user).with_context(allowed_company_ids=[self.company.id]).search([('source_id', '=', source.id), ('destination_id', '=', destination.id), ('kind', '=', 'transfer')])
        self.assertEqual((source._ceiling(), destination._ceiling(), source._consumed()), (90, 130, 60))
        event.action_reverse_transfer()
        self.assertEqual((source._ceiling(), destination._ceiling(), source._consumed()), (120, 100, 60))
        source.action_transfer(destination.id, 30, 'Second transfer')
        event = self.env['erp.budget.plan.event'].with_user(self.user).with_context(allowed_company_ids=[self.company.id]).search([('source_id', '=', source.id), ('destination_id', '=', destination.id), ('kind', '=', 'transfer'), ('reference', '=', 'Second transfer')])
        vals = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': other.id, 'amount': 130}
        ac, fc = self.env['erp.budget.control'].create([dict(vals, name='Destination analytic control', level='analytic'), dict(vals, name='Destination fund control', level='fund', fund_id=self.fund.id)])
        (ac | fc).action_open()
        self.analytic, self.ac, self.fc = other, ac, fc
        dest_request = self.make_request(120)
        dest_request.action_submit()
        dest_request.action_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            event.action_reverse_transfer()
        self.assertEqual((source._ceiling(), destination._ceiling(), destination._consumed()), (90, 130, 120))
        dest_request.action_reject()
        event.action_reverse_transfer()
        self.assertEqual((source._ceiling(), destination._ceiling(), destination._consumed()), (120, 100, 0))

    def test_allocation_revision_real_pr_po_bill(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        period = env['erp.budget.period'].create({'name': 'Allocated finance year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        allocation = env['erp.budget.allocation'].create({'name': 'Finance fund allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        fund = allocation.line_ids.control_id
        fund.action_open()
        analytic = env['erp.budget.control'].create({'name': 'Allocated finance analytic', 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'amount': 100})
        analytic.action_open()
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Approved increase'})
        revision.line_ids.write({'amount': 120})
        revision.action_activate()
        self.assertEqual((fund.amount, allocation.plan_id.line_ids._ceiling()), (120, 120))
        original_line = allocation.line_ids
        replacement_fund = env['erp.budget.fund'].create({'name': 'Revised source fund', 'company_id': self.company.id, 'group_id': self.fund.group_id.id})
        dimension_revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        dimension_revision.write({'reason': 'Replace unused source fund'})
        dimension_revision.line_ids.write({'amount': 0, 'excluded': True})
        replacement_row = env['erp.budget.allocation.revision.line'].browse(dimension_revision.action_add_dimension(self.unit.id, self.analytic.id, replacement_fund.id, 120))
        dimension_revision.action_activate()
        self.assertEqual((fund.amount, replacement_row.allocation_line_id.control_id.amount, allocation.plan_id.line_ids._ceiling()), (0, 120, 120))
        self.fund = replacement_fund
        self.period, self.ac, self.fc = period, analytic, replacement_row.allocation_line_id.control_id
        request = self.make_request(100)
        request.date_start = '2027-06-01'
        request.action_submit()
        request.action_approve()
        po = self.test_env['purchase.order'].create({'company_id': self.company.id, 'partner_id': self.vendor.id, 'date_order': '2027-06-01 12:00:00', 'order_line': [(0, 0, {'name': 'Ordered service', 'product_id': self.product.id, 'product_qty': 10, 'price_unit': 10, 'date_planned': '2027-06-05 12:00:00', 'tax_ids': [(5, 0, 0)], 'erp_request_line_id': request.line_ids.id, 'erp_budget_fund_id': self.fund.id, 'erp_budget_analytic_id': self.analytic.id, 'erp_budget_account_id': self.account.id, 'analytic_distribution': {str(self.analytic.id): 100}})]})
        po.button_confirm()
        bill = self.make_bill(po, 4, 10)
        bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
        bill.action_post()
        self.assertEqual((allocation.state, original_line.released_amount, allocation.plan_id.line_ids._consumed()), ('done', 100, 100))
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 40))

    def test_coordinated_source_planning_revision_real_pr_po_bill(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        env = self.test_env
        kpi = self.env['erp.budget.kpi'].create({'name': 'Coordinated finance KPI', 'company_id': self.company.id})
        template = self.env['erp.budget.template'].create({'name': 'Coordinated finance template', 'company_id': self.company.id, 'line_ids': [(0, 0, {'account_id': self.account.id, 'kpi_id': kpi.id})]})
        period = self.env['erp.budget.period'].create({'name': 'Coordinated finance year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31', 'release_policy': 'formal', 'template_id': template.id})
        allocation = env['erp.budget.allocation'].create({'name': 'Coordinated finance allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        fund = allocation.line_ids.control_id
        fund.action_open()
        control = env['erp.budget.control'].create({'name': 'Coordinated finance control', 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'kpi_id': kpi.id, 'amount': 100})
        reviewer = self.env['res.users'].create({'name': 'Coordinated finance reviewer', 'login': 'coordinated_finance_reviewer', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': 10, 'reviewer_id': reviewer.id})
        release = env['erp.budget.kpi.release'].create({'name': 'Initial finance planning', 'plan_line_id': allocation.plan_id.line_ids.id, 'released_amount': 100, 'line_ids': [(0, 0, {'control_id': control.id})]})
        release.action_submit()
        release.with_user(reviewer).action_approve()
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Finance coordinated source revision'})
        revision.line_ids.write({'amount': 120})
        planning = env['erp.budget.kpi.release'].browse(release.action_prepare_revision(revision.id)['res_id'])
        planning.write({'released_amount': 120})
        planning.line_ids.write({'amount': 120})
        planning.action_submit()
        planning.with_user(reviewer).action_approve()
        self.assertEqual((planning.state, control.amount, fund.amount), ('approved', 100, 100))
        revision.action_activate()
        self.period, self.ac, self.fc = period, control, fund
        request = self.make_request(120)
        request.date_start = '2027-06-01'
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10, date_order='2027-06-01 12:00:00', date_planned='2027-06-05 12:00:00')
        po.order_line.write({'product_qty': 12, 'date_planned': '2027-06-05 12:00:00'})
        po.button_confirm()
        bill = self.make_bill(po, 4, 10)
        bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
        bill.action_post()
        self.assertEqual((release.state, release.line_ids.amount, planning.state, planning.line_ids.amount), ('superseded', 100, 'done', 120))
        self.assertEqual((allocation.plan_id.line_ids._consumed(), self.active('po_commitment'), self.active('actual')), (120, 80, 40))
        with self.assertRaises(UserError), self.cr.savepoint():
            allocation.action_cancel()
        self.assertEqual((allocation.state, allocation.plan_id.line_ids._consumed()), ('done', 120))

    def test_activity_kpi_selection_and_distinct_gl_account_real_bills(self):
        from odoo.addons.erp_budget.tests.common_activity import source_activity_allocation
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        budget_account = self.env['account.account'].create({'name': 'Activity budget account', 'code': 'ACTBUD', 'account_type': 'expense', 'company_ids': [(6, 0, [self.company.id])]})
        data = source_activity_allocation(self, self.user, self.company, self.unit, self.analytic, self.fund, budget_account, 'Finance activity')
        self.period, self.fc = data.period, data.fund_control
        missing = self.make_request(1)
        missing.date_start = '2027-06-01'
        with self.assertRaises(ValidationError), self.cr.savepoint():
            missing.action_submit()
        self.assertEqual(missing.state, 'draft')
        orders = []
        for activity, quantity in zip(data.activities, (4, 6)):
            request = self.make_request(quantity * 10)
            request.date_start = '2027-06-01'
            request.line_ids.activity_id = activity
            self.assertEqual(request.line_ids.account_id, budget_account)
            request.action_submit()
            request.action_approve()
            order = self.make_po(request, 10, date_order='2027-06-01 12:00:00', date_planned='2027-06-05 12:00:00', budget_account=budget_account)
            order.order_line.product_qty = quantity
            self.assertEqual(order.order_line.erp_budget_activity_id, activity)
            order.button_confirm()
            orders.append(order)
        first = self.make_bill(orders[0], 4, 10)
        second = self.make_bill(orders[1], 3, 10)
        for bill, activity in zip((first, second), data.activities):
            bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
            bill.action_post()
            self.assertEqual(bill.invoice_line_ids.erp_budget_activity_id, activity)
            self.assertEqual(bill.invoice_line_ids.account_id, self.account)
            self.assertNotEqual(bill.invoice_line_ids.account_id, budget_account)
        self.ac = data.controls[0]
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (40, 0))
        self.ac = data.controls[1]
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (30, 30))
        self.assertEqual((data.allocation.plan_id.line_ids._consumed(), data.allocation.plan_id.line_ids._ceiling()), (100, 100))
        with self.assertRaises(UserError), self.cr.savepoint():
            orders[0].order_line.write({'erp_budget_activity_id': data.activities[1].id})
        with self.assertRaises(UserError), self.cr.savepoint():
            data.activities[0].write({'account_id': self.account.id})

    def test_total_analytic_planning_initializes_real_outstanding_kpis(self):
        from odoo.addons.erp_budget.tests.common_activity import source_activity_allocation
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        data = source_activity_allocation(self, self.user, self.company, self.unit, self.analytic, self.fund, self.account, 'Total finance', control_level='analytic')
        self.period, self.fc, self.ac = data.period, data.fund_control, data.controls
        orders = []
        for activity, quantity in zip(data.activities, (6, 4)):
            request = self.make_request(quantity * 10)
            request.date_start = '2027-06-01'
            request.line_ids.activity_id = activity
            request.action_submit()
            request.action_approve()
            order = self.make_po(request, 10, date_order='2027-06-01 12:00:00', date_planned='2027-06-05 12:00:00')
            order.order_line.product_qty = quantity
            order.button_confirm()
            orders.append(order)
        bill = self.make_bill(orders[0], 2, 10)
        bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
        bill.action_post()
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (20, 80))
        release = data.env['erp.budget.kpi.release'].search([('period_id', '=', data.period.id), ('state', '=', 'done')])
        successor = data.env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        successor.action_initialize_commitments()
        self.assertEqual(successor.line_ids.planning_ids.mapped('amount'), [40, 40])
        self.assertEqual((data.controls.amount, data.allocation.plan_id.line_ids._ceiling()), (100, 100))
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (20, 80))

    def test_reviewed_transfer_with_real_po_and_partial_bill(self):
        from odoo.addons.erp_budget.tests.test_budget_transfer import TestBudgetTransfer
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        env, doc, controls, reviewers = TestBudgetTransfer._setup_transfer(self)
        self.period = doc.period_id
        self.ac, self.fc = controls[0], doc.line_ids.source_id.control_id
        request = self.make_request(60)
        request.date_start = '2027-06-01'
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10, date_order='2027-06-01 12:00:00', date_planned='2027-06-05 12:00:00')
        po.order_line.product_qty = 6
        po.button_confirm()
        bill = self.make_bill(po, 2, 10)
        bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
        bill.action_post()
        moves = self.env['erp.budget.move'].sudo().search([('control_id', '=', self.ac.id)]).ids
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (40, 20))
        doc.action_submit()
        TestBudgetTransfer._approve_transfer(self, doc, reviewers)
        self.assertEqual((self.ac.amount, self.fc.amount, self.total()), (70, 70, 60))
        self.assertEqual(self.env['erp.budget.move'].sudo().browse(moves).exists().ids, moves)
        self.analytic = doc.line_ids.destination_id.analytic_id
        self.ac, self.fc = controls[1], doc.line_ids.destination_id.control_id
        destination_request = self.make_request(110)
        destination_request.date_start = '2027-06-01'
        destination_request.action_submit()
        destination_request.action_approve()
        reverse = env['erp.budget.transfer'].browse(doc.action_reverse()['res_id'])
        with self.assertRaises(UserError), self.cr.savepoint():
            reverse.action_submit()
        self.assertEqual((doc.state, self.ac.amount, self.total()), ('done', 130, 110))

    def test_explicit_legacy_capture_keeps_real_po_bill_and_control_ids(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        request = self.make_request(60)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.order_line.product_qty = 6
        po.button_confirm()
        bill = self.make_bill(po, 2, 10)
        bill.action_post()
        controls = (self.ac | self.fc).ids
        moves = self.env['erp.budget.move'].sudo().search([('control_id', 'in', controls)]).ids
        plan = self.test_env['erp.budget.plan'].create({'name': 'Legacy real plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        plan.action_confirm()
        allocation = self.test_env['erp.budget.allocation'].browse(plan.action_capture_legacy_allocation()['res_id'])
        baseline = self.test_env['erp.budget.kpi.release'].search([('plan_line_id', '=', plan.line_ids.id), ('state', '=', 'done')])
        reviewer = self.env['res.users'].create({'name': 'Legacy real reviewer', 'login': 'legacy_real_reviewer', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, self.env.ref('erp_budget.group_budget_manager').ids)]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'reviewer_id': reviewer.id})
        revision = self.test_env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Convert existing actual business history'})
        planning = self.test_env['erp.budget.kpi.release'].browse(baseline.action_prepare_revision(revision.id)['res_id'])
        planning.action_submit()
        planning.with_user(reviewer).action_approve()
        revision.action_activate()
        request.line_ids._reconcile_budget(True)
        self.assertEqual((self.ac | self.fc).ids, controls)
        self.assertEqual(self.env['erp.budget.move'].sudo().search([('control_id', 'in', controls)]).ids, moves)
        self.assertEqual((self.active('po_commitment'), self.active('actual'), plan.line_ids._ceiling()), (40, 20, 100))
        self.assertFalse(baseline.review_ids or baseline.released_at)
        self.assertEqual(planning.state, 'done')

    def test_commitment_forward_partial_bills_and_balance_are_separate(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        request = self.make_request(60)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.order_line.product_qty = 6
        po.button_confirm()
        first_bill = self.make_bill(po, 2, 10)
        first_bill.write({'invoice_date': '2026-06-01', 'date': '2026-06-01'})
        first_bill.action_post()
        source_controls = self.ac | self.fc
        old_moves = self.env['erp.budget.move'].sudo().search([('control_id', 'in', source_controls.ids)])
        old_amounts = {move.id: move.amount for move in old_moves}
        source_plan = self.test_env['erp.budget.plan'].create({'name': 'Forward source plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        source_plan.action_confirm()
        destination_period = self.env['erp.budget.period'].create({'name': 'Forward destination', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        target_analytic = self.env['account.analytic.account'].create({'name': 'New fiscal analytic', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        balance = self.test_env['erp.budget.balance.forward'].create({'name': 'Available 40', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': destination_period.id})
        balance.action_review()
        self.assertEqual(balance._current_lines().balance_amount, 40)
        balance._current_lines().destination_analytic_id = target_analytic
        balance.action_forward()
        destination_plan = self.test_env['erp.budget.plan'].create({'name': 'Forward destination plan', 'company_id': self.company.id, 'period_id': destination_period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': target_analytic.id, 'initial_amount': 80})]})
        destination_plan.action_confirm()
        base = {'company_id': self.company.id, 'period_id': destination_period.id, 'organization_id': self.unit.id, 'analytic_id': target_analytic.id, 'amount': 80}
        destination_controls = self.test_env['erp.budget.control'].create([dict(base, name='Forward analytic', level='analytic'), dict(base, name='Forward fund', level='fund', fund_id=self.fund.id)])
        destination_controls.action_open()
        forward = self.test_env['erp.budget.commit.forward'].create({'name': 'Outstanding PO 40', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': destination_period.id})
        forward.action_review()
        row = forward._current_lines()
        self.assertEqual((row.source_key, row.amount), ('purchase.order.line:%s' % po.order_line.id, 40))
        row.write({'destination_analytic_control_id': destination_controls.filtered(lambda control: control.level == 'analytic').id, 'destination_fund_control_id': destination_controls.filtered(lambda control: control.level == 'fund').id})
        forward.action_forward()
        forward.action_forward()
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (20, 0))
        self.assertEqual(balance._balance_for(source_plan.line_ids), 40)
        self.assertEqual(destination_plan.line_ids._opening_minimum(), 80)
        self.ac, self.fc = destination_controls.filtered(lambda control: control.level == 'analytic'), destination_controls.filtered(lambda control: control.level == 'fund')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (40, 0))
        self.product.product_tmpl_id.purchase_method = 'purchase'
        action = po.action_create_invoice()
        second_bill = self.test_env['account.move'].browse(action['res_id'])
        self.assertEqual(second_bill.invoice_line_ids.analytic_distribution, {str(target_analytic.id): 100})
        second_bill.invoice_line_ids.quantity = 2
        second_bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
        second_bill.action_post()
        request.line_ids._reconcile_budget(True)
        self.assertEqual((self.active('po_commitment'), self.active('actual'), destination_plan.line_ids._ceiling()), (20, 20, 80))
        self.assertEqual(source_plan.line_ids._consumed(), 20)
        self.assertEqual(first_bill.invoice_line_ids.analytic_distribution, {str(self.analytic.id): 100})
        self.assertTrue(self.env['account.analytic.line'].search([('move_line_id', 'in', second_bill.invoice_line_ids.ids), (target_analytic.plan_id._column_name(), '=', target_analytic.id)]))
        self.assertEqual(balance._balance_for(source_plan.line_ids), 40)
        self.assertEqual({move.id: move.amount for move in old_moves}, old_amounts)
        duplicate = self.test_env['erp.budget.commit.forward'].create({'name': 'Duplicate PO forward', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': destination_period.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            duplicate.action_review()

    def test_forwarded_po_cancellation_restores_primary_request_in_new_period(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        request = self.make_request(60)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 60)
        po.button_confirm()
        later = self.env['erp.budget.period'].create({'name': 'PO fallback year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        base = {'company_id': self.company.id, 'period_id': later.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 60}
        controls = self.test_env['erp.budget.control'].create([dict(base, name='Fallback analytic', level='analytic'), dict(base, name='Fallback fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        forward = self.test_env['erp.budget.commit.forward'].create({'name': 'Forward unbilled PO', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        forward.action_review()
        forward._current_lines().write({'destination_analytic_control_id': controls.filtered(lambda item: item.level == 'analytic').id, 'destination_fund_control_id': controls.filtered(lambda item: item.level == 'fund').id})
        forward.action_forward()
        po.button_cancel()
        self.ac = controls.filtered(lambda item: item.level == 'analytic')
        self.assertEqual((self.active('po_commitment'), self.active('pr_commitment')), (0, 60))
        self.assertEqual(sum(self.env['erp.budget.move'].sudo().search([('control_id', '=', self.ac.id)]).mapped('amount')), 60)
        request.action_reject()
        self.assertEqual(self.active('pr_commitment'), 0)

    def test_primary_request_forward_does_not_duplicate_commitment(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        request = self.make_request(40)
        request.action_submit()
        request.action_approve()
        later = self.env['erp.budget.period'].create({'name': 'PR forward year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        base = {'company_id': self.company.id, 'period_id': later.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 40}
        controls = self.test_env['erp.budget.control'].create([dict(base, name='PR forward analytic', level='analytic'), dict(base, name='PR forward fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        forward = self.test_env['erp.budget.commit.forward'].create({'name': 'Forward primary PR', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        forward.action_review()
        forward._current_lines().write({'destination_analytic_control_id': controls.filtered(lambda item: item.level == 'analytic').id, 'destination_fund_control_id': controls.filtered(lambda item: item.level == 'fund').id})
        forward.action_forward()
        request.line_ids._reconcile_budget(True)
        self.assertEqual(self.active('pr_commitment'), 0)
        original = self.ac | self.fc
        self.ac = controls.filtered(lambda item: item.level == 'analytic')
        self.assertEqual(self.active('pr_commitment'), 40)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.test_env['erp.budget.control.service']._commit(original.with_env(self.test_env), 1, '2026-06-01', 'forward:old-date-reuse')
        request.action_reject()
        self.assertEqual(self.active('pr_commitment'), 0)

    def test_reviewed_commit_return_withdraws_capacity_and_restores_original_po(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        request = self.make_request(60)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 60)
        po.button_confirm()
        source_plan = self.test_env['erp.budget.plan'].create({'name': 'Return source plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        source_plan.action_confirm()
        later = self.env['erp.budget.period'].create({'name': 'Return fiscal scope', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        balance = self.test_env['erp.budget.balance.forward'].create({'name': 'Retain unused 40', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        balance.action_review()
        balance.action_forward()
        destination_plan = self.test_env['erp.budget.plan'].create({'name': 'Return destination plan', 'company_id': self.company.id, 'period_id': later.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        destination_plan.action_confirm()
        values = {'company_id': self.company.id, 'period_id': later.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 100}
        destination = self.test_env['erp.budget.control'].create([dict(values, name='Return analytic', level='analytic'), dict(values, name='Return fund', level='fund', fund_id=self.fund.id)])
        destination.action_open()
        forward = self.test_env['erp.budget.commit.forward'].create({'name': 'Return outstanding 60', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        forward.action_review()
        forward._current_lines().write({'destination_analytic_control_id': destination.filtered(lambda row: row.level == 'analytic').id, 'destination_fund_control_id': destination.filtered(lambda row: row.level == 'fund').id})
        forward.action_forward()
        reviewer = self.env['res.users'].create({'name': 'Return reviewer', 'login': 'commit_return_reviewer', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id, self.env.ref('erp_procurement.group_procurement_user').id, self.env.ref('purchase.group_purchase_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        for kind in ('planning', 'transfer'):
            self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'kind': kind, 'reviewer_id': reviewer.id})
        future_bill = self.make_bill(po, 1, 60)
        future_bill.write({'date': '2027-06-01', 'invoice_date': '2027-06-01'})
        future_bill.action_post()
        with self.assertRaises(UserError), self.cr.savepoint():
            forward.action_cancel()
        future_bill.button_draft()
        forward.action_cancel()
        self.assertEqual((forward.state, destination.mapped('amount'), source_plan.line_ids._consumed()), ('done', [100, 100], 0))
        with self.assertRaises(AccessError), self.cr.savepoint():
            forward.return_revision_id.action_activate()
        with self.assertRaises(UserError), self.cr.savepoint():
            forward.action_apply_return()
        old_revision = forward.return_revision_id
        forward.return_approval_id.with_user(reviewer).action_reject()
        self.assertEqual((forward.state, old_revision.state, destination.mapped('amount')), ('done', 'cancel', [100, 100]))
        forward.action_prepare_return()
        self.assertNotEqual(forward.return_revision_id, old_revision)
        with self.assertRaises(AccessError), self.cr.savepoint():
            forward.action_approve_return()
        forward.action_submit_return_planning()
        forward.with_user(reviewer).action_approve_return()
        for planning in forward.return_planning_ids:
            planning.with_user(reviewer).action_approve()
        forward.action_apply_return()
        forward.action_apply_return()
        self.assertEqual((forward.state, destination.mapped('amount'), destination_plan.line_ids._ceiling()), ('cancel', [40, 40], 40))
        self.assertEqual((source_plan.line_ids._consumed(), self.active('po_commitment')), (60, 60))
        self.assertEqual(forward._current_lines().opening_id.state, 'cancel')
        self.assertEqual(destination_plan.line_ids._opening_minimum(), 40)
        request.line_ids._reconcile_budget(True)
        self.assertEqual((source_plan.line_ids._consumed(), destination_plan.line_ids._consumed()), (60, 0))
        self.assertEqual((balance.state, balance._balance_for(source_plan.line_ids)), ('done', 40))

    def test_source_currency_policy_freezes_po_and_uses_native_actual_rates(self):
        self.company.erp_budget_amount_mode = 'net'
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 1})
        original_rate = self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 0.5})
        self.assertEqual(foreign._convert(1, self.company.currency_id, self.company, '2026-06-01', round=False), 2)
        request = self.make_request(80)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.write({'currency_id': foreign.id})
        po.order_line.product_qty = 4
        po.button_confirm()
        self.assertEqual((self.active('po_commitment'), po.order_line.erp_budget_total_company, po.erp_budget_fx_rate), (80, 80, 2))
        original_rate.rate = 0.8
        request.line_ids._reconcile_budget(True)
        self.assertEqual(self.active('po_commitment'), 80)
        # Native Odoo 20 selects the latest rate strictly before the invoice date.
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-06-01', 'rate': 0.4})
        bill = self.make_bill(po, 2, 10)
        bill.write({'currency_id': foreign.id, 'date': '2026-06-02', 'invoice_date': '2026-06-02'})
        bill.action_post()
        self.assertEqual((bill.invoice_currency_rate, bill.invoice_line_ids.balance, self.active('actual'), self.active('po_commitment')), (0.4, 50, 50, 40))
        self.assertEqual(bill.invoice_line_ids.erp_budget_amount_snapshot['invoice_currency_rate'], 0.4)
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-06-02', 'rate': 0.25})
        exchange_account = self.env['account.account'].create({'name': 'FX difference', 'code': 'FXDIFF', 'account_type': 'expense', 'company_ids': [(6, 0, self.company.ids)]})
        exchange_journal = self.env['account.journal'].create({'name': 'FX differences', 'code': 'FXD', 'type': 'general', 'company_id': self.company.id})
        self.company.write({'currency_exchange_journal_id': exchange_journal.id, 'income_currency_exchange_account_id': exchange_account.id, 'expense_currency_exchange_account_id': exchange_account.id})
        refund = self.make_bill(po, 1, 10, 'in_refund', bill)
        refund.write({'currency_id': foreign.id, 'date': '2026-06-03', 'invoice_date': '2026-06-03'})
        refund.action_post()
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (10, 60))
        with self.assertRaises(AccessError), self.cr.savepoint():
            po.write({'erp_budget_fx_rate': 0.001})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.make_po(request, 10).write({'erp_budget_manual_rate': 0.001})
        nodes = self.env['erp.budget.move'].sudo().search([('control_id', '=', self.ac.id), ('move_type', '=', 'actual'), ('reversal_of_id', '=', False)])
        self.assertTrue(all(node.amount_snapshot for node in nodes))

    def _tax_policy_case(self, mode, expected):
        self.company.write({'erp_budget_amount_mode': mode, 'country_id': self.env.ref('base.th').id})
        self.env.cr.execute('UPDATE erp_budget_control SET amount=120 WHERE id IN %s', [tuple((self.ac | self.fc).ids)])
        (self.ac | self.fc).invalidate_recordset(['amount'])
        group = self.env['account.tax.group'].create({'name': 'Budget tax policy', 'company_id': self.company.id})
        tax_account = self.env['account.account'].create({'name': 'Budget input tax', 'code': 'BUDTAX', 'account_type': 'asset_current', 'company_ids': [(6, 0, self.company.ids)]})
        taxes = self.env['account.tax'].with_company(self.company).create([{'name': 'Budget VAT', 'amount': 7, 'amount_type': 'percent', 'type_tax_use': 'purchase', 'company_id': self.company.id, 'tax_group_id': group.id}, {'name': 'Budget withholding', 'amount': -3, 'amount_type': 'percent', 'type_tax_use': 'purchase', 'company_id': self.company.id, 'tax_group_id': group.id}])
        for tax in taxes:
            (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(lambda item: item.repartition_type == 'tax').account_id = tax_account
        if mode == 'specific':
            self.company.write({'erp_budget_purchase_tax_ids': [(6, 0, taxes[:1].ids)], 'erp_budget_account_tax_ids': [(6, 0, taxes[:1].ids)]})
        request = self.make_request(110)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.order_line.write({'product_qty': 10, 'tax_ids': [(6, 0, taxes.ids)]})
        po.button_confirm()
        self.assertEqual(self.active('po_commitment'), expected)
        bill = self.make_bill(po, 10, 10)
        bill.invoice_line_ids.tax_ids = taxes
        bill.action_post()
        self.assertEqual((bill.invoice_line_ids.balance, self.active('actual'), self.active('po_commitment')), (100, expected, 0))
        snapshot = bill.invoice_line_ids.erp_budget_amount_snapshot
        taxes[0].amount = 9
        self.company.erp_budget_amount_mode = 'net'
        request.line_ids._reconcile_budget(True)
        self.assertEqual(self.active('actual'), expected)
        self.assertEqual(bill.invoice_line_ids.erp_budget_amount_snapshot, snapshot)

    def test_source_tax_policy_net(self):
        self._tax_policy_case('net', 100)

    def test_source_tax_policy_all(self):
        self._tax_policy_case('all', 104)

    def test_source_tax_policy_specific(self):
        self._tax_policy_case('specific', 107)

    def test_foreign_actual_over_budget_is_atomic_and_manual_commitment_is_authorized(self):
        self.company.erp_budget_amount_mode = 'net'
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 10)
        po.write({'currency_id': foreign.id})
        po.order_line.product_qty = 4
        with self.assertRaises(AccessError), self.cr.savepoint():
            po.erp_budget_manual_rate = 2
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        po.erp_budget_manual_rate = 2
        po.button_confirm()
        self.assertEqual(self.active('po_commitment'), 80)
        bill = self.make_bill(po, 4, 10)
        bill.write({'currency_id': foreign.id, 'invoice_currency_rate': 1 / 3})
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual((bill.state, self.active('po_commitment'), self.active('actual')), ('draft', 80, 0))
        bill.invoice_currency_rate = 0.5
        bill.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 80))
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.invoice_line_ids.with_context(check_move_validity=False).write({'amount_currency': 1})
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.invoice_currency_rate = 1

    def direct_dimensions(self):
        return {'erp_budget_period_id': self.period.id, 'erp_budget_organization_id': self.unit.id, 'erp_budget_fund_id': self.fund.id, 'erp_budget_analytic_id': self.analytic.id, 'analytic_distribution': {str(self.analytic.id): 100}}

    def make_direct_bill(self, amount):
        po = self.test_env['purchase.order'].create({'company_id': self.company.id, 'partner_id': self.vendor.id, 'order_line': [(0, 0, {'name': 'Uncontrolled draft quote', 'product_id': self.product.id, 'product_qty': 1, 'price_unit': amount, 'tax_ids': [(5, 0, 0)]})]})
        bill = self.make_bill(po, 1, amount)
        bill.invoice_line_ids.write(dict(self.direct_dimensions(), purchase_line_id=False))
        return bill

    def test_direct_actual_native_refund_reset_and_history(self):
        bill = self.make_direct_bill(70)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.write({'state': 'posted'})
        bill.action_post()
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (70, 0))
        original = self.env['erp.budget.move'].search([('source_key', '=', 'account.move.line:%s' % bill.invoice_line_ids.id)])
        self.assertEqual(len(original), 2)
        credit = bill._reverse_moves([{'date': fields.Date.today(), 'journal_id': bill.journal_id.id}])
        credit.invoice_date = fields.Date.today()
        self.assertEqual(credit.invoice_line_ids.erp_budget_fund_id, self.fund)
        credit.action_post()
        self.assertEqual(self.active('actual'), 0)
        credit.button_draft()
        self.assertEqual(self.active('actual'), 70)
        bill.button_draft()
        self.assertEqual(self.active('actual'), 0)
        self.assertEqual(original.exists(), original)
        bill.invoice_line_ids.write({name: False for name in self.direct_dimensions() if name != 'analytic_distribution'})
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.unlink()

    def test_direct_actual_multi_company_ou_and_over_budget(self):
        bill = self.make_direct_bill(110)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual((bill.state, self.active('actual')), ('draft', 0))
        other = self.env['res.company'].create({'name': 'Direct actual other company'})
        other_period = self.env['erp.budget.period'].create({'name': 'Other direct period', 'company_id': other.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        with self.assertRaises((AccessError, ValidationError, UserError)), self.cr.savepoint():
            bill.invoice_line_ids.erp_budget_period_id = other_period
            bill.action_post()
        bill.invoice_line_ids.price_unit = 60
        bill.action_post()
        all_lines = bill.line_ids
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id), ('unit_id', '=', self.unit.id)]).unlink()
        self.assertFalse(self.test_env['account.move'].search([('id', '=', bill.id)]))
        self.assertFalse(self.test_env['account.move.line'].search([('id', 'in', all_lines.ids)]))
        with self.assertRaises(AccessError):
            bill.check_access('read')
        with self.assertRaises(AccessError):
            bill.invoice_line_ids.check_access('read')

    def test_mixed_direct_credit_and_po_actual_check_final_document_total(self):
        self.company.erp_budget_amount_mode = 'net'
        request = self.make_request(80)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 80)
        po.button_confirm()
        bill = self.make_bill(po, 1, 140)
        bill.write({'invoice_line_ids': [(0, 0, dict(self.direct_dimensions(), name='Expense credit', account_id=self.account.id, quantity=1, price_unit=-60, tax_ids=[(5, 0, 0)]))]})
        bill.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 80))
        bill.button_draft()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (80, 0))

    def test_direct_journal_actual_uses_signed_native_balance(self):
        self.company.erp_budget_amount_mode = 'net'
        offset = self.env['account.account'].create({'name': 'Direct offset', 'code': 'DROFF', 'account_type': 'liability_current', 'company_ids': [(6, 0, self.company.ids)]})
        journal = self.env['account.journal'].create({'name': 'Direct journal', 'code': 'DRJ', 'type': 'general', 'company_id': self.company.id})
        move = self.test_env['account.move'].with_company(self.company).create({'move_type': 'entry', 'journal_id': journal.id, 'date': '2026-06-01', 'line_ids': [(0, 0, dict(self.direct_dimensions(), name='Expense', account_id=self.account.id, debit=75)), (0, 0, {'name': 'Offset', 'account_id': offset.id, 'credit': 75})]})
        move.action_post()
        self.assertEqual(self.active('actual'), 75)
        with self.assertRaises(UserError), self.cr.savepoint():
            move.line_ids.with_context(check_move_validity=False).write({'balance': 0})
        move.button_draft()
        self.assertEqual(self.active('actual'), 0)

    def test_direct_budget_exemption_is_explicit_and_preserves_posted_policy(self):
        bill = self.make_direct_bill(70)
        with self.assertRaises(AccessError), self.cr.savepoint():
            bill.erp_budget_exempt = True
        bill.sudo().erp_budget_exempt = True
        bill.action_post()
        self.assertEqual(self.active('actual'), 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.sudo().erp_budget_exempt = False
        bill.button_draft()
        bill.sudo().erp_budget_exempt = False
        bill.action_post()
        self.assertEqual(self.active('actual'), 70)
        bill.journal_id.sudo().erp_budget_exempt = True
        self.assertFalse(bill.erp_budget_exempt)
        bill.button_draft()
        another = self.make_direct_bill(50)
        self.assertTrue(another.erp_budget_exempt)
        another.action_post()
        self.assertEqual(self.active('actual'), 0)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['account.move'].with_context(default_erp_budget_exempt=False).create({'journal_id': bill.journal_id.id, 'company_id': self.company.id, 'move_type': 'in_invoice', 'partner_id': self.vendor.id})

    def test_direct_actual_preserves_native_manual_tax_and_refund(self):
        self.company.write({'erp_budget_amount_mode': 'all', 'country_id': self.env.ref('base.th').id})
        self.env.cr.execute('UPDATE erp_budget_control SET amount=120 WHERE id IN %s', [tuple((self.ac | self.fc).ids)])
        (self.ac | self.fc).invalidate_recordset(['amount'])
        group = self.env['account.tax.group'].create({'name': 'Native manual VAT', 'company_id': self.company.id})
        tax_account = self.env['account.account'].create({'name': 'Manual VAT account', 'code': 'MANTAX', 'account_type': 'asset_current', 'company_ids': [(6, 0, self.company.ids)]})
        tax = self.env['account.tax'].with_company(self.company).create({'name': 'Manual VAT 7', 'amount': 7, 'company_id': self.company.id, 'tax_group_id': group.id, 'type_tax_use': 'purchase'})
        (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(lambda item: item.repartition_type == 'tax').account_id = tax_account
        bill = self.make_direct_bill(100)
        bill.invoice_line_ids.tax_ids = tax
        from copy import deepcopy
        totals = deepcopy(bill.tax_totals)
        totals['subtotals'][0]['tax_groups'][0]['tax_amount_currency'] = 8
        bill.tax_totals = totals
        bill.action_post()
        self.assertEqual((sum(bill.line_ids.filtered('tax_line_id').mapped('balance')), self.active('actual')), (8, 108))
        self.assertEqual(bill.invoice_line_ids.erp_budget_amount_snapshot['included_tax_company'], 8)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.line_ids.filtered('tax_line_id').write({'balance': 9})
        credit = bill._reverse_moves([{'date': fields.Date.today(), 'journal_id': bill.journal_id.id}])
        credit.invoice_date = fields.Date.today()
        credit.action_post()
        # Changing the native credit-note date recomputes VAT to 7; Budget must
        # retain the same one-unit difference as the actual journal entries.
        self.assertEqual((sum(credit.line_ids.filtered('tax_line_id').mapped('balance')), self.active('actual')), (-7, 1))
        credit.button_draft()
        totals = deepcopy(credit.tax_totals)
        totals['subtotals'][0]['tax_groups'][0]['tax_amount_currency'] = 8
        credit.tax_totals = totals
        credit.action_post()
        self.assertEqual(self.active('actual'), 0)
        journal = self.env['account.journal'].create({'name': 'Taxed direct journal', 'code': 'DTX', 'type': 'general', 'company_id': self.company.id})
        offset = self.env['account.account'].create({'name': 'Taxed direct offset', 'code': 'DTXOFF', 'account_type': 'liability_current', 'company_ids': [(6, 0, self.company.ids)]})
        tax_repartition = tax.invoice_repartition_line_ids.filtered(lambda item: item.repartition_type == 'tax')
        entry = self.test_env['account.move'].with_company(self.company).create({'move_type': 'entry', 'journal_id': journal.id, 'date': '2026-06-01', 'line_ids': [(0, 0, dict(self.direct_dimensions(), name='Taxed expense', account_id=self.account.id, debit=100, tax_ids=[(6, 0, tax.ids)])), (0, 0, {'name': 'VAT', 'account_id': tax_account.id, 'debit': 7, 'display_type': 'tax', 'tax_repartition_line_id': tax_repartition.id}), (0, 0, {'name': 'Offset', 'account_id': offset.id, 'credit': 107})]})
        entry.action_post()
        self.assertEqual(self.active('actual'), 107)
        entry.button_draft()
        self.assertEqual(self.active('actual'), 0)

    def make_expense(self, amount=60):
        self.user.write({'group_ids': [(4, self.env.ref('hr_expense.group_hr_expense_manager').id), (4, self.env.ref('erp_budget.group_budget_user').id)]})
        employee = self.env['hr.employee'].create({'name': 'Budget expense employee', 'company_id': self.company.id, 'expense_manager_id': self.user.id})
        payable = self.env['account.account'].create({'name': 'Expense payable', 'code': 'EXPPAY', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, [self.company.id])]})
        employee.work_contact_id.with_company(self.company).property_account_payable_id = payable
        journal = self.env['account.journal'].create({'name': 'Expenses', 'code': 'EXP', 'type': 'purchase', 'company_id': self.company.id, 'default_account_id': self.account.id})
        self.company.expense_journal_id = journal
        self.product.can_be_expensed = True
        return self.test_env['hr.expense'].create({'name': 'Budget expense', 'company_id': self.company.id, 'employee_id': employee.id, 'product_id': self.product.id, 'account_id': self.account.id, 'date': '2026-06-01', 'quantity': 1, 'total_amount_currency': amount, 'currency_id': self.company.currency_id.id, 'tax_ids': [(5, 0, 0)], 'analytic_distribution': {str(self.analytic.id): 100}, 'erp_budget_period_id': self.period.id, 'erp_budget_organization_id': self.unit.id, 'erp_budget_fund_id': self.fund.id, 'erp_budget_analytic_id': self.analytic.id})

    def test_expense_approval_post_reset_and_immutable_history(self):
        expense = self.make_expense()
        expense.action_submit()
        self.assertEqual(self.total(), 0)
        expense.action_approve()
        self.assertEqual((expense.approval_state, self.active('expense_commitment')), ('approved', 60))
        bill = expense.account_move_id
        self.assertEqual(bill.state, 'draft')
        bill.action_post()
        self.assertEqual((self.active('expense_commitment'), self.active('actual')), (0, 60))
        moves = self.env['erp.budget.move'].search([('family_key', '=', expense._budget_family())])
        self.assertTrue(moves)
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.total_amount_currency = 1
        bill.button_draft()
        self.assertEqual((self.active('expense_commitment'), self.active('actual')), (60, 0))
        # Native reset normally deletes draft accounting. Historical lines must
        # instead remain auditable; the adapter must retain a cancelled entry.
        expense.action_reset()
        self.assertFalse(expense.approval_state)
        self.assertEqual(self.total(), 0)
        self.assertEqual(len(moves.exists()), len(moves))
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.unlink()

    def test_expense_insufficient_submission_and_approval_are_atomic(self):
        expense = self.make_expense(110)
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.action_submit()
        self.assertFalse(expense.approval_state)
        self.assertEqual(self.total(), 0)
        expense.total_amount_currency = 80
        expense.action_submit()
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.action_approve()
        self.assertEqual(expense.approval_state, 'submitted')
        self.assertFalse(expense.account_move_id)
        self.assertEqual(self.total(), 30)

    def test_expense_raw_approval_and_ou_revocation_are_rejected(self):
        expense = self.make_expense()
        with self.assertRaises(AccessError), self.cr.savepoint():
            expense.write({'approval_state': 'approved'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            expense.write({'erp_budget_amount': 1})
        expense.action_submit()
        expense.action_approve()
        bill = expense.account_move_id
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            expense.action_reset()
        with self.assertRaises(AccessError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(self.total(), 60)

    def test_expense_tax_policy_refund_and_cancelled_history_cannot_repost(self):
        expense = self.make_expense(80)
        self.company.write({'country_id': self.env.ref('base.th').id, 'erp_budget_amount_mode': 'all'})
        tax_group = self.env['account.tax.group'].create({'name': 'Expense VAT group', 'company_id': self.company.id})
        tax = self.env['account.tax'].with_company(self.company).create({'name': 'Expense VAT', 'amount': 7, 'type_tax_use': 'purchase', 'company_id': self.company.id, 'tax_group_id': tax_group.id})
        expense.write({'tax_ids': [(6, 0, tax.ids)], 'total_amount_currency': 85.6})
        expense.action_submit()
        expense.action_approve()
        self.assertAlmostEqual(expense.erp_budget_amount, 85.6)
        bill = expense.account_move_id
        bill.action_post()
        self.assertAlmostEqual(self.active('actual'), 85.6)
        reverse = bill._reverse_moves(default_values_list=[{'date': bill.date, 'invoice_date': bill.invoice_date}])
        reverse.action_post()
        self.assertAlmostEqual(self.total(), 0)
        reverse.button_draft()
        bill.button_draft()
        expense.action_reset()
        self.assertEqual(bill.state, 'cancel')
        expense.total_amount_currency = 40
        expense.action_submit()
        expense.action_approve()
        self.assertEqual(self.active('expense_commitment'), 40)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()

    def test_expense_company_payment_and_accounting_scope(self):
        expense = self.make_expense(70)
        bank = self.env['account.account'].create({'name': 'Expense bank', 'code': 'EXPBANK', 'account_type': 'asset_cash', 'company_ids': [(6, 0, [self.company.id])]})
        outstanding = self.env['account.account'].create({'name': 'Expense outstanding', 'code': 'EXPOUT', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, [self.company.id])]})
        journal = self.env['account.journal'].create({'name': 'Expense bank', 'code': 'EXPB', 'type': 'bank', 'company_id': self.company.id, 'default_account_id': bank.id})
        method = journal.outbound_payment_method_line_ids[:1]
        method.payment_account_id = outstanding
        expense.write({'payment_mode': 'company_account', 'payment_method_line_id': method.id})
        expense.action_submit()
        expense.action_approve()
        bill = expense.account_move_id
        self.assertEqual(self.active('expense_commitment'), 70)
        bill.action_post()
        self.assertEqual((self.active('expense_commitment'), self.active('actual')), (0, 70))
        bad_company = self.env['res.company'].create({'name': 'Expense other company'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            bill.with_context(allowed_company_ids=bad_company.ids).button_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.line_ids.filtered(lambda line: not line.expense_id).write({'balance': -1})

    def test_expense_ordered_tiers_reject_resubmit_and_final_capacity(self):
        expense = self.make_expense(80)
        reviewers = self.env['res.users'].create([{'name': 'Expense reviewer '+str(number), 'login': 'expense_reviewer_'+str(number), 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, [self.env.ref('hr_expense.group_hr_expense_manager').id, self.env.ref('erp_budget.group_budget_user').id])]} for number in (1, 2)])
        for sequence, reviewer in enumerate(reviewers, 1):
            self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
            self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'kind': 'expense', 'reviewer_id': reviewer.id, 'sequence': sequence})
        expense.action_submit()
        self.assertEqual(len(expense.erp_review_ids), 2)
        with self.assertRaises(AccessError), self.cr.savepoint():
            expense.with_user(reviewers[1]).action_approve()
        with self.assertRaises(AccessError), self.cr.savepoint():
            expense.action_approve()
        expense.with_user(reviewers[0]).action_approve()
        expense.with_user(reviewers[0]).action_approve()
        self.assertEqual(self.total(), 0)
        self.assertFalse(expense.account_move_id)
        expense.with_user(reviewers[1])._do_refuse('Correct the expense')
        old = expense.erp_review_ids
        expense.action_reset()
        expense.action_submit()
        self.assertEqual(len(expense.erp_review_ids), 4)
        self.assertTrue(old.exists())
        expense.with_user(reviewers[0]).action_approve()
        request = self.make_request(30)
        request.action_submit()
        request.action_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.with_user(reviewers[1]).action_approve()
        self.assertEqual(expense.approval_state, 'submitted')
        request.action_reject()
        expense.with_user(reviewers[1]).action_approve()
        self.assertEqual((expense.approval_state, self.total()), ('approved', 80))
        with self.assertRaises(AccessError), self.cr.savepoint():
            expense.erp_review_ids.sudo().write({'state': 'approved'})

    def test_expense_forward_preserves_fiscal_origin_and_native_actuals(self):
        expense = self.make_expense(60)
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        expense.action_submit()
        expense.action_approve()
        old = self.env['erp.budget.move'].search([('family_key', '=', expense._budget_family())])
        source = self.test_env['erp.budget.plan'].create({'name': 'Expense source plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        source.action_confirm()
        period = self.env['erp.budget.period'].create({'name': 'Expense next year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        analytic = self.env['account.analytic.account'].create({'name': 'Expense next analytic', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        plan = self.test_env['erp.budget.plan'].create({'name': 'Expense next plan', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': analytic.id, 'initial_amount': 100})]})
        plan.action_confirm()
        vals = {'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': analytic.id, 'amount': 100}
        controls = self.test_env['erp.budget.control'].create([dict(vals, name='Expense next analytic', level='analytic'), dict(vals, name='Expense next fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        forward = self.test_env['erp.budget.commit.forward'].create({'name': 'Expense forward', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': period.id})
        forward.action_review()
        row = forward._current_lines()
        self.assertEqual((row.source_key, row.move_type, row.amount), (expense._budget_family(), 'expense_commitment', 60))
        row.write({'destination_analytic_control_id': controls.filtered(lambda control: control.level == 'analytic').id, 'destination_fund_control_id': controls.filtered(lambda control: control.level == 'fund').id})
        forward.action_forward()
        forward.action_forward()
        self.assertEqual(self.total(), 0)
        self.ac, self.fc = controls.filtered(lambda control: control.level == 'analytic'), controls.filtered(lambda control: control.level == 'fund')
        self.assertEqual(self.active('expense_commitment'), 60)
        bill = expense.account_move_id
        bill.write({'date': '2027-01-02', 'invoice_date': '2027-01-02'})
        bill.invoice_line_ids.analytic_distribution = {str(analytic.id): 100}
        bill.action_post()
        self.assertEqual((self.active('expense_commitment'), self.active('actual')), (0, 60))
        bill.button_draft()
        self.assertEqual((self.active('expense_commitment'), self.active('actual')), (60, 0))
        self.assertEqual(len(old.exists()), len(old))
        self.assertEqual(old.mapped('amount'), [60, 60])

    def test_uncontrolled_native_expense_does_not_require_budget_role(self):
        expense = self.make_expense(40)
        expense.write({'erp_budget_period_id': False, 'erp_budget_organization_id': False, 'erp_budget_fund_id': False, 'erp_budget_analytic_id': False, 'analytic_distribution': False})
        self.user.write({'group_ids': [(6, 0, [self.env.ref('hr_expense.group_hr_expense_manager').id, self.env.ref('account.group_account_invoice').id])]})
        self.assertFalse(self.user.has_group('erp_budget.group_budget_user'))
        expense.action_submit()
        expense.action_approve()
        expense.account_move_id.action_post()
        self.assertEqual(self.total(), 0)

    def make_advance(self, amount=80):
        expense = self.make_expense(amount)
        advance_account = self.env['account.account'].create({'name': 'Employee advances', 'code': 'ADVACC', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        journal = self.env['account.journal'].create({'name': 'Advance settlement', 'code': 'ADVS', 'type': 'general', 'company_id': self.company.id})
        bank = self.env['account.account'].create({'name': 'Advance return bank', 'code': 'ADVBANK', 'account_type': 'asset_cash', 'company_ids': [(6, 0, self.company.ids)]})
        bank_journal = self.env['account.journal'].create({'name': 'Advance bank', 'code': 'ADVB', 'type': 'bank', 'company_id': self.company.id, 'default_account_id': bank.id})
        self.company.write({'erp_employee_advance_account_id': advance_account.id, 'erp_employee_advance_journal_id': journal.id})
        expense.write({'erp_is_advance': True, 'account_id': advance_account.id})
        return expense, bank_journal

    def make_clearing(self, advance, amount):
        return self.test_env['hr.expense'].create({'name': 'Advance clearing', 'company_id': self.company.id, 'employee_id': advance.employee_id.id, 'product_id': self.product.id, 'erp_advance_ids': [(6, 0, advance.ids)], 'account_id': self.account.id, 'total_amount_currency': amount, 'quantity': 1, 'currency_id': self.company.currency_id.id, 'tax_ids': [(5, 0, 0)], 'date': '2026-06-02', 'erp_budget_period_id': self.period.id, 'erp_budget_organization_id': self.unit.id, 'erp_budget_fund_id': self.fund.id, 'erp_budget_analytic_id': self.analytic.id, 'analytic_distribution': {str(self.analytic.id): 100}})

    def make_advance_return(self, advance, bank, amount):
        return self.test_env['erp.finance.advance.return'].create({'name': 'Return unused advance', 'advance_id': advance.id, 'journal_id': bank.id, 'date': '2026-06-03', 'amount': amount, 'currency_id': self.company.currency_id.id})

    def test_advance_clearing_return_accounting_and_budget_reversals(self):
        advance, bank = self.make_advance()
        advance.action_submit()
        advance.action_approve()
        advance.account_move_id.action_post()
        self.assertEqual((self.active('advance_commitment'), self.active('actual'), advance.erp_advance_remaining), (80, 0, 80))
        clearing = self.make_clearing(advance, 30)
        clearing.action_submit()
        self.assertEqual(self.total(), 80)
        clearing.action_approve()
        self.assertEqual((self.active('advance_commitment'), self.active('expense_commitment')), (50, 30))
        bill = clearing.account_move_id
        bill.action_post()
        self.assertEqual((self.active('advance_commitment'), self.active('expense_commitment'), self.active('actual')), (50, 0, 30))
        self.assertEqual((advance.erp_advance_remaining, bill.amount_residual), (50, 0))
        settlements = clearing.erp_advance_settlement_ids
        self.assertEqual(len(settlements), 1)
        with self.assertRaises(UserError), self.cr.savepoint():
            advance.account_move_id.button_draft()
        returned = self.make_advance_return(advance, bank, 20)
        returned.action_post()
        returned.action_post()
        self.assertEqual((self.total(), advance.erp_advance_remaining), (60, 30))
        node = self.env['erp.budget.move'].search([('control_id', '=', self.ac.id), ('family_key', '=', advance._budget_family()), ('move_type', '=', 'advance_commitment')], order='id desc', limit=1)
        self.assertEqual(node.amount_snapshot['clearing_allocations'], {str(clearing.id): 30})
        self.assertEqual(node.amount_snapshot['return_line_ids'], returned.move_id.line_ids.filtered('erp_advance_origin_id').ids)
        returned.action_cancel()
        self.assertEqual((self.total(), advance.erp_advance_remaining), (80, 50))
        bill.button_draft()
        clearing.action_reset()
        self.assertEqual((self.active('advance_commitment'), self.total(), advance.erp_advance_remaining), (80, 80, 80))
        self.assertEqual(settlements.state, 'cancel')
        with self.assertRaises(UserError), self.cr.savepoint():
            settlements.unlink()

    def test_advance_pending_clearings_limit_return_and_excess_remains_payable(self):
        advance, bank = self.make_advance()
        advance.action_submit()
        advance.action_approve()
        advance.account_move_id.action_post()
        clearing = self.make_clearing(advance, 100)
        clearing.action_submit()
        clearing.action_approve()
        self.assertEqual((self.active('advance_commitment'), self.active('expense_commitment')), (0, 100))
        returned = self.make_advance_return(advance, bank, 1)
        with self.assertRaises(UserError), self.cr.savepoint():
            returned.action_post()
        self.assertEqual(returned.state, 'draft')
        clearing.account_move_id.action_post()
        self.assertEqual((advance.erp_advance_remaining, clearing.account_move_id.amount_residual, self.total()), (0, 20, 100))

    def test_advance_return_cancellation_cannot_restore_consumed_capacity(self):
        advance, bank = self.make_advance()
        advance.action_submit()
        advance.action_approve()
        advance.account_move_id.action_post()
        returned = self.make_advance_return(advance, bank, 30)
        returned.action_post()
        request = self.make_request(40)
        request.action_submit()
        request.action_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            returned.action_cancel()
        self.assertEqual((returned.state, returned.move_id.state, self.total(), advance.erp_advance_remaining), ('done', 'posted', 90, 50))
        with self.assertRaises(AccessError), self.cr.savepoint():
            returned.move_id.button_draft()
        with self.assertRaises(AccessError), self.cr.savepoint():
            returned.move_id.line_ids.write({'balance': 0})
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            returned.action_cancel()

    def test_advance_kpi_uses_shared_plan_without_extra_child_capacity(self):
        advance, bank = self.make_advance(80)
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        self.ac.action_close()
        kpi = self.env['erp.budget.kpi'].create({'name': 'Employee advance reservation', 'company_id': self.company.id, 'advance_reservation': True})
        template = self.env['erp.budget.template'].create({'name': 'Advance template', 'company_id': self.company.id, 'line_ids': [(0, 0, {'kpi_id': kpi.id, 'account_id': advance.account_id.id})]})
        self.period = self.env['erp.budget.period'].create({'name': 'Advance KPI period', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31', 'template_id': template.id, 'control_level': 'analytic_kpi'})
        advance.write({'erp_budget_period_id': self.period.id, 'date': '2027-06-01'})
        self.fc = self.test_env['erp.budget.control'].create({'name': 'Advance KPI fund', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'level': 'fund', 'amount': 200})
        self.fc.action_open()
        shared = self.test_env['erp.budget.plan'].create({'name': 'Advance shared cap', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        shared.action_confirm()
        tracked = self.test_env['erp.budget.control'].create({'name': 'Advance tracking', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'kpi_id': kpi.id, 'amount': 0})
        tracked.action_open()
        self.ac = tracked
        advance.action_submit()
        advance.action_approve()
        advance.account_move_id.action_post()
        self.assertEqual((tracked.amount, shared.line_ids._consumed(), self.active('advance_commitment'), self.active('actual')), (0, 80, 80, 0))
        excess = self.make_clearing(advance, 30)
        excess.write({'erp_is_advance': True, 'erp_advance_ids': [(5, 0, 0)], 'account_id': advance.account_id.id, 'date': '2027-06-03'})
        with self.assertRaises(UserError), self.cr.savepoint():
            excess.action_submit()
        # The KPI does not authorize ordinary transactions or extra parent funds.
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.test_env['erp.budget.control.service']._commit(tracked | self.fc, 1, '2027-06-02', 'forged-advance-origin')
        with self.assertRaises(UserError), self.cr.savepoint():
            kpi.advance_reservation = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            tracked.copy({'amount': 100, 'state': 'draft'})
        returned = self.make_advance_return(advance, bank, 20)
        returned.action_post()
        self.assertEqual(shared.line_ids._consumed(), 60)

    def test_multiple_advances_clear_oldest_first_and_pending_scope_is_preserved(self):
        first, bank = self.make_advance(40)
        second = self.make_clearing(first, 40)
        second.write({'erp_is_advance': True, 'erp_advance_ids': [(5, 0, 0)], 'account_id': first.account_id.id, 'date': '2026-06-03'})
        for advance in (first, second):
            advance.action_submit()
            advance.action_approve()
            advance.account_move_id.action_post()
        clearing = self.make_clearing(first, 60)
        clearing.erp_advance_ids = first | second
        clearing.action_submit()
        clearing.action_approve()
        self.assertEqual((self.active('advance_commitment'), self.active('expense_commitment')), (20, 60))
        clearing.account_move_id.action_post()
        self.assertEqual((first.erp_advance_remaining, second.erp_advance_remaining), (0, 20))
        with self.assertRaises(AccessError), self.cr.savepoint():
            clearing.erp_advance_settlement_ids.button_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            clearing.erp_advance_ids = first
        clearing.account_move_id.button_draft()
        clearing.action_reset()
        self.assertEqual((first.erp_advance_remaining, second.erp_advance_remaining, self.active('advance_commitment')), (40, 40, 80))

    def test_advance_foreign_currency_uses_native_company_amount_and_bank_return(self):
        advance, bank = self.make_advance(80)
        self.company.erp_budget_amount_mode = 'net'
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-06-01', 'rate': 1})
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-06-01', 'rate': 2})
        advance.write({'currency_id': foreign.id, 'total_amount_currency': 80})
        self.assertEqual(advance.total_amount, 40)
        advance.action_submit()
        advance.action_approve()
        advance.account_move_id.action_post()
        self.assertEqual((self.active('advance_commitment'), advance.erp_advance_remaining), (40, 40))
        bank.currency_id = foreign
        returned = self.make_advance_return(advance, bank, 20)
        returned.currency_id = foreign
        returned.action_post()
        self.assertEqual((self.active('advance_commitment'), advance.erp_advance_remaining), (30, 30))
        self.assertEqual(returned.move_id.line_ids.filtered('erp_advance_origin_id').balance, -10)
        self.assertEqual(returned.move_id.line_ids.filtered('erp_advance_origin_id').amount_currency, -20)

    def test_advance_forward_then_next_year_clearing_keeps_native_origins(self):
        expense, bank = self.make_advance(60)
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        expense.action_submit()
        expense.action_approve()
        expense.account_move_id.action_post()
        old = self.env['erp.budget.move'].search([('family_key', '=', expense._budget_family())])
        source = self.test_env['erp.budget.plan'].create({'name': 'Expense source plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        source.action_confirm()
        period = self.env['erp.budget.period'].create({'name': 'Expense next year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        analytic = self.env['account.analytic.account'].create({'name': 'Expense next analytic', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        plan = self.test_env['erp.budget.plan'].create({'name': 'Expense next plan', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': analytic.id, 'initial_amount': 100})]})
        plan.action_confirm()
        vals = {'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': analytic.id, 'amount': 100}
        controls = self.test_env['erp.budget.control'].create([dict(vals, name='Expense next analytic', level='analytic'), dict(vals, name='Expense next fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        forward = self.test_env['erp.budget.commit.forward'].create({'name': 'Expense forward', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': period.id})
        forward.action_review()
        row = forward._current_lines()
        self.assertEqual((row.source_key, row.move_type, row.amount), (expense._budget_family(), 'advance_commitment', 60))
        row.write({'destination_analytic_control_id': controls.filtered(lambda control: control.level == 'analytic').id, 'destination_fund_control_id': controls.filtered(lambda control: control.level == 'fund').id})
        forward.action_forward()
        forward.action_forward()
        self.assertEqual(self.total(), 0)
        self.ac, self.fc = controls.filtered(lambda control: control.level == 'analytic'), controls.filtered(lambda control: control.level == 'fund')
        self.assertEqual(self.active('advance_commitment'), 60)
        self.period = period
        self.analytic = analytic
        clearing = self.make_clearing(expense, 40)
        clearing.date = '2027-01-02'
        clearing.action_submit()
        clearing.action_approve()
        bill = clearing.account_move_id
        bill.write({'date': '2027-01-02', 'invoice_date': '2027-01-02'})
        bill.action_post()
        self.assertEqual((self.active('advance_commitment'), self.active('actual'), expense.erp_advance_remaining), (20, 40, 20))
        self.assertEqual(expense.account_move_id.invoice_line_ids.analytic_distribution, {str(source.line_ids.analytic_id.id): 100})
        self.assertEqual(bill.invoice_line_ids.analytic_distribution, {str(analytic.id): 100})
        bill.button_draft()
        clearing.action_reset()
        self.assertEqual((self.active('advance_commitment'), self.active('actual'), expense.erp_advance_remaining), (60, 0, 60))
        self.assertEqual(len(old.exists()), len(old))
        self.assertEqual(old.mapped('amount'), [60, 60])


    def test_advance_prepare_actions_create_scoped_native_drafts(self):
        advance, bank = self.make_advance(60)
        advance.erp_clearing_product_id = self.product
        advance.action_submit()
        advance.action_approve()
        advance.account_move_id.action_post()
        action = advance.action_prepare_clearing()
        clearing = self.test_env['hr.expense'].with_context(**action['context']).create({})
        self.assertEqual((clearing.erp_advance_ids, clearing.employee_id, clearing.account_id, clearing.total_amount, clearing.erp_budget_period_id), (advance, advance.employee_id, self.account, 60, self.period))
        self.assertFalse(clearing.erp_is_advance or clearing.approval_state)
        action = advance.action_prepare_advance_return()
        returned = self.test_env['erp.finance.advance.return'].with_context(**action['context']).create({'journal_id': bank.id})
        self.assertEqual((returned.advance_id, returned.amount, returned.state), (advance, 60, 'draft'))

    def make_deposit(self, po, amount=30):
        origin = po.order_line.filtered('erp_request_line_id')[:1]
        bill = self.make_bill(po, 1, amount)
        bill.invoice_line_ids.write({'purchase_line_id': False, 'product_id': False})
        bill.action_post()
        wizard = self.test_env['bill.to.po.wizard'].with_context(active_ids=[-bill.invoice_line_ids.id]).create({'purchase_order_id': po.id, 'erp_deposit_origin_id': origin.id})
        wizard.action_add_downpayment()
        return bill

    def test_purchase_deposit_native_final_bill_reset_and_history(self):
        request, po = self.scenario()
        original = po.order_line
        deposit = self.make_deposit(po)
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (70, 30))
        count = self.env['erp.budget.move'].search_count([])
        request.line_ids._reconcile_budget(True)
        self.assertEqual(self.env['erp.budget.move'].search_count([]), count)
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_cancel()
        po.action_create_invoice()
        final = po.invoice_ids.filtered(lambda move: move.state == 'draft')
        self.assertEqual(len(final), 1)
        final.write({'invoice_date': '2026-10-30', 'date': '2026-10-30'})
        self.assertEqual(final.invoice_line_ids.filtered(lambda line: line.purchase_line_id.is_downpayment and not line.display_type == 'line_section').quantity, -1)
        final.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 100))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            deposit.button_draft()
        self.assertEqual(deposit.state, 'posted')
        final.button_draft()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (70, 30))
        deposit.button_draft()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (100, 0))
        deposit.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (70, 30))
        self.assertTrue(original.exists())

    def test_purchase_deposit_partial_deduction_and_scope_guards(self):
        request, po = self.scenario()
        deposit = self.make_deposit(po, 40)
        dpl = deposit.invoice_line_ids.purchase_line_id
        po.action_create_invoice()
        partial = po.invoice_ids.filtered(lambda move: move.state == 'draft')
        partial.invoice_date = '2026-10-30'
        partial.invoice_line_ids.filtered(lambda line: line.purchase_line_id == dpl).quantity = -0.5
        partial.invoice_line_ids.filtered(lambda line: line.purchase_line_id.erp_request_line_id).quantity = 4
        partial.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (40, 60))
        po.action_create_invoice()
        over = po.invoice_ids.filtered(lambda move: move.state == 'draft')
        over.invoice_date = '2026-10-30'
        over.invoice_line_ids.filtered(lambda line: line.purchase_line_id == dpl).quantity = -1
        with self.assertRaises(ValidationError), self.cr.savepoint():
            over.action_post()
        with self.assertRaises((UserError, AccessError)), self.cr.savepoint():
            dpl.write({'erp_deposit_origin_id': False})
        with self.assertRaises(UserError), self.cr.savepoint():
            po.order_line.filtered('erp_request_line_id').write({'is_downpayment': True})
        with self.assertRaises(UserError), self.cr.savepoint():
            deposit.invoice_line_ids.write({'purchase_line_id': False})
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (40, 60))

    def test_purchase_deposit_refund_and_cross_organization_denial(self):
        request, po = self.scenario()
        deposit = self.make_deposit(po, 30)
        refund = deposit._reverse_moves([{'date': deposit.date, 'invoice_date': deposit.invoice_date}], cancel=False)
        refund.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (100, 0))
        refund.button_draft()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (70, 30))
        outsider = self.env['res.users'].create({'name': 'Deposit outsider', 'login': 'deposit_outsider', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, self.user.group_ids.ids)]})
        for records in (deposit, deposit.line_ids, deposit.invoice_line_ids.purchase_line_id, po):
            with self.assertRaises(AccessError), self.cr.savepoint():
                records.with_user(outsider).check_access('read')
        other_company = self.env['res.company'].create({'name': 'Deposit other company'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            deposit.with_context(allowed_company_ids=other_company.ids).check_access('read')
        dpl = deposit.invoice_line_ids.purchase_line_id
        with self.assertRaises(UserError), self.cr.savepoint():
            self.test_env['purchase.order.line'].create({'order_id': po.id, 'name': 'Forged deposit', 'is_downpayment': True, 'product_qty': 0, 'price_unit': 10})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['purchase.order.line'].with_context(default_erp_deposit_origin_id=dpl.erp_deposit_origin_id.id).create({'order_id': po.id, 'name': 'Forged origin', 'product_qty': 0, 'price_unit': 10})
        with self.assertRaises(UserError), self.cr.savepoint():
            refund.write({'state': 'posted'})

    def test_purchase_deposit_foreign_native_amount(self):
        self.company.erp_budget_amount_mode = 'net'
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 1})
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 0.5})
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 50)
        po.currency_id = foreign
        po.button_confirm()
        bill = self.make_bill(po, 1, 15)
        bill.currency_id = foreign
        bill.invoice_line_ids.write({'purchase_line_id': False, 'product_id': False})
        bill.action_post()
        self.test_env['bill.to.po.wizard'].with_context(active_ids=[-bill.invoice_line_ids.id]).create({'purchase_order_id': po.id}).action_add_downpayment()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (70, 30))
        po.action_create_invoice()
        final = po.invoice_ids.filtered(lambda move: move.state == 'draft')
        final.invoice_date = '2026-10-30'
        final.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 100))
        self.assertEqual(final.amount_total, 35)
        self.assertTrue(all(line.erp_budget_amount_snapshot for line in final._erp_finance_lines()))

    def test_purchase_deposit_forward_keeps_prior_actual_and_routes_deduction(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        request, po = self.scenario()
        origin = po.order_line
        deposit = self.make_deposit(po, 30)
        old_rows = self.env['erp.budget.move'].search([('control_id', '=', self.ac.id)])
        old_amounts = {row.id: row.amount for row in old_rows}
        plan = self.test_env['erp.budget.plan'].create({'name': 'Deposit source', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 120})]})
        plan.action_confirm()
        period = self.env['erp.budget.period'].create({'name': 'Deposit next fiscal year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        analytic = self.env['account.analytic.account'].create({'name': 'Deposit next analytic', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        plan2 = self.test_env['erp.budget.plan'].create({'name': 'Deposit destination', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': analytic.id, 'initial_amount': 70})]})
        plan2.action_confirm()
        base = {'company_id': self.company.id, 'organization_id': self.unit.id, 'period_id': period.id, 'analytic_id': analytic.id, 'amount': 70}
        controls = self.test_env['erp.budget.control'].create([dict(base, name='Deposit analytic', level='analytic'), dict(base, name='Deposit fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        forward = self.test_env['erp.budget.commit.forward'].create({'name': 'Deposit remainder 70', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': period.id})
        forward.action_review()
        row = forward._current_lines()
        self.assertEqual((row.source_key, row.amount), ('purchase.order.line:%s' % origin.id, 70))
        row.write({'destination_analytic_control_id': controls.filtered(lambda control: control.level == 'analytic').id, 'destination_fund_control_id': controls.filtered(lambda control: control.level == 'fund').id})
        forward.action_forward()
        po.action_create_invoice()
        bill = po.invoice_ids.filtered(lambda move: move.state == 'draft')
        bill.write({'date': '2027-06-01', 'invoice_date': '2027-06-01'})
        bill.action_post()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 30))
        self.ac = controls.filtered(lambda control: control.level == 'analytic')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (0, 70))
        self.assertEqual({row.id: row.amount for row in old_rows}, old_amounts)
        self.assertEqual(deposit.invoice_line_ids.analytic_distribution, {str(self.analytic.id): 100})
        self.assertTrue(all(line.analytic_distribution == {str(analytic.id): 100} for line in bill._erp_finance_lines()))
        bill.button_draft()
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (70, 0))

    def test_request_expense_handoff_simulation_post_and_reset(self):
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        expense = self.make_expense(60)
        expense.employee_id.sudo().user_id = self.user
        expense.erp_request_line_id = request.line_ids
        expense.action_submit()
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment')), (100, 0))
        expense.action_approve()
        self.assertEqual(expense.erp_budget_snapshot['request_line_id'], request.line_ids.id)
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment')), (0, 60))
        request.line_ids._reconcile_budget(True)
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment')), (0, 60))
        bill = expense.account_move_id
        bill.action_post()
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment'), self.active('actual')), (0, 0, 60))
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_reject()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.make_po(request, 60)
        bill.button_draft()
        expense.action_reset()
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment'), self.active('actual')), (100, 0, 0))
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.erp_request_line_id = False
        self.assertEqual(bill.state, 'cancel')

    def test_request_expense_duplicate_and_manager_variance(self):
        request = self.make_request(50)
        request.action_submit()
        request.action_approve()
        expense = self.make_expense(60)
        expense.employee_id.sudo().user_id = self.user
        expense.erp_request_line_id = request.line_ids
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.action_submit()
        expense.erp_request_amount_override = True
        expense.action_submit()
        expense.action_approve()
        duplicate = expense.copy({'name': 'Second expense claim', 'erp_request_line_id': request.line_ids.id, 'total_amount_currency': 40, 'erp_request_amount_override': False})
        with self.assertRaises(UserError), self.cr.savepoint():
            duplicate.action_submit()
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment')), (0, 60))

    def test_request_advance_then_clearing_has_single_commitment(self):
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        advance, bank = self.make_advance(80)
        advance.employee_id.sudo().user_id = self.user
        advance.erp_request_line_id = request.line_ids
        advance.action_submit()
        self.assertEqual((self.active('pr_commitment'), self.active('advance_commitment')), (100, 0))
        advance.action_approve()
        advance.account_move_id.action_post()
        clearing = self.make_clearing(advance, 50)
        clearing.action_submit()
        clearing.action_approve()
        clearing.account_move_id.action_post()
        self.assertEqual((self.active('pr_commitment'), self.active('advance_commitment'), self.active('actual')), (0, 30, 50))
        returned = self.make_advance_return(advance, bank, 30)
        returned.action_post()
        self.assertEqual((self.active('pr_commitment'), self.active('advance_commitment'), self.active('actual')), (0, 0, 50))
        request.line_ids._reconcile_budget(True)
        self.assertEqual(self.active('pr_commitment'), 0)

    def test_request_expense_restore_consumed_variance_is_atomic(self):
        request = self.make_request(100)
        request.action_submit()
        request.action_approve()
        expense = self.make_expense(60)
        expense.employee_id.sudo().user_id = self.user
        expense.erp_request_line_id = request.line_ids
        expense.action_submit()
        expense.action_approve()
        other = self.make_request(30)
        other.action_submit()
        other.action_approve()
        bill = expense.account_move_id
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.action_reset()
        self.assertEqual((expense.approval_state, expense.account_move_id, bill.state), ('approved', bill, 'draft'))
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment')), (30, 60))

    def test_request_expense_requires_requester_and_scoped_source(self):
        request = self.make_request(50)
        request.action_submit()
        request.action_approve()
        expense = self.make_expense(40)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            expense.erp_request_line_id = request.line_ids
        expense.employee_id.sudo().user_id = self.user
        expense.erp_request_line_id = request.line_ids
        other = self.env['erp.organization.unit'].create({'name': 'Other request OU', 'code': 'EXRO', 'company_id': self.company.id})
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': other.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            expense.erp_budget_organization_id = other
        self.user.write({'group_ids': [(6, 0, [self.env.ref('erp_procurement.group_procurement_manager').id, self.env.ref('hr_expense.group_hr_expense_user').id, self.env.ref('account.group_account_invoice').id])]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            expense.erp_request_amount_override = True

    def test_request_expense_handoff_after_fiscal_forward(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        request = self.make_request(80)
        request.action_submit()
        request.action_approve()
        later = self.env['erp.budget.period'].create({'name': 'PR expense forward', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        analytic = self.env['account.analytic.account'].create({'name': 'PR expense destination', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        base = {'company_id': self.company.id, 'period_id': later.id, 'organization_id': self.unit.id, 'analytic_id': analytic.id, 'amount': 80}
        controls = self.test_env['erp.budget.control'].create([dict(base, name='PR expense analytic', level='analytic'), dict(base, name='PR expense fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        forward = self.test_env['erp.budget.commit.forward'].create({'name': 'PR before expense', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        forward.action_review()
        forward._current_lines().write({'destination_analytic_control_id': controls.filtered(lambda item: item.level == 'analytic').id, 'destination_fund_control_id': controls.filtered(lambda item: item.level == 'fund').id})
        forward.action_forward()
        expense = self.make_expense(60)
        expense.employee_id.sudo().user_id = self.user
        expense.write({'erp_request_line_id': request.line_ids.id, 'erp_budget_period_id': later.id, 'erp_budget_analytic_id': analytic.id, 'analytic_distribution': {str(analytic.id): 100}, 'date': '2027-06-01'})
        expense.action_submit()
        expense.action_approve()
        expense.account_move_id.write({'date': '2027-06-01', 'invoice_date': '2027-06-01'})
        expense.account_move_id.action_post()
        self.assertEqual(self.total(), 0)
        self.ac = controls.filtered(lambda item: item.level == 'analytic')
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment'), self.active('actual')), (0, 0, 60))
        expense.account_move_id.button_draft()
        expense.action_reset()
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment'), self.active('actual')), (80, 0, 0))

    def make_withholding(self, expense, rate=-3):
        self.company.write({'erp_budget_amount_mode': 'net', 'country_id': self.env.ref('base.th').id})
        base = self.env['account.account'].create({'name': 'Withholding base', 'code': 'WHTBASE', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        liability = self.env['account.account'].create({'name': 'Withholding payable', 'code': 'WHTPAY', 'account_type': 'liability_current', 'company_ids': [(6, 0, self.company.ids)]})
        self.company.withholding_tax_base_account_id = base
        group = self.env['account.tax.group'].create({'name': 'Withholding', 'company_id': self.company.id})
        tax = self.env['account.tax'].create({'tax_group_id': group.id, 'name': 'WHT 3%', 'amount': rate, 'amount_type': 'percent', 'type_tax_use': 'purchase', 'is_withholding_tax': True, 'company_id': self.company.id, 'invoice_repartition_line_ids': [(0, 0, {'repartition_type': 'base'}), (0, 0, {'repartition_type': 'tax', 'account_id': liability.id})], 'refund_repartition_line_ids': [(0, 0, {'repartition_type': 'base'}), (0, 0, {'repartition_type': 'tax', 'account_id': liability.id})]})
        expense.write({'tax_ids': [(6, 0, tax.ids)], 'vendor_id': self.vendor.id, 'erp_tax_invoice_reference': 'SUP-001', 'erp_tax_invoice_date': '2026-06-01'})
        return tax

    def test_withholding_advance_cash_and_budget_are_distinct(self):
        advance, bank = self.make_advance(80)
        advance.action_submit()
        advance.action_approve()
        advance.account_move_id.action_post()
        clearing = self.make_clearing(advance, 80)
        tax = self.make_withholding(clearing)
        clearing.action_submit()
        clearing.action_approve()
        bill = clearing.account_move_id
        bill.action_post()
        payment = clearing.erp_withholding_payment_ids
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.withhold, 'withhold')
        self.assertEqual(payment.partner_id, self.vendor)
        self.assertEqual(payment.withholding_amount, 2.4)
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(sum(payment.move_id.line_ids.filtered(lambda line: line.tax_line_id == tax).mapped('balance')), -2.4)
        self.assertEqual(payment.move_id.line_ids.filtered(lambda line: line.account_type == 'liability_payable').partner_id, advance.employee_id.work_contact_id)
        self.assertEqual((advance.erp_advance_remaining, bill.amount_residual, self.active('actual'), self.active('advance_commitment')), (2.4, 0, 80, 0))
        returned = self.make_advance_return(advance, bank, 2.4)
        returned.action_post()
        self.assertEqual((advance.erp_advance_remaining, self.active('actual'), self.total()), (0, 80, 80))
        excessive = self.make_advance_return(advance, bank, .01)
        with self.assertRaises(UserError), self.cr.savepoint():
            excessive.action_post()
        with self.assertRaises(AccessError), self.cr.savepoint():
            payment.action_cancel()
        with self.assertRaises(AccessError), self.cr.savepoint():
            payment.withholding_line_ids.write({'amount': 1})
        with self.assertRaises(AccessError), self.cr.savepoint():
            payment.move_id.button_draft()
        with self.assertRaises(AccessError), self.cr.savepoint():
            payment.move_id.line_ids.remove_move_reconcile()
        bill.button_draft()
        self.assertEqual(payment.move_id.state, 'cancel')
        self.assertEqual(payment.state, 'canceled')
        clearing.action_reset()
        self.assertEqual((self.total(), advance.erp_advance_remaining), (77.6, 77.6))
        returned.action_cancel()
        self.assertEqual((self.total(), advance.erp_advance_remaining), (80, 80))
        with self.assertRaises(UserError), self.cr.savepoint():
            payment.unlink()

    def test_withholding_ordinary_receipt_preserves_gross_actual_and_supplier(self):
        expense = self.make_expense(100)
        self.make_withholding(expense)
        self.env['account.journal'].create({'name': 'Withholding journal', 'code': 'WHT', 'type': 'general', 'company_id': self.company.id})
        expense.action_submit()
        expense.action_approve()
        expense.account_move_id.action_post()
        self.assertEqual((expense.account_move_id.amount_residual, self.total()), (97, 100))
        self.assertEqual(expense.erp_withholding_payment_ids.withholding_amount, 3)
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.vendor_id = False
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['account.payment'].create({'erp_withholding_expense_id': expense.id})
        expense.account_move_id.button_draft()
        expense.account_move_id.action_post()
        self.assertEqual(len(expense.erp_withholding_payment_ids), 2)
        self.assertEqual(len(expense.erp_withholding_payment_ids.filtered(lambda payment: payment.move_id.state == 'posted')), 1)
        self.assertEqual((expense.account_move_id.amount_residual, self.total()), (97, 100))

    def test_withholding_missing_or_foreign_vendor_is_atomic(self):
        expense = self.make_expense(100)
        self.make_withholding(expense)
        foreign = self.env['res.company'].create({'name': 'Foreign WHT company'})
        partner = self.env['res.partner'].create({'name': 'Foreign WHT supplier', 'company_id': foreign.id})
        expense.vendor_id = False
        expense.action_submit()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            expense.action_approve()
        expense.action_reset()
        expense.vendor_id = partner
        expense.action_submit()
        with self.assertRaises((ValidationError, AccessError)), self.cr.savepoint():
            expense.action_approve()
        self.assertEqual(self.total(), 0)

    def _company_withholding_scenario(self, foreign_currency=False):
        expense = self.make_expense(100)
        tax = self.make_withholding(expense)
        if foreign_currency:
            foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
            foreign.active = True
            self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-06-01', 'rate': 1})
            self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-06-01', 'rate': 2})
            expense.write({'currency_id': foreign.id, 'total_amount_currency': 100})
        expected = expense.total_amount
        bank = self.env['account.account'].create({'name': 'WHT bank', 'code': 'WHTBANK', 'account_type': 'asset_cash', 'company_ids': [(6, 0, self.company.ids)]})
        outstanding = self.env['account.account'].create({'name': 'WHT outstanding', 'code': 'WHTOUT', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, self.company.ids)]})
        journal = self.env['account.journal'].create({'name': 'WHT bank', 'code': 'WHTB', 'type': 'bank', 'company_id': self.company.id, 'default_account_id': bank.id})
        method = journal.outbound_payment_method_line_ids[:1]
        method.payment_account_id = outstanding
        expense.write({'payment_mode': 'company_account', 'payment_method_line_id': method.id})
        expense.action_submit()
        expense.action_approve()
        bill = expense.account_move_id
        bill.action_post()
        self.assertEqual(self.total(), expected)
        self.assertEqual(sum(bill.line_ids.filtered(lambda line: line.account_id == outstanding).mapped('balance')), -expected * .97)
        self.assertEqual(sum(bill.line_ids.filtered(lambda line: line.tax_line_id == tax).mapped('balance')), -expected * .03)
        self.assertEqual((bill.origin_payment_id.withholding_amount, bill.origin_payment_id.withholding_net_amount), (3, 97))
        self.assertEqual(bill.origin_payment_id.partner_id, self.vendor)
        with self.assertRaises(AccessError), self.cr.savepoint():
            bill.origin_payment_id.withholding_line_ids.amount = 2
        bill.button_draft()
        bill.action_post()
        self.assertEqual(sum(bill.line_ids.filtered(lambda line: line.tax_line_id == tax).mapped('balance')), -expected * .03)
        self.assertEqual(self.total(), expected)

    def test_withholding_company_payment_keeps_expense_and_net_cash(self):
        self._company_withholding_scenario()

    def test_withholding_foreign_company_payment(self):
        self._company_withholding_scenario(foreign_currency=True)

    def test_withholding_all_tax_policy_retains_gross_cost(self):
        self.test_withholding_company_payment_keeps_expense_and_net_cash()
        expense = self.test_env['hr.expense'].search([('company_id', '=', self.company.id)])
        bill = expense.account_move_id
        bill.button_draft()
        self.company.erp_budget_amount_mode = 'all'
        bill.action_post()
        self.assertEqual(self.total(), 100)
        self.assertEqual(bill._erp_expense_lines().erp_budget_actual_company, 100)

    def test_withholding_foreign_clearing_and_ou_scope(self):
        advance, bank = self.make_advance(80)
        advance.action_submit()
        advance.action_approve()
        advance.account_move_id.action_post()
        clearing = self.make_clearing(advance, 80)
        self.make_withholding(clearing)
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-06-01', 'rate': 1})
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-06-01', 'rate': 2})
        clearing.write({'currency_id': foreign.id, 'total_amount_currency': 100})
        clearing.action_submit()
        clearing.action_approve()
        clearing.account_move_id.action_post()
        payment = clearing.erp_withholding_payment_ids
        self.assertEqual((self.active('actual'), advance.erp_advance_remaining, payment.withholding_amount), (50, 31.5, 1.5))
        self.assertEqual(payment.currency_id, self.company.currency_id)
        self.assertEqual(self.total(), 80)
        protected = (payment, payment.move_id, payment.move_id.line_ids, payment.withholding_line_ids)
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id), ('unit_id', '=', self.unit.id)]).unlink()
        for record in protected:
            with self.assertRaises(AccessError), self.cr.savepoint():
                record.with_user(self.user).read(['id'])
        with self.assertRaises(AccessError), self.cr.savepoint():
            clearing.account_move_id.button_draft()

    def test_withholding_vat_supplier_invoice_provenance(self):
        expense = self.make_expense(80)
        withholding = self.make_withholding(expense)
        self.company.write({'erp_budget_amount_mode': 'all', 'l10n_th_is_vat_registered': True})
        group = self.env['account.tax.group'].create({'name': 'Supplier VAT', 'company_id': self.company.id})
        vat = self.env['account.tax'].with_company(self.company).create({'name': 'VAT 7%', 'amount': 7, 'type_tax_use': 'purchase', 'tax_group_id': group.id})
        expense.write({'tax_ids': [(6, 0, (vat | withholding).ids)], 'total_amount_currency': 85.6})
        self.env['account.journal'].create({'name': 'Supplier withholding', 'code': 'SWHT', 'type': 'general', 'company_id': self.company.id})
        expense.action_submit()
        expense.action_approve()
        bill = expense.account_move_id
        bill.action_post()
        self.assertAlmostEqual(self.total(), 85.6)
        self.assertAlmostEqual(bill.amount_residual, 83.2)
        tax_invoice = bill.l10n_th_tax_invoice_ids.filtered(lambda record: record.state == 'posted')
        self.assertEqual(len(tax_invoice), 1)
        self.assertEqual(tax_invoice.tax_invoice_number, 'SUP-001')
        self.assertEqual(str(tax_invoice.date), '2026-06-01')
        self.assertEqual(tax_invoice.erp_expense_vendor_id, self.vendor)
        snapshot = bill._erp_expense_lines().erp_budget_amount_snapshot
        self.assertEqual(snapshot['supplier_tax_invoice_reference'], 'SUP-001')
        self.assertEqual(snapshot['expense_vendor_id'], self.vendor.id)
        bill.button_draft()
        self.assertEqual(tax_invoice.state, 'cancel')
        bill.action_post()
        self.assertEqual(len(bill.l10n_th_tax_invoice_ids), 2)
        self.assertEqual(tax_invoice.erp_expense_vendor_id, self.vendor)
        with self.assertRaises(UserError), self.cr.savepoint():
            tax_invoice.unlink()

    def test_native_requisition_po_bill_keeps_canonical_budget_family(self):
        request = self.make_request(50)
        request.action_submit()
        request.action_approve()
        requisition = self.test_env['purchase.requisition'].browse(request.action_create_requisition()['res_id'])
        requisition.vendor_id = self.vendor
        requisition.action_confirm()
        po = self.test_env['purchase.order'].browse(requisition.action_create_rfq()['res_id'])
        po.order_line.price_unit = 70
        po.button_confirm()
        bill = self.make_bill(po, 0.5, 70)
        bill.action_post()
        self.assertEqual((self.active('pr_commitment'), self.active('po_commitment'), self.active('actual')), (0, 35, 35))
        bill.button_draft()
        po.button_cancel()
        self.assertEqual((self.active('pr_commitment'), self.active('po_commitment'), self.active('actual')), (50, 0, 0))
        self.assertEqual(po.order_line.erp_requisition_line_id, requisition.line_ids)

    def test_foreign_request_expense_limit_uses_approved_company_amount(self):
        self.company.erp_budget_amount_mode = 'net'
        currency = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        currency.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 1})
        self.env['res.currency.rate'].create({'currency_id': currency.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 2})
        request = self.make_request(100)
        request.currency_id = currency
        request.action_submit()
        request.action_approve()
        self.assertEqual(self.active('pr_commitment'), 50)
        expense = self.make_expense(60)
        expense.employee_id.sudo().user_id = self.user
        expense.erp_request_line_id = request.line_ids
        with self.assertRaisesRegex(UserError, 'exceeds the approved request'), self.cr.savepoint():
            expense.action_submit()
        expense.total_amount_currency = 40
        expense.action_submit()
        expense.action_approve()
        self.assertEqual(expense.erp_budget_snapshot['request_approved_amount'], 50)
        self.assertEqual((self.active('pr_commitment'), self.active('expense_commitment')), (0, 40))
        expense.account_move_id.action_post()
        self.assertEqual((self.active('actual'), self.total()), (40, 40))

    def test_government_request_expense_conversion_done_and_reset_guard(self):
        setup = self.make_expense(1)
        setup.employee_id.sudo().user_id = self.user
        method = self.test_env['erp.procurement.method'].create({'name': 'Expense method', 'company_id': self.company.id})
        kind = self.test_env['erp.procurement.purchase.type'].create({'name': 'Direct reimbursement', 'company_id': self.company.id, 'to_create': 'expense', 'method_ids': [(6, 0, method.ids)]})
        request = self.make_request(60)
        request.write({'purchase_type_id': kind.id, 'procurement_method_id': method.id})
        request.action_submit()
        request.action_verify()
        request.action_approve()
        action = request.action_create_expense()
        expense = self.test_env['hr.expense'].browse(action['domain'][0][2])
        self.assertEqual(request.action_create_expense()['domain'], action['domain'])
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_reset()
        expense.action_submit()
        expense.action_approve()
        request.action_done()
        expense.account_move_id.action_post()
        self.assertEqual((self.active('actual'), self.active('pr_commitment'), self.active('expense_commitment')), (60, 0, 0))

    def test_done_request_native_bill_and_refund_keep_budget_source(self):
        request = self.make_request(80)
        request.action_submit()
        request.action_approve()
        po = self.make_po(request, 60)
        po.button_confirm()
        request.action_done()
        bill = self.make_bill(po, 1, 60)
        bill.action_post()
        self.assertEqual((self.active('pr_commitment'), self.active('po_commitment'), self.active('actual')), (0, 0, 60))
        credit = bill._reverse_moves([{'date': bill.date}])
        credit.invoice_date = bill.invoice_date
        credit.action_post()
        self.assertEqual(self.active('actual'), 0)
