import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare


class BudgetOpeningBalance(models.Model):
    _name = 'erp.budget.opening.balance'
    _description = 'Budget Opening Balance Reconciliation'
    _check_company_auto = True

    reference = fields.Char(required=True, help='Stable origin reference for opening or carry-forward reconciliation.')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict', index=True)
    period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict', index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict', index=True)
    analytic_id = fields.Many2one('account.analytic.account', required=True, check_company=True, ondelete='restrict', index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    initial_available = fields.Monetary(required=True, default=0)
    initial_commit = fields.Monetary(required=True, default=0)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Confirmed'), ('cancel', 'Cancelled')], required=True, default='draft', readonly=True)
    confirmed_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    confirmed_at = fields.Datetime(readonly=True)
    _origin_unique = models.Constraint('unique(company_id, period_id, reference)', 'This opening origin has already been recorded.')

    @api.constrains('initial_available', 'initial_commit', 'company_id', 'period_id', 'organization_id', 'analytic_id')
    def _check_opening(self):
        for record in self:
            if record.period_id.company_id != record.company_id or record.organization_id.company_id != record.company_id or (record.analytic_id.company_id and record.analytic_id.company_id != record.company_id):
                raise ValidationError(_('Opening balance dimensions must belong to the company.'))
            for amount in (record.initial_available, record.initial_commit):
                if not math.isfinite(amount) or amount < 0 or abs(amount - record.currency_id.round(amount)) > 1e-9:
                    raise ValidationError(_('Opening amounts must be nonnegative and use company currency precision.'))

    @api.model_create_multi
    def create(self, vals_list):
        forbidden = {'confirmed_at', 'confirmed_by_id'}
        if any(vals.get('state', 'draft') != 'draft' or forbidden & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in forbidden | {'state'}):
            raise AccessError(_('Opening balances begin in draft.'))
        for vals in vals_list:
            unit = self.env['erp.organization.unit'].browse(vals.get('organization_id')).exists()
            unit.ensure_one()
            unit.check_access('read')
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.mapped('period_id')._lock_plan_periods()
        if any(record.state != 'draft' for record in self) or set(vals) - {'reference', 'initial_available', 'initial_commit'}:
            raise AccessError(_('Only draft opening references and amounts can be edited.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.mapped('period_id')._lock_plan_periods()
        if any(record.state != 'draft' for record in self):
            raise AccessError(_('Confirmed opening provenance cannot be deleted.'))
        return super().unlink()

    def action_confirm(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget manager capability is required.'))
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        if self.state == 'done':
            return True
        if self.state != 'draft' or not self.organization_id.active or not self.analytic_id.active:
            raise ValidationError(_('An active draft opening reconciliation is required.'))
        lines = self.env['erp.budget.plan.line'].sudo().search([('company_id', '=', self.company_id.id), ('period_id', '=', self.period_id.id), ('analytic_id', '=', self.analytic_id.id), ('plan_id.state', 'in', ('confirm', 'done'))])
        for line in lines.with_env(self.env):
            line.check_access('read')
            line._check_opening_minimum(line._ceiling(), extra=self.initial_available + self.initial_commit)
        return super(BudgetOpeningBalance, self).write({'state': 'done', 'confirmed_by_id': self.env.user.id, 'confirmed_at': fields.Datetime.now()})

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self.period_id._lock_plan_periods()
        self.invalidate_recordset()
        if self.state != 'draft':
            raise UserError(_('Confirmed opening balances require an explicit successor reconciliation.'))
        return super(BudgetOpeningBalance, self).write({'state': 'cancel'})


class BudgetPlanOpening(models.Model):
    _inherit = 'erp.budget.plan.line'

    opening_amount = fields.Monetary(compute='_compute_opening_amount')

    def _compute_opening_amount(self):
        for line in self:
            line.opening_amount = line._opening_minimum()

    def _opening_minimum(self):
        self.ensure_one()
        records = self.env['erp.budget.opening.balance'].sudo().search([('company_id', '=', self.company_id.id), ('period_id', '=', self.period_id.id), ('analytic_id', '=', self.analytic_id.id), ('state', '=', 'done')])
        records.with_env(self.env).check_access('read')
        return sum(records.mapped('initial_available')) + sum(records.mapped('initial_commit'))

    def _check_opening_minimum(self, amount, extra=0):
        self.ensure_one()
        if float_compare(amount, self._opening_minimum() + extra, precision_rounding=self.currency_id.rounding) < 0:
            raise UserError(_('Planning must cover initial available plus initial commitment.'))
