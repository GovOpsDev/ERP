"""Source account.budget.move behavior for native bills and journal entries."""
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

_direct_posting = ContextVar('erp_direct_actual_posting', default=False)
_DIRECT_FIELDS = {'erp_budget_period_id', 'erp_budget_organization_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_direct_activity_id', 'erp_budget_dimension_ids'}


def _direct_document_access(user_id):
    # Inspect every source line, including lines hidden by its own OU restriction.
    unauthorized_unit = Domain('active', '=', False) | Domain('assignment_ids', 'not any!', Domain('user_id', '=', user_id))
    return Domain('line_ids', 'not any!', Domain('erp_budget_organization_id', 'any!', unauthorized_unit))


class DirectActualMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & _direct_document_access(self.env.uid)

    def _erp_direct_actual_lines(self):
        lines = self.sudo().filtered(lambda move: not move.erp_budget_exempt).line_ids.filtered(lambda line: any(line[name] for name in _DIRECT_FIELDS)).with_env(self.env)
        lines.check_access('read')
        return lines

    def _erp_budget_amount_lines(self):
        return super()._erp_budget_amount_lines() | self._erp_direct_actual_lines()

    def _budget_scope_specs(self):
        specs, families = super()._budget_scope_specs()
        for line in self._erp_direct_actual_lines():
            specs.append(line._direct_budget_spec())
            families.append('account.move.line:%s' % line.id)
        return specs, families

    def _budget_financial_transition(self):
        return super()._budget_financial_transition() or _direct_posting.get()

    def _check_erp_budget_posting_ready(self):
        super()._check_erp_budget_posting_ready()
        if not _direct_posting.get() and self._erp_direct_actual_lines():
            raise UserError(_('Direct budget actuals require native accounting posting.'))

    def _post(self, soft=True):
        if not self._erp_direct_actual_lines():
            return super()._post(soft=soft)
        self.check_access('write')
        service = self.env['erp.budget.control.service']
        with self.env.cr.savepoint(), service._accounting_transaction(self._prelock_budget_sources()):
            self._capture_budget_amount_policy()
            token = _direct_posting.set(True)
            try:
                posted = super()._post(soft=soft)
            finally:
                _direct_posting.reset(token)
            posted._finalize_budget_amounts()
            posted._reconcile_direct_actuals()
            return posted

    def _reconcile_direct_actuals(self):
        service = self.env['erp.budget.control.service']
        for line in self._erp_direct_actual_lines():
            period, unit, analytic, fund, account, dimensions, activity = line._direct_budget_spec()
            controls = service._resolve(period, unit, analytic, fund, account, dimensions, activity=activity)
            key = 'account.move.line:%s' % line.id
            amount = line._erp_actual_budget_amount() if line.move_id.state == 'posted' else 0
            actuals = [(key, controls, amount, line.move_id.date)] if amount else []
            service._reconcile_actual(controls, line.move_id.date, key, actuals, {key: ('account.move:%s' % line.move_id.id, False)})

    def write(self, vals):
        direct = self._erp_direct_actual_lines()
        if direct and self.filtered(lambda move: move.state == 'posted'):
            if vals.get('state') in ('draft', 'cancel') and not self._budget_financial_transition():
                raise UserError(_('Use native accounting actions to reset budget actuals.'))
            if {'date', 'invoice_date', 'company_id', 'currency_id', 'move_type', 'reversed_entry_id', 'invoice_currency_rate', 'taxable_supply_date', 'partner_id', 'journal_id'} & vals.keys() and not _direct_posting.get():
                raise UserError(_('Reset the budget accounting document before changing its identity.'))
        if direct and vals.get('state') in ('draft', 'cancel'):
            with self.env.cr.savepoint():
                result = super().write(vals)
                self._reconcile_direct_actuals()
                return result
        return super().write(vals)


class DirectActualLine(models.Model):
    _inherit = 'account.move.line'

    erp_budget_period_id = fields.Many2one('erp.budget.period', check_company=True, ondelete='restrict', copy=False)
    erp_budget_organization_id = fields.Many2one('erp.organization.unit', check_company=True, ondelete='restrict', copy=False, index=True)
    erp_budget_fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict', copy=False)
    erp_budget_analytic_id = fields.Many2one('account.analytic.account', check_company=True, ondelete='restrict', copy=False)
    erp_budget_direct_activity_id = fields.Many2one('erp.budget.activity', check_company=True, ondelete='restrict', copy=False)
    erp_budget_dimension_ids = fields.Many2many('account.analytic.account', 'erp_direct_actual_dimension_rel', 'line_id', 'analytic_id', check_company=True, copy=False)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_id', 'any!', _direct_document_access(self.env.uid))

    def _direct_budget_spec(self):
        self.ensure_one()
        self.check_access('read')
        self.move_id.check_access('read')
        if self._erp_purchase_budget_source().erp_request_line_id or ('erp_contract_line_id' in self._fields and self.erp_contract_line_id) or self.expense_id._budget_expenses():
            raise ValidationError(_('Choose the purchase, contract or expense source, or direct budget dimensions for a line.'))
        if not all((self.erp_budget_period_id, self.erp_budget_organization_id, self.erp_budget_fund_id, self.erp_budget_analytic_id, self.account_id)):
            raise ValidationError(_('A direct budget line requires period, organization, fund, analytic and account.'))
        if self.erp_budget_period_id.company_id != self.company_id:
            raise ValidationError(_('The direct budget period must match the accounting company.'))
        ids = {self.erp_budget_analytic_id.id, *self.erp_budget_dimension_ids.ids}
        distribution = self.analytic_distribution or {}
        if len(distribution) != 1 or any(set(map(int, key.split(','))) != ids or percentage != 100 for key, percentage in distribution.items()):
            raise ValidationError(_('Direct budget dimensions must match the native analytic distribution at 100 percent.'))
        activity = self.erp_budget_direct_activity_id
        return (self.erp_budget_period_id, self.erp_budget_organization_id, self.erp_budget_analytic_id, self.erp_budget_fund_id, activity.account_id or self.account_id, self.erp_budget_dimension_ids, activity)

    @api.depends('purchase_line_id.erp_budget_activity_id', 'erp_budget_direct_activity_id')
    def _compute_budget_activity(self):
        super()._compute_budget_activity()
        for line in self.filtered('erp_budget_direct_activity_id'):
            line.erp_budget_activity_id = line.erp_budget_direct_activity_id

    @api.onchange('erp_budget_analytic_id', 'erp_budget_dimension_ids')
    def _onchange_direct_budget_distribution(self):
        for line in self.filtered('erp_budget_analytic_id'):
            line.analytic_distribution = {','.join(map(str, sorted({line.erp_budget_analytic_id.id, *line.erp_budget_dimension_ids.ids}))): 100}

    def _copy_data_extend_business_fields(self, values):
        super()._copy_data_extend_business_fields(values)
        if any(self[name] for name in _DIRECT_FIELDS):
            for name in _DIRECT_FIELDS - {'erp_budget_dimension_ids'}:
                values[name] = self[name].id
            values['erp_budget_dimension_ids'] = [(6, 0, self.erp_budget_dimension_ids.ids)]

    def _has_actual_budget_history(self):
        keys = ['account.move.line:%s' % line.id for line in self]
        return bool(keys and self.env['erp.budget.move'].sudo().search_count([('source_key', 'in', keys)], limit=1))

    def write(self, vals):
        if 'move_id' in vals and self._has_actual_budget_history():
            raise UserError(_('An accounting line with budget history cannot move to another document.'))
        if _DIRECT_FIELDS & vals.keys() and any(line.move_id.state == 'posted' for line in self):
            raise UserError(_('Reset the journal or bill before changing direct budget dimensions.'))
        with self.env.cr.savepoint():
            result = super().write(vals)
            if _DIRECT_FIELDS & vals.keys() and self.filtered(lambda line: line.move_id.state == 'posted'):
                raise UserError(_('Direct budget dimensions cannot be added to a posted entry.'))
            return result

    def unlink(self):
        if self._has_actual_budget_history():
            raise UserError(_('Accounting lines with budget history cannot be deleted.'))
        return super().unlink()


class DirectActualActivity(models.Model):
    _inherit = 'erp.budget.activity'

    def _has_document_usage(self):
        return super()._has_document_usage() or bool(self.env['account.move.line'].sudo().search_count([('erp_budget_direct_activity_id', 'in', self.ids)], limit=1))
