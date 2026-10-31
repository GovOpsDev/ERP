from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBudgetControl(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Control Company'})
        cls.unit = cls.env['erp.organization.unit'].create({'name': 'Control Unit', 'code': 'CTL', 'company_id': cls.company.id})
        cls.user = cls.env['res.users'].create({'name': 'Control Manager', 'login': 'control_manager', 'company_id': cls.company.id, 'company_ids': [(6, 0, [cls.company.id])], 'group_ids': [(6, 0, [cls.env.ref('erp_budget.group_budget_manager').id])]})
        cls.env['erp.organization.assignment'].create({'user_id': cls.user.id, 'unit_id': cls.unit.id})
        cls.group = cls.env['erp.budget.fund.group'].create({'name': 'Fund group', 'company_id': cls.company.id})
        cls.fund = cls.env['erp.budget.fund'].create({'name': 'Fund', 'company_id': cls.company.id, 'group_id': cls.group.id})
        cls.period = cls.env['erp.budget.period'].create({'name': 'Period', 'company_id': cls.company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        cls.plan = cls.env['account.analytic.plan'].create({'name': 'Cost centers'})
        cls.analytic = cls.env['account.analytic.account'].create({'name': 'Analytic', 'plan_id': cls.plan.id, 'company_id': cls.company.id})
        cls.account = cls.env['account.account'].create({'name': 'Expense', 'code': 'ZZ01', 'account_type': 'expense', 'company_ids': [(6, 0, [cls.company.id])]})
        Control = cls.env['erp.budget.control'].with_user(cls.user).with_context(allowed_company_ids=[cls.company.id])
        vals = {'company_id': cls.company.id, 'period_id': cls.period.id, 'organization_id': cls.unit.id, 'analytic_id': cls.analytic.id, 'amount': 100}
        cls.a = Control.create(dict(vals, name='Analytic control', level='analytic'))
        cls.f = Control.create(dict(vals, name='Fund control', level='fund', fund_id=cls.fund.id))
        (cls.a | cls.f).action_open()
        cls.day = fields.Date.from_string('2026-06-01')

    def test_check_commit_and_idempotency(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = service._resolve(self.period.with_user(self.user), self.unit.with_user(self.user), self.analytic, self.fund.with_user(self.user), self.account, self.env['account.analytic.account'])
        service._check_available(controls, 80, self.day)
        self.assertFalse(self.env['erp.budget.move'].search([('control_id', 'in', controls.ids)]))
        service._commit(controls, 80, self.day, 'test:1')
        controls.invalidate_recordset(['available_amount'])
        self.assertEqual(controls.mapped('available_amount'), [20, 20])
        service._commit(controls, 80, self.day, 'test:1')
        self.assertEqual(self.env['erp.budget.move'].search_count([('origin_key', '=', 'test:1')]), 2)
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(controls, 30, self.day, 'test:2')
        self.assertFalse(self.env['erp.budget.move'].search([('origin_key', '=', 'test:2')]))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._commit(controls, 79, self.day, 'test:1')

    def test_reversal_is_idempotent_and_restores_balance(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        service._commit(controls, 80, self.day, 'test:reverse')
        service._reverse(controls, 'test:reverse')
        service._reverse(controls, 'test:reverse')
        self.assertEqual(self.env['erp.budget.move'].search_count([('control_id', 'in', controls.ids), ('reversal_of_id', '!=', False)]), 2)
        service._check_available(controls, 100, self.day)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._commit(controls, 80, self.day, 'test:reverse')

    def test_each_control_level_can_independently_reject(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        self.env.cr.execute('UPDATE erp_budget_control SET amount=60 WHERE id=%s', [self.f.id])
        controls.invalidate_recordset(['amount'])
        with self.assertRaises(UserError), self.cr.savepoint():
            service._check_available(controls, 70, self.day)
        self.env.cr.execute('UPDATE erp_budget_control SET amount=100 WHERE id=%s', [self.f.id])
        self.env.cr.execute('UPDATE erp_budget_control SET amount=60 WHERE id=%s', [self.a.id])
        controls.invalidate_recordset(['amount'])
        with self.assertRaises(UserError), self.cr.savepoint():
            service._check_available(controls, 70, self.day)
        service._check_available(controls, 50, self.day)

    def test_reconcile_pr_and_multiple_purchase_orders(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        def reconcile(orders, eligible=True):
            service._reconcile_purchase(controls, self.day, 'pr:1', 'pr-line:1', 100, eligible, orders)
        def totals():
            moves = self.env['erp.budget.move'].search([('control_id', '=', self.a.id), ('family_key', '=', 'pr:1')])
            return sum(moves.mapped('amount'))
        reconcile([])
        self.assertEqual(totals(), 100)
        reconcile([('po:1', 40)])
        self.assertEqual(totals(), 40)
        reconcile([('po:1', 40), ('po:2', 60)])
        self.assertEqual(totals(), 100)
        count = self.env['erp.budget.move'].search_count([('family_key', '=', 'pr:1')])
        reconcile([('po:1', 40), ('po:2', 60)])
        self.assertEqual(self.env['erp.budget.move'].search_count([('family_key', '=', 'pr:1')]), count)
        reconcile([('po:2', 60)])
        self.assertEqual(totals(), 60)
        reconcile([])
        self.assertEqual(totals(), 100)
        reconcile([], eligible=False)
        self.assertEqual(totals(), 0)

    def test_reconcile_insufficient_is_atomic(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        service._reconcile_purchase(controls, self.day, 'pr:2', 'pr-line:2', 30, True, [])
        count = self.env['erp.budget.move'].search_count([('family_key', '=', 'pr:2')])
        with self.assertRaises(UserError), self.cr.savepoint():
            service._reconcile_purchase(controls, self.day, 'pr:2', 'pr-line:2', 30, True, [('po:1', 120)])
        self.assertEqual(self.env['erp.budget.move'].search_count([('family_key', '=', 'pr:2')]), count)
        moves = self.env['erp.budget.move'].search([('control_id', '=', self.a.id), ('family_key', '=', 'pr:2')])
        self.assertEqual(sum(moves.mapped('amount')), 30)

    def test_reconcile_purchase_with_different_fund_controls(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        pr_controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        other_fund = self.env['erp.budget.fund'].create({'name': 'Other funding source', 'company_id': self.company.id, 'group_id': self.group.id})
        other_control = self.env['erp.budget.control'].with_user(self.user).with_context(allowed_company_ids=[self.company.id]).create({'name': 'Other fund control', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 70, 'level': 'fund', 'fund_id': other_fund.id})
        other_control.action_open()
        po_controls = self.a.with_user(self.user) | other_control
        def total(row):
            return sum(self.env['erp.budget.move'].search([('control_id', '=', row.id), ('family_key', '=', 'cross-key')]).mapped('amount'))
        service._reconcile_purchase_multi(pr_controls, self.day, 'cross-key', 'pr:1', 30, True, [])
        self.assertEqual((total(self.a), total(self.f), total(other_control)), (30, 30, 0))
        service._reconcile_purchase_multi(pr_controls, self.day, 'cross-key', 'pr:1', 30, True, [('po:1', po_controls, 50, self.day)])
        self.assertEqual((total(self.a), total(self.f), total(other_control)), (50, 0, 50))
        service._reconcile_purchase_multi(pr_controls, self.day, 'cross-key', 'pr:1', 30, True, [])
        self.assertEqual((total(self.a), total(self.f), total(other_control)), (30, 30, 0))
        with self.assertRaises(UserError), self.cr.savepoint():
            service._reconcile_purchase_multi(pr_controls, self.day, 'cross-key', 'pr:1', 30, True, [('po:1', po_controls, 80, self.day)])
        self.assertEqual((total(self.a), total(self.f), total(other_control)), (30, 30, 0))

    def test_purchase_reconciliation_preserves_finance_actuals(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        service._reconcile_purchase_multi(controls, self.day, 'family:finance', 'pr:finance', 30, True, [])
        actuals = self.env['erp.budget.move'].sudo().create([{'control_id': c.id, 'origin_key': 'finance:test', 'family_key': 'family:finance', 'source_key': 'test.actual:1', 'move_type': 'actual', 'amount': 10} for c in controls])
        service._reconcile_purchase_multi(controls, self.day, 'family:finance', 'pr:finance', 30, True, [('po:finance', controls, 50, self.day)])
        self.assertFalse(self.env['erp.budget.move'].sudo().search([('reversal_of_id', 'in', actuals.ids)]))
        self.assertEqual(sum(self.env['erp.budget.move'].sudo().search([('family_key', '=', 'family:finance'), ('control_id', '=', self.a.id)]).mapped('amount')), 60)
        with self.assertRaises(UserError), self.cr.savepoint():
            service._reconcile_purchase_multi(controls, self.day, 'family:finance', 'pr:finance', 30, True, [('po:finance', controls, 95, self.day)])
        self.assertFalse(self.env['erp.budget.move'].sudo().search([('reversal_of_id', 'in', actuals.ids)]))

    def test_purchase_and_actual_reconciled_atomically(self):
        # Synthetic ledger identities must not resolve to real rows in an upgraded DB.
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        self.env.cr.execute('UPDATE erp_budget_control SET amount=120 WHERE id IN %s', [tuple(controls.ids)])
        controls.invalidate_recordset(['amount'])
        def reconcile(amount, actuals):
            service._reconcile_purchase_multi(controls, self.day, 'finance:atomic', 'pr:atomic', 100, True, [('po:atomic', controls, amount, self.day)], actuals)
        reconcile(100, [])
        reconcile(60, [('test.actual:1', controls, 48, self.day)])
        moves = self.env['erp.budget.move'].sudo().search([('family_key', '=', 'finance:atomic'), ('control_id', '=', self.a.id)])
        self.assertEqual(sum(moves.mapped('amount')), 108)
        before = len(moves)
        reconcile(60, [('test.actual:1', controls, 48, self.day)])
        self.assertEqual(self.env['erp.budget.move'].sudo().search_count([('family_key', '=', 'finance:atomic'), ('control_id', '=', self.a.id)]), before)
        with self.assertRaises(UserError), self.cr.savepoint():
            reconcile(60, [('test.actual:1', controls, 65, self.day)])
        reconcile(100, [])
        moves = self.env['erp.budget.move'].sudo().search([('family_key', '=', 'finance:atomic'), ('control_id', '=', self.a.id)])
        self.assertEqual(sum(moves.mapped('amount')), 100)
        self.assertEqual(len(moves.filtered(lambda m: m.move_type == 'actual_reversal')), 1)

    def test_contract_and_purchase_families_are_independent(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        self.env.cr.execute('UPDATE erp_budget_control SET amount=120 WHERE id IN %s', [tuple(controls.ids)])
        controls.invalidate_recordset(['amount'])
        service._reconcile_purchase_multi(controls, self.day, 'purchase-family', 'pr:separate', 50, True, [])
        service._reconcile_purchase_multi(controls, self.day, 'contract-family', 'contract:1', 30, True, [], [('test.actual:1', controls, 10, self.day)], primary_type='contract_commitment')
        service._reconcile_purchase_multi(controls, self.day, 'purchase-family', 'pr:separate', 50, True, [('po:separate', controls, 70, self.day)])
        ledger = self.env['erp.budget.move'].sudo().search([('control_id', '=', self.a.id)])
        self.assertEqual(sum(ledger.filtered(lambda m: m.family_key == 'purchase-family').mapped('amount')), 70)
        self.assertEqual(sum(ledger.filtered(lambda m: m.family_key == 'contract-family').mapped('amount')), 40)
        self.assertFalse(ledger.filtered(lambda m: m.family_key == 'contract-family' and m.move_type == 'actual_reversal'))

    def test_fund_and_analytic_dimension_matching(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        other_fund = self.env['erp.budget.fund'].create({'name': 'Other fund', 'company_id': self.company.id, 'group_id': self.group.id})
        dimension_plan = self.env['account.analytic.plan'].create({'name': 'Dimension plan'})
        dimension = self.env['account.analytic.account'].create({'name': 'Dimension', 'plan_id': dimension_plan.id, 'company_id': self.company.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._check_key(self.period, self.unit, self.analytic, other_fund, self.account, self.env['account.analytic.account'], 10, self.day)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._check_key(self.period, self.unit, self.analytic, self.fund, self.account, dimension, 10, self.day)
        service._check_key(self.period, self.unit, self.analytic, self.fund, self.account, self.env['account.analytic.account'], 10, self.day)

    def test_kpi_mapping_must_match_control(self):
        kpi = self.env['erp.budget.kpi'].create({'name': 'Expense KPI', 'company_id': self.company.id})
        other_kpi = self.env['erp.budget.kpi'].create({'name': 'Other KPI', 'company_id': self.company.id})
        template = self.env['erp.budget.template'].create({'name': 'Budget template', 'company_id': self.company.id})
        other_account = self.env['account.account'].create({'name': 'Other expense', 'code': 'ZZ02', 'account_type': 'expense', 'company_ids': [(6, 0, [self.company.id])]})
        self.env['erp.budget.template.line'].create([
            {'template_id': template.id, 'account_id': self.account.id, 'kpi_id': kpi.id},
            {'template_id': template.id, 'account_id': other_account.id, 'kpi_id': other_kpi.id},
        ])
        self.period.template_id = template
        self.a.action_close()
        control = self.env['erp.budget.control'].with_user(self.user).with_context(allowed_company_ids=[self.company.id]).create({'name': 'KPI control', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 100, 'level': 'analytic', 'kpi_id': kpi.id})
        control.action_open()
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        service._check_key(self.period, self.unit, self.analytic, self.fund, self.account, self.env['account.analytic.account'], 10, self.day)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._check_key(self.period, self.unit, self.analytic, self.fund, other_account, self.env['account.analytic.account'], 10, self.day)

    def test_organization_scope_cannot_be_bypassed_with_elevated_records(self):
        other = self.env['res.users'].create({'name': 'Other OU', 'login': 'control_other', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id])]})
        service = self.env['erp.budget.control.service'].with_user(other).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).sudo()
        self.assertFalse(self.env['erp.budget.control'].with_user(other).search([('id', 'in', controls.ids)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            service._check_available(controls, 1, self.day)
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.a.sudo().with_user(other).action_close()

    def test_cross_company_fund_and_archived_organization_fail(self):
        company_b = self.env['res.company'].create({'name': 'Other control company'})
        group_b = self.env['erp.budget.fund.group'].create({'name': 'Other group', 'company_id': company_b.id})
        fund_b = self.env['erp.budget.fund'].create({'name': 'Other fund', 'company_id': company_b.id, 'group_id': group_b.id})
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            service._check_key(self.period, self.unit, self.analytic, fund_b, self.account, self.env['account.analytic.account'], 10, self.day)
        self.unit.active = False
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            service._check_available(self.a | self.f, 10, self.day)

    def test_two_levels_both_required_and_invalid_date(self):
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        controls = (self.a | self.f).with_user(self.user).with_context(allowed_company_ids=[self.company.id])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._check_available(controls[:1], 1, self.day)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._check_available(controls, 1, fields.Date.from_string('2027-01-01'))
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['erp.budget.move'].with_user(self.user).create({'control_id': self.a.id, 'amount': 1, 'origin_key': 'manual'})
        self.a.action_close()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._check_available(controls, 1, self.day)

    def test_explicit_cross_organization_budget_role_preserves_company_and_domain_scope(self):
        hidden = self.env['erp.organization.unit'].create({'name': 'Central budget OU', 'code': 'CENT', 'company_id': self.company.id})
        base = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': hidden.id, 'analytic_id': self.analytic.id, 'amount': 100}
        controls = self.env['erp.budget.control'].create([dict(base, name='Central analytic', level='analytic'), dict(base, name='Central fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        e = self.env(user=self.user, context={'allowed_company_ids': self.company.ids})
        service = e['erp.budget.control.service']
        with self.assertRaises(AccessError), self.cr.savepoint():
            service._resolve(self.period, hidden, self.analytic, self.fund, self.account, e['account.analytic.account'])
        self.user.write({'group_ids': [(4, self.env.ref('erp_budget.group_budget_all_ou').id)]})
        resolved = service._resolve(self.period, hidden, self.analytic, self.fund, self.account, e['account.analytic.account'])
        service._commit(resolved, 20, self.day, 'central:commitment')
        self.assertEqual(set(resolved.ids), set(controls.ids))
        self.assertFalse(e['erp.organization.assignment'].search([('unit_id', '=', hidden.id)]))
        foreign = self.env['res.company'].create({'name': 'Foreign central budget'})
        other_unit = self.env['erp.organization.unit'].create({'name': 'Foreign central OU', 'code': 'FCENT', 'company_id': foreign.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            other_unit.with_env(e).check_access('read')
        self.user.write({'group_ids': [(3, self.env.ref('erp_budget.group_budget_all_ou').id)]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            resolved.check_access('read')

    def test_document_defaults_cannot_reclassify_or_reassign_ledger_nodes(self):
        e = self.env(user=self.user, context={'allowed_company_ids': self.company.ids})
        controls = e['erp.budget.control'].browse((self.a | self.f).ids)
        service = e['erp.budget.control.service']
        service._commit(controls, 20, self.day, 'defaults:original')
        original = e['erp.budget.move'].search([('origin_key', '=', 'defaults:original')])
        foreign = self.env['res.company'].create({'name': 'Foreign ledger default'})
        service.with_context(default_company_id=foreign.id, default_reversal_of_id=original[0].id, default_move_type='actual', default_source_key='forged-source')._commit(controls, 30, self.day, 'defaults:protected')
        protected = e['erp.budget.move'].search([('origin_key', '=', 'defaults:protected')])
        self.assertEqual((len(protected), protected.company_id), (2, self.company))
        self.assertFalse(protected.reversal_of_id or any(protected.mapped('move_type')) or any(protected.mapped('source_key')))
        service._check_available(controls, 50, self.day)
        self.assertEqual(sum(e['erp.budget.move'].search([('control_id', '=', self.a.id)]).mapped('amount')), 50)

    def test_amount_policy_price_included_tax_and_scope_authority(self):
        self.company.country_id = self.env.ref('base.th')
        group = self.env['account.tax.group'].create({'name': 'Included VAT', 'company_id': self.company.id})
        vat = self.env['account.tax'].with_company(self.company).create({'name': 'Included VAT 7', 'amount': 7, 'amount_type': 'percent', 'price_include_override': 'tax_included', 'type_tax_use': 'purchase', 'company_id': self.company.id, 'tax_group_id': group.id})
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=self.company.ids)
        currency = self.company.currency_id
        self.assertEqual(service._amount_currency(107, 1, currency, self.company, vat, 'net', vat), 100)
        self.assertEqual(service._amount_currency(107, 1, currency, self.company, vat, 'all', vat), 107)
        self.assertEqual(service._amount_currency(107, 1, currency, self.company, vat, 'specific', self.env['account.tax']), 100)
        service._check_manual_amount_rate(2.5)
        with self.assertRaises(ValidationError):
            service._check_manual_amount_rate(-1)
        with self.assertRaises(ValidationError):
            service._check_manual_amount_rate(float('inf'))
        other = self.env['res.company'].create({'name': 'Other amount company'})
        with self.assertRaises(AccessError):
            service._amount_policy(other, 'purchase')
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.company.with_user(self.user).write({'erp_budget_amount_mode': 'all'})
        outsider = self.env['res.users'].create({'name': 'Ordinary amount user', 'login': 'ordinary_amount_user', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_user').id])]})
        with self.assertRaises(AccessError):
            service.with_user(outsider)._check_manual_amount_rate(2)
        service.with_user(outsider)._check_manual_amount_rate(0)

    def make_adjustment(self, amount, direction='consume'):
        return self.env['erp.budget.adjustment'].with_user(self.user).with_context(allowed_company_ids=self.company.ids).create({'company_id': self.company.id, 'organization_id': self.unit.id, 'description': 'Source correction with an explicit reason', 'date': self.day, 'line_ids': [(0, 0, {'name': 'Correction', 'amount': amount, 'direction': direction, 'period_id': self.period.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id, 'account_id': self.account.id})]})

    def test_adjustment_apply_cancel_reset_keeps_audit_history(self):
        adjustment = self.make_adjustment(80)
        adjustment.action_adjust()
        original = self.env['erp.budget.move'].search([('family_key', '=', adjustment.line_ids._family_key())])
        self.assertEqual((adjustment.state, len(original), original.mapped('amount')), ('done', 2, [80, 80]))
        self.assertEqual(original[0].amount_snapshot['direction'], 'consume')
        adjustment.action_adjust()
        self.assertEqual(self.env['erp.budget.move'].search_count([('family_key', '=', adjustment.line_ids._family_key())]), 2)
        adjustment.action_cancel()
        adjustment.action_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            adjustment.line_ids.amount = 1
        with self.assertRaises(UserError), self.cr.savepoint():
            adjustment.unlink()
        adjustment.action_adjust()
        self.assertEqual(original.exists(), original)
        self.assertEqual(self.env['erp.budget.move'].search_count([('family_key', '=', adjustment.line_ids._family_key())]), 6)
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', self.a.id)]).mapped('amount')), 80)
        successor = adjustment.copy()
        self.assertEqual((successor.state, bool(successor.confirmed_at)), ('draft', False))
        successor.line_ids.amount = 10

    def test_adjustment_release_cannot_cancel_after_capacity_is_consumed(self):
        consume = self.make_adjustment(80)
        consume.action_adjust()
        release = self.make_adjustment(40, 'release')
        release.action_adjust()
        service = self.env['erp.budget.control.service'].with_user(self.user).with_context(allowed_company_ids=self.company.ids)
        service._commit(self.a | self.f, 50, self.day, 'adjustment:later-consumption')
        with self.assertRaises(UserError), self.cr.savepoint():
            release.action_cancel()
        self.assertEqual(release.state, 'done')
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', self.a.id)]).mapped('amount')), 90)
        service._reverse(self.a | self.f, 'adjustment:later-consumption')
        release.action_cancel()
        self.assertEqual(sum(self.env['erp.budget.move'].search([('control_id', '=', self.a.id)]).mapped('amount')), 80)

    def test_adjustment_scope_and_forged_workflow_are_rejected(self):
        adjustment = self.make_adjustment(110)
        with self.assertRaises(UserError), self.cr.savepoint():
            adjustment.action_adjust()
        self.assertEqual(adjustment.state, 'draft')
        self.assertFalse(self.env['erp.budget.move'].search([('family_key', '=', adjustment.line_ids._family_key())]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            adjustment.state = 'done'
        with self.assertRaises(AccessError), self.cr.savepoint():
            adjustment.with_context(default_confirmed_at=fields.Datetime.now()).copy()
        other = self.env['res.company'].create({'name': 'Adjustment foreign company'})
        other_unit = self.env['erp.organization.unit'].create({'name': 'Adjustment foreign unit', 'code': 'ADJ', 'company_id': other.id})
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            adjustment.copy({'company_id': other.id, 'organization_id': other_unit.id})
        self.user.write({'group_ids': [(3, self.env.ref('erp_budget.group_budget_manager').id)]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            adjustment.action_adjust()
