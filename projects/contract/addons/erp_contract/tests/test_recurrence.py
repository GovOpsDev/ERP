from datetime import date, timedelta
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestContractRecurrence(TransactionCase):
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


    def active_amount(self, kind):
        moves = self.env['erp.budget.move'].sudo().search([('control_id', '=', self.ac.id), ('move_type', '=', kind), ('reversal_of_id', '=', False)])
        reversed_ids = self.env['erp.budget.move'].sudo().search([('reversal_of_id', 'in', moves.ids)]).mapped('reversal_of_id').ids
        return sum(moves.filtered(lambda m: m.id not in reversed_ids).mapped('amount'))


    def recurring(self, **values):
        contract, line = self.make_contract()
        contract.recurrence_enabled = True
        line.write(dict(quantity=1, **values))
        return contract, line

    def generate(self, contract):
        action = contract.action_generate_recurring()
        return self.e['account.move'].browse(action['domain'][0][2])

    def test_recurring_native_actuals_refund_cancel_and_idempotent_period(self):
        contract, line = self.recurring(name='Service #START# to #END#')
        first = self.generate(contract)
        self.assertNotIn('#START#', first.invoice_line_ids.name)
        self.assertFalse(first.invoice_line_ids.erp_contract_line_id)
        self.assertEqual((first.amount_untaxed, self.active_amount('contract_commitment')), (10, 0))
        cycle = first.erp_contract_cycle_id
        self.assertEqual(cycle.action_create_invoice()['res_id'], first.id)
        first.action_post()
        second = self.generate(contract)
        second.action_post()
        self.assertEqual((cycle.date_to, second.invoice_date, self.active_amount('actual')), (date(2026, 1, 31), date(2026, 2, 1), 20))
        credit = first._reverse_moves([{'date': first.date, 'journal_id': self.journal.id}])
        credit.invoice_date = first.invoice_date
        credit.action_post()
        self.assertEqual(self.active_amount('actual'), 10)
        with self.assertRaises(UserError), self.cr.savepoint():
            first.button_draft()
        over = first._reverse_moves([{'date': first.date, 'journal_id': self.journal.id}])
        over.invoice_date = first.invoice_date
        with self.assertRaises(ValidationError), self.cr.savepoint():
            over.action_post()
        over.button_cancel()
        credit.button_draft()
        credit.button_cancel()
        first.button_draft()
        first.button_cancel()
        self.assertEqual(self.active_amount('actual'), 10)
        replacement = self.e['account.move'].browse(cycle.action_create_invoice()['res_id'])
        self.assertNotEqual(replacement, first)
        replacement.action_post()
        self.assertEqual(self.active_amount('actual'), 20)
        self.assertIn(first, cycle.invoice_ids)
        with self.assertRaises(UserError), self.cr.savepoint():
            line.price_unit = 25
        with self.assertRaises(UserError), self.cr.savepoint():
            first.unlink()

    def test_recurrence_period_rules_and_postpaid_offset(self):
        ends = {'daily': '2026-01-15', 'weekly': '2026-01-21', 'monthly': '2026-02-14', 'monthlylastday': '2026-01-31', 'quarterly': '2026-04-14', 'semesterly': '2026-07-14', 'yearly': '2026-12-31'}
        for rule, expected in ends.items():
            contract, line = self.recurring(date_start='2026-01-15', recurring_rule_type=rule, recurring_invoicing_type='post-paid')
            start, end, invoice = line._next_cycle_dates()
            self.assertEqual(end, fields.Date.to_date(expected))
            self.assertEqual((invoice - end).days, 0 if rule == 'monthlylastday' else 1)
        contract, line = self.recurring(date_start='2026-02-28', date_end='2026-03-01', recurring_rule_type='monthly')
        bill = self.generate(contract)
        self.assertEqual(bill.amount_untaxed, 10)  # base upstream bills full quantity for a short tail
        self.assertFalse(line.recurring_next_date)

    def test_successor_renewal_stop_and_termination_preserve_history(self):
        contract, line = self.recurring()
        bill = self.generate(contract)
        bill.action_post()
        with self.assertRaises(UserError), self.cr.savepoint():
            line.action_stop('2026-01-15')
        successor = line.action_amend('2026-02-01', '2026-03-31', quantity=2, price_unit=15)
        self.assertEqual(successor.predecessor_id, line)
        self.assertFalse(line.recurring_next_date)
        with self.assertRaises(UserError), self.cr.savepoint():
            line.action_amend('2026-03-01', '2026-04-30')
        new = self.generate(contract)
        new.action_post()
        self.assertEqual(self.active_amount('actual'), 40)
        contract.action_terminate('2026-02-28', 'Service ended')
        self.assertFalse(self.generate(contract))
        self.assertEqual(bill.invoice_line_ids.price_unit, 10)
        contract.action_cancel_termination()
        renewed = successor.action_renew()
        self.assertEqual(renewed.date_start, date(2026, 3, 1))
        self.assertEqual(renewed.predecessor_id, successor)
        self.assertEqual(self.active_amount('actual'), 40)

    def test_recurrence_company_ou_provenance_and_mode_guards(self):
        contract, line = self.recurring()
        with self.assertRaises(UserError), self.cr.savepoint():
            contract.action_commit_budget()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            contract.erp_use_invoice_plan = True
        with self.assertRaises(AccessError), self.cr.savepoint():
            line.recurrence_canceled = True
        bill = self.generate(contract)
        cycle = bill.erp_contract_cycle_id
        with self.assertRaises(AccessError), self.cr.savepoint():
            cycle.copy()
        with self.assertRaises(AccessError), self.cr.savepoint():
            bill.erp_contract_cycle_id = False
        other = self.env['res.company'].create({'name': 'Other recurring company'})
        with self.assertRaises((AccessError, UserError, ValidationError)), self.cr.savepoint():
            bill.company_id = other
            bill.action_post()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.invoice_line_ids.quantity = 2
            bill.action_post()
        bill.action_post()
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        self.assertFalse(self.e['erp.contract.cycle'].search([('id', '=', cycle.id)]))
        self.assertFalse(self.e['account.move'].search([('id', '=', bill.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            cycle.action_create_invoice()

    def test_cancel_reset_cron_and_automatic_successor(self):
        today = fields.Date.today()
        contract, line = self.recurring(date_start=today, date_end=today, auto_renew=True, termination_notice_days=0)
        line.action_cancel_recurrence()
        self.assertFalse(self.generate(contract))
        line.action_reset_recurrence()
        self.e['erp.contract.contract']._cron_recurring_invoices()
        self.e['erp.contract.contract']._cron_recurring_invoices()
        self.assertEqual(len(line.cycle_ids), 1)
        self.env['erp.contract.line']._cron_renew_contract_lines()
        self.env['erp.contract.line']._cron_renew_contract_lines()
        self.assertEqual(len(line.successor_ids), 1)
        self.assertEqual(line.successor_ids.date_start, today + timedelta(days=1))

    def test_recurring_fx_and_budget_failure_remain_native_and_atomic(self):
        self.company.erp_budget_amount_mode = 'net'
        self.env['res.currency.rate'].create({'currency_id': self.company.currency_id.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 1})
        currency = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'EUR')], limit=1)
        if currency == self.company.currency_id:
            currency = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'USD')], limit=1)
        currency.active = True
        self.env['res.currency.rate'].create({'currency_id': currency.id, 'company_id': self.company.id, 'name': '2026-01-01', 'rate': 2})
        self.journal.currency_id = currency
        contract, line = self.recurring(price_unit=100)
        first = self.generate(contract)
        first.action_post()
        self.assertEqual((first.currency_id, self.active_amount('actual')), (currency, 50))
        second = self.generate(contract)
        second.action_post()
        third = self.generate(contract)
        with self.assertRaisesRegex(UserError, 'Insufficient budget'), self.cr.savepoint():
            third.action_post()
        self.assertEqual((third.state, self.active_amount('actual'), self.active_amount('contract_commitment')), ('draft', 100, 0))
