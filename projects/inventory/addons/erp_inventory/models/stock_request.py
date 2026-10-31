"""Selected stock-request workflow on Odoo's native procurement rules."""
import math
from contextvars import ContextVar
from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.erp_budget.models.budget_release import _review_internal

_request_run = ContextVar('erp_stock_request_run', default=False)


class RequestTier(models.Model):
    _inherit = 'erp.procurement.tier'
    kind = fields.Selection(selection_add=[('stock_request', 'Stock Request')], ondelete={'stock_request': 'cascade'})


class StockRequestReview(models.Model):
    _name = 'erp.inventory.request.review'
    _inherit = 'erp.procurement.review'
    _description = 'Stock Request Review'
    request_id = fields.Many2one('erp.procurement.request', required=False)
    stock_request_id = fields.Many2one('erp.inventory.request', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='stock_request_id.company_id', store=True)
    organization_id = fields.Many2one(related='stock_request_id.organization_id', store=True)
    _stock_review_unique = models.Constraint('unique(stock_request_id,round_number,sequence)', 'Stock request review order must be unique per round.')


class StockRequest(models.Model):
    _name = 'erp.inventory.request'
    _description = 'Stock Request Order'
    _check_company_auto = True
    name = fields.Char(default='New', required=True, readonly=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict')
    requested_by = fields.Many2one('res.users', required=True, default=lambda self: self.env.user)
    warehouse_id = fields.Many2one('stock.warehouse', required=True, check_company=True, ondelete='restrict')
    location_id = fields.Many2one('stock.location', required=True, check_company=True, ondelete='restrict')
    expected_date = fields.Datetime(required=True, default=fields.Datetime.now)
    separate_picking = fields.Boolean(default=True)
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted'), ('open', 'In progress'), ('done', 'Done'), ('cancel', 'Cancelled')], default='draft', required=True, readonly=True, copy=False)
    line_ids = fields.One2many('erp.inventory.request.line', 'request_id', copy=True)
    review_ids = fields.One2many('erp.inventory.request.review', 'stock_request_id', readonly=True, copy=False)
    review_round = fields.Integer(readonly=True, copy=False)
    lock_version = fields.Integer(readonly=True, copy=False)
    reference_id = fields.Many2one('stock.reference', readonly=True, copy=False, ondelete='restrict')
    history = fields.Json(readonly=True, copy=False)
    _name_company_unique = models.Constraint('unique(company_id,name)', 'Stock request number must be unique per company.')

    def _lock(self):
        self.check_access('write')
        if self:
            self.env.cr.execute('SELECT id FROM erp_inventory_request WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE erp_inventory_request SET lock_version=COALESCE(lock_version,0)+1 WHERE id IN %s', [tuple(self.ids)])
            self.invalidate_recordset()

    def _manager(self):
        self.check_access('write')
        if not self.env.su and not self.env.user.has_group('erp_inventory.group_stock_request_manager'):
            raise AccessError(_('Stock request management is required.'))

    def _workflow_write(self, vals):
        return super(StockRequest, self).write(vals)

    def _reviews(self):
        self.ensure_one()
        return self.review_ids.filtered(lambda r: r.round_number == self.review_round).sorted('sequence')

    def _snapshot(self):
        return {'company_id': self.company_id.id, 'organization_id': self.organization_id.id, 'warehouse_id': self.warehouse_id.id, 'location_id': self.location_id.id, 'date': str(self.expected_date), 'lines': [{'product_id': l.product_id.id, 'uom_id': l.uom_id.id, 'quantity': l.quantity, 'route_id': l.route_id.id, 'fund_id': l.fund_id.id, 'analytic_id': l.analytic_id.id, 'dimensions': l.dimension_ids.ids} for l in self.line_ids]}

    @api.constrains('company_id', 'organization_id', 'warehouse_id', 'location_id', 'requested_by')
    def _check_source(self):
        for request in self:
            if not request.organization_id.active or request.organization_id.company_id != request.company_id or request.warehouse_id.company_id != request.company_id or request.company_id not in request.requested_by.company_ids or request.requested_by.share:
                raise ValidationError(_('The warehouse, requester and active organization must belong to this company.'))
            if request.location_id.usage not in ('internal', 'transit', 'customer') or request.location_id.company_id and request.location_id.company_id != request.company_id:
                raise ValidationError(_('Choose an internal, transit or configured customer destination in this company.'))
            if request.location_id.usage == 'customer' and not request.company_id.erp_stock_request_virtual_location:
                raise ValidationError(_('Enable virtual customer destinations in the company configuration.'))

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'state', 'review_ids', 'review_round', 'lock_version', 'reference_id', 'history', 'name'}
        if any(protected & v.keys() for v in vals_list) or any('default_' + n in self.env.context for n in protected):
            raise AccessError(_('Stock request identity and history are generated by workflow.'))
        for vals in vals_list:
            vals['name'] = self.env['ir.sequence'].next_by_code('erp.inventory.request')
            if not self.env.su and vals.get('requested_by', self.env.uid) != self.env.uid and not self.env.user.has_group('erp_inventory.group_stock_request_manager'):
                raise AccessError(_('Only stock request management may request on behalf of another user.'))
        return super().create(vals_list)

    def write(self, vals):
        self._lock()
        if 'requested_by' in vals and not self.env.su and vals['requested_by'] != self.env.uid:
            self._manager()
        if {'state', 'name', 'company_id', 'review_ids', 'review_round', 'lock_version', 'reference_id', 'history'} & vals.keys() or any(r.state != 'draft' for r in self):
            raise UserError(_('Reset an unused stock request before changing its terms.'))
        return super().write(vals)

    def unlink(self):
        self._lock()
        if self.review_ids or self.line_ids.move_ids or self.line_ids.purchase_line_ids or any(r.state != 'draft' or r.history for r in self):
            raise UserError(_('Stock request fulfillment and review history cannot be deleted.'))
        return super().unlink()

    def action_submit(self):
        with self.env.cr.savepoint():
            self._lock()
            for request in self:
                if request.state != 'draft' or not request.line_ids:
                    raise UserError(_('Submit a draft stock request with lines.'))
                request._check_source()
                request.line_ids._check_quantity()
                # Stock requests do not authorize Budget: tiers are unconditional.
                tiers = self.env['erp.procurement.tier'].search([('company_id', '=', request.company_id.id), ('kind', '=', 'stock_request')])
                for tier in tiers:
                    if not tier.reviewer_id.active or not tier.reviewer_id.has_group('erp_inventory.group_stock_request_manager'):
                        raise ValidationError(_('Stock reviewers require active stock request management capability.'))
                    request.with_user(tier.reviewer_id).with_context(allowed_company_ids=request.company_id.ids).check_access('write')
                number = max(request.review_ids.mapped('round_number'), default=0) + 1
                request._workflow_write({'state': 'submitted', 'review_round': number})
                token = _review_internal.set(True)
                try:
                    self.env['erp.inventory.request.review'].sudo().create([{'stock_request_id': request.id, 'sequence': t.sequence, 'reviewer_id': t.reviewer_id.id, 'round_number': number, 'request_snapshot': request._snapshot()} for t in tiers])
                finally:
                    _review_internal.reset(token)
        return True

    def action_approve(self):
        self.ensure_one()
        self._manager()
        with self.env.cr.savepoint():
            self._lock()
            reviews = self._reviews()
            if self.state in ('open', 'done'):
                return True
            if self.state != 'submitted' or any(r.state == 'rejected' for r in reviews):
                raise UserError(_('Submit the stock request before approval.'))
            pending = reviews.filtered(lambda r: r.state == 'pending')[:1]
            if (not pending or pending.reviewer_id != self.env.user) and self.env.user in reviews.filtered(lambda r: r.state == 'approved').reviewer_id:
                return True
            if pending and pending.reviewer_id != self.env.user:
                raise AccessError(_('Only the next stock request reviewer may approve.'))
            if pending:
                token = _review_internal.set(True)
                try:
                    pending.sudo().write({'state': 'approved'})
                finally:
                    _review_internal.reset(token)
            if not reviews or all(r.state == 'approved' for r in reviews):
                return self._launch()
        return True

    def _launch(self):
        self.ensure_one()
        self._check_source()
        if not self.reference_id and self.separate_picking:
            self._workflow_write({'reference_id': self.env['stock.reference'].create({'name': self.name}).id})
        rule = self.env['stock.rule']
        procurements = []
        for line in self.line_ids:
            values = {'warehouse_id': self.warehouse_id, 'route_ids': line.route_id, 'date_planned': self.expected_date, 'date_deadline': self.expected_date, 'reference_ids': self.reference_id, 'erp_stock_request_line_id': line.id, 'erp_fund_id': line.fund_id.id, 'erp_analytic_id': line.analytic_id.id, 'erp_dimension_ids': [(6, 0, line.dimension_ids.ids)], 'erp_analytic_distribution': {str(line.analytic_id.id): 100} if line.analytic_id else {}}
            procurements.append(rule.Procurement(line.product_id, line.quantity, line.uom_id, self.location_id, self.name, self.name, self.company_id, values))
        token = _request_run.set(True)
        try:
            rule.run(procurements)
        finally:
            _request_run.reset(token)
        self._workflow_write({'state': 'open', 'history': (self.history or []) + [self._snapshot()]})
        return True

    def action_reject(self):
        self.ensure_one()
        self._manager()
        self._lock()
        pending = self._reviews().filtered(lambda r: r.state == 'pending')[:1]
        if self.state != 'submitted' or not pending or pending.reviewer_id != self.env.user:
            raise AccessError(_('Only the next reviewer may reject this submission.'))
        token = _review_internal.set(True)
        try:
            pending.sudo().write({'state': 'rejected'})
        finally:
            _review_internal.reset(token)
        return True

    def action_cancel(self):
        self._manager()
        with self.env.cr.savepoint():
            self._lock()
            for request in self:
                if request.line_ids.move_ids.filtered(lambda m: m.state == 'done') or request.line_ids.purchase_line_ids.filtered(lambda l: l.order_id.state != 'cancel'):
                    raise UserError(_('Cancel purchasing and retain completed stock movements before closing their request.'))
                request.line_ids.move_ids._action_cancel()
                request._workflow_write({'state': 'cancel'})
        return True

    def action_reset(self):
        self._manager()
        self._lock()
        if self.line_ids.move_ids.filtered(lambda m: m.state != 'cancel') or self.line_ids.purchase_line_ids.filtered(lambda l: l.order_id.state != 'cancel'):
            raise UserError(_('Cancel live fulfillment before resetting a stock request.'))
        return self._workflow_write({'state': 'draft', 'review_round': 0})

    def action_check_done(self):
        self._manager()
        return self._update_completion()

    def _update_completion(self):
        self._lock()
        for request in self:
            if request.state == 'open' and all(l.uom_id.compare(l.delivered_qty, l.quantity) >= 0 for l in request.line_ids):
                request._workflow_write({'state': 'done'})
        return True


class StockRequestLine(models.Model):
    _name = 'erp.inventory.request.line'
    _description = 'Stock Request Line'
    _check_company_auto = True
    request_id = fields.Many2one('erp.inventory.request', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='request_id.company_id', store=True)
    organization_id = fields.Many2one(related='request_id.organization_id', store=True)
    product_id = fields.Many2one('product.product', required=True, check_company=True, ondelete='restrict')
    uom_id = fields.Many2one('uom.uom', required=True, default=lambda self: self.env.ref('uom.product_uom_unit'))
    quantity = fields.Float(required=True, default=1, digits='Product Unit')
    route_id = fields.Many2one('stock.route', check_company=True, ondelete='restrict')
    fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict')
    analytic_id = fields.Many2one('account.analytic.account', check_company=True, ondelete='restrict')
    dimension_ids = fields.Many2many('account.analytic.account', check_company=True)
    move_ids = fields.One2many('stock.move', 'erp_stock_request_line_id', readonly=True)
    purchase_line_ids = fields.Many2many('purchase.order.line', 'erp_stock_request_purchase_rel', 'request_line_id', 'purchase_line_id', readonly=True)
    delivered_qty = fields.Float(compute='_compute_delivered')

    @api.depends('move_ids.state', 'move_ids.quantity')
    def _compute_delivered(self):
        for line in self:
            destination = line.request_id.location_id
            line.delivered_qty = sum(m.uom_id._compute_quantity(m.quantity, line.uom_id, round=False) * (1 if m.location_dest_id == destination else -1) for m in line.move_ids.filtered(lambda m: m.state == 'done' and (m.location_dest_id == destination or m.location_id == destination)))

    @api.constrains('product_id', 'uom_id', 'quantity')
    def _check_quantity(self):
        for line in self:
            if not math.isfinite(line.quantity) or line.quantity <= 0 or line.product_id.type == 'service' or not line.uom_id._has_common_reference(line.product_id.uom_id):
                raise ValidationError(_('Stock requests require goods, a compatible unit and a positive finite quantity.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            parent = self.env['erp.inventory.request'].browse(vals.get('request_id', self.env.context.get('default_request_id')))
            parent._lock()
            if parent.state != 'draft' or {'move_ids', 'purchase_line_ids'} & vals.keys():
                raise UserError(_('Add lines only to draft stock requests.'))
        return super().create(vals_list)

    def write(self, vals):
        self.request_id._lock()
        if any(r.state != 'draft' for r in self.request_id) or {'request_id', 'move_ids', 'purchase_line_ids'} & vals.keys():
            raise UserError(_('Stock request lines and fulfillment provenance are frozen after submission.'))
        return super().write(vals)

    def unlink(self):
        self.request_id._lock()
        if any(r.state != 'draft' for r in self.request_id) or self.move_ids or self.purchase_line_ids:
            raise UserError(_('Retain stock fulfillment history.'))
        return super().unlink()


class StockRequestCompany(models.Model):
    _inherit = 'res.company'
    erp_stock_request_virtual_location = fields.Boolean(string='Allow Customer Stock Request Destinations')


class RequestStockRule(models.Model):
    _inherit = 'stock.rule'
    def _get_custom_move_fields(self):
        return super()._get_custom_move_fields() + ['erp_stock_request_line_id']

    def _update_purchase_order_line(self, product_id, product_qty, product_uom, company_id, values, line):
        vals = super()._update_purchase_order_line(product_id, product_qty, product_uom, company_id, values, line)
        if values.get('erp_stock_request_line_id'):
            vals['erp_stock_request_line_ids'] = [(4, values['erp_stock_request_line_id'])]
        return vals


class RequestPurchaseLine(models.Model):
    _inherit = 'purchase.order.line'
    erp_stock_request_line_ids = fields.Many2many('erp.inventory.request.line', 'erp_stock_request_purchase_rel', 'purchase_line_id', 'request_line_id', readonly=True, copy=False)

    def _prepare_purchase_order_line_from_procurement(self, product_id, product_qty, product_uom, location_dest_id, name, origin, company_id, values, po):
        vals = super()._prepare_purchase_order_line_from_procurement(product_id, product_qty, product_uom, location_dest_id, name, origin, company_id, values, po)
        if values.get('erp_stock_request_line_id'):
            vals.update(erp_stock_request_line_ids=[(4, values['erp_stock_request_line_id'])], erp_budget_fund_id=values.get('erp_fund_id'), erp_budget_analytic_id=values.get('erp_analytic_id'), analytic_distribution=values.get('erp_analytic_distribution'))
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        if not _request_run.get() and (any('erp_stock_request_line_ids' in v for v in vals_list) or 'default_erp_stock_request_line_ids' in self.env.context):
            raise AccessError(_('Stock request purchase provenance comes from procurement rules.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_stock_request_line_ids' in vals and not _request_run.get():
            raise AccessError(_('Stock request purchase provenance is immutable.'))
        return super().write(vals)


class RequestStockMove(models.Model):
    _inherit = 'stock.move'
    erp_stock_request_line_id = fields.Many2one('erp.inventory.request.line', check_company=True, readonly=True, ondelete='restrict', index=True)

    @api.model
    def _access_domain(self, operation):
        allowed = Domain('organization_id.active', '=', True) & Domain('organization_id.assignment_ids.user_id', '=', self.env.uid)
        return super()._access_domain(operation) & Domain('erp_stock_request_line_id', 'not any!', ~allowed)

    def _prepare_merge_moves_distinct_fields(self):
        return super()._prepare_merge_moves_distinct_fields() + ['erp_stock_request_line_id']

    def _prepare_procurement_values(self):
        vals = super()._prepare_procurement_values()
        if self.erp_stock_request_line_id:
            vals['erp_stock_request_line_id'] = self.erp_stock_request_line_id.id
        return vals

    def write(self, vals):
        if 'erp_stock_request_line_id' in vals:
            raise AccessError(_('Stock fulfillment provenance is immutable.'))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not _request_run.get() and (any(v.get('erp_stock_request_line_id') for v in vals_list) or self.env.context.get('default_erp_stock_request_line_id')):
            raise AccessError(_('Generate stock request moves through native procurement.'))
        return super().create(vals_list)

    def copy(self, default=None):
        self.check_access('read')
        token = _request_run.set(True)
        try:
            return super().copy(default)
        finally:
            _request_run.reset(token)

    def _action_done(self, cancel_backorder=False):
        token = _request_run.set(True)
        try:
            result = super()._action_done(cancel_backorder=cancel_backorder)
            requests = result.erp_stock_request_line_id.request_id
            if requests:
                requests.sudo()._update_completion()
            return result
        finally:
            _request_run.reset(token)


def _request_access(uid):
    return Domain('organization_id.active', '=', True) & Domain('organization_id.assignment_ids.user_id', '=', uid)


def _request_move_access(uid):
    return Domain('erp_stock_request_line_id', 'not any!', ~_request_access(uid))


class RequestPickingScope(models.Model):
    _inherit = 'stock.picking'

    def _create_return(self):
        self.check_access('read')
        token = _request_run.set(True)
        try:
            return super()._create_return()
        finally:
            _request_run.reset(token)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_ids', 'not any!', ~_request_move_access(self.env.uid))


class RequestMoveLineScope(models.Model):
    _inherit = 'stock.move.line'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_id', 'not any!', ~_request_move_access(self.env.uid))


class RequestPurchaseScope(models.Model):
    _inherit = 'purchase.order'
    erp_stock_request_line_id = fields.Many2one('erp.inventory.request.line', readonly=True, copy=False, check_company=True, ondelete='restrict')

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('erp_stock_request_line_id', 'not any!', ~_request_access(self.env.uid))

    @api.model_create_multi
    def create(self, vals_list):
        if not _request_run.get() and (any('erp_stock_request_line_id' in v for v in vals_list) or 'default_erp_stock_request_line_id' in self.env.context):
            raise AccessError(_('Stock request RFQs are created by procurement rules.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_stock_request_line_id' in vals:
            raise AccessError(_('Stock request RFQ provenance is immutable.'))
        return super().write(vals)


class RequestPurchaseLineScope(models.Model):
    _inherit = 'purchase.order.line'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('order_id', 'any!', Domain('erp_stock_request_line_id', 'not any!', ~_request_access(self.env.uid)))


class RequestPurchaseRuleScope(models.Model):
    _inherit = 'stock.rule'
    def _make_po_get_domain(self, company_id, values, partner):
        return super()._make_po_get_domain(company_id, values, partner) + (('erp_stock_request_line_id', '=', values.get('erp_stock_request_line_id', False)),)

    def _prepare_purchase_order(self, company_id, origins, values):
        vals = super()._prepare_purchase_order(company_id, origins, values)
        if values[0].get('erp_stock_request_line_id'):
            vals['erp_stock_request_line_id'] = values[0]['erp_stock_request_line_id']
        return vals

    def _get_procurements_to_merge_groupby(self, procurement):
        return super()._get_procurements_to_merge_groupby(procurement) + (procurement.values.get('erp_stock_request_line_id'),)


def _request_invoice_access(uid):
    invalid = Domain('purchase_line_id', 'any!', Domain('order_id', 'any!', Domain('erp_stock_request_line_id', 'any!', ~_request_access(uid))))
    invalid_move = Domain('invoice_line_ids', 'any!', invalid)
    return ~invalid_move & Domain('origin_payment_id', 'not any!', Domain('invoice_ids', 'any!', invalid_move))


class RequestAccountScope(models.Model):
    _inherit = 'account.move'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & _request_invoice_access(self.env.uid)


class RequestAccountLineScope(models.Model):
    _inherit = 'account.move.line'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_id', 'any!', _request_invoice_access(self.env.uid))


class RequestPaymentScope(models.Model):
    _inherit = 'account.payment'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('invoice_ids', 'not any!', ~_request_invoice_access(self.env.uid))


class RequestPartialScope(models.Model):
    _inherit = 'account.partial.reconcile'
    @api.model
    def _access_domain(self, operation):
        valid = Domain('move_id', 'any!', _request_invoice_access(self.env.uid))
        return super()._access_domain(operation) & Domain('debit_move_id', 'any!', valid) & Domain('credit_move_id', 'any!', valid)


class RequestFullScope(models.Model):
    _inherit = 'account.full.reconcile'
    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('reconciled_line_ids', 'not any!', Domain('move_id', 'not any!', _request_invoice_access(self.env.uid)))
