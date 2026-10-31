"""Contract plans share purchase installment safety, not spending authority."""
import math
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_round
from odoo.addons.erp_procurement.models.invoice_plan import PurchasePlan


class ContractPlanSource(models.Model):
    _inherit = 'erp.contract.contract'
    erp_invoice_plan_ids = fields.One2many('erp.contract.invoice.plan', 'contract_id', copy=False)
    erp_use_invoice_plan = fields.Boolean(copy=False)
    erp_plan_installments = fields.Integer(default=1)
    erp_plan_start = fields.Date(default=fields.Date.context_today)
    erp_plan_interval = fields.Integer(default=1)
    erp_plan_interval_type = fields.Selection([('day', 'Days'), ('month', 'Months'), ('year', 'Years')], default='month')
    erp_invoice_plan_lock_version = fields.Integer(readonly=True, copy=False)
    erp_plan_manual_selection = fields.Boolean(string='Allow Manual Installment Selection')

    def _invoice_plan_model(self):
        return 'erp.contract.invoice.plan', 'contract_id'

    def _plan_generation_allowed(self):
        return self.active

    create_invoice_plan = PurchasePlan.create_invoice_plan
    action_create_invoice_plan = PurchasePlan.action_create_invoice_plan

    def _lock_invoice_plan(self):
        self.check_access('write')
        if self:
            self.env.cr.execute('SELECT id FROM erp_contract_contract WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE erp_contract_contract SET erp_invoice_plan_lock_version=COALESCE(erp_invoice_plan_lock_version,0)+1 WHERE id IN %s', [tuple(self.ids)])
            self.invalidate_recordset()

    def _editable_configuration_fields(self):
        return super()._editable_configuration_fields() | {'erp_use_invoice_plan', 'erp_plan_installments', 'erp_plan_start', 'erp_plan_interval', 'erp_plan_interval_type', 'erp_plan_manual_selection'}

    @api.model_create_multi
    def create(self, vals_list):
        if any('erp_invoice_plan_lock_version' in v for v in vals_list) or 'default_erp_invoice_plan_lock_version' in self.env.context:
            raise AccessError(_('Invoice-plan locking is internal.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_invoice_plan_lock_version' in vals:
            raise AccessError(_('Invoice-plan locking is internal.'))
        if {'erp_use_invoice_plan', 'erp_plan_manual_selection'} & vals.keys() and self.erp_invoice_plan_ids.invoice_ids:
            raise UserError(_('An invoiced contract plan retains its original billing mode.'))
        return super().write(vals)


class ContractInvoicePlan(models.Model):
    _name = 'erp.contract.invoice.plan'
    _inherit = 'erp.procurement.invoice.plan'
    _description = 'Contract Invoice Plan'

    purchase_id = fields.Many2one('purchase.order', required=False)
    contract_id = fields.Many2one('erp.contract.contract', required=True, check_company=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True)
    organization_id = fields.Many2one(related='contract_id.organization_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    invoice_ids = fields.One2many('account.move', 'erp_contract_invoice_plan_id', readonly=True)
    selection_ids = fields.One2many('erp.contract.invoice.plan.selection', 'plan_id', copy=True)
    _contract_installment_unique = models.Constraint('unique(contract_id, installment)', 'Installment number must be unique in the contract.')

    def _source(self):
        return self.contract_id

    def _parent_field(self):
        return 'contract_id'

    def _invoice_field(self):
        return 'erp_contract_invoice_plan_id'

    def _source_total(self):
        return sum(l.quantity * l.price_unit for l in self.contract_id.line_ids)

    def _source_ready(self):
        return self.contract_id.active and self.contract_id.erp_use_invoice_plan

    def _requires_sequence(self):
        return not self.contract_id.erp_plan_manual_selection

    @api.depends('percent', 'contract_id.line_ids.quantity', 'contract_id.line_ids.price_unit', 'contract_id.erp_invoice_plan_ids.percent', 'contract_id.erp_invoice_plan_ids.invoice_ids.state', 'invoice_ids.state', 'invoice_ids.amount_untaxed')
    def _compute_amount(self):
        return super()._compute_amount()

    @api.constrains('contract_id', 'purchase_id')
    def _check_contract_identity(self):
        if self.purchase_id:
            raise ValidationError(_('A contract plan cannot also link a purchase order.'))

    def _invoice_values(self):
        contract = self.contract_id
        commands = []
        last = self == self._siblings()[-1]
        manual = bool(self.selection_ids)
        for line in contract.line_ids:
            selected = self.selection_ids.filtered(lambda row: row.contract_line_id == line)
            if manual and not selected:
                continue
            claimed = line.invoice_line_ids.filtered(lambda l: l.move_id.state != 'cancel')
            billed = sum(l.product_uom_id._compute_quantity(l.quantity, line.uom_id, round=False) * (-1 if l.move_id.move_type == 'in_refund' else 1) for l in claimed)
            remaining = line.quantity - billed
            quantity = selected.quantity if manual else remaining if last else line.quantity * self.percent / 100
            quantity = float_round(quantity, precision_digits=self.env['decimal.precision'].precision_get('Product Unit'))
            if float_compare(quantity, remaining, precision_digits=self.env['decimal.precision'].precision_get('Product Unit')) > 0:
                raise ValidationError(_('The planned quantity exceeds the unbilled contract quantity.'))
            if quantity <= 0:
                continue
            commands.append((0, 0, {'name': line.name, 'product_id': line.product_id.id, 'product_uom_id': line.uom_id.id,
                                     'quantity': quantity, 'price_unit': line.price_unit, 'account_id': line.account_id.id,
                                     'tax_ids': [(6, 0, line.product_id.supplier_taxes_id.filtered(lambda t: t.company_id == contract.company_id).ids)],
                                     'erp_contract_line_id': line.id, 'analytic_distribution': line._invoice_analytic_distribution(self.plan_date)}))
        if not commands:
            raise UserError(_('No contract quantity remains for this installment.'))
        if manual:
            amount = sum(command[2]['quantity'] * command[2]['price_unit'] for command in commands)
            if self.currency_id.compare_amounts(amount, self.amount) != 0:
                raise ValidationError(_('Selected contract quantities must match this installment amount.'))
        return {'move_type': 'in_invoice', 'company_id': contract.company_id.id, 'journal_id': contract.journal_id.id,
                'partner_id': contract.partner_id.id, 'currency_id': self.currency_id.id, 'date': self.plan_date,
                'invoice_date': self.plan_date, self._invoice_field(): self.id, 'invoice_line_ids': commands}


class ContractPlanSelection(models.Model):
    _name = 'erp.contract.invoice.plan.selection'
    _description = 'Contract Installment Quantity Selection'
    _check_company_auto = True
    plan_id = fields.Many2one('erp.contract.invoice.plan', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    organization_id = fields.Many2one(related='plan_id.organization_id', store=True)
    contract_line_id = fields.Many2one('erp.contract.line', required=True, check_company=True, ondelete='restrict')
    quantity = fields.Float(required=True, digits='Product Unit')
    _selection_unique = models.Constraint('unique(plan_id, contract_line_id)', 'Select each contract line only once.')

    @api.constrains('plan_id', 'contract_line_id', 'quantity')
    def _check_selection(self):
        for row in self:
            if row.contract_line_id.contract_id != row.plan_id.contract_id or not math.isfinite(row.quantity) or row.quantity <= 0:
                raise ValidationError(_('Select a positive quantity from this plan contract.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            plan = self.env['erp.contract.invoice.plan'].browse(vals.get('plan_id', self.env.context.get('default_plan_id')))
            plan.check_access('write')
            plan._lock_plan()
            if plan.invoice_ids:
                raise UserError(_('An invoiced installment retains its original selected quantities.'))
        return super().create(vals_list)

    def write(self, vals):
        self.plan_id._lock_plan()
        if 'plan_id' in vals or self.plan_id.invoice_ids:
            raise UserError(_('Used quantity selections cannot change.'))
        return super().write(vals)

    def unlink(self):
        self.plan_id._lock_plan()
        if self.plan_id.invoice_ids:
            raise UserError(_('Used quantity selections cannot be deleted.'))
        return super().unlink()


class ContractPlannedMove(models.Model):
    _inherit = 'account.move'
    erp_contract_invoice_plan_id = fields.Many2one('erp.contract.invoice.plan', readonly=True, copy=False, check_company=True, ondelete='restrict')

    def _invoice_plan_fields(self):
        return super()._invoice_plan_fields() | {'erp_contract_invoice_plan_id'}
