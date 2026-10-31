from odoo.exceptions import AccessError, ValidationError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBudgetMaster(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a = cls.env['res.company'].create({'name': 'Budget A'})
        cls.b = cls.env['res.company'].create({'name': 'Budget B'})
        cls.manager = cls.env['res.users'].create({
            'name': 'Budget Manager', 'login': 'budget_manager_test', 'company_id': cls.a.id,
            'company_ids': [(6, 0, [cls.a.id, cls.b.id])],
            'group_ids': [(6, 0, [cls.env.ref('erp_budget.group_budget_manager').id])],
        })
        cls.reader = cls.env['res.users'].create({
            'name': 'Budget Reader', 'login': 'budget_reader_test', 'company_id': cls.a.id,
            'company_ids': [(6, 0, [cls.a.id])],
            'group_ids': [(6, 0, [cls.env.ref('erp_budget.group_budget_user').id])],
        })
        cls.outsider = cls.env['res.users'].create({
            'name': 'Budget Outsider', 'login': 'budget_outsider_test', 'company_id': cls.a.id,
            'company_ids': [(6, 0, [cls.a.id])],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.group_a = cls.env['erp.budget.fund.group'].create({'name': 'Group A', 'company_id': cls.a.id})
        cls.group_b = cls.env['erp.budget.fund.group'].create({'name': 'Group B', 'company_id': cls.b.id})
        cls.fund_a = cls.env['erp.budget.fund'].create({'name': 'Fund A', 'company_id': cls.a.id, 'group_id': cls.group_a.id})
        cls.fund_b = cls.env['erp.budget.fund'].create({'name': 'Fund B', 'company_id': cls.b.id, 'group_id': cls.group_b.id})
        cls.kpi_a = cls.env['erp.budget.kpi'].create({'name': 'KPI A', 'company_id': cls.a.id})
        cls.kpi_b = cls.env['erp.budget.kpi'].create({'name': 'KPI B', 'company_id': cls.b.id})
        cls.period_a = cls.env['erp.budget.period'].create({'name': '2026', 'company_id': cls.a.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        cls.period_b = cls.env['erp.budget.period'].create({'name': '2026', 'company_id': cls.b.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})

    def test_company_access_and_roles(self):
        for model, a, b in [('erp.budget.period', self.period_a, self.period_b), ('erp.budget.fund.group', self.group_a, self.group_b), ('erp.budget.fund', self.fund_a, self.fund_b), ('erp.budget.kpi', self.kpi_a, self.kpi_b)]:
            records = self.env[model].with_user(self.manager).with_context(allowed_company_ids=[self.a.id])
            self.assertEqual(records.search([('id', 'in', [a.id, b.id])]).ids, [a.id])
            with self.assertRaises(AccessError), self.cr.savepoint():
                records.browse(b.id).write({'name': 'Forbidden'})
            with self.assertRaises(AccessError), self.cr.savepoint():
                records.browse(a.id).write({'company_id': self.b.id})
            self.assertEqual(set(records.with_context(allowed_company_ids=[self.a.id, self.b.id]).search([('id', 'in', [a.id, b.id])]).ids), {a.id, b.id})
            with self.assertRaises(AccessError), self.cr.savepoint():
                a.with_user(self.reader).write({'name': 'Forbidden'})
            with self.assertRaises(AccessError), self.cr.savepoint():
                self.env[model].with_user(self.outsider).search([])
        self.assertEqual(self.fund_a.with_user(self.reader).name, 'Fund A')

    def test_manager_create_and_delete(self):
        funds = self.env['erp.budget.fund'].with_user(self.manager).with_context(allowed_company_ids=[self.a.id])
        fund = funds.create({'name': 'New', 'company_id': self.a.id, 'group_id': self.group_a.id})
        fund.write({'name': 'Updated'})
        fund.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            funds.create({'name': 'Forbidden', 'company_id': self.b.id, 'group_id': self.group_b.id})

    def test_period_validation(self):
        periods = self.env['erp.budget.period']
        with self.assertRaises(ValidationError), self.cr.savepoint():
            periods.create({'name': 'Backwards', 'company_id': self.a.id, 'date_from': '2027-12-31', 'date_to': '2027-01-01'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            periods.create({'name': 'Overlap', 'company_id': self.a.id, 'date_from': '2026-12-31', 'date_to': '2027-01-01'})
        periods.create({'name': '2027', 'company_id': self.a.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})

    def test_fund_company_consistency(self):
        with self.assertRaises((ValidationError, UserError)), self.cr.savepoint():
            self.fund_a.write({'group_id': self.group_b.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.group_a.write({'company_id': self.b.id})
        self.fund_a.active = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.group_a.write({'company_id': self.b.id})

    def test_kpi_manager_lifecycle(self):
        kpis = self.env['erp.budget.kpi'].with_user(self.manager).with_context(allowed_company_ids=[self.a.id])
        kpi = kpis.create({'name': 'Travel', 'company_id': self.a.id})
        kpi.write({'name': 'Travel updated'})
        kpi.write({'active': False})
        self.assertFalse(kpis.search([('id', '=', kpi.id)]))
        self.assertEqual(kpis.with_context(active_test=False).browse(kpi.id).name, 'Travel updated')
        kpi.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            kpis.create({'name': 'Cross company', 'company_id': self.b.id})
