"""Balance forwarding records opening floors and seals the prior spending scope."""
from contextvars import ContextVar
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_opening import BudgetOpeningBalance

_balance_forward_internal = ContextVar('budget_balance_forward_internal', default=False)


class BudgetForwardWorkflow(models.AbstractModel):
    _name = 'erp.budget.forward.workflow'
    _description = 'Budget Fiscal Forward Workflow'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict', index=True)
    source_period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict')
    destination_period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict')
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([('draft', 'Draft'), ('review', 'Review'), ('done', 'Forwarded'), ('cancel', 'Cancelled')], default='draft', readonly=True, required=True)
    review_round = fields.Integer(default=0, readonly=True)
    forwarded_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    forwarded_at = fields.Datetime(readonly=True)

    @api.constrains('company_id', 'source_period_id', 'destination_period_id')
    def _check_periods(self):
        for doc in self:
            if doc.source_period_id.company_id != doc.company_id or doc.destination_period_id.company_id != doc.company_id or doc.destination_period_id.date_from <= doc.source_period_id.date_to:
                raise ValidationError(_('Carry-forward requires later fiscal scope in the same company.'))

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'state', 'review_round', 'line_ids', 'forwarded_by_id', 'forwarded_at'}
        if any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected):
            raise AccessError(_('Carry-forward begins in draft without generated history.'))
        result = super().create(vals_list)
        result._check_company_scope()
        return result

    def _check_company_scope(self):
        if any(doc.company_id not in self.env.companies for doc in self):
            raise AccessError(_('Carry-forward company must be active.'))

    def _lock_scope(self):
        self.ensure_one()
        self._check_company_scope()
        controls = self.env['erp.budget.control'].sudo().with_context(active_test=False).search([('period_id', 'in', (self.source_period_id | self.destination_period_id).ids)])
        controls.with_env(self.env).check_access('write')
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        (self.source_period_id | self.destination_period_id)._lock_plan_periods()
        self.invalidate_recordset()
        controls.invalidate_recordset()
        return controls.with_env(self.env)

    def write(self, vals):
        self.check_access('write')
        for doc in self:
            doc._lock_scope()
        if not _balance_forward_internal.get() and (set(vals) - {'name'} or any(doc.state != 'draft' for doc in self)):
            raise AccessError(_('Carry-forward history changes through workflow actions.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Carry-forward history cannot be deleted.'))

    def _current_lines(self):
        return self.line_ids.filtered(lambda line: line.round_number == self.review_round)

    def action_draft(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state != 'cancel':
            raise UserError(_('Only cancelled forwards may be reset.'))
        token = _balance_forward_internal.set(True)
        try:
            return self.write({'state': 'draft'})
        finally:
            _balance_forward_internal.reset(token)


class BudgetBalanceForward(models.Model):
    _name = 'erp.budget.balance.forward'
    _inherit = 'erp.budget.forward.workflow'
    _description = 'Budget Balance Forward'

    line_ids = fields.One2many('erp.budget.balance.forward.line', 'forward_id')

    def _balance_for(self, plan_line):
        # Commitment forward credits must not turn encumbered source money into
        # an unused balance. The commit adapter supplies those preserved origins.
        carried = self.env['erp.budget.control.service']._carried_commitment(plan_line)
        return max(0, self.currency_id.round(plan_line._ceiling() - plan_line._consumed() - carried))

    def action_review(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state != 'draft':
            raise UserError(_('Only draft balance forwards may be reviewed.'))
        plans = self.env['erp.budget.plan'].search([('period_id', '=', self.source_period_id.id), ('state', 'in', ('confirm', 'done'))])
        if len(plans) != 1:
            raise UserError(_('One confirmed source plan is required.'))
        lines = plans.line_ids
        all_lines = self.env['erp.budget.plan.line'].sudo().search([('plan_id', '=', plans.id)])
        all_lines.with_env(self.env).check_access('write')
        if set(lines.ids) != set(all_lines.ids):
            raise AccessError(_('Access to every source plan line is required.'))
        reserved = self.env['erp.budget.balance.forward.line'].sudo().search([('source_line_id', 'in', lines.ids), ('reserved', '=', True)]).mapped('source_line_id')
        lines -= reserved.with_env(self.env)
        if not lines:
            raise UserError(_('Every source analytic is already reserved or forwarded.'))
        token = _balance_forward_internal.set(True)
        try:
            with self.env.cr.savepoint():
                next_round = self.review_round + 1
                self.env['erp.budget.balance.forward.line'].create([{'forward_id': self.id, 'source_line_id': line.id, 'round_number': next_round, 'balance_amount': self._balance_for(line), 'forward_amount': self._balance_for(line), 'destination_analytic_id': line.analytic_id.id, 'reserved': True} for line in lines])
                return self.write({'state': 'review', 'review_round': next_round})
        finally:
            _balance_forward_internal.reset(token)

    def action_forward(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state == 'done':
            return True
        if self.state != 'review' or not self._current_lines():
            raise UserError(_('Review the source balances before forwarding.'))
        token = _balance_forward_internal.set(True)
        try:
            with self.env.cr.savepoint():
                for line in self._current_lines():
                    line._validate_amounts()
                    if float_compare(line.balance_amount, self._balance_for(line.source_line_id), precision_rounding=self.currency_id.rounding):
                        raise UserError(_('The source balance changed; cancel and review it again.'))
                    for kind, analytic, amount in (('forward', line.destination_analytic_id, line.forward_amount), ('accumulate', line.accumulate_analytic_id, line.balance_amount - line.forward_amount)):
                        if not amount:
                            continue
                        opening = self.env['erp.budget.opening.balance'].create({'reference': 'balance-forward:%s:%s' % (line.id, kind), 'company_id': self.company_id.id, 'period_id': self.destination_period_id.id, 'organization_id': line.organization_id.id, 'analytic_id': analytic.id, 'initial_available': amount})
                        opening.action_confirm()
                        line.write({'opening_ids': [(4, opening.id)]})
                return self.write({'state': 'done', 'forwarded_by_id': self.env.user.id, 'forwarded_at': fields.Datetime.now()})
        finally:
            _balance_forward_internal.reset(token)

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state == 'cancel':
            return True
        if self.state not in ('draft', 'review', 'done'):
            raise UserError(_('This carry-forward cannot be cancelled.'))
        analytics = self._current_lines().mapped('destination_analytic_id') | self._current_lines().mapped('accumulate_analytic_id')
        if self.state == 'done' and (self.env['erp.budget.plan.line'].sudo().search_count([('period_id', '=', self.destination_period_id.id), ('analytic_id', 'in', analytics.ids), ('plan_id.state', 'in', ('confirm', 'done'))]) or self.env['erp.budget.control'].sudo().search_count([('period_id', '=', self.destination_period_id.id), ('analytic_id', 'in', analytics.ids), ('state', 'in', ('open', 'closed'))])):
            raise UserError(_('Withdraw effective destination planning before cancelling its opening provenance.'))
        token = _balance_forward_internal.set(True)
        try:
            with self.env.cr.savepoint():
                self._current_lines().mapped('opening_ids')._cancel_forward_origin()
                self._current_lines().write({'reserved': False})
                return self.write({'state': 'cancel'})
        finally:
            _balance_forward_internal.reset(token)



class BudgetBalanceForwardLine(models.Model):
    _name = 'erp.budget.balance.forward.line'
    _description = 'Budget Balance Forward Origin'
    _check_company_auto = True

    forward_id = fields.Many2one('erp.budget.balance.forward', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='forward_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='source_line_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    source_line_id = fields.Many2one('erp.budget.plan.line', required=True, check_company=True, ondelete='restrict')
    round_number = fields.Integer(required=True, readonly=True)
    balance_amount = fields.Monetary(required=True, readonly=True)
    forward_amount = fields.Monetary(required=True)
    destination_analytic_id = fields.Many2one('account.analytic.account', required=True, check_company=True, ondelete='restrict')
    accumulate_analytic_id = fields.Many2one('account.analytic.account', check_company=True, ondelete='restrict')
    reserved = fields.Boolean(readonly=True)
    opening_ids = fields.Many2many('erp.budget.opening.balance', readonly=True)

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute('CREATE UNIQUE INDEX IF NOT EXISTS erp_budget_balance_origin_reserved ON erp_budget_balance_forward_line (source_line_id) WHERE reserved')
        return result

    @api.constrains('balance_amount', 'forward_amount', 'destination_analytic_id', 'accumulate_analytic_id')
    def _validate_amounts(self):
        for line in self:
            if not math.isfinite(line.forward_amount) or line.forward_amount < 0 or line.forward_amount > line.balance_amount or abs(line.forward_amount - line.currency_id.round(line.forward_amount)) > 1e-9:
                raise ValidationError(_('Forward amount must be within the preserved balance and currency precision.'))
            if line.balance_amount > line.forward_amount and not line.accumulate_analytic_id:
                raise ValidationError(_('Select an accumulate analytic for the remaining balance.'))
            for analytic in line.destination_analytic_id | line.accumulate_analytic_id:
                analytic.check_access('read')
                if not analytic.active or (analytic.company_id and analytic.company_id != line.company_id):
                    raise ValidationError(_('Destination analytics must be active and company-compatible.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not _balance_forward_internal.get():
            raise AccessError(_('Balance origins are generated on review.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        for doc in self.mapped('forward_id'):
            doc._lock_scope()
        if not _balance_forward_internal.get() and (set(vals) - {'forward_amount', 'destination_analytic_id', 'accumulate_analytic_id'} or any(line.forward_id.state != 'review' or line.round_number != line.forward_id.review_round for line in self)):
            raise AccessError(_('Only current review destinations and amounts may be edited.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Carry-forward origins remain auditable.'))


class BudgetForwardOpening(models.Model):
    _inherit = 'erp.budget.opening.balance'

    def _cancel_forward_origin(self):
        if not _balance_forward_internal.get():
            raise AccessError(_('Forward opening cancellation is internal.'))
        return super(BudgetOpeningBalance, self).write({'state': 'cancel'})


class BudgetBalanceForwardService(models.AbstractModel):
    _inherit = 'erp.budget.control.service'

    def _carried_commitment(self, plan_line):
        return 0

    def _allow_sealed_scope(self, controls):
        return False

    def _is_forward_sealed(self, period_id, analytic_id):
        return bool(self.env['erp.budget.balance.forward.line'].sudo().search_count([('source_line_id.period_id', '=', period_id), ('source_line_id.analytic_id', '=', analytic_id), ('reserved', '=', True), ('forward_id.state', '=', 'done')]))

    def _check_plan_deltas(self, controls, deltas):
        scopes = {}
        for control in controls.filtered(lambda item: item.level == 'analytic'):
            key = (control.period_id.id, control.analytic_id.id)
            scopes[key] = scopes.get(key, 0) + deltas.get(control.id, 0)
        for (period_id, analytic_id), delta in scopes.items():
            if delta > 0 and not self._allow_sealed_scope(controls.filtered(lambda control: control.period_id.id == period_id and control.analytic_id.id == analytic_id)) and self._is_forward_sealed(period_id, analytic_id):
                raise UserError(_('The prior analytic is sealed after balance forwarding; spending belongs to its new fiscal scope.'))
        return super()._check_plan_deltas(controls, deltas)
