"""Typed commitment origins move by immutable credits and debits, not edits."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_balance_forward import _balance_forward_internal


class BudgetCommitForward(models.Model):
    _name = 'erp.budget.commit.forward'
    _inherit = 'erp.budget.forward.workflow'
    _description = 'Budget Commitment Forward'

    line_ids = fields.One2many('erp.budget.commit.forward.line', 'forward_id')

    def _lock_scope(self):
        self.ensure_one()
        moves = self.env['erp.budget.move'].search([('control_id.period_id', '=', self.source_period_id.id), ('move_type', 'in', ('pr_commitment', 'po_commitment', 'contract_commitment', 'expense_commitment', 'advance_commitment'))])
        activities = self.env['erp.budget.activity']
        periods = self.source_period_id | self.destination_period_id
        for move in moves.filtered(lambda item: item.control_id.level == 'analytic'):
            source = move._planning_source()
            if source:
                source[0].check_access('read')
                activities |= source[2]
            fallback = move._planning_fallback_key()
            if fallback:
                activities |= fallback['activity']
                periods |= fallback['period']
        routes = self.env['erp.budget.commit.forward.line'].sudo().search([('family_key', 'in', moves.mapped('family_key')), ('reserved', '=', True)])
        periods |= routes.mapped('source_period_id') | routes.mapped('forward_id.destination_period_id')
        activities._lock_activity_key()
        controls = self.env['erp.budget.control'].sudo().with_context(active_test=False).search([('period_id', 'in', periods.ids)]).with_env(self.env)
        controls.check_access('write')
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        periods._lock_plan_periods()
        return super()._lock_scope()

    def action_review(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state != 'draft':
            raise UserError(_('Only draft commitment forwards may be reviewed.'))
        Move = self.env['erp.budget.move']
        moves = Move.search([('control_id.period_id', '=', self.source_period_id.id), ('move_type', 'in', ('pr_commitment', 'po_commitment', 'contract_commitment', 'expense_commitment', 'advance_commitment')), ('reversal_of_id', '=', False)])
        reversed_ids = Move.sudo().search([('reversal_of_id', 'in', moves.ids)]).mapped('reversal_of_id').ids
        moves = moves.filtered(lambda move: move.id not in reversed_ids and move.amount > 0)
        grouped = {}
        for move in moves:
            grouped.setdefault((move.family_key, move.source_key), Move)
            grouped[(move.family_key, move.source_key)] |= move
        reserved = self.env['erp.budget.commit.forward.line'].sudo().search([('source_period_id', '=', self.source_period_id.id), ('reserved', '=', True)]).mapped('source_key')
        values = []
        for (family, key), entries in grouped.items():
            if key in reserved:
                continue
            analytic = entries.filtered(lambda move: move.control_id.level == 'analytic')
            fund = entries.filtered(lambda move: move.control_id.level == 'fund')
            if not family or not key or len(entries) != 2 or len(analytic) != 1 or len(fund) != 1 or analytic.amount != fund.amount or analytic.move_type != fund.move_type:
                raise ValidationError(_('Only complete paired typed commitment origins may be forwarded.'))
            source = analytic._planning_source()
            if not source:
                raise ValidationError(_('The commitment must retain an identifiable authorized source document.'))
            source[0].check_access('read')
            values.append({'forward_id': self.id, 'round_number': self.review_round + 1, 'source_key': key, 'family_key': family, 'amount': analytic.amount, 'move_type': analytic.move_type, 'source_analytic_control_id': analytic.control_id.id, 'source_fund_control_id': fund.control_id.id, 'source_move_ids': [(6, 0, entries.ids)], 'reserved': True})
        if not values:
            raise UserError(_('No unforwarded outstanding typed commitment remains in this source period.'))
        token = _balance_forward_internal.set(True)
        try:
            with self.env.cr.savepoint():
                self.env['erp.budget.commit.forward.line'].create(values)
                return self.write({'state': 'review', 'review_round': self.review_round + 1})
        finally:
            _balance_forward_internal.reset(token)

    def action_forward(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state == 'done':
            return True
        if self.state != 'review' or not self._current_lines():
            raise UserError(_('Review the outstanding commitments first.'))
        token = _balance_forward_internal.set(True)
        try:
            with self.env.cr.savepoint():
                for line in self._current_lines():
                    line._validate_destination()
                    current = line._current_moves()
                    if set(current.ids) != set(line.source_move_ids.ids):
                        raise UserError(_('The source commitment changed; cancel and review again.'))
                    destination = line.destination_analytic_control_id | line.destination_fund_control_id
                    self.env['erp.budget.control.service']._check_available(destination, line.amount, self.destination_period_id.date_from)
                    opening = self.env['erp.budget.opening.balance'].create({'reference': 'commit-forward:%s' % line.id, 'company_id': self.company_id.id, 'period_id': self.destination_period_id.id, 'organization_id': line.organization_id.id, 'analytic_id': line.destination_analytic_control_id.analytic_id.id, 'initial_commit': line.amount})
                    opening.action_confirm()
                    line._move_commitment(current, destination)
                    line.write({'opening_id': opening.id})
                return self.write({'state': 'done', 'forwarded_by_id': self.env.user.id, 'forwarded_at': fields.Datetime.now()})
        finally:
            _balance_forward_internal.reset(token)

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state == 'cancel':
            return True
        if self.state not in ('draft', 'review'):
            raise UserError(_('An applied commitment forward needs a reviewed economic return before cancellation.'))
        token = _balance_forward_internal.set(True)
        try:
            self._current_lines().write({'reserved': False})
            return self.write({'state': 'cancel'})
        finally:
            _balance_forward_internal.reset(token)


class BudgetCommitForwardLine(models.Model):
    _name = 'erp.budget.commit.forward.line'
    _description = 'Budget Commitment Forward Origin'
    _check_company_auto = True

    forward_id = fields.Many2one('erp.budget.commit.forward', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='forward_id.company_id', store=True, index=True)
    source_period_id = fields.Many2one(related='forward_id.source_period_id', store=True, index=True)
    organization_id = fields.Many2one(related='source_analytic_control_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    round_number = fields.Integer(required=True, readonly=True)
    source_key = fields.Char(required=True, readonly=True, index=True)
    family_key = fields.Char(required=True, readonly=True, index=True)
    move_type = fields.Selection([('pr_commitment', 'PR commitment'), ('po_commitment', 'PO commitment'), ('contract_commitment', 'Contract commitment'), ('expense_commitment', 'Expense commitment'), ('advance_commitment', 'Advance commitment')], required=True, readonly=True)
    amount = fields.Monetary(required=True, readonly=True)
    source_analytic_control_id = fields.Many2one('erp.budget.control', required=True, readonly=True, check_company=True, ondelete='restrict')
    source_fund_control_id = fields.Many2one('erp.budget.control', required=True, readonly=True, check_company=True, ondelete='restrict')
    destination_analytic_control_id = fields.Many2one('erp.budget.control', check_company=True, ondelete='restrict')
    destination_fund_control_id = fields.Many2one('erp.budget.control', check_company=True, ondelete='restrict')
    fallback_source_analytic_control_id = fields.Many2one('erp.budget.control', readonly=True, check_company=True, ondelete='restrict')
    fallback_source_fund_control_id = fields.Many2one('erp.budget.control', readonly=True, check_company=True, ondelete='restrict')
    fallback_analytic_control_id = fields.Many2one('erp.budget.control', check_company=True, ondelete='restrict')
    fallback_fund_control_id = fields.Many2one('erp.budget.control', check_company=True, ondelete='restrict')
    source_move_ids = fields.Many2many('erp.budget.move', readonly=True)
    opening_id = fields.Many2one('erp.budget.opening.balance', readonly=True, check_company=True, ondelete='restrict')
    reserved = fields.Boolean(readonly=True)

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute('CREATE UNIQUE INDEX IF NOT EXISTS erp_budget_commit_origin_reserved ON erp_budget_commit_forward_line (source_period_id, source_key) WHERE reserved')
        return result

    def _current_moves(self):
        self.ensure_one()
        moves = self.env['erp.budget.move'].search([('family_key', '=', self.family_key), ('source_key', '=', self.source_key), ('control_id.period_id', '=', self.source_period_id.id), ('move_type', '=', self.move_type), ('reversal_of_id', '=', False)])
        reversed_ids = self.env['erp.budget.move'].sudo().search([('reversal_of_id', 'in', moves.ids)]).mapped('reversal_of_id').ids
        return moves.filtered(lambda move: move.id not in reversed_ids)

    def _validate_destination(self):
        self.ensure_one()
        source_controls = self.source_analytic_control_id | self.source_fund_control_id
        destination = self.destination_analytic_control_id | self.destination_fund_control_id
        (source_controls | destination).check_access('read')
        if len(destination) != 2 or set(destination.mapped('level')) != {'analytic', 'fund'}:
            raise ValidationError(_('Select one analytic and one fund control for the next period.'))
        source = self.source_move_ids.filtered(lambda move: move.control_id.level == 'analytic')._planning_source()
        if not source:
            raise ValidationError(_('The original authorized source line is required.'))
        record, account, activity = source
        record.check_access('read')
        expected = self.env['erp.budget.control.service']._resolve(self.forward_id.destination_period_id, self.organization_id, self.destination_analytic_control_id.analytic_id, self.source_fund_control_id.fund_id, account, self.source_fund_control_id.dimension_ids, activity=activity)
        if set(expected.ids) != set(destination.ids):
            raise ValidationError(_('Forward controls must retain the source company, organization, fund, dimensions and mapped activity/KPI.'))
        self._validate_fallback()

    def _validate_fallback(self):
        source_move = self.source_move_ids.filtered(lambda move: move.control_id.level == 'analytic')
        key = source_move._planning_fallback_key()
        if not key:
            return
        service = self.env['erp.budget.control.service']
        original = service._resolve(**key)
        original, date = service._forward_route(self.family_key, original, key['period'].date_from)
        selected = self.fallback_analytic_control_id | self.fallback_fund_control_id
        if not selected:
            if original.analytic_id != self.source_analytic_control_id.analytic_id:
                raise UserError(_('Select an explicit primary-request destination when the PO and PR analytics differ.'))
            target_analytic = self.destination_analytic_control_id.analytic_id
        else:
            if len(selected) != 2:
                raise ValidationError(_('Both fallback controls are required.'))
            target_analytic = self.fallback_analytic_control_id.analytic_id
        expected = service._resolve(self.forward_id.destination_period_id, key['organization'], target_analytic, key['fund'], key['account'], key['dimensions'], activity=key['activity'])
        if selected and set(expected.ids) != set(selected.ids):
            raise ValidationError(_('Fallback controls must preserve the primary request key in its destination period.'))
        siblings = self.search([('family_key', '=', self.family_key), ('forward_id.destination_period_id', '=', self.forward_id.destination_period_id.id), ('forward_id.state', '=', 'done'), ('reserved', '=', True)])
        for sibling in siblings:
            if set((sibling.fallback_analytic_control_id | sibling.fallback_fund_control_id).ids) != set(expected.ids):
                raise ValidationError(_('A primary request must have one agreed fallback destination per fiscal period.'))
        if not _balance_forward_internal.get():
            raise AccessError(_('Fallback routing is recorded during authorized forwarding.'))
        self.write({'fallback_source_analytic_control_id': original.filtered(lambda control: control.level == 'analytic').id, 'fallback_source_fund_control_id': original.filtered(lambda control: control.level == 'fund').id, 'fallback_analytic_control_id': expected.filtered(lambda control: control.level == 'analytic').id, 'fallback_fund_control_id': expected.filtered(lambda control: control.level == 'fund').id})

    def _move_commitment(self, current, destination):
        if not _balance_forward_internal.get():
            raise AccessError(_('Commitment movement belongs to the forward workflow.'))
        source = self.source_analytic_control_id | self.source_fund_control_id
        self.env['erp.budget.control.service']._check_plan_deltas(source | destination, {control.id: -self.amount if control in source else self.amount for control in source | destination if control.level == 'analytic'})
        Move = self.env['erp.budget.move'].sudo()
        self.env.cr.execute('UPDATE erp_budget_control SET lock_version = lock_version + 1 WHERE id IN %s', [tuple(sorted((source | destination).ids))])
        for move in current:
            Move.create({'control_id': move.control_id.id, 'origin_key': 'forward-credit:%s:%s' % (self.id, move.id), 'family_key': self.family_key, 'source_key': self.source_key, 'move_type': {'pr_commitment': 'pr_reversal', 'po_commitment': 'po_reversal', 'contract_commitment': 'contract_reversal', 'expense_commitment': 'expense_reversal', 'advance_commitment': 'advance_reversal'}[self.move_type], 'amount': -move.amount, 'reversal_of_id': move.id})
        Move.create([{'control_id': control.id, 'origin_key': 'forward-debit:%s' % self.id, 'family_key': self.family_key, 'source_key': self.source_key, 'move_type': self.move_type, 'amount': self.amount} for control in destination])

    @api.model_create_multi
    def create(self, vals_list):
        if not _balance_forward_internal.get():
            raise AccessError(_('Commitment origins are generated during review.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        for doc in self.mapped('forward_id'):
            doc._lock_scope()
        if not _balance_forward_internal.get() and (set(vals) - {'destination_analytic_control_id', 'destination_fund_control_id', 'fallback_analytic_control_id', 'fallback_fund_control_id'} or any(line.forward_id.state != 'review' or line.round_number != line.forward_id.review_round for line in self)):
            raise AccessError(_('Only current review destinations may be edited.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Commitment forward origins remain auditable.'))


class BudgetCommitForwardService(models.AbstractModel):
    _inherit = 'erp.budget.control.service'

    def _is_forward_sealed(self, period_id, analytic_id):
        return super()._is_forward_sealed(period_id, analytic_id) or bool(self.env['erp.budget.commit.forward.line'].sudo().search_count([('source_period_id', '=', period_id), ('source_analytic_control_id.analytic_id', '=', analytic_id), ('reserved', '=', True), ('forward_id.state', '=', 'done')]))

    def _carried_commitment(self, plan_line):
        lines = self.env['erp.budget.commit.forward.line'].sudo().search([('source_period_id', '=', plan_line.period_id.id), ('source_analytic_control_id.analytic_id', '=', plan_line.analytic_id.id), ('reserved', '=', True), ('forward_id.state', '=', 'done')])
        return super()._carried_commitment(plan_line) + sum(lines.mapped('amount'))

    def _forward_route(self, source_key, controls, date, actual=False):
        routes = self.env['erp.budget.commit.forward.line'].sudo().search([('source_key', '=', source_key), ('company_id', 'in', controls.mapped('company_id').ids), ('reserved', '=', True), ('forward_id.state', '=', 'done')]).sorted(lambda line: (line.forward_id.destination_period_id.date_from, line.id))
        for line in routes.with_env(self.env):
            line.check_access('read')
            cutoff = line.forward_id.destination_period_id.date_from
            if actual and fields.Date.to_date(date) < cutoff:
                break
            old = line.source_analytic_control_id | line.source_fund_control_id
            destination = line.destination_analytic_control_id | line.destination_fund_control_id
            if set(controls.ids) != set(old.ids):
                raise ValidationError(_('The immutable forwarded source budget key changed.'))
            controls = destination
            if not actual:
                date = cutoff
        if not actual:
            fallbacks = self.env['erp.budget.commit.forward.line'].sudo().search([('family_key', '=', source_key), ('fallback_analytic_control_id', '!=', False), ('reserved', '=', True), ('forward_id.state', '=', 'done')]).sorted(lambda line: (line.forward_id.destination_period_id.date_from, line.id))
            for line in fallbacks.with_env(self.env):
                if line.forward_id.destination_period_id.date_from <= fields.Date.to_date(date):
                    continue
                line.check_access('read')
                original = line.fallback_source_analytic_control_id | line.fallback_source_fund_control_id
                if set(original.ids) != set(controls.ids):
                    raise ValidationError(_('The primary request fallback no longer matches its captured source key.'))
                controls = line.fallback_analytic_control_id | line.fallback_fund_control_id
                date = line.forward_id.destination_period_id.date_from
        return controls, date

    def _carry_lock_controls(self, family_keys):
        lines = self.env['erp.budget.commit.forward.line'].sudo().search([('family_key', 'in', family_keys), ('reserved', '=', True), ('forward_id.state', '=', 'done')]).with_env(self.env)
        lines.check_access('read')
        controls = lines.mapped('destination_analytic_control_id') | lines.mapped('destination_fund_control_id') | lines.mapped('fallback_analytic_control_id') | lines.mapped('fallback_fund_control_id')
        controls.check_access('read')
        return controls

    def _source_distribution(self, source_key, declared_controls, distribution, date, actual=True):
        """Keep native GL analytics aligned with the approved fiscal source."""
        current, effective_date = self._forward_route(source_key, declared_controls, date, actual=actual)
        original = declared_controls.filtered(lambda control: control.level == 'analytic').analytic_id
        target = current.filtered(lambda control: control.level == 'analytic').analytic_id
        if original == target:
            return distribution
        result = {}
        for key, percentage in (distribution or {}).items():
            accounts = set(map(int, key.split(',')))
            if original.id not in accounts:
                raise ValidationError(_('The original analytic is missing from the source distribution.'))
            accounts.remove(original.id)
            accounts.add(target.id)
            translated = ','.join(map(str, sorted(accounts)))
            result[translated] = result.get(translated, 0) + percentage
        return result

    def _reconcile_purchase_multi(self, pr_controls, pr_date, family_key, pr_key, pr_amount, pr_eligible, purchase_orders, actuals=None, actual_provenance=None, primary_type='pr_commitment'):
        if not purchase_orders:
            pr_controls, pr_date = self._forward_route(pr_key, pr_controls, pr_date)
        orders = []
        for key, controls, amount, date in purchase_orders:
            controls, date = self._forward_route(key, controls, date)
            orders.append((key, controls, amount, date))
        purchase_orders = orders
        if actuals is not None:
            transformed = []
            for key, controls, amount, date in actuals:
                origin = (actual_provenance or {}).get(key, (False, False))[1]
                controls, date = self._forward_route(origin, controls, date, actual=True)
                transformed.append((key, controls, amount, date))
            actuals = transformed
        return super()._reconcile_purchase_multi(pr_controls, pr_date, family_key, pr_key, pr_amount, pr_eligible, purchase_orders, actuals, actual_provenance, primary_type)
