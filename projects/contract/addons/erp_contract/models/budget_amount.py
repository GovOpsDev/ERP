from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_contract_amount_internal = ContextVar('erp_contract_amount_internal', default=False)
_LINE_POLICY_FIELDS = {'erp_budget_amount_mode', 'erp_budget_fx_rate', 'erp_budget_unit_company', 'erp_budget_amount_captured'}


class ContractBudgetAmount(models.Model):
    _inherit = 'erp.contract.contract'

    currency_id = fields.Many2one('res.currency', compute='_compute_contract_currency')
    erp_budget_currency_id = fields.Many2one('res.currency', readonly=True, copy=False, ondelete='restrict')
    erp_budget_manual_rate = fields.Float(string='Budget Manual Exchange Rate', digits=0)

    @api.depends('journal_id.currency_id', 'company_id.currency_id', 'erp_budget_currency_id')
    def _compute_contract_currency(self):
        for contract in self:
            legacy = bool(not contract.erp_budget_currency_id and contract.id and contract._checked_lines()._has_budget_history())
            contract.currency_id = contract.erp_budget_currency_id or (contract.company_id.currency_id if legacy else contract.journal_id.currency_id or contract.company_id.currency_id)

    @api.model_create_multi
    def create(self, vals_list):
        if any('erp_budget_currency_id' in vals for vals in vals_list) or 'default_erp_budget_currency_id' in self.env.context:
            raise AccessError(_('Contract budget currency is captured by commitment.'))
        for vals in vals_list:
            self.env['erp.budget.control.service']._check_manual_amount_rate(vals.get('erp_budget_manual_rate', self.env.context.get('default_erp_budget_manual_rate', 0)) or 0)
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_budget_currency_id' in vals:
            if not _contract_amount_internal.get() or set(vals) != {'erp_budget_currency_id'}:
                raise AccessError(_('The committed contract currency is immutable.'))
            from .contract import Contract
            return super(Contract, self).write(vals)
        if 'erp_budget_manual_rate' in vals:
            self.env['erp.budget.control.service']._check_manual_amount_rate(vals['erp_budget_manual_rate'] or 0)
        return super().write(vals)

    def action_commit_budget(self):
        with self.env.cr.savepoint():
            self._manager_check()
            self._lock_budget_rows()
            token = _contract_amount_internal.set(True)
            try:
                for contract in self.filtered(lambda item: not item.erp_budget_currency_id):
                    contract.write({'erp_budget_currency_id': contract.currency_id.id})
            finally:
                _contract_amount_internal.reset(token)
            self._checked_lines()._capture_budget_amount_policy()
            return super().action_commit_budget()


class ContractLineBudgetAmount(models.Model):
    _inherit = 'erp.contract.line'

    currency_id = fields.Many2one(related='contract_id.currency_id')
    erp_budget_company_currency_id = fields.Many2one(related='company_id.currency_id')
    erp_budget_amount_mode = fields.Selection([('legacy', 'Compatibility'), ('net', 'Exclude taxes'), ('all', 'Include all taxes'), ('specific', 'Include selected taxes')], readonly=True, copy=False)
    erp_budget_fx_rate = fields.Float(readonly=True, copy=False, digits=0)
    erp_budget_unit_company = fields.Float(readonly=True, copy=False, digits=0)
    erp_budget_amount_captured = fields.Boolean(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(_LINE_POLICY_FIELDS & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in _LINE_POLICY_FIELDS):
            raise AccessError(_('Contract amount policies are captured by commitment.'))
        return super().create(vals_list)

    def write(self, vals):
        if _LINE_POLICY_FIELDS & vals.keys():
            if not _contract_amount_internal.get() or set(vals) - _LINE_POLICY_FIELDS:
                raise AccessError(_('Committed contract amount policies are immutable.'))
            return self._write_amount_policy(vals)
        return super().write(vals)

    def _write_amount_policy(self, vals):
        from .contract import ContractLine
        if not _contract_amount_internal.get():
            raise AccessError(_('Contract amount capture is internal.'))
        return super(ContractLine, self).write(vals)

    def _capture_budget_amount_policy(self):
        service = self.env['erp.budget.control.service']
        for line in self.filtered(lambda line: not line.erp_budget_amount_captured and not line._has_budget_history()):
            mode, taxes = service._amount_policy(line.company_id, 'purchase')
            rate = service._amount_rate(line.currency_id, line.company_id, line.date_start, line.contract_id.erp_budget_manual_rate)
            unit = service._amount_currency(line.price_unit, 1, line.currency_id, line.company_id, self.env['account.tax'], mode, self.env['account.tax']) * rate
            token = _contract_amount_internal.set(True)
            try:
                line.write({'erp_budget_amount_mode': mode, 'erp_budget_fx_rate': rate, 'erp_budget_unit_company': unit, 'erp_budget_amount_captured': True})
            finally:
                _contract_amount_internal.reset(token)

    def _erp_budget_amount(self, quantity):
        self.ensure_one()
        if self.erp_budget_amount_captured:
            return self.company_id.currency_id.round(quantity * self.erp_budget_unit_company)
        if self._has_budget_history():
            mode, rate = 'legacy', 1
        else:
            mode, taxes = self.env['erp.budget.control.service']._amount_policy(self.company_id, 'purchase')
            rate = self.env['erp.budget.control.service']._amount_rate(self.currency_id, self.company_id, self.date_start, self.contract_id.erp_budget_manual_rate)
        return self.env['erp.budget.control.service']._document_amount(self.price_unit, quantity, self.currency_id, self.company_id, self.date_start, mode=mode, rate=rate)

    def _budget_amount_snapshot(self):
        self.ensure_one()
        return {'scope': 'contract', 'mode': self.erp_budget_amount_mode if self.erp_budget_amount_captured else 'legacy', 'currency_id': self.currency_id.id, 'company_currency_id': self.company_id.currency_id.id, 'company_rate': self.erp_budget_fx_rate if self.erp_budget_amount_captured else 1, 'unit': self.price_unit, 'quantity': self.quantity, 'unit_company': self.erp_budget_unit_company if self.erp_budget_amount_captured else self.price_unit}


class InvoiceContractAmount(models.Model):
    _inherit = 'account.move'

    def _erp_budget_amount_lines(self):
        lines = super()._erp_budget_amount_lines()
        contract_lines = self.sudo().mapped('invoice_line_ids').filtered('erp_contract_line_id').with_env(self.env)
        contract_lines.check_access('read')
        return lines | contract_lines


class BudgetMoveContractAmount(models.Model):
    _inherit = 'erp.budget.move'

    def _source_amount_snapshot(self, values):
        model, separator, identifier = (values.get('source_key') or '').partition(':')
        if separator and model == 'erp.contract.line' and identifier.isdigit():
            line = self.env[model].browse(int(identifier)).exists()
            if line:
                return line._budget_amount_snapshot()
        return super()._source_amount_snapshot(values)
