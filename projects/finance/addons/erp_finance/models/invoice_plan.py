"""Invoice-plan retention terms and native deposit matching/deduction."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PurchaseRetentionTerms(models.Model):
    _inherit = 'purchase.order'
    erp_payment_retention = fields.Selection([('percent', 'Percent'), ('amount', 'Amount')], copy=False)
    erp_retention_value = fields.Float(copy=False)
    erp_retention_method = fields.Selection([('untax', 'Untaxed amount'), ('total', 'Total')], default='untax')

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.erp_use_invoice_plan:
            vals.update({'erp_payment_retention': self.erp_payment_retention, 'erp_retention_value': self.erp_retention_value, 'erp_retention_method': self.erp_retention_method})
        return vals

    def write(self, vals):
        if {'erp_payment_retention', 'erp_retention_value', 'erp_retention_method'} & vals.keys() and self.erp_invoice_plan_ids.invoice_ids:
            raise UserError(_('Retain the payment retention terms of an invoiced purchase plan.'))
        return super().write(vals)


class DepositInvoicePlan(models.Model):
    _inherit = 'erp.procurement.invoice.plan'
    invoice_type = fields.Selection(selection_add=[('advance', 'Deposit')], ondelete={'advance': lambda records: records.unlink()})
    deposit_origin_id = fields.Many2one('purchase.order.line', check_company=True, ondelete='restrict')

    @api.constrains('invoice_type', 'deposit_origin_id', 'purchase_id', 'installment', 'percent')
    def _check_deposit_plan(self):
        for plan in self.filtered(lambda p: p.invoice_type == 'advance'):
            if not plan.purchase_id or plan.installment > 0 or plan.percent > 100 or not plan.deposit_origin_id or plan.deposit_origin_id.order_id != plan.purchase_id or not plan.deposit_origin_id.erp_request_line_id:
                raise ValidationError(_('A deposit installment uses number zero or a negative number and an approved line from its purchase.'))

    def _source_total(self):
        return self.deposit_origin_id.price_subtotal if self.invoice_type == 'advance' else super()._source_total()

    def _invoice_amount(self, moves):
        if self.invoice_type == 'advance':
            return super()._invoice_amount(moves)
        return sum(moves.invoice_line_ids.filtered(lambda l: not l.purchase_line_id.is_downpayment).mapped('price_subtotal'))

    def _invoice_values(self):
        if self.invoice_type == 'advance':
            source = self.deposit_origin_id
            vals = self.purchase_id._prepare_invoice()
            amount = self.currency_id.round(source.price_subtotal * self.percent / 100)
            vals.update({'date': self.plan_date, 'invoice_date': self.plan_date, self._invoice_field(): self.id,
                         'invoice_line_ids': [(0, 0, {'name': _('Planned deposit: %s', source.name), 'quantity': 1, 'price_unit': amount,
                                                    'account_id': source.erp_budget_account_id.id, 'tax_ids': [(6, 0, source.tax_ids.ids)],
                                                    'analytic_distribution': source.analytic_distribution})]})
            return vals
        vals = super()._invoice_values()
        if not self.purchase_id:
            return vals
        deposits = self.purchase_id.order_line.filtered('erp_deposit_origin_id')
        for line in deposits:
            original = line.erp_deposit_bill_line_id
            if original.move_id.state != 'posted':
                raise UserError(_('Post the planned deposit before billing its deductions.'))
            prior = line.invoice_lines.filtered(lambda l: l.move_id.state != 'cancel')
            remaining = sum(l.quantity * (-1 if l.move_id.move_type == 'in_refund' else 1) for l in prior)
            last = self == self._regular_plans()[-1]
            fraction = remaining if last else min(remaining, self.percent / 100)
            if fraction > 0:
                values = line._prepare_account_move_line()
                values['quantity'] = -fraction
                vals['invoice_line_ids'].append((0, 0, values))
        return vals

    def _after_create_invoice(self, move):
        super()._after_create_invoice(move)
        if self.invoice_type == 'advance':
            self.env['bill.to.po.wizard'].with_context(active_ids=[-move.invoice_line_ids.id]).create({
                'purchase_order_id': self.purchase_id.id, 'erp_deposit_origin_id': self.deposit_origin_id.id}).action_add_downpayment()
