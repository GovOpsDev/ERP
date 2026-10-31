"""Balance origins reuse the Budget return workflow and existing review engine."""
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_balance_forward import _balance_forward_internal
from .budget_commit_return import BudgetCommitReturn, _return_internal


class BudgetBalanceReturn(models.Model):
    _inherit = 'erp.budget.balance.forward'

    return_revision_id = fields.Many2one('erp.budget.allocation.revision', readonly=True, check_company=True, ondelete='restrict')
    return_approval_id = fields.Many2one('erp.budget.kpi.release', readonly=True, check_company=True, ondelete='restrict')
    return_planning_ids = fields.Many2many('erp.budget.kpi.release', compute='_compute_return_planning')
    return_editable = fields.Boolean(compute='_compute_return_editable')
    return_mapping_ids = fields.One2many('erp.budget.balance.return.line', 'forward_id')

    # These are the same Budget-specific economic-return actions, with explicit
    # balance-origin hooks below. Approval continues to use existing Budget tiers.
    _compute_return_planning = BudgetCommitReturn._compute_return_planning
    _return_planning = BudgetCommitReturn._return_planning
    action_submit_return_planning = BudgetCommitReturn.action_submit_return_planning
    action_approve_return = BudgetCommitReturn.action_approve_return
    action_cancel_return = BudgetCommitReturn.action_cancel_return
    action_apply_return = BudgetCommitReturn.action_apply_return

    @api.depends('state', 'return_revision_id.state')
    def _compute_return_editable(self):
        for doc in self:
            doc.return_editable = doc.state == 'done' and doc.return_revision_id.state != 'draft'

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'return_revision_id', 'return_approval_id', 'return_planning_ids', 'return_mapping_ids'}
        if any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected):
            raise AccessError(_('Balance return history is prepared from its preserved origins.'))
        return super().create(vals_list)

    def write(self, vals):
        protected = {'return_revision_id', 'return_approval_id', 'return_planning_ids'}
        if protected & vals.keys() and not _return_internal.get():
            raise AccessError(_('Balance return history is assigned by its workflow.'))
        if 'return_mapping_ids' in vals:
            if self.state != 'done' or self.return_revision_id.state == 'draft':
                raise AccessError(_('Return distributions must be prepared before submitting their proposal.'))
            vals = dict(vals)
            commands = vals.pop('return_mapping_ids')
            for command in commands:
                if command[0] == 0:
                    self.env['erp.budget.balance.return.line'].create(dict(command[2], forward_id=self.id))
                elif command[0] == 1:
                    line = self.return_mapping_ids.filtered(lambda line: line.id == command[1])
                    line.ensure_one()
                    line.write(command[2])
                elif command[0] == 2:
                    line = self.return_mapping_ids.filtered(lambda line: line.id == command[1])
                    line.ensure_one()
                    line.unlink()
                else:
                    raise AccessError(_('Return distributions use explicit origin lines.'))
            if not vals:
                return True
        token = _balance_forward_internal.set(True) if _return_internal.get() else None
        try:
            return super().write(vals)
        finally:
            if token is not None:
                _balance_forward_internal.reset(token)

    def _return_link_field(self):
        return 'balance_return_id'

    def _return_openings(self):
        return self._current_lines().mapped('opening_ids').filtered(lambda opening: opening.state == 'done')

    def _return_movements(self):
        return []

    def _validate_return(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError(_('Only an applied balance forward may be returned.'))
        for model in ('erp.budget.balance.forward', 'erp.budget.commit.forward'):
            if self.env[model].search_count([('company_id', '=', self.company_id.id), ('state', '=', 'done'), ('source_period_id.date_from', '>=', self.destination_period_id.date_from)]):
                raise UserError(_('Return subsequent fiscal forwards before withdrawing this balance origin.'))
        return []

    def _ensure_return_mapping(self):
        for opening in self._return_openings():
            existing = self.return_mapping_ids.filtered(lambda line: line.opening_id == opening)
            if existing:
                continue
            controls = self.env['erp.budget.control'].search([('period_id', '=', self.destination_period_id.id), ('analytic_id', '=', opening.analytic_id.id), ('state', '=', 'open')])
            analytics = controls.filtered(lambda control: control.level == 'analytic')
            funds = controls.filtered(lambda control: control.level == 'fund')
            self.env['erp.budget.balance.return.line'].create({'forward_id': self.id, 'opening_id': opening.id, 'amount': opening.initial_available, 'analytic_control_id': analytics.id if len(analytics) == 1 else False, 'fund_control_id': funds.id if len(funds) == 1 else False})

    def action_prepare_return_mapping(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        self._validate_return()
        self._ensure_return_mapping()
        return True

    def _withdrawal_deltas(self):
        funds, analytics = {}, {}
        for opening in self._return_openings():
            lines = self.return_mapping_ids.filtered(lambda line: line.opening_id == opening)
            if not lines or float_compare(sum(lines.mapped('amount')), opening.initial_available, precision_rounding=self.currency_id.rounding):
                raise UserError(_('Distribute the complete preserved opening balance over its destination controls.'))
            for line in lines:
                line._validate_mapping(require_controls=True)
                funds[line.fund_control_id.id] = funds.get(line.fund_control_id.id, 0) + line.amount
                analytics[line.analytic_control_id.id] = analytics.get(line.analytic_control_id.id, 0) + line.amount
        return funds, analytics

    def action_prepare_return(self):
        self.action_prepare_return_mapping()
        return BudgetCommitReturn.action_prepare_return(self)

    def action_cancel(self):
        self.ensure_one()
        if self.state != 'done':
            return super().action_cancel()
        self.check_access('write')
        self._lock_scope()
        if not self._return_openings():
            token = _balance_forward_internal.set(True)
            try:
                self._current_lines().write({'reserved': False})
                return self.write({'state': 'cancel'})
            finally:
                _balance_forward_internal.reset(token)
        analytics = self._return_openings().analytic_id
        effective = self.env['erp.budget.plan.line'].sudo().search_count([('period_id', '=', self.destination_period_id.id), ('analytic_id', 'in', analytics.ids), ('plan_id.state', 'in', ('confirm', 'done'))]) or self.env['erp.budget.control'].sudo().search_count([('period_id', '=', self.destination_period_id.id), ('analytic_id', 'in', analytics.ids), ('state', 'in', ('open', 'closed'))])
        if effective:
            return self.action_prepare_return()
        return super().action_cancel()


class BudgetBalanceReturnLine(models.Model):
    _name = 'erp.budget.balance.return.line'
    _description = 'Balance Return Capacity Distribution'
    _check_company_auto = True

    forward_id = fields.Many2one('erp.budget.balance.forward', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='forward_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='opening_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    opening_id = fields.Many2one('erp.budget.opening.balance', required=True, check_company=True, ondelete='restrict')
    analytic_control_id = fields.Many2one('erp.budget.control', check_company=True, ondelete='restrict')
    fund_control_id = fields.Many2one('erp.budget.control', check_company=True, ondelete='restrict')
    amount = fields.Monetary(required=True)

    @api.constrains('forward_id', 'opening_id', 'analytic_control_id', 'fund_control_id', 'amount')
    def _check_mapping(self):
        self._validate_mapping()

    def _validate_mapping(self, require_controls=False):
        for line in self:
            if line.opening_id not in line.forward_id._return_openings():
                raise ValidationError(_('The return must reference a current confirmed balance origin.'))
            if not math.isfinite(line.amount) or line.amount <= 0 or abs(line.amount - line.currency_id.round(line.amount)) > 1e-9:
                raise ValidationError(_('A return distribution requires a positive precise amount.'))
            if require_controls and (not line.analytic_control_id or not line.fund_control_id):
                raise UserError(_('Select the exact destination fund and analytic/KPI controls for the return.'))
            for control, level in ((line.analytic_control_id, 'analytic'), (line.fund_control_id, 'fund')):
                if not control:
                    continue
                control.check_access('write')
                if control.period_id != line.forward_id.destination_period_id or control.company_id != line.company_id or control.analytic_id != line.opening_id.analytic_id or control.level != level or control.state != 'open':
                    raise ValidationError(_('Return controls must match the opening analytic and destination fiscal scope.'))

    def _check_editable(self):
        self.check_access('write')
        for doc in self.mapped('forward_id'):
            doc._lock_scope()
            if doc.state != 'done' or doc.return_revision_id.state == 'draft':
                raise AccessError(_('Only unsubmitted current balance return distributions may be edited.'))
        if any(line.opening_id not in line.forward_id._return_openings() for line in self):
            raise AccessError(_('Past return distributions are immutable.'))

    @api.model_create_multi
    def create(self, vals_list):
        forbidden = {'company_id', 'organization_id', 'currency_id'}
        if any(forbidden & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in forbidden):
            raise AccessError(_('Distribution scope derives from its preserved origin.'))
        for vals in vals_list:
            doc = self.env['erp.budget.balance.forward'].browse(vals.get('forward_id'))
            doc.check_access('write')
            doc._lock_scope()
            if doc.state != 'done' or doc.return_revision_id.state == 'draft':
                raise AccessError(_('Prepare distributions before the economic return proposal.'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_editable()
        if set(vals) - {'analytic_control_id', 'fund_control_id', 'amount'}:
            raise AccessError(_('Return origin ownership is immutable.'))
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()
