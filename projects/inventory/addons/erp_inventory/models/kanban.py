"""Reusable replenishment cards and card census, not physical stock adjustment."""
from reportlab.graphics.barcode import getCodes
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
import math


class StockRequestCard(models.Model):
    _name = 'erp.inventory.card'
    _description = 'Stock Request Kanban Card'
    _check_company_auto = True
    name = fields.Char(required=True, default='New', copy=False)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict')
    warehouse_id = fields.Many2one('stock.warehouse', required=True, check_company=True, ondelete='restrict')
    location_id = fields.Many2one('stock.location', required=True, check_company=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', required=True, check_company=True, ondelete='restrict')
    uom_id = fields.Many2one('uom.uom', required=True, default=lambda self: self.env.ref('uom.product_uom_unit'))
    quantity = fields.Float(required=True, default=1, digits='Product Unit')
    route_id = fields.Many2one('stock.route', check_company=True, ondelete='restrict')
    fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict')
    analytic_id = fields.Many2one('account.analytic.account', check_company=True, ondelete='restrict')
    active = fields.Boolean(default=True)
    barcode = fields.Char(compute='_compute_barcode')
    _card_name_unique = models.Constraint('unique(company_id,name)', 'Card names must be unique within company.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('erp.inventory.card')
        return super().create(vals_list)

    @api.constrains('product_id', 'quantity', 'uom_id', 'warehouse_id', 'organization_id', 'company_id')
    def _check_card(self):
        for card in self:
            if not math.isfinite(card.quantity) or card.quantity <= 0 or card.product_id.type == 'service' or not card.uom_id._has_common_reference(card.product_id.uom_id):
                raise ValidationError(_('Cards require goods and a positive quantity in a compatible unit.'))
            if card.warehouse_id.company_id != card.company_id or card.organization_id.company_id != card.company_id:
                raise ValidationError(_('Card warehouse and organization must belong to its company.'))

    def write(self, vals):
        if 'company_id' in vals:
            raise UserError(_('Card company is immutable.'))
        return super().write(vals)

    def _barcode_value(self, value):
        config = self.env['ir.config_parameter'].sudo()
        if config.get_str('stock_request_kanban.crc', '1') == '0':
            return value
        format_name = config.get_str('stock_request_kanban.barcode_format', 'Standard39')
        if format_name not in getCodes():
            raise ValidationError(_('Configure a supported card barcode format.'))
        barcode = getCodes()[format_name](value=value)
        barcode.validate()
        barcode.encode()
        return barcode.encoded[1:-1]

    @api.depends('name')
    def _compute_barcode(self):
        for card in self:
            card.barcode = card._barcode_value(card.name)

    @api.model
    def search_barcode(self, barcode):
        config = self.env['ir.config_parameter'].sudo()
        name = barcode
        if config.get_str('stock_request_kanban.crc', '1') != '0':
            name = barcode[:-1]
            if config.get_str('stock_request_kanban.ignore_crc', '0') != '1' and self._barcode_value(name) != barcode:
                raise ValidationError(_('Invalid Kanban barcode checksum.'))
        cards = self.search([('name', '=', name)])
        if len(cards) != 1:
            raise UserError(_('Scan one active card in your allowed company and organization.'))
        return cards

    def action_request(self):
        self.ensure_one()
        self.check_access('read')
        if not self.active:
            raise UserError(_('Archived cards cannot request stock.'))
        request = self.env['erp.inventory.request'].create({'company_id': self.company_id.id, 'organization_id': self.organization_id.id, 'warehouse_id': self.warehouse_id.id, 'location_id': self.location_id.id, 'card_id': self.id, 'line_ids': [(0, 0, {'product_id': self.product_id.id, 'uom_id': self.uom_id.id, 'quantity': self.quantity, 'route_id': self.route_id.id, 'fund_id': self.fund_id.id, 'analytic_id': self.analytic_id.id})]})
        request.action_submit()
        # Configured reviews remain mandatory for scanned requests.
        if not request.review_ids and self.env.user.has_group('erp_inventory.group_stock_request_manager'):
            request.action_approve()
        return {'type': 'ir.actions.act_window', 'res_model': 'erp.inventory.request', 'res_id': request.id, 'view_mode': 'form'}

    @api.model
    def action_scan_request(self, barcode):
        return self.search_barcode(barcode).action_request()


class CardRequest(models.Model):
    _inherit = 'erp.inventory.request'
    card_id = fields.Many2one('erp.inventory.card', check_company=True, ondelete='restrict', readonly=True, copy=False)

    @api.constrains('card_id', 'organization_id')
    def _check_card_organization(self):
        for request in self.filtered('card_id'):
            request.card_id.check_access('read')
            if request.card_id.organization_id != request.organization_id:
                raise ValidationError(_('The stock request must retain its card organization.'))

    def write(self, vals):
        if 'card_id' in vals:
            raise AccessError(_('Card provenance is immutable.'))
        return super().write(vals)


class CardCensus(models.Model):
    _name = 'erp.inventory.card.census'
    _description = 'Kanban Card Inventory'
    _check_company_auto = True
    name = fields.Char(required=True, default='New', copy=False)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict')
    warehouse_ids = fields.Many2many('stock.warehouse', check_company=True)
    location_ids = fields.Many2many('stock.location', check_company=True)
    product_ids = fields.Many2many('product.product', check_company=True)
    state = fields.Selection([('draft', 'Draft'), ('in_progress', 'In progress'), ('finished', 'Finished'), ('closed', 'Closed'), ('cancelled', 'Cancelled')], default='draft', required=True, readonly=True, copy=False)
    card_ids = fields.Many2many('erp.inventory.card', 'erp_card_census_expected', readonly=True, copy=False)
    scanned_ids = fields.Many2many('erp.inventory.card', 'erp_card_census_scanned', readonly=True, copy=False)
    missing_ids = fields.Many2many('erp.inventory.card', compute='_compute_missing')
    history = fields.Json(readonly=True, copy=False)
    lock_version = fields.Integer(readonly=True, copy=False)

    @api.depends('card_ids', 'scanned_ids')
    def _compute_missing(self):
        for census in self:
            census.missing_ids = census.card_ids - census.scanned_ids

    def _lock(self):
        self.check_access('write')
        if self:
            self.env.cr.execute('SELECT id FROM erp_inventory_card_census WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE erp_inventory_card_census SET lock_version=COALESCE(lock_version,0)+1 WHERE id IN %s', [tuple(self.ids)])
            self.invalidate_recordset()

    def _workflow_write(self, vals):
        return super(CardCensus, self).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'state', 'card_ids', 'scanned_ids', 'history', 'lock_version'}
        if any(protected & v.keys() for v in vals_list) or any('default_' + n in self.env.context for n in protected):
            raise AccessError(_('Card census history is generated by workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        self._lock()
        if {'state', 'company_id', 'organization_id', 'card_ids', 'scanned_ids', 'history', 'lock_version'} & vals.keys() or any(c.state != 'draft' for c in self):
            raise UserError(_('Only draft census filters can change.'))
        return super().write(vals)

    def unlink(self):
        if any(c.state != 'draft' or c.history for c in self):
            raise UserError(_('Retain card census history.'))
        return super().unlink()

    def action_start(self):
        self._lock()
        for census in self:
            if census.state != 'draft':
                raise UserError(_('Start a draft census.'))
            domain = [('company_id', '=', census.company_id.id), ('organization_id', '=', census.organization_id.id)]
            for filter_name, card_name in (('warehouse_ids', 'warehouse_id'), ('location_ids', 'location_id'), ('product_ids', 'product_id')):
                if census[filter_name]:
                    domain.append((card_name, 'in', census[filter_name].ids))
            cards = self.env['erp.inventory.card'].search(domain)
            census._workflow_write({'state': 'in_progress', 'card_ids': [(6, 0, cards.ids)], 'scanned_ids': [(5, 0, 0)]})
        return True

    def action_scan(self, barcode):
        self.ensure_one()
        self._lock()
        if self.state != 'in_progress':
            raise UserError(_('Scan cards while the census is in progress.'))
        card = self.env['erp.inventory.card'].search_barcode(barcode)
        if card not in self.card_ids:
            raise ValidationError(_('This card is outside the selected census scope.'))
        self._workflow_write({'scanned_ids': [(4, card.id)]})
        return True

    def action_finish(self):
        self._lock()
        if any(c.state != 'in_progress' for c in self):
            raise UserError(_('Finish an in-progress census.'))
        return self._workflow_write({'state': 'finished'})

    def action_close(self):
        self._lock()
        for census in self:
            if census.state != 'finished':
                raise UserError(_('Close a finished census.'))
            census._workflow_write({'state': 'closed', 'history': (census.history or []) + [{'date': str(fields.Datetime.now()), 'actor_id': self.env.uid, 'expected': census.card_ids.ids, 'scanned': census.scanned_ids.ids, 'missing': census.missing_ids.ids}]})
        return True

    def action_cancel(self):
        self._lock()
        if any(c.state == 'closed' for c in self):
            raise UserError(_('Closed census history remains final.'))
        return self._workflow_write({'state': 'cancelled'})

    def action_reset(self):
        self._lock()
        for census in self:
            if census.state != 'cancelled':
                raise UserError(_('Cancel a census before restarting.'))
            census._workflow_write({'history': (census.history or []) + [{'date': str(fields.Datetime.now()), 'actor_id': self.env.uid, 'expected': census.card_ids.ids, 'scanned': census.scanned_ids.ids}], 'state': 'draft', 'card_ids': [(5, 0, 0)], 'scanned_ids': [(5, 0, 0)]})
        return True


class CardScanner(models.TransientModel):
    _name = 'erp.inventory.card.scan'
    _description = 'Scan Kanban Card'
    barcode = fields.Char(required=True)
    census_id = fields.Many2one('erp.inventory.card.census')

    def action_scan(self):
        self.ensure_one()
        if self.census_id:
            self.census_id.action_scan(self.barcode)
            return {'type': 'ir.actions.act_window_close'}
        return self.env['erp.inventory.card'].action_scan_request(self.barcode)
