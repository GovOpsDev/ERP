from psycopg2.errors import UniqueViolation
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBudgetTemplate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a = cls.env['res.company'].create({'name': 'Template A'})
        cls.b = cls.env['res.company'].create({'name': 'Template B'})
        cls.kpi_a = cls.env['erp.budget.kpi'].create({'name': 'KPI A', 'company_id': cls.a.id})
        cls.kpi_b = cls.env['erp.budget.kpi'].create({'name': 'KPI B', 'company_id': cls.b.id})
        cls.account_a = cls.env['account.account'].create({'name': 'Account A', 'code': 'TA1', 'account_type': 'expense', 'company_ids': [(6, 0, [cls.a.id])]})
        cls.account_b = cls.env['account.account'].create({'name': 'Account B', 'code': 'TB1', 'account_type': 'expense', 'company_ids': [(6, 0, [cls.b.id])]})
        cls.template = cls.env['erp.budget.template'].create({'name': 'Template A', 'company_id': cls.a.id})

    def test_mapping_and_isolation(self):
        Line = self.env['erp.budget.template.line']
        line = Line.create({'template_id': self.template.id, 'account_id': self.account_a.id, 'kpi_id': self.kpi_a.id})
        self.assertEqual(self.template._kpi_for_account(self.account_a), self.kpi_a)
        with self.assertRaises((ValidationError, UserError)), self.cr.savepoint():
            Line.create({'template_id': self.template.id, 'account_id': self.account_b.id, 'kpi_id': self.kpi_a.id})
        with self.assertRaises((ValidationError, UserError)), self.cr.savepoint():
            line.write({'kpi_id': self.kpi_b.id})
        with self.assertRaises(UniqueViolation), self.cr.savepoint():
            Line.create({'template_id': self.template.id, 'account_id': self.account_a.id, 'kpi_id': self.kpi_a.id})
        self.kpi_a.active = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.template._kpi_for_account(self.account_a)

    def test_distinct_account_kpis_and_unmapped_account(self):
        second_kpi = self.env['erp.budget.kpi'].create({'name': 'KPI C', 'company_id': self.a.id})
        second_account = self.env['account.account'].create({'name': 'Account C', 'code': 'TA2', 'account_type': 'expense', 'company_ids': [(6, 0, [self.a.id])]})
        self.env['erp.budget.template.line'].create([
            {'template_id': self.template.id, 'account_id': self.account_a.id, 'kpi_id': self.kpi_a.id},
            {'template_id': self.template.id, 'account_id': second_account.id, 'kpi_id': second_kpi.id},
        ])
        self.assertEqual(self.template._kpi_for_account(self.account_a), self.kpi_a)
        self.assertEqual(self.template._kpi_for_account(second_account), second_kpi)
        unmapped = self.env['account.account'].create({'name': 'Unmapped', 'code': 'TA3', 'account_type': 'expense', 'company_ids': [(6, 0, [self.a.id])]})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.template._kpi_for_account(unmapped)

    def test_period_template_company(self):
        period = self.env['erp.budget.period'].create({'name': '2026', 'company_id': self.a.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31', 'template_id': self.template.id})
        self.assertEqual(period.template_id, self.template)
        other = self.env['erp.budget.template'].create({'name': 'Template B', 'company_id': self.b.id})
        with self.assertRaises((ValidationError, UserError)), self.cr.savepoint():
            period.write({'template_id': other.id})

    def test_acl_and_company_rules(self):
        manager = self.env['res.users'].create({'name': 'Template Manager', 'login': 'template_mgr', 'company_id': self.a.id, 'company_ids': [(6, 0, [self.a.id, self.b.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id])]})
        other = self.env['erp.budget.template'].create({'name': 'Template B', 'company_id': self.b.id})
        templates = self.env['erp.budget.template'].with_user(manager).with_context(allowed_company_ids=[self.a.id])
        self.assertFalse(templates.search([('id', '=', other.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            templates.browse(other.id).write({'name': 'Forbidden'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            templates.create({'name': 'Forbidden', 'company_id': self.b.id})
