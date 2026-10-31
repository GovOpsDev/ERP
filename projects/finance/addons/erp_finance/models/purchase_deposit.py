"""Native purchase down payments with explicit approved budget provenance."""
from contextvars import ContextVar
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from .finance import _finance_posting

_deposit_link = ContextVar('erp_purchase_deposit_link', default=False)


def _deposit_access(user):
    unauthorized = Domain('active', '=', False) | Domain('assignment_ids', 'not any!', Domain('user_id', '=', user))
    return Domain('line_ids', 'not any!', Domain('purchase_line_id', 'any!', Domain('erp_deposit_origin_id', 'any!', Domain('erp_request_line_id', 'any!', Domain('organization_id', 'any!', unauthorized)))))


class DepositPurchaseLine(models.Model):
    _inherit = 'purchase.order.line'

    erp_deposit_origin_id = fields.Many2one('purchase.order.line', string='Deposit Budget Source', readonly=True, copy=False, check_company=True, ondelete='restrict', index=True)

    erp_deposit_bill_line_id = fields.Many2one('account.move.line', readonly=True, copy=False, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        if not _deposit_link.get() and (any({'erp_deposit_origin_id', 'erp_deposit_bill_line_id'} & v.keys() for v in vals_list) or any('default_' + key in self.env.context for key in ('erp_deposit_origin_id', 'erp_deposit_bill_line_id'))):
            raise AccessError(_('Use the native bill matching wizard to assign deposit provenance.'))
        if not _deposit_link.get():
            for vals in vals_list:
                order = self.env['purchase.order'].browse(vals.get('order_id'))
                if vals.get('is_downpayment') and not vals.get('display_type') and order.erp_request_organization_id:
                    raise UserError(_('Use native bill matching to add a controlled deposit.'))
        return super().create(vals_list)

    def write(self, vals):
        protected = {'erp_deposit_bill_line_id', 'erp_deposit_origin_id', 'order_id', 'is_downpayment', 'product_qty', 'price_unit', 'tax_ids', 'analytic_distribution', 'erp_request_line_id'}
        if {'erp_deposit_origin_id', 'erp_deposit_bill_line_id'} & vals.keys() and not _deposit_link.get():
            raise AccessError(_('Deposit provenance is immutable.'))
        if protected & vals.keys() and self.filtered('erp_deposit_origin_id') and not _deposit_link.get():
            # Native order linkage writes the same order without changing it.
            if set(vals) != {'order_id'} or any(line.order_id.id != vals['order_id'] for line in self):
                raise UserError(_('A controlled deposit line cannot change its source or amount.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('erp_deposit_origin_id'):
            raise UserError(_('Retain deposit provenance and reverse the accounting document instead.'))
        return super().unlink()

    def _prepare_account_move_line(self, move=False):
        vals = super()._prepare_account_move_line(move=move)
        if self.erp_deposit_origin_id:
            origin = self.erp_deposit_origin_id
            vals['analytic_distribution'] = self.env['erp.budget.control.service']._source_distribution('purchase.order.line:%s' % origin.id, origin._erp_budget_controls(), origin.analytic_distribution, move.date if move else fields.Date.to_date(origin.order_id.date_order), actual=False)
        return vals

    def _reconcile_deposit_actuals(self, remaining, actuals, provenance):
        remaining = super()._reconcile_deposit_actuals(remaining, actuals, provenance)
        deposits = self.sudo().search([('erp_deposit_origin_id', '=', self.id)]).with_env(self.env)
        deposits.check_access('read')
        controls = self._erp_budget_controls()
        outstanding = 0
        for deposit in deposits:
            lines = self.env['account.move.line'].sudo().search([('purchase_line_id', '=', deposit.id), ('move_id.state', '=', 'posted'), ('display_type', '=', 'product')]).with_env(self.env)
            lines.check_access('read')
            lines.move_id.check_access('read')
            positive = 0
            negative = 0
            currency_net = 0
            original = deposit.erp_deposit_bill_line_id
            for line in lines.sorted('id'):
                move = line.move_id
                expected = self.env['erp.budget.control.service']._source_distribution('purchase.order.line:%s' % self.id, controls, self.analytic_distribution, move.date)
                if move.company_id != self.company_id or move.partner_id != self.order_id.partner_id or move.move_type not in ('in_invoice', 'in_refund') or line.analytic_distribution != expected:
                    raise ValidationError(_('Deposit company, supplier and analytic dimensions must match its approved purchase source.'))
                if not all(math.isfinite(v) for v in (line.quantity, line.price_unit, line.price_subtotal)) or line.price_unit <= 0:
                    raise ValidationError(_('Deposit lines require a finite positive unit price.'))
                if line.account_id != original.account_id or line.currency_id != original.currency_id:
                    raise ValidationError(_('Deposit deductions must preserve the original account and currency.'))
                if move.move_type == 'in_refund':
                    if not move.reversed_entry_id or move.reversed_entry_id.state != 'posted' or not move.reversed_entry_id.invoice_line_ids.filtered(lambda item: item.purchase_line_id == deposit):
                        raise ValidationError(_('A deposit refund must reverse its posted deposit or deduction bill.'))
                elif line.quantity > 0 and line != original:
                    raise ValidationError(_('A deposit has one original bill; create another deposit for an additional payment.'))
                currency_net += line.amount_currency
                amount = line._erp_actual_budget_amount()
                if amount > 0:
                    positive += amount
                else:
                    negative -= amount
                key = 'account.move.line:%s' % line.id
                actuals.append((key, controls, amount, move.date))
                provenance[key] = ('account.move:%s' % move.id, 'purchase.order.line:%s' % self.id)
            if original.currency_id.compare_amounts(currency_net, 0) < 0 or original.currency_id.compare_amounts(currency_net, original.amount_currency if original.move_id.state == 'posted' else 0) > 0:
                raise ValidationError(_('Deposit deductions or refunds cannot exceed the posted deposit.'))
            outstanding += positive - negative
        return max(0, remaining - max(0, outstanding))


class DepositInvoiceLine(models.Model):
    _inherit = 'account.move.line'

    def _erp_purchase_budget_source(self):
        source = super()._erp_purchase_budget_source()
        return source.erp_deposit_origin_id or source

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_id', 'any!', _deposit_access(self.env.uid))

    def write(self, vals):
        if 'purchase_line_id' in vals and not _deposit_link.get() and self.env['purchase.order.line'].sudo().search_count([('erp_deposit_bill_line_id', 'in', self.ids)]):
            raise UserError(_('The original deposit bill must retain its purchase provenance.'))
        if 'purchase_line_id' in vals and self.filtered(lambda line: line.move_id.state == 'posted') and not _deposit_link.get():
            target = self.env['purchase.order.line'].browse(vals['purchase_line_id'])
            if target.erp_deposit_origin_id or self.purchase_line_id.erp_deposit_origin_id:
                raise UserError(_('Use the native matching wizard to attach a posted deposit.'))
        return super().write(vals)


class DepositInvoice(models.Model):
    _inherit = 'account.move'

    def _check_erp_budget_posting_ready(self):
        super()._check_erp_budget_posting_ready()
        if not _finance_posting.get() and self.sudo().invoice_line_ids.purchase_line_id.erp_deposit_origin_id:
            raise UserError(_('Use native posting to reconcile the controlled deposit.'))

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & _deposit_access(self.env.uid)


class DepositPurchase(models.Model):
    _inherit = 'purchase.order'

    def write(self, vals):
        if vals.get('state') in ('draft', 'cancel'):
            deposits = self.order_line.filtered('erp_deposit_origin_id')
            if deposits and self.env['account.move.line'].sudo().search_count([('purchase_line_id', 'in', deposits.ids), ('move_id.state', '=', 'posted')]):
                raise UserError(_('Reset the posted deposit documents before cancelling the purchase order.'))
        return super().write(vals)


class DepositBillWizard(models.TransientModel):
    _inherit = 'bill.to.po.wizard'

    erp_deposit_origin_id = fields.Many2one('purchase.order.line', string='Deposit Budget Source', domain="[('order_id', '=', purchase_order_id), ('erp_request_line_id', '!=', False), ('is_downpayment', '=', False)]")

    def action_add_downpayment(self):
        self.ensure_one()
        order = self.purchase_order_id
        if not order.erp_request_organization_id:
            return super().action_add_downpayment()
        order.check_access('write')
        origins = order.order_line.filtered('erp_request_line_id')
        origin = self.erp_deposit_origin_id or (origins if len(origins) == 1 else self.env['purchase.order.line'])
        if not origin or origin not in origins or order.state not in ('purchase', 'done'):
            raise ValidationError(_('Select an approved purchase line as the deposit budget source. Split deposits into separate bill lines for different sources.'))
        origin.check_access('read')
        lines = self.env['account.move.line'].browse([abs(i) for i in self.env.context.get('active_ids', []) if i < 0]).exists()
        if not lines:
            raise ValidationError(_('Select deposit bill lines.'))
        lines.check_access('write')
        lines.move_id.check_access('write')
        if any(line.purchase_line_id or line.display_type != 'product' or line.move_id.move_type != 'in_invoice' or line.move_id.state not in ('draft', 'posted') or line.quantity != 1 or line.price_unit <= 0 or line.company_id != order.company_id or line.partner_id != order.partner_id or line.move_id._erp_direct_actual_lines() or line.expense_id or ('erp_contract_line_id' in line._fields and line.erp_contract_line_id) for line in lines):
            raise ValidationError(_('Use an unassigned positive deposit bill line for the same company and supplier, with quantity one.'))
        service = self.env['erp.budget.control.service']
        request = origin.erp_request_line_id.request_id
        with self.env.cr.savepoint(), service._accounting_transaction(request._lock_budget_rows()):
            order._lock_request_scope()
            old_lines = order.order_line
            token = _deposit_link.set(True)
            posting = _finance_posting.set(True)
            try:
                result = super().action_add_downpayment()
                deposits = (order.order_line - old_lines).filtered(lambda line: not line.display_type)
                for deposit, line in zip(deposits.sorted('id'), lines):
                    deposit.write({'erp_deposit_origin_id': origin.id, 'erp_deposit_bill_line_id': line.id, 'analytic_distribution': origin.analytic_distribution})
                for line in lines:
                    expected = service._source_distribution('purchase.order.line:%s' % origin.id, origin._erp_budget_controls(), origin.analytic_distribution, line.move_id.date)
                    if line.analytic_distribution != expected:
                        raise ValidationError(_('Set the deposit analytic distribution to its approved purchase source before matching.'))
                lines.move_id._capture_budget_amount_policy()
                lines.move_id._finalize_budget_amounts()
                origin.erp_request_line_id._reconcile_budget(pr_eligible=True)
            finally:
                _finance_posting.reset(posting)
                _deposit_link.reset(token)
            return result
