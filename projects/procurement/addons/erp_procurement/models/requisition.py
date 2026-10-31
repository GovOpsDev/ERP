"""Native Odoo purchase agreements with canonical PR/Budget provenance."""
import math
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain


class RequestRequisition(models.Model):
    _inherit = 'erp.procurement.request'

    erp_conversion_lock_version = fields.Integer(readonly=True, default=0, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if 'default_erp_conversion_lock_version' in self.env.context or any('erp_conversion_lock_version' in vals for vals in vals_list):
            raise AccessError(_('Conversion locking is internal.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_conversion_lock_version' in vals:
            raise AccessError(_('Conversion locking is internal.'))
        return super().write(vals)

    def _lock_conversion(self):
        self.check_access('read')
        if self:
            ids = tuple(sorted(self.ids))
            self.env.cr.execute('SELECT id FROM erp_procurement_request WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
            self.env.cr.execute('UPDATE erp_procurement_request SET erp_conversion_lock_version = COALESCE(erp_conversion_lock_version, 0) + 1 WHERE id IN %s', [ids])
            self.invalidate_recordset()

    def action_create_requisition(self):
        self.ensure_one()
        self._lock_conversion()
        if self.state != 'approved' or not self.line_ids or any(not line.product_id for line in self.line_ids):
            raise UserError(_('An approved request with products is required.'))
        requisition = self.env['purchase.requisition'].search([
            ('line_ids.erp_request_line_id.request_id', '=', self.id), ('state', '!=', 'cancel')], limit=1)
        if not requisition:
            requisition = self.env['purchase.requisition'].create({
                'company_id': self.company_id.id, 'erp_organization_id': self.organization_id.id,
                'reference': self.name, 'requisition_type': 'purchase_template',
                'currency_id': self.currency_id.id, 'erp_budget_manual_rate': self.erp_budget_manual_rate, 'date_start': self.date_start,
                'line_ids': [(0, 0, {'product_id': line.product_id.id, 'product_qty': line.product_qty,
                                   'price_unit': line.estimated_cost / line.product_qty, 'uom_id': line.product_id.uom_id.id,
                                   'erp_request_line_id': line.id, 'analytic_distribution': {
                                       ','.join(map(str, sorted({line.analytic_id.id, *line.dimension_ids.ids}))): 100}}) for line in self.line_ids]})
        return {'type': 'ir.actions.act_window', 'name': _('Purchase Agreement'),
                'res_model': 'purchase.requisition', 'view_mode': 'form', 'res_id': requisition.id}


class Requisition(models.Model):
    _inherit = 'purchase.requisition'

    erp_organization_id = fields.Many2one('erp.organization.unit', check_company=True, ondelete='restrict', index=True)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & (Domain('erp_organization_id', '=', False) |
            (Domain('erp_organization_id.active', '=', True) & Domain('erp_organization_id.assignment_ids.user_id', '=', self.env.uid)))

    @api.constrains('erp_organization_id', 'company_id', 'line_ids')
    def _check_erp_source(self):
        for requisition in self:
            requests = requisition.line_ids.erp_request_line_id.request_id
            requests.check_access('read')
            if any(request.state != 'approved' for request in requests):
                raise ValidationError(_('Only approved purchase requests can source an agreement.'))
            unit = requisition.erp_organization_id
            if unit and (unit.company_id != requisition.company_id or not unit.active):
                raise ValidationError(_('The purchase agreement organization must be active and belong to its company.'))
            if requests and (len(requests.organization_id) != 1 or requests.organization_id != unit or requests.company_id != requisition.company_id):
                raise ValidationError(_('Request and purchase agreement company/organization must match.'))

    def action_confirm(self):
        requests = self.line_ids.erp_request_line_id.request_id
        requests._lock_conversion()
        if any(request.state != 'approved' for request in requests):
            raise UserError(_('Every source request must still be approved.'))
        self._check_erp_source()
        return super().action_confirm()

    def write(self, vals):
        if {'company_id', 'erp_organization_id'} & vals.keys() and any(r.line_ids.erp_request_line_id or r.purchase_ids for r in self):
            raise UserError(_('A sourced purchase agreement cannot change its company or organization.'))
        return super().write(vals)

    def action_create_rfq(self):
        self.ensure_one()
        self.check_access('read')
        requests = self.line_ids.erp_request_line_id.request_id
        requests._lock_conversion()
        if self.state != 'confirmed' or not self.vendor_id or any(r.state != 'approved' for r in requests):
            raise UserError(_('A confirmed agreement, vendor and approved source requests are required.'))
        order = self.purchase_ids.filtered(lambda po: po.state == 'draft' and po.partner_id == self.vendor_id)[:1]
        if not order:
            order = self.env['purchase.order'].create({
                'company_id': self.company_id.id, 'partner_id': self.vendor_id.id,
                'requisition_id': self.id, 'origin': self.name, 'currency_id': self.currency_id.id, 'erp_budget_manual_rate': self.erp_budget_manual_rate,
                'date_order': fields.Datetime.to_datetime(self.date_start) if self.date_start else fields.Datetime.now(),
                'order_line': [(0, 0, line._prepare_purchase_order_line(
                    name=line.product_id.display_name, product_qty=line.product_qty,
                    price_unit=line.price_unit, taxes_ids=line.product_id.supplier_taxes_id.filtered(
                        lambda tax: tax.company_id == self.company_id).ids)) for line in self.line_ids if not line.display_type]})
        return {'type': 'ir.actions.act_window', 'name': _('Request for Quotation'),
                'res_model': 'purchase.order', 'view_mode': 'form', 'res_id': order.id}


class RequisitionLine(models.Model):
    _inherit = 'purchase.requisition.line'

    erp_request_line_id = fields.Many2one('erp.procurement.request.line', check_company=True, ondelete='restrict', index=True)

    @api.model
    def _access_domain(self, operation):
        invalid = Domain('active', '=', False) | Domain('assignment_ids', 'not any!', Domain('user_id', '=', self.env.uid))
        return super()._access_domain(operation) & Domain('requisition_id', 'not any!', Domain('erp_organization_id', 'any!', invalid))

    @api.constrains('erp_request_line_id', 'requisition_id', 'product_id', 'product_qty', 'price_unit')
    def _check_erp_source(self):
        self.requisition_id._check_erp_source()
        for line in self.filtered('erp_request_line_id'):
            if line.product_id != line.erp_request_line_id.product_id:
                raise ValidationError(_('The purchase agreement product must match its source request line.'))
            if not all(math.isfinite(value) and value > 0 for value in (line.product_qty, line.price_unit)):
                raise ValidationError(_('Sourced purchase agreement quantity and price must be positive.'))

    def _prepare_purchase_order_line(self, name, product_qty=0.0, price_unit=0.0, taxes_ids=False):
        vals = super()._prepare_purchase_order_line(name, product_qty, price_unit, taxes_ids)
        source = self.erp_request_line_id
        if source:
            vals.update({'erp_requisition_line_id': self.id, 'erp_request_line_id': source.id,
                         'erp_budget_period_id': source.period_id.id, 'erp_budget_fund_id': source.fund_id.id,
                         'erp_budget_analytic_id': source.analytic_id.id, 'erp_budget_account_id': source.account_id.id,
                         'erp_budget_activity_id': source.activity_id.id, 'erp_budget_dimension_ids': [(6, 0, source.dimension_ids.ids)]})
        return vals

    def write(self, vals):
        if {'erp_request_line_id', 'requisition_id', 'product_id'} & vals.keys() and any(line.erp_request_line_id for line in self):
            raise UserError(_('Purchase agreement source identity cannot be reassigned.'))
        return super().write(vals)


class RequisitionOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    erp_requisition_line_id = fields.Many2one('purchase.requisition.line', check_company=True, ondelete='restrict', copy=False)

    @api.constrains('erp_requisition_line_id', 'erp_request_line_id', 'order_id')
    def _check_requisition_provenance(self):
        for line in self.filtered('erp_requisition_line_id'):
            source = line.erp_requisition_line_id
            source.check_access('read')
            if source.requisition_id != line.order_id.requisition_id or source.erp_request_line_id != line.erp_request_line_id:
                raise ValidationError(_('RFQ line and agreement must retain the same request source.'))


class RequisitionOrder(models.Model):
    _inherit = 'purchase.order'

    @api.constrains('requisition_id', 'company_id', 'order_line')
    def _check_requisition_company(self):
        for order in self.filtered('requisition_id'):
            requisition = order.requisition_id
            requisition.check_access('read')
            if order.company_id != requisition.company_id:
                raise ValidationError(_('RFQ and purchase agreement companies must match.'))
            if requisition.erp_organization_id and any(not line.erp_requisition_line_id for line in order.order_line if not line.display_type):
                raise ValidationError(_('A sourced agreement RFQ must retain its agreement line identities.'))
            order.order_line._check_requisition_provenance()

    def _check_requisition_confirmed(self):
        for order in self.filtered(lambda po: po.requisition_id.erp_organization_id):
            if order.requisition_id.state != 'confirmed':
                raise UserError(_('Confirm the source purchase agreement before approving its RFQ.'))
        self._check_requisition_company()

    def button_confirm(self):
        self._check_requisition_confirmed()
        return super().button_confirm()

    def button_approve(self, force=False):
        self._check_requisition_confirmed()
        return super().button_approve(force=force)
