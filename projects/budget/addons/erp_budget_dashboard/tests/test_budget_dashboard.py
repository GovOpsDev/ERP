import json

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBudgetDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'BI THB', 'currency_id': cls.env.ref('base.THB').id})
        cls.other_company = cls.env['res.company'].create({'name': 'BI USD', 'currency_id': cls.env.ref('base.USD').id})
        cls.plan = cls.env['account.analytic.plan'].create({'name': 'BI projects'})
        cls.controls = cls.env['erp.budget.control']
        cls.units = cls.env['erp.organization.unit']
        for i, company in enumerate([cls.company, cls.company, cls.other_company]):
            unit = cls.env['erp.organization.unit'].create({'name': f'BI unit {i}', 'code': f'BI{i}', 'company_id': company.id})
            cls.units |= unit
            period = cls.env['erp.budget.period'].search([('company_id', '=', company.id)], limit=1) or cls.env['erp.budget.period'].create({'name': f'BI period {i}', 'company_id': company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
            analytic = cls.env['account.analytic.account'].create({'name': f'BI project {i}', 'plan_id': cls.plan.id, 'company_id': company.id})
            control = cls.env['erp.budget.control'].create({'name': f'BI allocation {i}', 'company_id': company.id, 'organization_id': unit.id, 'period_id': period.id, 'analytic_id': analytic.id, 'level': 'analytic', 'amount': 1000})
            control.action_open()
            cls.controls |= control
        cls.user = cls.env['res.users'].create({'name': 'BI reader', 'login': 'bi_reader_test', 'company_id': cls.company.id, 'company_ids': [(6, 0, (cls.company | cls.other_company).ids)], 'group_ids': [(6, 0, [cls.env.ref('erp_budget.group_budget_user').id, cls.env.ref('base.group_allow_export').id])]})
        cls.env['erp.organization.assignment'].create([{'user_id': cls.user.id, 'unit_id': u.id} for u in cls.units[::2]])
        cls.reader = cls.env['erp.budget.report'].with_user(cls.user).with_context(allowed_company_ids=[cls.company.id, cls.other_company.id])
        cls.ledger = cls.env['erp.budget.ledger.report'].with_env(cls.reader.env)
        cls.moves = cls.env['erp.budget.move']
        for i, control in enumerate(cls.controls):
            cls.moves |= cls.env['erp.budget.move'].create({'control_id': control.id, 'origin_key': f'bi:po:{i}', 'move_type': 'po_commitment', 'amount': 300})
        cls.env.flush_all()

    def test_live_totals_reversals_and_unclassified(self):
        control = self.controls[0]
        self.env['erp.budget.move'].create([
            {'control_id': control.id, 'origin_key': 'bi:reverse', 'move_type': 'po_reversal', 'amount': -100},
            {'control_id': control.id, 'origin_key': 'bi:actual', 'move_type': 'actual', 'amount': 80},
            {'control_id': control.id, 'origin_key': 'bi:actual-reverse', 'move_type': 'actual_reversal', 'amount': -20},
            {'control_id': control.id, 'origin_key': 'bi:unknown', 'amount': 10},
        ])
        self.env.flush_all()
        row = self.reader.search([('control_id', '=', control.id)])
        self.assertEqual((row.allocated_amount, row.committed_amount, row.actual_amount, row.other_amount, row.available_amount), (1000, 200, 60, 10, 730))
        self.assertEqual(row.available_amount, control.available_amount)
        grouped = dict(self.ledger._read_group([('control_id', '=', control.id)], ['category'], ['amount:sum']))
        self.assertEqual(grouped, {'po': 200, 'actual': 60, 'other': 10})
        self.assertEqual(sum(grouped.values()), 1000 - row.available_amount)

    def test_company_and_organization_in_search_group_read_export(self):
        self.assertEqual(self.reader.search([]).ids, self.controls[:1].ids)
        self.assertEqual(self.reader._read_group([], [], ['allocated_amount:sum']), [(1000,)])
        self.assertEqual(self.ledger._read_group([], [], ['amount:sum']), [(300,)])
        for denied in self.controls[1:]:
            with self.assertRaises(AccessError):
                self.reader.browse(denied.id).read(['allocated_amount'])
            with self.assertRaises(AccessError):
                self.reader.browse(denied.id).export_data(['allocated_amount'])
        other = self.reader.with_context(allowed_company_ids=[self.other_company.id, self.company.id])
        self.assertEqual(other.search([]).ids, self.controls[2:].ids)
        self.assertEqual(other.search([]).currency_id, self.env.ref('base.USD'))

    def test_all_ou_stays_within_current_company(self):
        self.user.group_ids += self.env.ref('erp_budget.group_budget_all_ou')
        self.assertEqual(set(self.reader.search([]).ids), set(self.controls[:2].ids))
        self.assertEqual(self.reader._read_group([], [], ['allocated_amount:sum']), [(2000,)])

    def test_no_budget_role_and_readonly(self):
        user = self.env['res.users'].create({'name': 'No BI', 'login': 'bi_no_role_test', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        for model in ['erp.budget.report', 'erp.budget.fund.report', 'erp.budget.ledger.report']:
            with self.assertRaises(AccessError):
                self.env[model].with_user(user).search([])
            report = self.env[model].with_env(self.reader.env)
            with self.assertRaises(AccessError):
                report.create({})
            with self.assertRaises(AccessError):
                report.browse(self.controls[0].id).write({})
            with self.assertRaises(AccessError):
                report.browse(self.controls[0].id).unlink()

    def test_hierarchy_and_shared_project_do_not_duplicate(self):
        control = self.controls[0]
        group = self.env['erp.budget.fund.group'].create({'name': 'BI fund group', 'company_id': self.company.id})
        fund = self.env['erp.budget.fund'].create({'name': 'BI fund', 'company_id': self.company.id, 'group_id': group.id})
        child = self.env['erp.budget.control'].create({'name': 'BI fund control', 'company_id': self.company.id, 'period_id': control.period_id.id, 'organization_id': control.organization_id.id, 'analytic_id': control.analytic_id.id, 'fund_id': fund.id, 'level': 'fund', 'amount': 1000})
        child.action_open()
        self.env['erp.budget.move'].create({'control_id': child.id, 'origin_key': 'bi:fund', 'move_type': 'po_commitment', 'amount': 300})
        self.env['project.project'].create([{'name': f'BI shared project {i}', 'company_id': self.company.id, 'account_id': control.analytic_id.id} for i in range(2)])
        self.env.flush_all()
        self.assertEqual(self.reader._read_group([], [], ['allocated_amount:sum', 'committed_amount:sum']), [(1000, 300)])
        self.assertEqual(self.env['erp.budget.fund.report'].with_env(self.reader.env)._read_group([], [], ['allocated_amount:sum', 'committed_amount:sum']), [(1000, 300)])
        self.assertEqual(self.ledger.search_count([]), 1)

    def test_draft_closed_inactive_are_not_current_capacity(self):
        self.controls[0].action_close()
        self.env.flush_all()
        self.assertFalse(self.reader.search([]))
        self.assertFalse(self.ledger.search([]))

    def test_dashboard_sources_and_filter_mapping(self):
        dashboard = self.env.ref('erp_budget_dashboard.dashboard_project_budget')
        snapshot = json.loads(dashboard.spreadsheet_data)
        self.assertEqual(snapshot['pivots']['budget-summary']['model'], 'erp.budget.report')
        self.assertEqual(set(snapshot['pivots']['budget-summary']['fieldMatching']), {f['id'] for f in snapshot['globalFilters']})
        self.assertFalse(dashboard.sample_dashboard_file_path)
        self.assertEqual(dashboard.group_ids, self.env.ref('erp_budget.group_budget_user'))

    def test_serialized_dashboard_uses_active_not_default_company(self):
        dashboard = self.env.ref('erp_budget_dashboard.dashboard_project_budget').with_env(self.reader.env)
        other = dashboard.with_context(allowed_company_ids=[self.other_company.id, self.company.id])
        serialized = json.loads(other._get_serialized_readonly_dashboard())
        data_sheet = next(s for s in serialized['snapshot']['sheets'] if s['name'] == 'Data')
        self.assertEqual(data_sheet['cells']['B1'], 'BI USD · USD')
        self.assertIn('$', serialized['snapshot']['formats']['1'])
        serialized = json.loads(dashboard._get_serialized_readonly_dashboard())
        self.assertIn('฿', serialized['snapshot']['formats']['1'])

    def test_dashboard_truncates_only_display_after_aggregation(self):
        self.env['erp.budget.move'].create([
            {'control_id': self.controls[0].id, 'origin_key': 'bi:fraction:1', 'move_type': 'actual', 'amount': 10.99},
            {'control_id': self.controls[0].id, 'origin_key': 'bi:fraction:2', 'move_type': 'actual', 'amount': 10.99},
        ])
        self.env.flush_all()
        # The report and ledger still aggregate full amounts, not 10 + 10.
        self.assertAlmostEqual(self.reader._read_group([], [], ['actual_amount:sum'])[0][0], 21.98)
        dashboard = self.env.ref('erp_budget_dashboard.dashboard_project_budget').with_env(self.reader.env)
        original = dashboard.spreadsheet_data
        snapshot = json.loads(dashboard._get_serialized_readonly_dashboard())['snapshot']
        sheet = next(s for s in snapshot['sheets'] if s['name'] == 'Data')
        self.assertEqual(sheet['cells']['A3'], '=TRUNC(PIVOT.VALUE(1,"actual_amount"),0)')
        self.assertNotIn('.00', snapshot['formats']['1'])
        charts = [c for s in snapshot['sheets'] for f in s.get('figures', [])
                  for c in f.get('data', {}).get('chartDefinitions', {}).values()]
        self.assertTrue(charts)
        self.assertTrue(all(c['dataSource']['searchParams']['context']['erp_budget_integer_display'] for c in charts))
        self.assertEqual(dashboard.spreadsheet_data, original)
