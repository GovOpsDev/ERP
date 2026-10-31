from contextvars import ContextVar

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

_contract_posting = ContextVar('erp_contract_posting', default=False)
_contract_unposting = ContextVar('erp_contract_unposting', default=False)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    erp_contract_line_id = fields.Many2one('erp.contract.line', check_company=True, ondelete='restrict', copy=False, index=True)

    @api.onchange('erp_contract_line_id')
    def _onchange_contract_analytic(self):
        for line in self.filtered('erp_contract_line_id'):
            line.analytic_distribution = line.erp_contract_line_id._invoice_analytic_distribution()

    @api.depends('purchase_line_id.erp_budget_activity_id', 'erp_contract_line_id.activity_id')
    def _compute_budget_activity(self):
        super()._compute_budget_activity()
        for line in self.filtered('erp_contract_line_id'):
            line.erp_budget_activity_id = line.erp_contract_line_id.activity_id

    def _copy_data_extend_business_fields(self, values):
        super()._copy_data_extend_business_fields(values)
        values['erp_contract_line_id'] = self.erp_contract_line_id.id

    @api.constrains('erp_contract_line_id', 'purchase_line_id')
    def _check_exclusive_budget_sources(self):
        if any(line.erp_contract_line_id and line.purchase_line_id for line in self):
            raise ValidationError(_('A bill line cannot consume both contract and purchase budget sources.'))

    @api.model_create_multi
    def create(self, vals_list):
        with self.env.cr.savepoint():
            lines = super().create(vals_list)
            if not _contract_posting.get() and any(line.erp_contract_line_id and line.move_id.state == 'posted' for line in lines):
                raise UserError(_('A contract line cannot be added to a posted bill.'))
            return lines

    def write(self, vals):
        sensitive = {'erp_contract_line_id', 'purchase_line_id', 'move_id', 'quantity', 'price_unit', 'discount', 'product_id', 'product_uom_id', 'account_id', 'analytic_distribution', 'tax_ids'}
        if not _contract_posting.get() and sensitive.intersection(vals) and any(line.move_id.state == 'posted' and (line.erp_contract_line_id or vals.get('erp_contract_line_id')) for line in self):
            raise UserError(_('Reset the contract bill to draft before changing its source or amount.'))
        if not _contract_posting.get() and {'erp_contract_line_id', 'move_id'}.intersection(vals):
            with self.env.cr.savepoint():
                result = super().write(vals)
                if any(line.move_id.state == 'posted' and line.erp_contract_line_id for line in self):
                    raise UserError(_('A contract line cannot be attached to a posted bill.'))
                return result
        return super().write(vals)

    def unlink(self):
        if not _contract_posting.get() and any(line.move_id.state == 'posted' and line.erp_contract_line_id for line in self):
            raise UserError(_('Reset the contract bill to draft before deleting its source.'))
        return super().unlink()


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _erp_source_document_domain(self):
        invalid_unit = Domain('active', '=', False) | Domain(
            'assignment_ids', 'not any!', Domain('user_id', '=', self.env.uid))
        invalid_line = Domain('erp_contract_line_id', 'any!',
                              Domain('organization_id', 'any!', invalid_unit))
        return (super()._erp_source_document_domain()
                & Domain('line_ids', 'not any!', invalid_line)
                & Domain('erp_contract_cycle_id', 'not any!', Domain('organization_id', 'any!', invalid_unit))
                & Domain('erp_contract_invoice_plan_id', 'not any!', Domain('organization_id', 'any!', invalid_unit)))

    def _budget_financial_transition(self):
        return super()._budget_financial_transition() or _contract_posting.get() or _contract_unposting.get()

    def _erp_contract_lines(self):
        lines = self.sudo().mapped('invoice_line_ids').filtered('erp_contract_line_id').with_env(self.env)
        if lines:
            lines.check_access('read')
        sources = lines.mapped('erp_contract_line_id')
        if sources:
            sources.check_access('read')
        return sources

    def _budget_scope_specs(self):
        specs, families = super()._budget_scope_specs()
        for line in self._erp_contract_lines().mapped('contract_id')._checked_lines():
            specs.append((line.period_id, line.organization_id, line.analytic_id, line.fund_id, line.account_id, line.dimension_ids, line.activity_id))
            families.append(line._family_key())
        return specs, families

    def _check_contract_sources(self):
        for source in self._erp_contract_lines():
            if not source.contract_id.active or not source.contract_id.commit_budget:
                raise ValidationError(_('The contract must be active with budget commitment enabled.'))

    def _post(self, soft=True):
        sources = self._erp_contract_lines()
        if not sources:
            return super()._post(soft=soft)
        self.check_access('write')
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()):
            self._check_contract_sources()
            self._prelock_budget_sources()
            sources.mapped('contract_id')._lock_budget_rows()
            if not self._erp_finance_requests():
                self._capture_budget_amount_policy()
            token = _contract_posting.set(True)
            try:
                posted = super()._post(soft=soft)
            finally:
                _contract_posting.reset(token)
            posted._check_contract_sources()
            if not posted._erp_finance_requests():
                posted._finalize_budget_amounts()
            for source in posted._erp_contract_lines():
                source._reconcile_budget()
            return posted

    def button_draft(self):
        token = _contract_unposting.set(True)
        try:
            return super().button_draft()
        finally:
            _contract_unposting.reset(token)

    def button_cancel(self):
        token = _contract_unposting.set(True)
        try:
            return super().button_cancel()
        finally:
            _contract_unposting.reset(token)

    def write(self, vals):
        if vals.get('state') == 'posted' and not _contract_posting.get() and self._erp_contract_lines():
            raise UserError(_('Use the native accounting posting workflow for contract bills.'))
        posted_sources = self.filtered(lambda move: move.state == 'posted')._erp_contract_lines() if vals.get('state') in ('draft', 'cancel', 'posted') or {'date', 'invoice_date', 'company_id', 'currency_id', 'move_type', 'reversed_entry_id', 'invoice_currency_rate', 'taxable_supply_date', 'partner_id', 'journal_id'}.intersection(vals) else self.env['erp.contract.line']
        if posted_sources and not _contract_posting.get():
            if vals.get('state') == 'posted' or (vals.get('state') in ('draft', 'cancel') and not _contract_unposting.get()):
                raise UserError(_('Use native accounting actions for contract bills.'))
            if {'date', 'invoice_date', 'company_id', 'currency_id', 'move_type', 'reversed_entry_id', 'invoice_currency_rate', 'taxable_supply_date', 'partner_id', 'journal_id'}.intersection(vals):
                raise UserError(_('Reset the contract bill before changing its identity or date.'))
        sources = self._erp_contract_lines() if vals.get('state') in ('draft', 'cancel') else self.env['erp.contract.line']
        if not sources:
            return super().write(vals)
        with self.env.cr.savepoint():
            sources.mapped('contract_id')._lock_budget_rows()
            result = super().write(vals)
            for source in sources:
                source._reconcile_budget()
            return result

    @api.model_create_multi
    def create(self, vals_list):
        with self.env.cr.savepoint():
            moves = super().create(vals_list)
            if not _contract_posting.get() and moves.filtered(lambda move: move.state == 'posted')._erp_contract_lines():
                raise UserError(_('Contract bills must use the native posting workflow.'))
            return moves
