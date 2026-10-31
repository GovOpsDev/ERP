"""An applied forward returns through a reviewed capacity-withdrawal successor."""
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_allocation_revision import BudgetAllocationRevision
from .budget_balance_forward import _balance_forward_internal
from .budget_release import _planning_internal, _tier_approved

_return_internal = ContextVar('budget_commit_return_internal', default=False)
_return_source_ids = ContextVar('budget_commit_return_source_ids', default=())


class BudgetCommitReturn(models.Model):
    _inherit = 'erp.budget.commit.forward'

    return_revision_id = fields.Many2one('erp.budget.allocation.revision', readonly=True, check_company=True, ondelete='restrict')
    return_approval_id = fields.Many2one('erp.budget.kpi.release', readonly=True, check_company=True, ondelete='restrict')
    return_planning_ids = fields.Many2many('erp.budget.kpi.release', compute='_compute_return_planning')

    @api.depends('return_revision_id')
    def _compute_return_planning(self):
        for doc in self:
            doc.return_planning_ids = doc._return_planning() if doc.return_revision_id else self.env['erp.budget.kpi.release']

    def _return_link_field(self):
        return 'commit_return_id'

    def _return_openings(self):
        return self._current_lines().mapped('opening_id')

    def _return_planning(self):
        return self.env['erp.budget.kpi.release'].search([('allocation_revision_id', '=', self.return_revision_id.id)])

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'return_revision_id', 'return_approval_id', 'return_planning_ids'}
        if any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected):
            raise AccessError(_('Economic return history is assigned by the return workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'return_revision_id', 'return_approval_id', 'return_planning_ids'} & vals.keys() and not _return_internal.get():
            raise AccessError(_('Economic return history is assigned by the return workflow.'))
        token = _balance_forward_internal.set(True) if _return_internal.get() else None
        try:
            return super().write(vals)
        finally:
            if token is not None:
                _balance_forward_internal.reset(token)

    def _return_movements(self):
        """Current encumbrance may now be the primary PR restored from a PO."""
        self.ensure_one()
        mappings = {}
        for line in self._current_lines():
            old = line.source_analytic_control_id | line.source_fund_control_id
            destination = line.destination_analytic_control_id | line.destination_fund_control_id
            mappings[line.source_key] = (old, destination, line.amount)
            if line.fallback_analytic_control_id:
                original = line.fallback_source_analytic_control_id | line.fallback_source_fund_control_id
                fallback = line.fallback_analytic_control_id | line.fallback_fund_control_id
                if line.family_key in mappings:
                    prior_old, prior_destination, prior_limit = mappings[line.family_key]
                    if set(prior_old.ids) != set(original.ids) or set(prior_destination.ids) != set(fallback.ids):
                        raise ValidationError(_('Primary return routes must agree.'))
                    mappings[line.family_key] = original, fallback, prior_limit + line.amount
                else:
                    mappings[line.family_key] = original, fallback, line.amount
        Move = self.env['erp.budget.move']
        result = []
        for key, (original, destination, limit) in mappings.items():
            moves = Move.search([('source_key', '=', key), ('control_id.period_id', '=', self.destination_period_id.id), ('move_type', 'in', ('pr_commitment', 'po_commitment', 'contract_commitment', 'expense_commitment', 'advance_commitment')), ('reversal_of_id', '=', False)])
            reversed_ids = Move.sudo().search([('reversal_of_id', 'in', moves.ids)]).mapped('reversal_of_id').ids
            moves = moves.filtered(lambda move: move.id not in reversed_ids)
            if not moves:
                continue
            if len(moves) != 2 or set(moves.control_id.ids) != set(destination.ids) or len(set(moves.mapped('amount'))) != 1 or len(set(moves.mapped('move_type'))) != 1:
                raise ValidationError(_('The outstanding return origin no longer matches its paired destination.'))
            if float_compare(moves[0].amount, limit, precision_rounding=self.currency_id.rounding) > 0:
                raise UserError(_('New-period increases cannot be returned as prior-year commitments.'))
            original.check_access('write')
            result.append((moves, original))
        return result

    def _validate_return(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError(_('Only an applied commitment forward may be returned.'))
        later = self.search_count([('company_id', '=', self.company_id.id), ('state', '=', 'done'), ('destination_period_id.date_from', '>', self.destination_period_id.date_from)])
        if later:
            raise UserError(_('Return the latest fiscal forward first.'))
        keys = self._current_lines().mapped('source_key')
        actuals = self.env['erp.budget.move'].sudo().search([('purchase_source_key', 'in', keys), ('control_id.period_id', '=', self.destination_period_id.id), ('move_type', '=', 'actual'), ('reversal_of_id', '=', False)])
        reversed_ids = self.env['erp.budget.move'].sudo().search([('reversal_of_id', 'in', actuals.ids)]).mapped('reversal_of_id').ids
        if any(move.id not in reversed_ids and move.amount for move in actuals):
            raise UserError(_('Resolve destination-period actuals before returning their commitment origin.'))
        return self._return_movements()

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'done':
            return self.action_prepare_return()
        return super().action_cancel()

    def action_prepare_return(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        self._validate_return()
        if self.return_revision_id.state == 'draft':
            return {'type': 'ir.actions.act_window', 'res_model': self.return_revision_id._name, 'view_mode': 'form', 'res_id': self.return_revision_id.id}
        allocation = self.env['erp.budget.allocation'].search([('period_id', '=', self.destination_period_id.id)])
        if not allocation:
            plan = self.env['erp.budget.plan'].search([('period_id', '=', self.destination_period_id.id), ('state', 'in', ('confirm', 'done'))])
            if len(plan) != 1:
                raise UserError(_('Confirm and explicitly capture destination planning before preparing an economic return.'))
            allocation = self.env['erp.budget.allocation'].browse(plan.action_capture_legacy_allocation()['res_id'])
        token = _return_internal.set(True)
        try:
            with self.env.cr.savepoint():
                revision = self.env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
                revision._link_forward_return(self)
                revision.write({'reason': _('Return commitment forward: %s') % self.name})
                fund_deltas, analytic_deltas = self._withdrawal_deltas()
                for row in revision.line_ids:
                    row.write({'amount': row.base_amount - fund_deltas.get(row.allocation_line_id.control_id.id, 0)})
                self.write({'return_revision_id': revision.id})
                releases = self.env['erp.budget.kpi.release'].search([('plan_line_id.plan_id', '=', allocation.plan_id.id), ('state', '=', 'done')])
                if set(releases.plan_line_id.ids) != set(allocation.plan_id.line_ids.ids) or len(releases) != len(allocation.plan_id.line_ids):
                    raise UserError(_('Each destination analytic requires one complete effective planning version.'))
                for release in releases:
                    planning = self.env['erp.budget.kpi.release'].browse(release.action_prepare_revision(revision.id)['res_id'])
                    for row in planning.line_ids:
                        row.write({'amount': row.amount - analytic_deltas.get(row.control_id.id, 0)})
                    planning.write({'released_amount': sum(planning.line_ids.mapped('amount'))})
                proxy = self.env['erp.budget.kpi.release'].create({'name': _('Return review: %s') % self.name, 'plan_line_id': releases[0].plan_line_id.id, 'released_amount': 0, self._return_link_field(): self.id})
                self.write({'return_approval_id': proxy.id})
                proxy.action_submit()
        finally:
            _return_internal.reset(token)
        return {'type': 'ir.actions.act_window', 'res_model': revision._name, 'view_mode': 'form', 'res_id': revision.id}

    def _withdrawal_deltas(self):
        funds, analytics = {}, {}
        for line in self._current_lines():
            funds[line.destination_fund_control_id.id] = funds.get(line.destination_fund_control_id.id, 0) + line.amount
            analytics[line.destination_analytic_control_id.id] = analytics.get(line.destination_analytic_control_id.id, 0) + line.amount
        return funds, analytics

    def action_submit_return_planning(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        self._validate_return()
        if self.return_revision_id.state != 'draft':
            raise UserError(_('Prepare the economic return first.'))
        for planning in self._return_planning().filtered(lambda release: release.state == 'draft'):
            planning.action_submit()
        return True

    def action_approve_return(self):
        self.ensure_one()
        self.check_access('read')
        return self.return_approval_id.action_approve()

    def action_cancel_return(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.return_revision_id.state != 'draft':
            raise UserError(_('Only an unapplied return proposal may be cancelled.'))
        token = _planning_internal.set(True)
        try:
            with self.env.cr.savepoint():
                self.return_revision_id.action_cancel()
                self.return_approval_id.write({'state': 'cancel'})
        finally:
            _planning_internal.reset(token)
        return True

    def action_apply_return(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state == 'cancel' and self.return_revision_id.state == 'effective':
            return True
        movements = self._validate_return()
        if self.return_revision_id.state != 'draft' or self.return_approval_id.state != 'approved':
            raise UserError(_('Complete every economic return review first.'))
        funds, analytics = self._withdrawal_deltas()
        for row in self.return_revision_id.line_ids:
            expected = row.base_amount - funds.get(row.allocation_line_id.control_id.id, 0)
            if float_compare(row.amount, expected, precision_rounding=self.currency_id.rounding):
                raise UserError(_('The proposed fund capacity differs from the original forward withdrawal.'))
        planning = self._return_planning()
        for control_id, amount in analytics.items():
            control = self.env['erp.budget.control'].browse(control_id)
            row = planning.line_ids.filtered(lambda item: item.control_id == control)
            if len(row) != 1 or float_compare(row.amount, control.amount - amount, precision_rounding=self.currency_id.rounding):
                raise UserError(_('The proposed analytic capacity differs from the original forward withdrawal.'))
        source_ids = tuple(sorted({control.id for moves, original in movements for control in original}))
        token = _return_internal.set(True)
        balance_token = _balance_forward_internal.set(True)
        source_token = _return_source_ids.set(source_ids)
        try:
            with self.env.cr.savepoint():
                Move = self.env['erp.budget.move'].sudo()
                service = self.env['erp.budget.control.service']
                for moves, original in movements:
                    service._check_available(original, moves[0].amount, original.period_id.date_to)
                    for move in moves:
                        Move.create({'control_id': move.control_id.id, 'origin_key': 'forward-return-credit:%s:%s' % (self.return_revision_id.id, move.id), 'family_key': move.family_key, 'source_key': move.source_key, 'move_type': {'pr_commitment': 'pr_reversal', 'po_commitment': 'po_reversal', 'contract_commitment': 'contract_reversal', 'expense_commitment': 'expense_reversal', 'advance_commitment': 'advance_reversal'}[move.move_type], 'amount': -move.amount, 'reversal_of_id': move.id})
                    Move.create([{'control_id': control.id, 'origin_key': 'forward-return-debit:%s:%s' % (self.return_revision_id.id, moves[0].source_key), 'family_key': moves[0].family_key, 'source_key': moves[0].source_key, 'move_type': moves[0].move_type, 'amount': moves[0].amount} for control in original])
                    self.env.cr.execute('UPDATE erp_budget_control SET lock_version = lock_version + 1 WHERE id IN %s', [tuple(sorted((original | moves.control_id).ids))])
                self._return_openings()._cancel_forward_origin()
                self._current_lines().write({'reserved': False})
                self.write({'state': 'cancel'})
                self.return_revision_id.action_activate()
        finally:
            _return_source_ids.reset(source_token)
            _balance_forward_internal.reset(balance_token)
            _return_internal.reset(token)
        return True


class BudgetCommitReturnPlanning(models.Model):
    _inherit = 'erp.budget.kpi.release'

    commit_return_id = fields.Many2one('erp.budget.commit.forward', readonly=True, check_company=True, ondelete='restrict')
    balance_return_id = fields.Many2one('erp.budget.balance.forward', readonly=True, check_company=True, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        if not _return_internal.get() and (any({'commit_return_id', 'balance_return_id'} & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in ('commit_return_id', 'balance_return_id'))):
            raise AccessError(_('Return review origins are assigned internally.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'commit_return_id', 'balance_return_id'} & vals.keys() and not _return_internal.get():
            raise AccessError(_('Return review origins are immutable.'))
        return super().write(vals)

    def _lock_controls(self):
        self.ensure_one()
        if self.commit_return_id or self.balance_return_id:
            return (self.commit_return_id or self.balance_return_id)._lock_scope()
        return super()._lock_controls()

    def action_submit(self):
        self.ensure_one()
        if not (self.commit_return_id or self.balance_return_id):
            return super().action_submit()
        self.check_access('write')
        controls = self._lock_controls()
        (self.commit_return_id or self.balance_return_id)._validate_return()
        if self.state != 'draft' or self.line_ids or self.released_amount:
            raise UserError(_('Return approval carries no released capacity.'))
        tiers = self.env['erp.budget.kpi.tier'].search([('company_id', '=', self.company_id.id), ('organization_id', '=', self.organization_id.id), ('kind', '=', 'transfer'), ('active', '=', True)], order='sequence,id')
        return self._submit_tiers(tiers, controls)

    def action_release(self):
        self.ensure_one()
        if not (self.commit_return_id or self.balance_return_id):
            return super().action_release()
        self.check_access('write')
        self._lock_controls()
        (self.commit_return_id or self.balance_return_id)._validate_return()
        if not _tier_approved.get() or self.state != 'submit' or self.line_ids or self.released_amount:
            raise AccessError(_('Ordered reviewers must approve the economic return.'))
        token = _planning_internal.set(True)
        try:
            return self.write({'state': 'approved'})
        finally:
            _planning_internal.reset(token)

    def action_reject(self):
        result = super().action_reject()
        if self.commit_return_id or self.balance_return_id:
            (self.commit_return_id or self.balance_return_id).action_cancel_return()
        return result

    def _return_proposal(self):
        doc = self.allocation_revision_id.commit_return_id or self.allocation_revision_id.balance_return_id
        if doc.state == 'done' and doc.return_revision_id == self.allocation_revision_id and self.allocation_revision_id.state == 'draft':
            return doc
        return self.env['erp.budget.commit.forward']

    def _planning_consumed(self, control):
        amount = super()._planning_consumed(control)
        doc = self._return_proposal()
        if doc:
            for moves, original in doc._validate_return():
                amount -= sum(moves.filtered(lambda move: move.control_id == control).mapped('amount'))
        return amount

    def _check_planning_opening(self, amount):
        doc = self._return_proposal()
        if not doc:
            return super()._check_planning_opening(amount)
        doc._validate_return()
        openings = doc._return_openings().filtered(lambda opening: opening.state == 'done' and opening.analytic_id == self.plan_line_id.analytic_id)
        minimum = self.plan_line_id._opening_minimum() - sum(openings.mapped('initial_commit')) - sum(openings.mapped('initial_available'))
        if float_compare(amount, minimum, precision_rounding=self.currency_id.rounding) < 0:
            raise UserError(_('Revised planning must cover the retained opening balance.'))
        return True


class BudgetCommitReturnReleaseLine(models.Model):
    _inherit = 'erp.budget.kpi.release.line'

    @api.model_create_multi
    def create(self, vals_list):
        if any(self.env['erp.budget.kpi.release'].browse(vals.get('release_id')).commit_return_id or self.env['erp.budget.kpi.release'].browse(vals.get('release_id')).balance_return_id for vals in vals_list):
            raise AccessError(_('Economic return approvals cannot contain capacity.'))
        return super().create(vals_list)


class BudgetCommitReturnRevision(models.Model):
    _inherit = 'erp.budget.allocation.revision'

    commit_return_id = fields.Many2one('erp.budget.commit.forward', readonly=True, check_company=True, ondelete='restrict')
    balance_return_id = fields.Many2one('erp.budget.balance.forward', readonly=True, check_company=True, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        if not _return_internal.get() and (any({'commit_return_id', 'balance_return_id'} & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in ('commit_return_id', 'balance_return_id'))):
            raise AccessError(_('Return allocation origins are assigned internally.'))
        return super().create(vals_list)

    def _link_forward_return(self, doc):
        if not _return_internal.get() or self.period_id != doc.destination_period_id or self.state != 'draft':
            raise AccessError(_('Return revision links are internal.'))
        return super(BudgetAllocationRevision, self).write({doc._return_link_field(): doc.id})

    def action_activate(self):
        if (self.commit_return_id or self.balance_return_id) and not _return_internal.get():
            raise AccessError(_('Activate this successor through its reviewed commitment return.'))
        return super().action_activate()


class BudgetCommitReturnService(models.AbstractModel):
    _inherit = 'erp.budget.control.service'

    def _allow_sealed_scope(self, controls):
        return bool(_return_internal.get() and controls and set(controls.ids) <= set(_return_source_ids.get())) or super()._allow_sealed_scope(controls)
