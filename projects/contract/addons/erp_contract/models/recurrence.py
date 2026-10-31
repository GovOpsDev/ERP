"""OCA contract periods use native bills and Budget direct actuals.

The upstream budget_control_contract explicitly limits its one-time commitment
switch to non-recurring contracts. A recurring cycle never opens that bucket.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, format_date

_internal = ContextVar('erp_contract_recurrence_internal', default=False)
_RULES = [('daily', 'Days'), ('weekly', 'Weeks'), ('monthly', 'Months'), ('monthlylastday', 'Months, last day'), ('quarterly', 'Quarters'), ('semesterly', 'Semesters'), ('yearly', 'Years')]
_SCHEDULE = {'recurrence_stop_date', 'recurrence_canceled', 'predecessor_id'}


@contextmanager
def internal():
    token = _internal.set(True)
    try:
        yield
    finally:
        _internal.reset(token)


def delta(rule, interval):
    return relativedelta(**({'days': interval} if rule == 'daily' else {'weeks': interval} if rule == 'weekly' else {'months': interval, 'day': 1} if rule == 'monthlylastday' else {'years': interval} if rule == 'yearly' else {'months': interval * {'monthly': 1, 'quarterly': 3, 'semesterly': 6}[rule]}))


class RecurringContract(models.Model):
    _inherit = 'erp.contract.contract'

    recurrence_enabled = fields.Boolean(copy=False)
    termination_date = fields.Date(readonly=True, copy=False)
    termination_reason = fields.Char(readonly=True, copy=False)
    cycle_ids = fields.One2many('erp.contract.cycle', 'contract_id', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'termination_date', 'termination_reason'}
        if any(protected & v.keys() for v in vals_list) or any('default_' + n in self.env.context for n in protected):
            raise AccessError(_('Use the contract termination action.'))
        return super().create(vals_list)

    @api.constrains('recurrence_enabled', 'commit_budget', 'erp_use_invoice_plan')
    def _check_recurring_mode(self):
        if any(c.recurrence_enabled and (c.commit_budget or c.erp_use_invoice_plan) for c in self):
            raise ValidationError(_('Recurring contracts use per-period actuals, not a one-time commitment or installment plan.'))

    def write(self, vals):
        if {'termination_date', 'termination_reason'} & vals.keys():
            if not _internal.get() or vals.keys() - {'termination_date', 'termination_reason'}:
                raise AccessError(_('Use the contract termination action.'))
            from .contract import Contract
            return super(Contract, self).write(vals)
        if self.cycle_ids and vals.keys() - {'line_ids'}:
            raise UserError(_('Recurring history retains its contract configuration.'))
        if 'recurrence_enabled' in vals and (self._checked_lines().invoice_line_ids or self._checked_lines()._has_budget_history()):
            raise UserError(_('A contract with one-time financial history cannot become recurring.'))
        return super().write(vals)

    def action_commit_budget(self):
        if self.filtered('recurrence_enabled'):
            raise UserError(_('Recurring contracts consume Budget when each native bill posts.'))
        return super().action_commit_budget()

    def _plan_generation_allowed(self):
        return super()._plan_generation_allowed() and not self.recurrence_enabled

    def unlink(self):
        if self.cycle_ids:
            raise UserError(_('Recurring contract history cannot be deleted.'))
        return super().unlink()

    def action_generate_recurring(self):
        self._manager_check()
        invoices = self.env['account.move']
        with self.env.cr.savepoint():
            self._lock_invoice_plan()
            for contract in self:
                for line in contract._checked_lines():
                    invoices |= line._generate_cycle()
        return {'type': 'ir.actions.act_window', 'name': _('Recurring Bills'), 'res_model': 'account.move', 'view_mode': 'list,form', 'domain': [('id', 'in', invoices.ids)]}

    def action_terminate(self, end_date, reason):
        self._manager_check()
        end_date = fields.Date.to_date(end_date)
        if not end_date or not reason or any(not c.recurrence_enabled or c.termination_date for c in self):
            raise ValidationError(_('An unterminated recurring contract, end date and reason are required.'))
        with self.env.cr.savepoint():
            self._lock_invoice_plan()
            for contract in self:
                for line in contract._checked_lines().filtered(lambda l: not l.recurrence_canceled):
                    line.action_stop(end_date)
            with internal():
                self.write({'termination_date': end_date, 'termination_reason': reason})
        return True

    def action_cancel_termination(self):
        self._manager_check()
        # Re-enable only the lines' existing stop boundaries. Extend via successors.
        with self.env.cr.savepoint():
            self._lock_invoice_plan()
            with internal():
                self.write({'termination_date': False, 'termination_reason': False})
        return True

    @api.model
    def _cron_recurring_invoices(self):
        today = fields.Date.context_today(self)
        for contract in self.search([('recurrence_enabled', '=', True), ('termination_date', '=', False)]):
            with self.env.cr.savepoint():
                contract._lock_invoice_plan()
                for line in contract._checked_lines():
                    period = line._next_cycle_dates()
                    if period and period[2] <= today:
                        line._generate_cycle()


class RecurringLine(models.Model):
    _inherit = 'erp.contract.line'

    recurring_rule_type = fields.Selection(_RULES, required=True, default='monthly')
    recurring_interval = fields.Integer(required=True, default=1)
    recurring_invoicing_type = fields.Selection([('pre-paid', 'Pre-paid'), ('post-paid', 'Post-paid')], required=True, default='pre-paid')
    cycle_ids = fields.One2many('erp.contract.cycle', 'line_id', readonly=True)
    recurring_next_date = fields.Date(compute='_compute_next_cycle')
    next_period_start = fields.Date(compute='_compute_next_cycle')
    next_period_end = fields.Date(compute='_compute_next_cycle')
    recurrence_stop_date = fields.Date(readonly=True, copy=False)
    recurrence_canceled = fields.Boolean(readonly=True, copy=False)
    predecessor_id = fields.Many2one('erp.contract.line', readonly=True, copy=False, check_company=True, ondelete='restrict')
    successor_ids = fields.One2many('erp.contract.line', 'predecessor_id', readonly=True)
    auto_renew = fields.Boolean()
    auto_renew_rule_type = fields.Selection(_RULES, required=True, default='yearly')
    auto_renew_interval = fields.Integer(default=1, required=True)
    termination_notice_days = fields.Integer(default=30)
    _successor_unique = models.Constraint('unique(predecessor_id)', 'A contract line has only one historical successor.')

    @api.constrains('recurring_interval', 'auto_renew_interval', 'termination_notice_days', 'predecessor_id')
    def _check_recurrence(self):
        for line in self:
            if line.recurring_interval <= 0 or line.auto_renew_interval <= 0 or line.termination_notice_days < 0:
                raise ValidationError(_('Recurrence intervals must be positive and notice days nonnegative.'))
            if line.predecessor_id and (line.predecessor_id.contract_id != line.contract_id or line.date_start <= line.predecessor_id.date_start):
                raise ValidationError(_('A successor must start later in the same contract.'))

    @api.depends('cycle_ids.date_to', 'recurrence_stop_date', 'recurrence_canceled', 'date_start', 'date_end', 'recurring_interval', 'recurring_rule_type', 'recurring_invoicing_type', 'contract_id.termination_date', 'contract_id.active', 'contract_id.recurrence_enabled')
    def _compute_next_cycle(self):
        for line in self:
            dates = line._next_cycle_dates()
            line.next_period_start, line.next_period_end, line.recurring_next_date = dates or (False, False, False)

    def _next_cycle_dates(self):
        self.ensure_one()
        if not self.contract_id.active or not self.contract_id.recurrence_enabled or self.contract_id.termination_date or self.recurrence_canceled:
            return False
        start = max(self.cycle_ids.mapped('date_to')) + timedelta(days=1) if self.cycle_ids else self.date_start
        limit = min(self.date_end, self.recurrence_stop_date or self.date_end)
        if start > limit:
            return False
        end = min(start + delta(self.recurring_rule_type, self.recurring_interval) - timedelta(days=1), limit)
        invoice = start if self.recurring_invoicing_type == 'pre-paid' else end + timedelta(days=0 if self.recurring_rule_type == 'monthlylastday' else 1)
        return start, end, invoice

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal.get() and (any(_SCHEDULE & v.keys() for v in vals_list) or any('default_' + n in self.env.context for n in _SCHEDULE)):
            raise AccessError(_('Use contract schedule actions to create successors.'))
        for vals in vals_list:
            contract = self.env['erp.contract.contract'].browse(vals.get('contract_id'))
            if contract.termination_date:
                raise UserError(_('A terminated contract cannot receive new lines.'))
        return super().create(vals_list)

    def write(self, vals):
        if _SCHEDULE & vals.keys():
            if not _internal.get() or vals.keys() - _SCHEDULE:
                raise AccessError(_('Use contract schedule actions.'))
            from .contract import ContractLine
            return super(ContractLine, self).write(vals)
        if self.cycle_ids or self.predecessor_id or self.successor_ids or self.recurrence_stop_date or self.recurrence_canceled:
            raise UserError(_('Amend recurring terms with a successor; existing terms are historical.'))
        return super().write(vals)

    def unlink(self):
        if self.cycle_ids or self.predecessor_id or self.successor_ids or self.recurrence_stop_date or self.recurrence_canceled:
            raise UserError(_('Recurring schedule history cannot be deleted.'))
        return super().unlink()

    def _generate_cycle(self):
        self.ensure_one()
        self.check_access('read')
        self.contract_id._lock_invoice_plan()
        dates = self._next_cycle_dates()
        if not dates:
            return self.env['account.move']
        with internal():
            cycle = self.env['erp.contract.cycle'].create({'line_id': self.id, 'date_from': dates[0], 'date_to': dates[1], 'invoice_date': dates[2], 'currency_id': self.currency_id.id})
        return cycle._invoice()

    def action_stop(self, end_date):
        self.contract_id._manager_check()
        end_date = fields.Date.to_date(end_date)
        if not end_date or any(not l.contract_id.recurrence_enabled for l in self):
            raise ValidationError(_('A recurring line and end date are required.'))
        with self.env.cr.savepoint():
            self.contract_id._lock_invoice_plan()
            for line in self:
                if line.cycle_ids and end_date < max(line.cycle_ids.mapped('date_to')):
                    raise UserError(_('A stop cannot shorten an already generated invoice period.'))
                with internal():
                    if end_date < line.date_start:
                        line.write({'recurrence_canceled': True})
                    else:
                        line.write({'recurrence_stop_date': min(line.date_end, line.recurrence_stop_date or line.date_end, end_date)})
        return True

    def action_cancel_recurrence(self):
        self.contract_id._manager_check()
        with self.env.cr.savepoint():
            self.contract_id._lock_invoice_plan()
            if self.cycle_ids or self.successor_ids:
                raise UserError(_('An invoiced or succeeded line must be stopped, not canceled.'))
            with internal():
                self.write({'recurrence_canceled': True})
        return True

    def action_reset_recurrence(self):
        self.contract_id._manager_check()
        with self.env.cr.savepoint():
            self.contract_id._lock_invoice_plan()
            if self.cycle_ids or self.successor_ids or self.contract_id.termination_date:
                raise UserError(_('Only an unused canceled schedule can reset.'))
            with internal():
                self.write({'recurrence_canceled': False})
        return True

    def action_amend(self, start_date, end_date, quantity=None, price_unit=None):
        self.ensure_one()
        self.contract_id._manager_check()
        start, end = fields.Date.to_date(start_date), fields.Date.to_date(end_date)
        if not start or not end or end < start or start <= self.date_start or not self.contract_id.active or not self.contract_id.recurrence_enabled or self.contract_id.termination_date or self.recurrence_canceled:
            raise ValidationError(_('A successor requires a valid later period on an active recurring contract.'))
        with self.env.cr.savepoint():
            self.contract_id._lock_invoice_plan()
            if self.successor_ids:
                raise UserError(_('This line already has a successor.'))
            self.action_stop(start - timedelta(days=1))
            values = {n: self[n].id for n in ['contract_id', 'product_id', 'uom_id', 'period_id', 'fund_id', 'analytic_id', 'account_id', 'activity_id']}
            values.update({n: self[n] for n in ['name', 'recurring_rule_type', 'recurring_interval', 'recurring_invoicing_type', 'auto_renew', 'auto_renew_rule_type', 'auto_renew_interval', 'termination_notice_days']})
            values.update(date_start=start, date_end=end, quantity=self.quantity if quantity is None else quantity, price_unit=self.price_unit if price_unit is None else price_unit, dimension_ids=[(6, 0, self.dimension_ids.ids)], predecessor_id=self.id)
            with internal():
                return self.create(values)

    def action_renew(self):
        self.ensure_one()
        # Preserve predecessor financial history even when the source allowed extension.
        start = min(self.date_end, self.recurrence_stop_date or self.date_end) + timedelta(days=1)
        return self.action_amend(start, start + delta(self.auto_renew_rule_type, self.auto_renew_interval) - timedelta(days=1))

    @api.model
    def _cron_renew_contract_lines(self):
        today = fields.Date.context_today(self)
        lines = self.search([('auto_renew', '=', True), ('recurrence_canceled', '=', False), ('recurrence_stop_date', '=', False), ('successor_ids', '=', False), ('contract_id.recurrence_enabled', '=', True), ('contract_id.active', '=', True), ('contract_id.termination_date', '=', False)])
        for line in lines:
            if line.date_end - timedelta(days=line.termination_notice_days) <= today:
                line.action_renew()


class ContractCycle(models.Model):
    _name = 'erp.contract.cycle'
    _description = 'Contract Recurring Period'
    _check_company_auto = True
    _order = 'date_from, id'
    line_id = fields.Many2one('erp.contract.line', required=True, check_company=True, ondelete='restrict')
    contract_id = fields.Many2one(related='line_id.contract_id', store=True)
    company_id = fields.Many2one(related='line_id.company_id', store=True)
    organization_id = fields.Many2one(related='line_id.organization_id', store=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    invoice_date = fields.Date(required=True)
    currency_id = fields.Many2one('res.currency', required=True, ondelete='restrict')
    invoice_ids = fields.One2many('account.move', 'erp_contract_cycle_id', readonly=True)
    _period_unique = models.Constraint('unique(line_id,date_from)', 'A recurring period may only be generated once.')

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal.get():
            raise AccessError(_('Recurring periods are created by contract generation.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Recurring periods are immutable.'))

    def unlink(self):
        raise AccessError(_('Recurring period history cannot be deleted.'))

    def _invoice(self):
        self.ensure_one()
        self.check_access('read')
        self.contract_id._lock_invoice_plan()
        live = self.invoice_ids.filtered(lambda m: m.move_type == 'in_invoice' and m.state != 'cancel')
        if live:
            return live
        line, contract = self.line_id, self.contract_id
        periods = self.env['erp.budget.period'].search([('company_id', '=', self.company_id.id), ('date_from', '<=', self.invoice_date), ('date_to', '>=', self.invoice_date)])
        if len(periods) != 1:
            raise ValidationError(_('A unique company fiscal period must cover the recurring invoice date.'))
        name = line.name.replace('#START#', format_date(self.env, self.date_from)).replace('#END#', format_date(self.env, self.date_to))
        values = {'move_type': 'in_invoice', 'company_id': self.company_id.id, 'journal_id': contract.journal_id.id, 'partner_id': contract.partner_id.id, 'currency_id': self.currency_id.id,
                  'date': self.invoice_date, 'invoice_date': self.invoice_date, 'erp_contract_cycle_id': self.id,
                  'invoice_line_ids': [(0, 0, {'name': name, 'product_id': line.product_id.id, 'product_uom_id': line.uom_id.id, 'account_id': line.account_id.id, 'quantity': line.quantity, 'price_unit': line.price_unit,
                                             'tax_ids': [(6, 0, line.product_id.supplier_taxes_id.filtered(lambda t: t.company_id == self.company_id).ids)],
                                             'erp_budget_period_id': periods.id, 'erp_budget_organization_id': self.organization_id.id, 'erp_budget_fund_id': line.fund_id.id, 'erp_budget_analytic_id': line.analytic_id.id, 'erp_budget_direct_activity_id': line.activity_id.id, 'erp_budget_dimension_ids': [(6, 0, line.dimension_ids.ids)],
                                             'analytic_distribution': {','.join(map(str, sorted({line.analytic_id.id, *line.dimension_ids.ids}))): 100}})]}
        with internal():
            return self.env['account.move'].with_company(self.company_id).create(values)

    def action_create_invoice(self):
        self.contract_id._manager_check()
        with self.env.cr.savepoint():
            invoice = self._invoice()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': invoice.id, 'view_mode': 'form'}


class RecurringMove(models.Model):
    _inherit = 'account.move'
    erp_contract_cycle_id = fields.Many2one('erp.contract.cycle', readonly=True, copy=False, check_company=True, ondelete='restrict', index=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not _internal.get() and (any(v.get('erp_contract_cycle_id') for v in vals_list) or self.env.context.get('default_erp_contract_cycle_id')):
            raise AccessError(_('Recurring invoice provenance is assigned by the contract.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_contract_cycle_id' in vals:
            raise AccessError(_('Recurring invoice provenance is immutable.'))
        if vals.get('state') in ('draft', 'cancel'):
            cycles = self.erp_contract_cycle_id
            if cycles:
                cycles.contract_id._lock_invoice_plan()
            if any(move.move_type == 'in_invoice' and move.reversal_move_ids.filtered(lambda m: m.state == 'posted') for move in self.filtered('erp_contract_cycle_id')):
                raise UserError(_('Reset the posted recurring credit before its bill.'))
        return super().write(vals)

    def unlink(self):
        if self.erp_contract_cycle_id:
            raise UserError(_('Cancel recurring bills to retain their period history.'))
        return super().unlink()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        defaults = [dict(v) for v in (default_values_list or [{} for m in self])]
        for move, values in zip(self, defaults):
            if move.erp_contract_cycle_id:
                values['erp_contract_cycle_id'] = move.erp_contract_cycle_id.id
        with internal():
            return super()._reverse_moves(defaults, cancel=cancel)

    def _check_recurring_economics(self):
        for move in self.filtered('erp_contract_cycle_id'):
            cycle, line = move.erp_contract_cycle_id, move.erp_contract_cycle_id.line_id
            cycle.check_access('read')
            if move.company_id != cycle.company_id or move.partner_id != cycle.contract_id.partner_id or move.currency_id != cycle.currency_id or move.move_type not in ('in_invoice', 'in_refund'):
                raise ValidationError(_('Recurring bills retain their contract company, vendor, currency and type.'))
            rows = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')
            if len(rows) != 1:
                raise ValidationError(_('Each recurring period bills exactly one source service line.'))
            row = rows
            if row.erp_contract_line_id or row.purchase_line_id or row.product_id != line.product_id or row.product_uom_id != line.uom_id or row.account_id != line.account_id or row.erp_budget_organization_id != line.organization_id or row.erp_budget_fund_id != line.fund_id or row.erp_budget_analytic_id != line.analytic_id or row.erp_budget_direct_activity_id != line.activity_id or row.erp_budget_dimension_ids != line.dimension_ids or row.discount or cycle.currency_id.compare_amounts(row.price_unit, line.price_unit):
                raise ValidationError(_('The recurring bill must retain its source economics and Budget dimensions.'))
            if not row.erp_budget_period_id.date_from <= move.date <= row.erp_budget_period_id.date_to:
                raise ValidationError(_('The recurring accounting date must remain in its fiscal period.'))
            precision = self.env['decimal.precision'].precision_get('Product Unit')
            if row.quantity <= 0:
                raise ValidationError(_('Recurring quantities must be positive.'))
            if move.move_type == 'in_invoice':
                if float_compare(row.quantity, line.quantity, precision_digits=precision) or cycle.invoice_ids.filtered(lambda m: m != move and m.move_type == 'in_invoice' and m.state != 'cancel'):
                    raise ValidationError(_('Only one live bill of the configured quantity is allowed per period.'))
            else:
                original = move.reversed_entry_id
                if original.state != 'posted' or original.erp_contract_cycle_id != cycle or original.move_type != 'in_invoice':
                    raise ValidationError(_('A recurring credit must reference its posted period bill.'))
                if row.tax_ids != original.invoice_line_ids.filtered(lambda l: l.display_type == 'product').tax_ids:
                    raise ValidationError(_('A recurring credit must retain its original bill taxes.'))
                refunds = original.reversal_move_ids.filtered(lambda m: m.state == 'posted' or m == move)
                quantity = sum(refunds.invoice_line_ids.filtered(lambda l: l.display_type == 'product').mapped('quantity'))
                if float_compare(quantity, line.quantity, precision_digits=precision) > 0:
                    raise ValidationError(_('Recurring credits cannot exceed their original period bill.'))

    def _post(self, soft=True):
        cycles = self.erp_contract_cycle_id
        if not cycles:
            return super()._post(soft=soft)
        with self.env.cr.savepoint():
            cycles.contract_id._lock_invoice_plan()
            self._check_recurring_economics()
            return super()._post(soft=soft)


class RecurringLineProtection(models.Model):
    _inherit = 'account.move.line'

    def write(self, vals):
        if 'move_id' in vals and any(l.move_id.erp_contract_cycle_id and vals['move_id'] != l.move_id.id for l in self):
            raise AccessError(_('Recurring invoice lines cannot move to another document.'))
        return super().write(vals)

    def unlink(self):
        if any(l.move_id.erp_contract_cycle_id and l.display_type == 'product' for l in self):
            raise UserError(_('Recurring source lines must be retained; cancel the bill.'))
        return super().unlink()


class RecurrenceChange(models.TransientModel):
    _name = 'erp.contract.recurrence.change'
    _description = 'Change Contract Schedule'
    contract_id = fields.Many2one('erp.contract.contract', required=True)
    line_id = fields.Many2one('erp.contract.line')
    operation = fields.Selection([('amend', 'Amend with successor'), ('renew', 'Renew with successor'), ('stop', 'Stop line'), ('terminate', 'Terminate contract')], required=True, default='amend')
    start_date = fields.Date(default=fields.Date.context_today)
    end_date = fields.Date(required=True)
    quantity = fields.Float(default=1)
    price_unit = fields.Float()
    reason = fields.Char()

    def action_apply(self):
        self.ensure_one()
        self.contract_id._manager_check()
        if self.operation != 'terminate' and (not self.line_id or self.line_id.contract_id != self.contract_id):
            raise ValidationError(_('Select a line of this contract.'))
        if self.operation == 'amend':
            self.line_id.action_amend(self.start_date, self.end_date, self.quantity, self.price_unit)
        elif self.operation == 'renew':
            self.line_id.action_renew()
        elif self.operation == 'stop':
            self.line_id.action_stop(self.end_date)
        else:
            self.contract_id.action_terminate(self.end_date, self.reason)
        return {'type': 'ir.actions.act_window_close'}
