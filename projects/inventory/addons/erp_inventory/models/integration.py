from collections import defaultdict
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


_stock_completing = ContextVar('erp_inventory_stock_completing', default=False)


def lock_orders(orders):
    orders.check_access('read')
    if orders:
        ids = tuple(sorted(orders.ids))
        orders.env.cr.execute('SELECT id FROM purchase_order WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
        orders.env.cr.execute('UPDATE purchase_order SET erp_scope_version = COALESCE(erp_scope_version, 0) + 1 WHERE id IN %s', [ids])


def compare_quantities(env, expected, actual):
    precision = env['decimal.precision'].precision_get('Product Unit')
    if set(expected) != set(actual) or any(float_compare(expected[k], actual[k], precision_digits=precision) for k in expected):
        raise ValidationError(_('The document quantities must match the linked work acceptance.'))


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    erp_acceptance_id = fields.Many2one('erp.inventory.acceptance', string='Work Acceptance', check_company=True, copy=False, ondelete='restrict')

    def write(self, vals):
        if 'erp_acceptance_id' in vals and any(p.state in ('done', 'cancel') for p in self):
            raise UserError(_('A completed or cancelled transfer cannot change its work acceptance.'))
        return super().write(vals)

    def _action_done(self):
        linked = self.filtered('erp_acceptance_id')
        if linked:
            linked.mapped('erp_acceptance_id').check_access('read')
            lock_orders(linked.mapped('erp_acceptance_id.purchase_order_id'))
        if len(linked.mapped('erp_acceptance_id')) != len(linked):
            raise ValidationError(_('A work acceptance cannot be reused within one transfer batch.'))
        for picking in linked:
            acceptance = picking.erp_acceptance_id
            acceptance.invalidate_recordset(['state'])
            if acceptance.state != 'accept' or picking.company_id != acceptance.company_id or picking.picking_type_code != 'incoming':
                raise ValidationError(_('An accepted document in the incoming transfer company is required.'))
            duplicates = self.sudo().search_count([('id', '!=', picking.id), ('erp_acceptance_id', '=', acceptance.id), ('state', '=', 'done')])
            if duplicates:
                raise ValidationError(_('This acceptance has already been used by a completed transfer.'))
            expected = defaultdict(float)
            actual = defaultdict(float)
            for line in acceptance.line_ids.filtered(lambda l: l.product_id.type != 'service'):
                expected[line.purchase_line_id.id] += line.quantity
            for move in picking.move_ids.filtered(lambda m: m.state != 'cancel' and m.picked):
                po_line = move.purchase_line_id
                if not po_line or po_line.order_id != acceptance.purchase_order_id or move.product_id != po_line.product_id or not move.uom_id._has_common_reference(po_line.uom_id):
                    raise ValidationError(_('Every transfer move must match a product and unit on the acceptance purchase order.'))
                for move_line in move.move_line_ids.filtered(lambda row: row.picked and row.quantity):
                    if move_line.product_id != po_line.product_id or not move_line.uom_id._has_common_reference(po_line.uom_id):
                        raise ValidationError(_('Every picked line must match the ordered product and unit.'))
                    actual[po_line.id] += move_line.uom_id._compute_quantity(move_line.quantity, po_line.uom_id, round=False)
            compare_quantities(self.env, expected, actual)
        token = _stock_completing.set(True)
        try:
            return super()._action_done()
        finally:
            _stock_completing.reset(token)


class AccountMove(models.Model):
    _inherit = 'account.move'

    erp_acceptance_id = fields.Many2one('erp.inventory.acceptance', string='Work Acceptance', check_company=True, copy=False, ondelete='restrict')

    def write(self, vals):
        if 'erp_acceptance_id' in vals and any(m.state != 'draft' for m in self):
            raise UserError(_('Only a draft bill can change its work acceptance.'))
        return super().write(vals)

    def _post(self, soft=True):
        linked = self.filtered('erp_acceptance_id')
        if linked:
            linked.mapped('erp_acceptance_id').check_access('read')
            lock_orders(linked.mapped('erp_acceptance_id.purchase_order_id'))
        if len(linked.mapped('erp_acceptance_id')) != len(linked):
            raise ValidationError(_('A work acceptance cannot be reused within one bill batch.'))
        for move in linked:
            acceptance = move.erp_acceptance_id
            acceptance.invalidate_recordset(['state'])
            if move.move_type != 'in_invoice' or acceptance.state != 'accept' or move.company_id != acceptance.company_id or move.partner_id.commercial_partner_id != acceptance.partner_id.commercial_partner_id:
                raise ValidationError(_('The accepted purchase order, company and vendor must match the bill.'))
            duplicates = self.sudo().search_count([('id', '!=', move.id), ('erp_acceptance_id', '=', acceptance.id), ('state', '=', 'posted')])
            if duplicates:
                raise ValidationError(_('This acceptance has already been used by a posted bill.'))
            expected = defaultdict(float)
            actual = defaultdict(float)
            for line in acceptance.line_ids:
                expected[line.purchase_line_id.id] += line.quantity
            for line in move.invoice_line_ids.filtered(lambda l: l.product_id and l.quantity and not l.purchase_line_id.is_downpayment):
                po_line = line.purchase_line_id
                if not po_line or po_line.order_id != acceptance.purchase_order_id or line.product_id != po_line.product_id or not line.product_uom_id or not line.product_uom_id._has_common_reference(po_line.uom_id):
                    raise ValidationError(_('Every bill product line must match a product and unit on the acceptance purchase order.'))
                actual[po_line.id] += line.product_uom_id._compute_quantity(line.quantity, po_line.uom_id, round=False)
            compare_quantities(self.env, expected, actual)
        return super()._post(soft=soft)


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.model_create_multi
    def create(self, vals_list):
        pickings = self.env['stock.picking'].browse([vals['picking_id'] for vals in vals_list if vals.get('picking_id')])
        if not _stock_completing.get() and any(p.state == 'done' and p.erp_acceptance_id for p in pickings):
            raise UserError(_('A move cannot be added to an accepted completed receipt.'))
        return super().create(vals_list)

    def write(self, vals):
        sensitive = {'quantity', 'product_uom_qty', 'product_id', 'uom_id', 'picked', 'purchase_line_id', 'picking_id', 'location_id', 'location_dest_id'}
        target = self.env['stock.picking'].browse(vals.get('picking_id')).exists()
        if not _stock_completing.get() and sensitive.intersection(vals) and (any(m.picking_id.state == 'done' and m.picking_id.erp_acceptance_id for m in self) or any(p.state == 'done' and p.erp_acceptance_id for p in target)):
            raise UserError(_('Use a stock return instead of editing an accepted completed receipt.'))
        return super().write(vals)

    def unlink(self):
        if not _stock_completing.get() and any(m.picking_id.state == 'done' and m.picking_id.erp_acceptance_id for m in self):
            raise UserError(_('A move on an accepted completed receipt cannot be deleted.'))
        return super().unlink()


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        pickings = self.env['stock.picking'].browse([vals['picking_id'] for vals in vals_list if vals.get('picking_id')])
        moves = self.env['stock.move'].browse([vals['move_id'] for vals in vals_list if vals.get('move_id')])
        pickings |= moves.mapped('picking_id')
        if not _stock_completing.get() and any(p.state == 'done' and p.erp_acceptance_id for p in pickings):
            raise UserError(_('A line cannot be added to an accepted completed receipt.'))
        return super().create(vals_list)

    def write(self, vals):
        sensitive = {'quantity', 'product_id', 'uom_id', 'picked', 'move_id', 'picking_id', 'location_id', 'location_dest_id', 'lot_id'}
        target = self.env['stock.picking'].browse(vals.get('picking_id')).exists() | self.env['stock.move'].browse(vals.get('move_id')).exists().mapped('picking_id')
        if not _stock_completing.get() and sensitive.intersection(vals) and (any(line.picking_id.state == 'done' and line.picking_id.erp_acceptance_id for line in self) or any(p.state == 'done' and p.erp_acceptance_id for p in target)):
            raise UserError(_('Use a stock return instead of editing an accepted completed receipt.'))
        return super().write(vals)

    def unlink(self):
        if not _stock_completing.get() and any(line.picking_id.state == 'done' and line.picking_id.erp_acceptance_id for line in self):
            raise UserError(_('A line on an accepted completed receipt cannot be deleted.'))
        return super().unlink()
