from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    erp_agreement_required = fields.Boolean(string='Agreement Required', copy=False)
    erp_agreement_ids = fields.One2many('erp.contract.agreement', 'purchase_order_id', string='Agreements')

    def _has_agreements(self):
        return bool(self.env['erp.contract.agreement'].sudo().search_count([('purchase_order_id', 'in', self.ids)], limit=1))

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get('erp_agreement_required') for vals in vals_list) and not self.env.user.has_group('erp_contract.group_contract_manager'):
            raise AccessError(_('Only agreement managers can set the agreement requirement.'))
        return super().create(vals_list)

    def _has_active_agreements(self):
        return bool(self.env['erp.contract.agreement'].sudo().search_count([('purchase_order_id', 'in', self.ids), ('state', '=', 'active')], limit=1))

    def write(self, vals):
        if 'erp_agreement_required' in vals and not self.env.user.has_group('erp_contract.group_contract_manager'):
            raise AccessError(_('Only agreement managers can set the agreement requirement.'))
        if {'partner_id', 'company_id'} & vals.keys():
            self._lock_request_scope()
            if self._has_agreements():
                raise UserError(_('The vendor and company cannot change while agreements are linked.'))
        if 'erp_agreement_required' in vals and any(order.state not in ('draft', 'sent') for order in self):
            raise UserError(_('Agreement requirements can be changed only on an RFQ.'))
        return super().write(vals)

    def _check_agreement_required(self):
        required = self.filtered(lambda order: order.erp_agreement_required or order.requisition_id.erp_po_type == 'agreement')
        if required:
            required._lock_request_scope()
            for order in required:
                agreements = self.env['erp.contract.agreement'].sudo().search([('purchase_order_id', '=', order.id)])
                if not agreements:
                    raise UserError(_('An agreement is required before confirming this purchase order.'))
                agreements._validate_source()

    def button_confirm(self):
        self._check_agreement_required()
        return super().button_confirm()

    def button_approve(self, force=False):
        self._check_agreement_required()
        return super().button_approve(force=force)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        ids = {vals.get('order_id') for vals in vals_list if vals.get('order_id') and vals.get('erp_request_line_id')}
        orders = self.env['purchase.order'].browse(list(ids))
        all_orders = self.env['purchase.order'].browse(list({vals.get('order_id') for vals in vals_list if vals.get('order_id')}))
        scoped_orders = all_orders.filtered('erp_request_organization_id')
        if scoped_orders:
            scoped_orders._lock_request_scope()
        if all_orders and all_orders._has_active_agreements():
            raise UserError(_('Start a new agreement version before changing purchase order lines.'))
        if orders:
            orders._lock_request_scope()
            if orders._has_agreements():
                raise UserError(_('Request links cannot change while agreements are linked.'))
        return super().create(vals_list)

    def write(self, vals):
        monetary = {'price_unit', 'product_qty', 'discount', 'product_id', 'tax_ids', 'uom_id', 'order_id'}
        if monetary.intersection(vals):
            orders = self.mapped('order_id')
            scoped_orders = orders.filtered('erp_request_organization_id')
            if scoped_orders:
                scoped_orders._lock_request_scope()
            if orders._has_active_agreements():
                raise UserError(_('Start a new agreement version before changing purchase order amounts.'))
        if {'erp_request_line_id', 'order_id'} & vals.keys():
            orders = self.mapped('order_id') | self.env['purchase.order'].browse(vals.get('order_id'))
            orders._lock_request_scope()
            if orders._has_agreements():
                raise UserError(_('Request links cannot change while agreements are linked.'))
        return super().write(vals)

    def unlink(self):
        scoped_orders = self.mapped('order_id').filtered('erp_request_organization_id')
        if scoped_orders:
            scoped_orders._lock_request_scope()
        if self.mapped('order_id')._has_active_agreements():
            raise UserError(_('Start a new agreement version before removing purchase order lines.'))
        orders = self.filtered('erp_request_line_id').mapped('order_id')
        if orders:
            orders._lock_request_scope()
            if orders._has_agreements():
                raise UserError(_('Request links cannot change while agreements are linked.'))
        return super().unlink()
