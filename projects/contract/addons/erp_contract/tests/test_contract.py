from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestContractBudget(TransactionCase):
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

    def test_contract_accounting_source_scope(self):
        contract, line = self.make_contract()
        contract.action_commit_budget()
        bill = self.make_bill(line, 4, 10)
        bill.action_post()
        self.assertTrue(bill.read(['name']))
        lines = bill.line_ids
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        self.assertFalse(self.e['account.move'].search([('id', '=', bill.id)]))
        for record in [bill, *lines]:
            with self.assertRaises(AccessError), self.cr.savepoint():
                record.read(['name'])
            with self.assertRaises(AccessError), self.cr.savepoint():
                record.write({'name': 'Forbidden'})

    def test_dedicated_finance_posts_without_contract_management(self):
        contract, line = self.make_contract()
        contract.action_commit_budget()
        bill = self.make_bill(line, 4, 10)
        finance = self.env['res.users'].create({
            'name': 'Dedicated contract accountant', 'login': 'contract_accountant',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('account.group_account_invoice').id,
                                 self.env.ref('erp_budget.group_budget_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': finance.id, 'unit_id': self.unit.id})
        bill.with_user(finance).action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(self.active_amount('actual'), 40)
        with self.assertRaises(AccessError), self.cr.savepoint():
            contract.with_user(finance).action_close_budget()
        with self.assertRaises(AccessError), self.cr.savepoint():
            line.with_user(finance).write({'name': 'Forbidden'})

    def test_commit_bill_refund_close_and_reset(self):
        contract, line = self.make_contract()
        contract.action_commit_budget()
        self.assertEqual(self.active_amount('contract_commitment'), 100)
        bill = self.make_bill(line, 4, 12)
        self.assertEqual(self.active_amount('actual'), 0)
        bill.action_post()
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (60, 48))
        refund = self.make_bill(line, 2, 12, 'in_refund', bill)
        refund.action_post()
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (80, 24))
        count = self.env['erp.budget.move'].sudo().search_count([])
        line._reconcile_budget()
        self.assertEqual(self.env['erp.budget.move'].sudo().search_count([]), count)
        contract.action_close_budget()
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (0, 24))
        refund.button_draft()
        bill.button_draft()
        self.assertEqual(self.active_amount('actual'), 0)
        contract.action_archive_contract()
        self.assertFalse(contract.active)

    def test_contract_posting_and_overinvoice_fail_closed(self):
        contract, line = self.make_contract()
        bill = self.make_bill(line, 4, 10)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()
        contract.action_commit_budget()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.write({'state': 'posted'})
        over = self.make_bill(line, 11, 10)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            over.action_post()
        self.assertEqual(over.state, 'draft')
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (100, 0))

    def test_invalid_contract_sources_and_security(self):
        contract, line = self.make_contract()
        outsider = self.env['res.users'].create({'name': 'Contract outsider', 'login': 'contract_outsider', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_contract.group_contract_user').id])]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            contract.with_user(outsider).action_commit_budget()
        contract.action_commit_budget()
        bill = self.make_bill(line, 1, 10)
        bill.invoice_line_ids.analytic_distribution = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (100, 0))

    def test_native_reversal_preserves_contract_source(self):
        contract, line = self.make_contract()
        contract.action_commit_budget()
        bill = self.make_bill(line, 4, 10)
        bill.action_post()
        credit = bill._reverse_moves([{'date': fields.Date.today(), 'journal_id': self.journal.id}])
        self.assertEqual(credit.invoice_line_ids.erp_contract_line_id, line)
        credit.invoice_date = fields.Date.today()
        credit.action_post()
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (100, 0))

    def test_one_invoice_line_cannot_use_contract_and_purchase(self):
        contract, line = self.make_contract()
        contract.action_commit_budget()
        bill = self.make_bill(line, 1, 10)
        po = self.env['purchase.order'].with_company(self.company).create({'partner_id': self.vendor.id, 'company_id': self.company.id, 'order_line': [(0, 0, {'name': 'Other purchase', 'product_id': self.product.id, 'product_qty': 1, 'price_unit': 10, 'date_planned': fields.Datetime.now()})]})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.invoice_line_ids.purchase_line_id = po.order_line
        self.assertFalse(bill.invoice_line_ids.purchase_line_id)
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (100, 0))

    def test_insufficient_commitment_rolls_back_contract(self):
        contract, line = self.make_contract()
        line.price_unit = 13
        with self.assertRaises(UserError), self.cr.savepoint():
            contract.action_commit_budget()
        self.assertFalse(contract.commit_budget)
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (0, 0))

    def test_contract_ledger_history_prevents_destructive_edit_or_delete(self):
        contract, line = self.make_contract()
        contract.action_commit_budget()
        contract.action_close_budget()
        with self.assertRaises(UserError), self.cr.savepoint():
            line.write({'price_unit': 5})
        with self.assertRaises(UserError), self.cr.savepoint():
            line.unlink()
        with self.assertRaises(UserError), self.cr.savepoint():
            contract.unlink()

    def test_contract_line_cannot_move_to_posted_unrelated_bill(self):
        contract, line = self.make_contract()
        contract.action_commit_budget()
        draft = self.make_bill(line, 1, 10)
        unrelated = self.make_bill(line, 1, 10)
        unrelated.invoice_line_ids.erp_contract_line_id = False
        unrelated.action_post()
        with self.assertRaises((UserError, ValidationError)), self.cr.savepoint():
            draft.invoice_line_ids.move_id = unrelated
        self.assertEqual(draft.invoice_line_ids.erp_contract_line_id, line)
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (100, 0))

    def test_shared_plan_with_real_contract_and_bill(self):
        plan = self.env['erp.budget.plan'].create({'name': 'Contract plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        plan.action_confirm()
        cap = plan.line_ids
        contract, line = self.make_contract()
        contract.action_commit_budget()
        self.assertEqual(cap._consumed(), 100)
        expensive = self.make_bill(line, 4, 12)
        with self.assertRaises(UserError), self.cr.savepoint():
            expensive.action_post()
        self.assertEqual((expensive.state, cap._consumed()), ('draft', 100))
        bill = self.make_bill(line, 4, 10)
        bill.action_post()
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual'), cap._consumed()), (60, 40, 100))
        contract.action_close_budget()
        self.assertEqual(cap._consumed(), 40)

    def test_formal_release_real_contract_bill(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        original_analytic = self.analytic
        new_analytic = self.env['account.analytic.account'].create({'name': 'Contract release analytic', 'plan_id': original_analytic.plan_id.id, 'company_id': self.company.id})
        kpi = self.env['erp.budget.kpi'].create({'name': 'Contract release KPI', 'company_id': self.company.id})
        template = self.env['erp.budget.template'].create({'name': 'Contract release template', 'company_id': self.company.id, 'line_ids': [(0, 0, {'account_id': self.account.id, 'kpi_id': kpi.id})]})
        self.period.template_id = template
        plan = self.env['erp.budget.plan'].create({'name': 'Contract formal plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': original_analytic.id, 'initial_amount': 120}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': new_analytic.id, 'initial_amount': 100, 'allocation_mode': 'allocated', 'release_required': True})]})
        plan.action_confirm()
        cap = plan.line_ids.filtered(lambda row: row.analytic_id == new_analytic)
        vals = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': new_analytic.id, 'amount': 100}
        ac, fc = self.env['erp.budget.control'].create([dict(vals, name='Contract released KPI', level='analytic', kpi_id=kpi.id), dict(vals, name='Contract released fund', level='fund', fund_id=self.fund.id)])
        fc.action_open()
        release = self.env['erp.budget.kpi.release'].create({'name': 'Contract release', 'plan_line_id': cap.id, 'released_amount': 100, 'line_ids': [(0, 0, {'control_id': ac.id})]})
        reviewer = self.env['res.users'].create({'name': 'Budget release reviewer', 'login': 'contract_release_review', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': 10, 'reviewer_id': reviewer.id})
        release = release.with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        release.action_submit()
        release.with_user(reviewer).action_approve()
        self.analytic, self.ac, self.fc = new_analytic, ac, fc
        contract, contract_line = self.make_contract()
        contract.action_commit_budget()
        bill = self.make_bill(contract_line, 4, 10)
        bill.action_post()
        self.assertEqual((release.state, cap._consumed(), self.active_amount('contract_commitment'), self.active_amount('actual')), ('done', 100, 60, 40))
        with self.assertRaises(UserError), self.cr.savepoint():
            release.action_reverse()

    def test_allocation_revision_real_contract_bill(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        period = self.e['erp.budget.period'].create({'name': 'Allocated contract year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        allocation = self.e['erp.budget.allocation'].create({'name': 'Contract fund allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        fund = allocation.line_ids.control_id
        fund.action_open()
        analytic = self.e['erp.budget.control'].create({'name': 'Allocated contract analytic', 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'amount': 100})
        analytic.action_open()
        revision = self.e['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Approved increase'})
        revision.line_ids.write({'amount': 120})
        revision.action_activate()
        self.assertEqual((fund.amount, allocation.plan_id.line_ids._ceiling()), (120, 120))
        original_line = allocation.line_ids
        replacement_fund = self.e['erp.budget.fund'].create({'name': 'Revised source fund', 'company_id': self.company.id, 'group_id': self.fund.group_id.id})
        dimension_revision = self.e['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        dimension_revision.write({'reason': 'Replace unused source fund'})
        dimension_revision.line_ids.write({'amount': 0, 'excluded': True})
        replacement_row = self.e['erp.budget.allocation.revision.line'].browse(dimension_revision.action_add_dimension(self.unit.id, self.analytic.id, replacement_fund.id, 120))
        dimension_revision.action_activate()
        self.assertEqual((fund.amount, replacement_row.allocation_line_id.control_id.amount, allocation.plan_id.line_ids._ceiling()), (0, 120, 120))
        self.fund = replacement_fund
        self.period, self.ac, self.fc = period, analytic, replacement_row.allocation_line_id.control_id
        contract = self.e['erp.contract.contract'].create({'name': 'Allocated contract', 'company_id': self.company.id, 'organization_id': self.unit.id, 'partner_id': self.vendor.id, 'journal_id': self.journal.id})
        line = self.e['erp.contract.line'].create({'contract_id': contract.id, 'name': 'Service', 'product_id': self.product.id, 'uom_id': self.product.uom_id.id, 'quantity': 10, 'price_unit': 10, 'date_start': '2027-01-01', 'date_end': '2027-12-31', 'period_id': period.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id, 'account_id': self.account.id})
        contract.action_commit_budget()
        bill = self.make_bill(line, 4, 10)
        bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
        bill.action_post()
        self.assertEqual((allocation.state, original_line.released_amount, allocation.plan_id.line_ids._consumed()), ('done', 100, 100))
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (60, 40))

    def test_coordinated_source_planning_revision_real_contract_bill(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        kpi = self.env['erp.budget.kpi'].create({'name': 'Coordinated contract KPI', 'company_id': self.company.id})
        template = self.env['erp.budget.template'].create({'name': 'Coordinated contract template', 'company_id': self.company.id, 'line_ids': [(0, 0, {'account_id': self.account.id, 'kpi_id': kpi.id})]})
        period = self.env['erp.budget.period'].create({'name': 'Coordinated contract year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31', 'release_policy': 'formal', 'template_id': template.id})
        allocation = self.e['erp.budget.allocation'].create({'name': 'Coordinated contract allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        fund = allocation.line_ids.control_id
        fund.action_open()
        control = self.e['erp.budget.control'].create({'name': 'Coordinated contract control', 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'kpi_id': kpi.id, 'amount': 100})
        reviewer = self.env['res.users'].create({'name': 'Coordinated contract reviewer', 'login': 'coordinated_contract_reviewer', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': 10, 'reviewer_id': reviewer.id})
        release = self.e['erp.budget.kpi.release'].create({'name': 'Initial contract planning', 'plan_line_id': allocation.plan_id.line_ids.id, 'released_amount': 100, 'line_ids': [(0, 0, {'control_id': control.id})]})
        release.action_submit()
        release.with_user(reviewer).action_approve()
        revision = self.e['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Contract coordinated source revision'})
        revision.line_ids.write({'amount': 120})
        planning = self.e['erp.budget.kpi.release'].browse(release.action_prepare_revision(revision.id)['res_id'])
        planning.write({'released_amount': 120})
        planning.line_ids.write({'amount': 120})
        planning.action_submit()
        planning.with_user(reviewer).action_approve()
        self.assertEqual((planning.state, control.amount, fund.amount), ('approved', 100, 100))
        revision.action_activate()
        self.period, self.ac, self.fc = period, control, fund
        contract = self.e['erp.contract.contract'].create({'name': 'Coordinated contract', 'company_id': self.company.id, 'organization_id': self.unit.id, 'partner_id': self.vendor.id, 'journal_id': self.journal.id})
        line = self.e['erp.contract.line'].create({'contract_id': contract.id, 'name': 'Service', 'product_id': self.product.id, 'uom_id': self.product.uom_id.id, 'quantity': 12, 'price_unit': 10, 'date_start': '2027-01-01', 'date_end': '2027-12-31', 'period_id': period.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id, 'account_id': self.account.id})
        contract.action_commit_budget()
        bill = self.make_bill(line, 4, 10)
        bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
        bill.action_post()
        self.assertEqual((release.state, release.line_ids.amount, planning.state, planning.line_ids.amount), ('superseded', 100, 'done', 120))
        self.assertEqual((allocation.plan_id.line_ids._consumed(), self.active_amount('contract_commitment'), self.active_amount('actual')), (120, 80, 40))
        with self.assertRaises(UserError), self.cr.savepoint():
            allocation.action_cancel()
        self.assertEqual((allocation.state, allocation.plan_id.line_ids._consumed()), ('done', 120))

    def test_activity_kpi_selection_with_real_contract_bills(self):
        from odoo.addons.erp_budget.tests.common_activity import source_activity_allocation
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        budget_account = self.env['account.account'].create({'name': 'Contract activity budget account', 'code': 'ACTCONT', 'account_type': 'expense', 'company_ids': [(6, 0, [self.company.id])]})
        data = source_activity_allocation(self, self.user, self.company, self.unit, self.analytic, self.fund, budget_account, 'Contract activity')
        self.period, self.fc = data.period, data.fund_control
        for activity, quantity, bill_quantity in zip(data.activities, (4, 6), (4, 3)):
            contract, line = self.make_contract()
            line.write({'activity_id': activity.id, 'quantity': quantity, 'date_start': '2027-01-01', 'date_end': '2027-12-31'})
            self.assertEqual(line.account_id, budget_account)
            contract.action_commit_budget()
            bill = self.make_bill(line, bill_quantity, 10)
            bill.write({'invoice_date': '2027-06-01', 'date': '2027-06-01'})
            bill.action_post()
            self.assertEqual(bill.invoice_line_ids.erp_budget_activity_id, activity)
            self.assertEqual(bill.invoice_line_ids.account_id, self.account)
            self.assertNotEqual(bill.invoice_line_ids.account_id, budget_account)
        self.ac = data.controls[0]
        self.assertEqual((self.active_amount('actual'), self.active_amount('contract_commitment')), (40, 0))
        self.ac = data.controls[1]
        self.assertEqual((self.active_amount('actual'), self.active_amount('contract_commitment')), (30, 30))
        self.assertEqual((data.allocation.plan_id.line_ids._consumed(), data.allocation.plan_id.line_ids._ceiling()), (100, 100))
        with self.assertRaises(UserError), self.cr.savepoint():
            line.write({'activity_id': data.activities[0].id})
        with self.assertRaises(UserError), self.cr.savepoint():
            data.activities[0].write({'account_id': self.account.id})

    def test_contract_commitment_forward_across_two_years_with_partial_bills(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_manager').id)]})
        contract, line = self.make_contract()
        contract.action_commit_budget()
        first = self.make_bill(line, 4, 10)
        first.write({'date': '2026-06-01', 'invoice_date': '2026-06-01'})
        first.action_post()
        source_plan = self.e['erp.budget.plan'].create({'name': 'Contract carry source', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 120})]})
        source_plan.action_confirm()
        def forward_to(source_period, year, amount):
            period = self.env['erp.budget.period'].create({'name': 'Contract forward '+str(year), 'company_id': self.company.id, 'date_from': str(year)+'-01-01', 'date_to': str(year)+'-12-31'})
            target_analytic = self.env['account.analytic.account'].create({'name': 'Contract fiscal analytic '+str(year), 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
            plan = self.e['erp.budget.plan'].create({'name': 'Contract destination '+str(year), 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': target_analytic.id, 'initial_amount': amount})]})
            plan.action_confirm()
            values = {'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': target_analytic.id, 'amount': amount}
            controls = self.e['erp.budget.control'].create([dict(values, name='Forward analytic '+str(year), level='analytic'), dict(values, name='Forward fund '+str(year), level='fund', fund_id=self.fund.id)])
            controls.action_open()
            doc = self.e['erp.budget.commit.forward'].create({'name': 'Contract carry '+str(year), 'company_id': self.company.id, 'source_period_id': source_period.id, 'destination_period_id': period.id})
            doc.action_review()
            self.assertEqual(doc._current_lines().source_key, line._family_key())
            doc._current_lines().write({'destination_analytic_control_id': controls.filtered(lambda control: control.level == 'analytic').id, 'destination_fund_control_id': controls.filtered(lambda control: control.level == 'fund').id})
            doc.action_forward()
            return period, plan, controls, doc
        period2, plan2, controls2, forward2 = forward_to(self.period, 2027, 80)
        self.assertEqual((source_plan.line_ids._consumed(), plan2.line_ids._consumed()), (40, 60))
        second = self.make_bill(line, 2, 10)
        second.write({'date': '2027-06-01', 'invoice_date': '2027-06-01'})
        second.invoice_line_ids.analytic_distribution = line._invoice_analytic_distribution('2027-06-01')
        second.action_post()
        self.assertEqual(second.invoice_line_ids.analytic_distribution, {str(controls2.analytic_id.id): 100})
        self.assertEqual(plan2.line_ids._consumed(), 60)
        period3, plan3, controls3, forward3 = forward_to(period2, 2028, 40)
        third = self.make_bill(line, 1, 10)
        third.write({'date': '2028-06-01', 'invoice_date': '2028-06-01'})
        third.invoice_line_ids.analytic_distribution = line._invoice_analytic_distribution('2028-06-01')
        third.action_post()
        self.ac = controls3.filtered(lambda control: control.level == 'analytic')
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (30, 10))
        refund = self.make_bill(line, 1, 10, 'in_refund', first)
        refund.write({'date': '2028-06-02', 'invoice_date': '2028-06-02'})
        refund.invoice_line_ids.analytic_distribution = line._invoice_analytic_distribution('2028-06-02')
        refund.action_post()
        line._reconcile_budget()
        self.assertEqual((self.active_amount('contract_commitment'), self.active_amount('actual')), (40, 0))
        self.assertEqual((source_plan.line_ids._consumed(), plan2.line_ids._consumed(), plan3.line_ids._consumed()), (40, 20, 40))
        self.assertEqual(first.invoice_line_ids.analytic_distribution, {str(self.analytic.id): 100})
        self.assertNotEqual(controls2.analytic_id, controls3.analytic_id)
        self.assertEqual((forward2._current_lines().opening_id.initial_commit, forward3._current_lines().opening_id.initial_commit), (60, 40))

    def test_foreign_contract_forecast_and_native_company_actual(self):
        self.company.erp_budget_amount_mode = 'net'
        foreign = self.env.ref('base.EUR') if self.company.currency_id != self.env.ref('base.EUR') else self.env.ref('base.USD')
        foreign.active = True
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 1})
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 0.5})
        self.journal.currency_id = foreign
        contract, line = self.make_contract()
        line.quantity = 4
        contract.action_commit_budget()
        self.assertEqual((line.currency_id, line.erp_budget_fx_rate, self.active_amount('contract_commitment')), (foreign, 2, 80))
        self.env['res.currency.rate'].create({'currency_id': foreign.id, 'company_id': self.company.id, 'name': '2026-06-01', 'rate': 0.4})
        bill = self.make_bill(line, 2, 10)
        bill.write({'currency_id': foreign.id, 'invoice_date': '2026-06-02', 'date': '2026-06-02'})
        bill.invoice_line_ids.write({'price_unit': 10, 'quantity': 2})
        bill.action_post()
        self.assertEqual((bill.invoice_line_ids.balance, self.active_amount('actual'), self.active_amount('contract_commitment')), (50, 50, 40))
        self.assertTrue(bill.invoice_line_ids.erp_budget_amount_snapshot)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.invoice_line_ids.with_context(check_move_validity=False).write({'balance': 1})
