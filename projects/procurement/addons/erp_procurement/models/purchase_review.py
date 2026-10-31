"""Configured purchase tiers reuse PR reviewer records and ordered decisions."""
from contextvars import ContextVar
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.erp_budget.models.budget_release import _review_internal

_purchase_review = ContextVar('erp_po_review_internal', default=False)
_confirming = ContextVar('erp_po_review_confirming', default=False)
_FIELDS = {'erp_review_round', 'erp_review_ids'}


class PurchaseReview(models.Model):
    _name = 'erp.procurement.purchase.review'
    _inherit = 'erp.procurement.review'
    _description = 'Purchase Order Approval Review'
    request_id = fields.Many2one(required=False)
    order_id = fields.Many2one('purchase.order', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    organization_id = fields.Many2one(related='order_id.erp_request_organization_id', store=True)
    _order_review_unique = models.Constraint('unique(order_id,round_number,sequence)', 'Purchase review order must be unique per submission.')


class ReviewedPurchase(models.Model):
    _inherit = 'purchase.order'
    erp_review_round = fields.Integer(readonly=True, copy=False)
    erp_review_ids = fields.One2many('erp.procurement.purchase.review', 'order_id', readonly=True, copy=False)
    erp_review_status = fields.Selection([('none', 'Not requested'), ('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], compute='_compute_review_status')

    def _purchase_reviews(self):
        self.ensure_one()
        return self.erp_review_ids.filtered(lambda r: r.round_number == self.erp_review_round).sorted(lambda r: (r.sequence, r.id))

    @api.depends('erp_review_ids.state', 'erp_review_round')
    def _compute_review_status(self):
        for order in self:
            reviews = order._purchase_reviews()
            order.erp_review_status = 'none' if not reviews else 'rejected' if any(r.state == 'rejected' for r in reviews) else 'approved' if all(r.state == 'approved' for r in reviews) else 'pending'

    def _purchase_tiers(self):
        self.ensure_one()
        rate = self.env['erp.budget.control.service']._amount_rate(self.currency_id, self.company_id, fields.Date.to_date(self.date_order), self.erp_budget_manual_rate)
        amount = self.amount_total * rate
        return self.env['erp.procurement.tier'].search([('company_id', '=', self.company_id.id), ('kind', '=', 'purchase'), '|', ('minimum_amount', '=', 0), ('minimum_amount', '<', amount)])

    def _purchase_review_snapshot(self):
        self.ensure_one()
        return {'company_id': self.company_id.id, 'vendor_id': self.partner_id.id, 'currency_id': self.currency_id.id, 'date_order': str(self.date_order), 'manual_rate': self.erp_budget_manual_rate,
                'lines': [{'id': l.id, 'product_id': l.product_id.id, 'quantity': l.product_qty, 'price_unit': l.price_unit, 'discount': l.discount, 'tax_ids': l.tax_ids.ids, 'request_line_id': l.erp_request_line_id.id, 'fund_id': l.erp_budget_fund_id.id, 'analytic_id': l.erp_budget_analytic_id.id, 'distribution': l.analytic_distribution} for l in self.order_line if not l.display_type]}

    def action_request_tier_review(self):
        self.check_access('write')
        with self.env.cr.savepoint():
            self._lock_request_scope()
            for order in self:
                if order._purchase_reviews():
                    continue
                tiers = order._purchase_tiers()
                if not tiers:
                    continue
                if order.state not in ('draft', 'sent', 'to approve') or not order.order_line:
                    raise UserError(_('Only a draft RFQ with lines can request tier review.'))
                for tier in tiers:
                    reviewer = tier.reviewer_id
                    if not reviewer.active or not reviewer.has_group('purchase.group_purchase_user'):
                        raise ValidationError(_('Purchase reviewers require active purchase capability.'))
                    order.with_user(reviewer).with_context(allowed_company_ids=order.company_id.ids).check_access('write')
                number = max(order.erp_review_ids.mapped('round_number'), default=0) + 1
                token, review_token = _purchase_review.set(True), _review_internal.set(True)
                try:
                    order.write({'erp_review_round': number})
                    self.env['erp.procurement.purchase.review'].sudo().create([{'order_id': order.id, 'reviewer_id': tier.reviewer_id.id, 'sequence': tier.sequence, 'round_number': number, 'request_snapshot': order._purchase_review_snapshot()} for tier in tiers])
                finally:
                    _review_internal.reset(review_token)
                    _purchase_review.reset(token)
        return True

    def _purchase_review_gate(self):
        self.action_request_tier_review()
        for order in self:
            reviews = order._purchase_reviews()
            if reviews and any(r.state != 'approved' for r in reviews):
                return False
            if reviews and reviews[0].request_snapshot != order._purchase_review_snapshot():
                raise UserError(_('The RFQ changed after review; reset its reviews.'))
        return True

    def button_confirm(self):
        pending = self.filtered(lambda r: r.state in ('draft', 'sent', 'to approve'))
        if pending and not pending._purchase_review_gate():
            return True
        token = _confirming.set(True)
        try:
            return super().button_confirm()
        finally:
            _confirming.reset(token)

    def button_approve(self, force=False):
        pending = self.filtered(lambda r: r.state in ('draft', 'sent', 'to approve'))
        if pending and not pending._purchase_review_gate():
            raise AccessError(_('Complete the configured purchase review tiers before approval.'))
        token = _confirming.set(True)
        try:
            return super().button_approve(force=force)
        finally:
            _confirming.reset(token)

    def action_approve_tier(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('purchase.group_purchase_user'):
            raise AccessError(_('Purchase capability is required to review an order.'))
        with self.env.cr.savepoint():
            self._lock_request_scope()
            reviews = self._purchase_reviews()
            pending = reviews.filtered(lambda r: r.state == 'pending')[:1]
            if (not pending or pending.reviewer_id != self.env.user) and self.env.user in reviews.filtered(lambda r: r.state == 'approved').reviewer_id:
                return True
            if self.state not in ('draft', 'sent', 'to approve') or not pending or pending.reviewer_id != self.env.user or any(r.state == 'rejected' for r in reviews):
                raise AccessError(_('Only the next purchase reviewer may approve.'))
            token = _review_internal.set(True)
            try:
                pending.sudo().write({'state': 'approved'})
            finally:
                _review_internal.reset(token)
            if all(r.state == 'approved' for r in reviews):
                return self.button_confirm()
        return True

    def action_reject_tier(self):
        self.ensure_one()
        self.check_access('write')
        with self.env.cr.savepoint():
            self._lock_request_scope()
            pending = self._purchase_reviews().filtered(lambda r: r.state == 'pending')[:1]
            if self.state not in ('draft', 'sent', 'to approve') or not pending or pending.reviewer_id != self.env.user:
                raise AccessError(_('Only the next purchase reviewer may reject.'))
            token = _review_internal.set(True)
            try:
                pending.sudo().write({'state': 'rejected'})
            finally:
                _review_internal.reset(token)
        return True

    def action_reset_tier_review(self):
        self.check_access('write')
        if not self.env.su and not self.env.user.has_group('erp_procurement.group_procurement_manager'):
            raise AccessError(_('Procurement management is required to reset reviews.'))
        if any(r.state not in ('draft', 'sent', 'cancel') for r in self):
            raise UserError(_('Cancel confirmed purchase orders before resetting their reviews.'))
        with self.env.cr.savepoint():
            self._lock_request_scope()
            token = _purchase_review.set(True)
            try:
                self.write({'erp_review_round': 0})
            finally:
                _purchase_review.reset(token)
        return True

    def button_draft(self):
        with self.env.cr.savepoint():
            result = super().button_draft()
            reviewed = self.filtered('erp_review_ids')
            if reviewed:
                reviewed.action_reset_tier_review()
            return result

    @api.model_create_multi
    def create(self, vals_list):
        if any(_FIELDS & v.keys() for v in vals_list) or any('default_' + n in self.env.context for n in _FIELDS):
            raise AccessError(_('Purchase reviews are created by submission.'))
        return super().create(vals_list)

    def write(self, vals):
        if _FIELDS & vals.keys() and not _purchase_review.get():
            raise AccessError(_('Purchase review history is managed by workflow actions.'))
        sensitive = {'company_id', 'partner_id', 'currency_id', 'date_order', 'fiscal_position_id', 'erp_budget_manual_rate', 'order_line', 'requisition_id'}
        if sensitive & vals.keys() and any(order._purchase_reviews() for order in self):
            raise UserError(_('Reset purchase reviews before changing their terms.'))
        if vals.get('state') == 'purchase' and not _confirming.get() and any(order._purchase_reviews() or order._purchase_tiers() for order in self):
            raise AccessError(_('Use native confirmation after the configured purchase reviews.'))
        return super().write(vals)

    def unlink(self):
        if self.erp_review_ids:
            raise UserError(_('Purchase review history cannot be deleted.'))
        return super().unlink()


class ReviewedPurchaseLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            order = self.env['purchase.order'].browse(values.get('order_id', self.env.context.get('default_order_id')))
            if order and order._purchase_reviews() and not (order.state in ('purchase', 'done') and values.get('is_downpayment')):
                raise UserError(_('Reset purchase reviews before adding order lines.'))
        return super().create(vals_list)

    def write(self, vals):
        sensitive = {'price_unit', 'product_qty', 'discount', 'product_id', 'tax_ids', 'uom_id', 'order_id', 'erp_request_line_id', 'erp_budget_period_id', 'erp_budget_fund_id', 'erp_budget_analytic_id', 'erp_budget_account_id', 'erp_budget_activity_id', 'erp_budget_dimension_ids', 'analytic_distribution'}
        if sensitive & vals.keys() and any(order._purchase_reviews() for order in self.order_id):
            # Native confirmation may recompute the same values; compare changes.
            for line in self:
                if any(n in vals and line._fields[n].type not in ('many2many', 'json') and (line[n].id if line._fields[n].type == 'many2one' else line[n]) != vals[n] for n in sensitive) or {'tax_ids', 'erp_budget_dimension_ids', 'analytic_distribution'} & vals.keys():
                    raise UserError(_('Reset purchase reviews before changing order economics.'))
        return super().write(vals)

    def unlink(self):
        if any(order._purchase_reviews() for order in self.order_id):
            raise UserError(_('Reset purchase reviews before deleting order lines.'))
        return super().unlink()
