"""Source fund/analytic stock provenance and configurable negative-stock policy."""
import json
from contextvars import ContextVar
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

_valuation = ContextVar('erp_inventory_valuation', default=False)


class StockFund(models.Model):
    _inherit = 'stock.move'
    erp_fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict')
    erp_analytic_id = fields.Many2one('account.analytic.account', check_company=True, ondelete='restrict')
    erp_dimension_ids = fields.Many2many('account.analytic.account', check_company=True)
    erp_analytic_distribution = fields.Json()
    erp_distribution_key = fields.Char(compute='_compute_distribution_key', store=True)

    @api.depends('erp_analytic_distribution')
    def _compute_distribution_key(self):
        for move in self:
            move.erp_distribution_key = json.dumps(move.erp_analytic_distribution or {}, sort_keys=True)

    def _prepare_merge_moves_distinct_fields(self):
        return super()._prepare_merge_moves_distinct_fields() + ['erp_fund_id', 'erp_analytic_id', 'erp_dimension_ids', 'erp_distribution_key']

    def _prepare_procurement_values(self):
        vals = super()._prepare_procurement_values()
        vals.update(erp_fund_id=self.erp_fund_id.id, erp_analytic_id=self.erp_analytic_id.id, erp_dimension_ids=[(6, 0, self.erp_dimension_ids.ids)], erp_analytic_distribution=self.erp_analytic_distribution)
        return vals

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        vals = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        vals.update(erp_fund_id=self.erp_fund_id.id, erp_analytic_id=self.erp_analytic_id.id, erp_dimension_ids=[(6, 0, self.erp_dimension_ids.ids)])
        return vals

    def _get_analytic_distribution(self):
        return self.erp_analytic_distribution or ({str(self.erp_analytic_id.id): 100} if self.erp_analytic_id else super()._get_analytic_distribution())

    def _get_account_move_line_vals(self):
        vals = super()._get_account_move_line_vals()
        for value in vals:
            value.update(erp_budget_fund_id=self.erp_fund_id.id, erp_budget_analytic_id=self.erp_analytic_id.id, erp_budget_dimension_ids=[(6, 0, self.erp_dimension_ids.ids)])
        return vals

    def _create_account_move(self):
        token = _valuation.set(True)
        try:
            return super()._create_account_move()
        finally:
            _valuation.reset(token)

    def write(self, vals):
        if {'erp_fund_id', 'erp_analytic_id', 'erp_dimension_ids', 'erp_analytic_distribution'} & vals.keys() and any(m.state in ('done', 'cancel') for m in self):
            raise UserError(_('Completed stock movements retain their fund and analytic provenance.'))
        return super().write(vals)


class StockFundLine(models.Model):
    _inherit = 'stock.move.line'
    erp_fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict')
    erp_analytic_id = fields.Many2one('account.analytic.account', check_company=True, ondelete='restrict')
    erp_dimension_ids = fields.Many2many('account.analytic.account', check_company=True)

    def _prepare_stock_move_vals(self):
        vals = super()._prepare_stock_move_vals()
        vals.update(erp_fund_id=self.erp_fund_id.id, erp_analytic_id=self.erp_analytic_id.id, erp_dimension_ids=[(6, 0, self.erp_dimension_ids.ids)])
        return vals

    def write(self, vals):
        if {'erp_fund_id', 'erp_analytic_id', 'erp_dimension_ids'} & vals.keys() and any(l.state in ('done', 'cancel') for l in self):
            raise UserError(_('Completed stock details retain their provenance.'))
        return super().write(vals)


class PurchaseStockFund(models.Model):
    _inherit = 'purchase.order.line'
    def _prepare_stock_moves(self, picking=False):
        vals = super()._prepare_stock_moves(picking=picking)
        for value in vals:
            value.update(erp_fund_id=self.erp_budget_fund_id.id, erp_analytic_id=self.erp_budget_analytic_id.id, erp_dimension_ids=[(6, 0, self.erp_budget_dimension_ids.ids)], erp_analytic_distribution=self.analytic_distribution)
        return vals


class StockRuleFund(models.Model):
    _inherit = 'stock.rule'
    def _get_custom_move_fields(self):
        return super()._get_custom_move_fields() + ['erp_fund_id', 'erp_analytic_id', 'erp_dimension_ids', 'erp_analytic_distribution']


class StockValuationAccounting(models.Model):
    _inherit = 'account.move'
    @api.model_create_multi
    def create(self, vals_list):
        if _valuation.get():
            vals_list = [dict(v, erp_budget_exempt=True) for v in vals_list]
        return super().create(vals_list)


class NegativeProduct(models.Model):
    _inherit = 'product.template'
    erp_allow_negative_stock = fields.Boolean(string='Allow Negative Stock')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and (any(v.get('erp_allow_negative_stock') for v in vals_list) or self.env.context.get('default_erp_allow_negative_stock')) and not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError(_('Inventory management is required to allow negative stock.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_allow_negative_stock' in vals and not self.env.su and not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError(_('Inventory management is required to configure negative stock.'))
        return super().write(vals)


class NegativeCategory(models.Model):
    _inherit = 'product.category'
    erp_allow_negative_stock = fields.Boolean(string='Allow Negative Stock')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and (any(v.get('erp_allow_negative_stock') for v in vals_list) or self.env.context.get('default_erp_allow_negative_stock')) and not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError(_('Inventory management is required to allow negative stock.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_allow_negative_stock' in vals and not self.env.su and not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError(_('Inventory management is required to configure negative stock.'))
        return super().write(vals)


class NegativeLocation(models.Model):
    _inherit = 'stock.location'
    erp_allow_negative_stock = fields.Boolean(string='Allow Negative Stock')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and (any(v.get('erp_allow_negative_stock') for v in vals_list) or self.env.context.get('default_erp_allow_negative_stock')) and not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError(_('Inventory management is required to allow negative stock.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_allow_negative_stock' in vals and not self.env.su and not self.env.user.has_group('stock.group_stock_manager'):
            raise AccessError(_('Inventory management is required to configure negative stock.'))
        return super().write(vals)


class NegativeQuant(models.Model):
    _inherit = 'stock.quant'

    @api.constrains('product_id', 'quantity', 'location_id')
    def _check_negative_stock(self):
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        for quant in self:
            if quant.product_id.is_storable and quant.location_id.usage in ('internal', 'transit') and float_compare(quant.quantity, 0, precision_digits=precision) < 0 and not (quant.product_id.erp_allow_negative_stock or quant.product_id.categ_id.erp_allow_negative_stock or quant.location_id.erp_allow_negative_stock):
                raise ValidationError(_('Negative stock is not allowed for %(product)s at %(location)s.', product=quant.product_id.display_name, location=quant.location_id.display_name))
