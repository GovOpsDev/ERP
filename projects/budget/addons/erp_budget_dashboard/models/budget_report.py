from odoo import api, fields, models, tools, _
from odoo.exceptions import AccessError


class BudgetReportBase(models.AbstractModel):
    _name = 'erp.budget.report.base'
    _description = 'Read-only current-company budget analysis'

    control_id = fields.Many2one('erp.budget.control', string='วงเงินต้นทาง', readonly=True)
    company_id = fields.Many2one('res.company', string='บริษัท', readonly=True)
    currency_id = fields.Many2one('res.currency', string='สกุลเงิน', readonly=True)
    period_id = fields.Many2one('erp.budget.period', string='ปี / รอบงบประมาณ', readonly=True)
    organization_id = fields.Many2one('erp.organization.unit', string='หน่วยงาน', readonly=True)
    analytic_id = fields.Many2one('account.analytic.account', string='โครงการ / บัญชีวิเคราะห์', readonly=True)
    kpi_id = fields.Many2one('erp.budget.kpi', string='ตัวชี้วัด (KPI)', readonly=True)
    fund_id = fields.Many2one('erp.budget.fund', string='กองทุน', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Budget analysis is read-only.'))

    def write(self, vals):
        raise AccessError(_('Budget analysis is read-only.'))

    def unlink(self):
        raise AccessError(_('Budget analysis is read-only.'))


class BudgetReport(models.Model):
    _name = 'erp.budget.report'
    _inherit = 'erp.budget.report.base'
    _description = 'ภาพรวมงบประมาณโครงการ (บริษัทปัจจุบัน)'
    _auto = False
    _rec_name = 'control_id'
    _order = 'period_id, analytic_id, id'
    _control_level = 'analytic'

    allocated_amount = fields.Monetary(string='วงเงินจัดสรร', readonly=True)
    committed_amount = fields.Monetary(string='ผูกพันสุทธิ', readonly=True)
    actual_amount = fields.Monetary(string='ใช้จริงสุทธิ', readonly=True)
    other_amount = fields.Monetary(string='รายการไม่ระบุประเภท', readonly=True)
    available_amount = fields.Monetary(string='คงเหลือ', readonly=True)

    def init(self):
        # Aggregate before joining: one row per control, never per project or move.
        # Analytic and fund controls represent overlapping economic amounts;
        # expose separate models so no pivot can add both levels together.
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW %s AS
            SELECT c.id, c.id AS control_id, c.company_id, co.currency_id,
                   c.period_id, c.organization_id, c.analytic_id, c.kpi_id, c.fund_id,
                   c.amount AS allocated_amount,
                   COALESCE(m.committed, 0) AS committed_amount,
                   COALESCE(m.actual, 0) AS actual_amount,
                   COALESCE(m.other, 0) AS other_amount,
                   c.amount - COALESCE(m.total, 0) AS available_amount
            FROM erp_budget_control c
            JOIN res_company co ON co.id = c.company_id
            LEFT JOIN (
                SELECT control_id, SUM(amount) AS total,
                    SUM(CASE WHEN move_type IN ('actual', 'actual_reversal') THEN amount ELSE 0 END) AS actual,
                    SUM(CASE WHEN move_type IN ('pr_commitment', 'pr_reversal', 'po_commitment', 'po_reversal',
                        'contract_commitment', 'contract_reversal', 'expense_commitment', 'expense_reversal',
                        'advance_commitment', 'advance_reversal') THEN amount ELSE 0 END) AS committed,
                    SUM(CASE WHEN move_type IS NULL OR move_type NOT IN ('actual', 'actual_reversal',
                        'pr_commitment', 'pr_reversal', 'po_commitment', 'po_reversal', 'contract_commitment',
                        'contract_reversal', 'expense_commitment', 'expense_reversal', 'advance_commitment',
                        'advance_reversal') THEN amount ELSE 0 END) AS other
                FROM erp_budget_move GROUP BY control_id
            ) m ON m.control_id = c.id
            WHERE c.active AND c.state = 'open' AND c.level = '%s'
        """ % (self._table, self._control_level))


class BudgetFundReport(models.Model):
    _name = 'erp.budget.fund.report'
    _inherit = 'erp.budget.report'
    _description = 'วิเคราะห์งบประมาณแยกกองทุน (บริษัทปัจจุบัน)'
    _auto = False
    _control_level = 'fund'


class BudgetLedgerReport(models.Model):
    _name = 'erp.budget.ledger.report'
    _inherit = 'erp.budget.report.base'
    _description = 'รายการงบประมาณโครงการ (บริษัทปัจจุบัน)'
    _auto = False
    _rec_name = 'document_key'
    _order = 'recorded_at desc, id desc'

    move_id = fields.Many2one('erp.budget.move', string='รายการต้นทาง', readonly=True)
    recorded_at = fields.Datetime(string='เวลาบันทึกในระบบ', readonly=True)
    document_key = fields.Char(string='เอกสารอ้างอิง', readonly=True)
    origin_key = fields.Char(string='รหัสรายการ', readonly=True)
    category = fields.Selection([
        ('pr', 'ใบขอซื้อ'), ('po', 'ใบสั่งซื้อ'), ('contract', 'สัญญา'),
        ('expense', 'รายจ่าย'), ('advance', 'เงินทดรอง'), ('actual', 'ใช้จริง'),
        ('other', 'ไม่ระบุประเภท')], string='ประเภท', readonly=True)
    is_reversal = fields.Boolean(string='รายการกลับรายการ', readonly=True)
    amount = fields.Monetary(string='จำนวนเงินสุทธิ', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW erp_budget_ledger_report AS
            SELECT m.id, m.id AS move_id, c.id AS control_id, c.company_id, co.currency_id,
                c.period_id, c.organization_id, c.analytic_id, c.kpi_id, c.fund_id,
                m.create_date AS recorded_at, COALESCE(m.document_key, m.source_key, m.origin_key) AS document_key,
                m.origin_key, m.amount,
                (m.reversal_of_id IS NOT NULL OR m.move_type LIKE '%%_reversal') AS is_reversal,
                CASE WHEN m.move_type IN ('pr_commitment', 'pr_reversal') THEN 'pr'
                     WHEN m.move_type IN ('po_commitment', 'po_reversal') THEN 'po'
                     WHEN m.move_type IN ('contract_commitment', 'contract_reversal') THEN 'contract'
                     WHEN m.move_type IN ('expense_commitment', 'expense_reversal') THEN 'expense'
                     WHEN m.move_type IN ('advance_commitment', 'advance_reversal') THEN 'advance'
                     WHEN m.move_type IN ('actual', 'actual_reversal') THEN 'actual'
                     ELSE 'other' END AS category
            FROM erp_budget_move m
            JOIN erp_budget_control c ON c.id = m.control_id
            JOIN res_company co ON co.id = c.company_id
            WHERE c.active AND c.state = 'open' AND c.level = 'analytic'
        """)
