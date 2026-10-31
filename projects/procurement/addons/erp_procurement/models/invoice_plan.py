"""Source purchase invoice plans, using native quantities and invoice provenance."""
import math
from contextvars import ContextVar
from dateutil.relativedelta import relativedelta
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_round

_plan_workflow = ContextVar('erp_invoice_plan_workflow', default=False)


class PurchasePlan(models.Model):
    _inherit = 'purchase.order'
    erp_invoice_plan_ids = fields.One2many('erp.procurement.invoice.plan', 'purchase_id', copy=False)
    erp_use_invoice_plan = fields.Boolean(copy=False)
    erp_plan_installments = fields.Integer(default=1)
    erp_plan_start = fields.Date(default=fields.Date.context_today)
    erp_plan_interval = fields.Integer(default=1)
    erp_plan_interval_type = fields.Selection([('day', 'Days'), ('month', 'Months'), ('year', 'Years')], default='month')
    erp_invoice_plan_lock_version = fields.Integer(readonly=True, copy=False)

    def _lock_invoice_plan(self):
        self.check_access('write')
        if self:
            self.env.cr.execute('SELECT id FROM purchase_order WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE purchase_order SET erp_invoice_plan_lock_version=COALESCE(erp_invoice_plan_lock_version,0)+1 WHERE id IN %s', [tuple(self.ids)])
            self.invalidate_recordset()

    def _invoice_plan_model(self):
        return 'erp.procurement.invoice.plan', 'purchase_id'

    def _plan_generation_allowed(self):
        return self.state != 'cancel'

    def create_invoice_plan(self, num_installment, installment_date, interval=1, interval_type='month'):
        self.ensure_one()
        self._lock_invoice_plan()
        if not isinstance(num_installment, int) or not 1 <= num_installment <= 1000 or not isinstance(interval, int) or interval < 1 or interval_type not in ('day', 'month', 'year'):
            raise ValidationError(_('Use a positive installment count and interval.'))
        if not self._plan_generation_allowed():
            raise UserError(_('A cancelled purchase cannot create an invoice plan.'))
        date = fields.Date.to_date(installment_date)
        if not date:
            raise ValidationError(_('An installment start date is required.'))
        with self.env.cr.savepoint():
            self.erp_invoice_plan_ids.unlink()
            percent = float_round(100 / num_installment, precision_digits=6)
            model, parent_field = self._invoice_plan_model()
            for index in range(num_installment):
                self.env[model].create({parent_field: self.id, 'installment': index + 1, 'plan_date': date, 'percent': percent if index < num_installment - 1 else 100 - percent * index})
                date += relativedelta(**{interval_type + 's': interval})
            self.erp_use_invoice_plan = True
        return True

    def action_create_invoice_plan(self):
        return self.create_invoice_plan(self.erp_plan_installments, self.erp_plan_start, self.erp_plan_interval, self.erp_plan_interval_type)

    def button_confirm(self):
        for order in self.filtered('erp_use_invoice_plan'):
            if not order.erp_invoice_plan_ids:
                raise ValidationError(_('Create the selected invoice plan before confirming the purchase.'))
            order.erp_invoice_plan_ids._check_plan()
        return super().button_confirm()

    @api.model_create_multi
    def create(self, vals_list):
        if any('erp_invoice_plan_lock_version' in v for v in vals_list) or 'default_erp_invoice_plan_lock_version' in self.env.context:
            raise AccessError(_('Invoice-plan locking is internal.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_invoice_plan_lock_version' in vals:
            raise AccessError(_('Invoice-plan locking is internal.'))
        if 'erp_use_invoice_plan' in vals and self.erp_invoice_plan_ids.invoice_ids:
            raise UserError(_('An invoiced plan remains linked to its purchase.'))
        return super().write(vals)


class InvoicePlan(models.Model):
    _name = 'erp.procurement.invoice.plan'
    _description = 'Purchase Invoice Plan'
    _check_company_auto = True
    _order = 'installment, id'
    _rec_name = 'installment'

    purchase_id = fields.Many2one('purchase.order', required=True, check_company=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='purchase_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='purchase_id.erp_request_organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='purchase_id.currency_id')
    installment = fields.Integer(required=True)
    plan_date = fields.Date(required=True)
    invoice_type = fields.Selection([('installment', 'Installment')], default='installment', required=True)
    percent = fields.Float(required=True, digits=(16, 6))
    amount = fields.Monetary(compute='_compute_amount', inverse='_inverse_amount')
    invoice_ids = fields.One2many('account.move', 'erp_purchase_invoice_plan_id', readonly=True)
    _purchase_installment_unique = models.Constraint('unique(purchase_id, installment)', 'Installment number must be unique in its purchase.')

    def _source(self):
        return self.purchase_id

    def _siblings(self):
        return self._source().erp_invoice_plan_ids.sorted('installment')

    def _regular_plans(self):
        return self._siblings().filtered(lambda p: p.invoice_type == 'installment')

    def _invoice_amount(self, moves):
        return sum(moves.mapped('amount_untaxed'))

    def _source_total(self):
        return self.purchase_id.amount_untaxed

    def _source_ready(self):
        return self.purchase_id.state == 'purchase' and self.purchase_id.erp_use_invoice_plan

    def _parent_field(self):
        return 'purchase_id'

    def _invoice_field(self):
        return 'erp_purchase_invoice_plan_id'

    def _lock_plan(self):
        self.check_access('read')
        self._source()._lock_invoice_plan()

    @api.depends('percent', 'purchase_id.amount_untaxed', 'purchase_id.erp_invoice_plan_ids.percent', 'purchase_id.erp_invoice_plan_ids.invoice_ids.state', 'invoice_ids.state', 'invoice_ids.amount_untaxed')
    def _compute_amount(self):
        for plan in self:
            current = plan.invoice_ids.filtered(lambda m: m.state != 'cancel')
            siblings = plan._regular_plans()
            if current:
                plan.amount = plan._invoice_amount(current)
            elif siblings and plan == siblings[-1]:
                plan.amount = plan._source_total() - sum(other._invoice_amount(other.invoice_ids.filtered(lambda m: m.state != 'cancel')) if other.invoice_ids.filtered(lambda m: m.state != 'cancel') else other.currency_id.round(other._source_total() * other.percent / 100) for other in siblings - plan)
            else:
                plan.amount = plan.currency_id.round(plan._source_total() * plan.percent / 100)

    def _inverse_amount(self):
        for plan in self:
            if plan._source_total():
                plan.percent = plan.amount / plan._source_total() * 100

    @api.constrains('percent', 'installment', 'plan_date', 'purchase_id')
    def _check_plan(self):
        for plan in self:
            if not math.isfinite(plan.percent) or plan.percent <= 0 or (plan.installment < 1 and plan.invoice_type == 'installment'):
                raise ValidationError(_('Installment number and percentage must be positive.'))
            if float_compare(sum(plan._regular_plans().mapped('percent')), 100, precision_digits=5) > 0:
                raise ValidationError(_('Invoice plan percentages cannot exceed 100.'))

    @api.model_create_multi
    def create(self, vals_list):
        parent_field = self._parent_field()
        for vals in vals_list:
            if 'invoice_ids' in vals or 'default_invoice_ids' in self.env.context:
                raise AccessError(_('Invoice-plan history is generated by its invoice action.'))
            parent = self.env[self._fields[parent_field].comodel_name].browse(vals.get(parent_field, self.env.context.get('default_' + parent_field))).exists()
            parent.check_access('write')
            parent._lock_invoice_plan()
            if parent.erp_invoice_plan_ids.invoice_ids:
                raise UserError(_('An invoiced plan cannot add installments.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'invoice_ids', self._parent_field()} & vals.keys():
            raise AccessError(_('Plan identity and invoice provenance are immutable.'))
        for plan in self:
            plan._lock_plan()
            if plan._siblings().invoice_ids:
                raise UserError(_('Retain the used plan and its original percentages/dates.'))
        return super().write(vals)

    def unlink(self):
        for plan in self:
            plan._lock_plan()
            if plan._siblings().invoice_ids:
                raise UserError(_('An invoice plan with accounting history cannot be deleted.'))
        return super().unlink()

    def _invoice_values(self):
        order = self.purchase_id
        vals = order._prepare_invoice()
        vals.update({'invoice_date': self.plan_date, 'date': self.plan_date, self._invoice_field(): self.id})
        siblings = self._siblings()
        last = self == siblings[-1]
        commands = []
        for line in order.order_line.filtered(lambda l: not l.display_type and not l.is_downpayment):
            claimed = line.invoice_lines.filtered(lambda l: l.move_id.state != 'cancel' and l.move_id.move_type in ('in_invoice', 'in_refund'))
            billed = sum(l.product_uom_id._compute_quantity(l.quantity, line.uom_id, round=False) * (-1 if l.move_id.move_type == 'in_refund' else 1) for l in claimed)
            remaining = line.product_qty - billed
            quantity = remaining if last else line.product_qty * self.percent / 100
            quantity = float_round(quantity, precision_digits=self.env['decimal.precision'].precision_get('Product Unit'))
            invoiceable = line.qty_received - billed if line.product_id.purchase_method == 'receive' else remaining
            if float_compare(quantity, invoiceable, precision_digits=self.env['decimal.precision'].precision_get('Product Unit')) > 0:
                raise ValidationError(_('Receive the planned quantity before generating this installment invoice.'))
            if quantity <= 0:
                continue
            values = line._prepare_account_move_line()
            values['quantity'] = quantity
            commands.append((0, 0, values))
        if not commands:
            raise UserError(_('No quantity remains for this installment.'))
        vals['invoice_line_ids'] = commands
        return vals

    def _after_create_invoice(self, move):
        return

    def _extra_invoice_values(self):
        return {}

    def _requires_sequence(self):
        return True

    def action_create_invoice(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_plan()
        existing = self.invoice_ids.filtered(lambda m: m.state != 'cancel')[:1]
        if existing:
            return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': existing.id, 'view_mode': 'form'}
        if not self._source_ready():
            raise UserError(_('An active confirmed source using invoice plans is required.'))
        if self._requires_sequence() and any(not p.invoice_ids.filtered(lambda m: m.state != 'cancel') for p in self._siblings() if p.installment < self.installment):
            raise UserError(_('Create prior installments before this plan.'))
        self._check_plan()
        token = _plan_workflow.set(True)
        try:
            with self.env.cr.savepoint():
                values = self._invoice_values()
                values.update(self._extra_invoice_values())
                move = self.env['account.move'].with_company(self.company_id).create(values)
                self._after_create_invoice(move)
                return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'res_id': move.id, 'view_mode': 'form'}
        finally:
            _plan_workflow.reset(token)


class PlannedMove(models.Model):
    _inherit = 'account.move'
    erp_purchase_invoice_plan_id = fields.Many2one('erp.procurement.invoice.plan', readonly=True, copy=False, check_company=True, ondelete='restrict')

    def _invoice_plan_fields(self):
        return {'erp_purchase_invoice_plan_id'}

    @api.model_create_multi
    def create(self, vals_list):
        names = self._invoice_plan_fields()
        if not _plan_workflow.get() and (any(names & v.keys() for v in vals_list) or any('default_' + name in self.env.context for name in names)):
            raise AccessError(_('Create planned invoices through the installment action.'))
        return super().create(vals_list)

    def write(self, vals):
        if self._invoice_plan_fields() & vals.keys() and not _plan_workflow.get():
            raise AccessError(_('Invoice plan provenance cannot change.'))
        return super().write(vals)

    def unlink(self):
        if any(self.mapped(name) for name in self._invoice_plan_fields()):
            raise UserError(_('Cancel planned invoices to retain their installment history.'))
        return super().unlink()
