"""Normalize document money before it reaches company-currency budget caps."""
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class BudgetAmountCompany(models.Model):
    _inherit = 'res.company'

    erp_budget_amount_mode = fields.Selection([('legacy', 'Compatibility: company currency without tax'), ('net', 'Exclude taxes'), ('all', 'Include all taxes'), ('specific', 'Include selected taxes')], default='legacy', required=True, groups='base.group_system')
    erp_budget_purchase_tax_ids = fields.Many2many('account.tax', 'erp_budget_company_purchase_tax_rel', 'company_id', 'tax_id', groups='base.group_system', check_company=True)
    erp_budget_account_tax_ids = fields.Many2many('account.tax', 'erp_budget_company_account_tax_rel', 'company_id', 'tax_id', groups='base.group_system', check_company=True)
    erp_budget_expense_tax_ids = fields.Many2many('account.tax', 'erp_budget_company_expense_tax_rel', 'company_id', 'tax_id', groups='base.group_system', check_company=True)


class BudgetAmountSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    erp_budget_amount_mode = fields.Selection(related='company_id.erp_budget_amount_mode', readonly=False, groups='base.group_system')
    erp_budget_purchase_tax_ids = fields.Many2many(related='company_id.erp_budget_purchase_tax_ids', readonly=False, groups='base.group_system')
    erp_budget_account_tax_ids = fields.Many2many(related='company_id.erp_budget_account_tax_ids', readonly=False, groups='base.group_system')
    erp_budget_expense_tax_ids = fields.Many2many(related='company_id.erp_budget_expense_tax_ids', readonly=False, groups='base.group_system')


class BudgetAmountService(models.AbstractModel):
    _inherit = 'erp.budget.control.service'

    def _reconcile_actual(self, controls, date, family_key, actuals, provenance):
        """Reconcile an authorized native accounting source, without commitment authority."""
        return self._reconcile_purchase_multi(controls, date, family_key, 'actual-family:' + family_key, 0, False, [], actuals, provenance, primary_type='actual')

    def _amount_policy(self, company, scope):
        company.ensure_one()
        if company not in self.env.companies:
            raise AccessError(_('The amount company must be active.'))
        if scope not in ('purchase', 'account', 'expense'):
            raise ValidationError(_('Unknown budget document amount scope.'))
        config = company.sudo()
        return config.erp_budget_amount_mode, config['erp_budget_%s_tax_ids' % scope].with_env(self.env)

    def _amount_rate(self, currency, company, date, manual_rate=0):
        currency.ensure_one()
        company.ensure_one()
        if company not in self.env.companies:
            raise AccessError(_('The exchange-rate company must be active.'))
        rate = manual_rate or currency._convert(1, company.currency_id, company, date, round=False)
        if not math.isfinite(rate) or rate <= 0:
            raise ValidationError(_('A positive finite company-currency exchange rate is required.'))
        return rate

    def _check_manual_amount_rate(self, rate):
        if not math.isfinite(rate) or rate < 0:
            raise ValidationError(_('A manual rate must be positive, or zero for the native rate.'))
        if rate and not self.env.su and not (self.env.user.has_group('erp_budget.group_budget_manager') or self.env.user.has_group('account.group_account_manager')):
            raise AccessError(_('Budget or accounting manager authority is required for a manual budget exchange rate.'))

    def _amount_currency(self, unit, quantity, currency, company, taxes, mode, selected_taxes, discount=0, document_tax_mode=None):
        if any(not math.isfinite(value) for value in (unit, quantity, discount)) or quantity < 0:
            raise ValidationError(_('Budget price, quantity and discount must be finite.'))
        if company not in self.env.companies or any(tax.company_id != company for tax in taxes | selected_taxes):
            raise ValidationError(_('Budget taxes must belong to the active document company.'))
        price = unit * (1 - discount / 100)
        if mode == 'legacy':
            if taxes or currency != company.currency_id:
                raise ValidationError(_('Enable an explicit budget amount policy for taxes or foreign currency.'))
            return currency.round(price * quantity)
        if mode not in ('net', 'all', 'specific'):
            raise ValidationError(_('An explicit budget amount policy is required.'))
        all_values = taxes.compute_all(price, currency=currency, quantity=quantity, document_tax_mode=document_tax_mode)
        amount = all_values['total_excluded']
        included = taxes if mode == 'all' else taxes & selected_taxes if mode == 'specific' else self.env['account.tax']
        selected_ids = set(included.flatten_taxes_hierarchy().ids) if included else set()
        amount += sum(tax['amount'] for tax in all_values['taxes'] if tax['id'] in selected_ids)
        return currency.round(amount)

    def _document_amount(self, unit, quantity, currency, company, date, taxes=None, mode=None, selected_taxes=None, discount=0, rate=0, document_tax_mode=None):
        if mode is None:
            mode, selected_taxes = self._amount_policy(company, 'purchase')
        taxes = taxes or self.env['account.tax']
        selected_taxes = selected_taxes or self.env['account.tax']
        amount = self._amount_currency(unit, quantity, currency, company, taxes, mode, selected_taxes, discount, document_tax_mode)
        return company.currency_id.round(amount * self._amount_rate(currency, company, date, manual_rate=rate))


class BudgetAmountMove(models.Model):
    _inherit = 'erp.budget.move'

    amount_snapshot = fields.Json(readonly=True, copy=False, help='Document amount policy and rate captured for this new ledger node; old nodes are not backfilled.')

    def _source_amount_snapshot(self, values):
        return False

    @api.model_create_multi
    def create(self, vals_list):
        context = {key: value for key, value in self.env.context.items() if not (key.startswith('default_') and key[8:] in self._fields)}
        ledger = self.with_context(context)
        for vals in vals_list:
            if vals.get('reversal_of_id'):
                vals['amount_snapshot'] = ledger.browse(vals['reversal_of_id']).amount_snapshot
            elif 'amount_snapshot' not in vals:
                vals['amount_snapshot'] = ledger._source_amount_snapshot(vals)
        return super(BudgetAmountMove, ledger).create(vals_list)
