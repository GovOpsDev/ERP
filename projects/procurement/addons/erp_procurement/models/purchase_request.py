import math

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.erp_budget.models.budget_release import _review_internal


class ProcurementRequest(models.Model):
    _name = 'erp.procurement.request'
    _description = 'Purchase Request'
    _check_company_auto = True

    name = fields.Char(required=True, default='New', copy=False, readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, ondelete='restrict', check_company=True, index=True)
    requested_by = fields.Many2one('res.users', required=True, default=lambda self: self.env.user, ondelete='restrict', copy=False)
    date_start = fields.Date(required=True, default=fields.Date.context_today)
    line_ids = fields.One2many('erp.procurement.request.line', 'request_id', copy=True)
    review_round = fields.Integer(readonly=True, copy=False)
    review_ids = fields.One2many('erp.procurement.review', 'request_id', copy=False, readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('to_approve', 'To Approve'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('done', 'Done')], required=True, default='draft', copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if 'default_review_round' in self.env.context or 'default_review_ids' in self.env.context or self.env.context.get('default_state', 'draft') != 'draft':
            raise AccessError(_('Requests must begin in draft without forged reviews.'))
        for vals in vals_list:
            if 'review_round' in vals or vals.get('review_ids'):
                raise AccessError(_('Approval reviews are created only by submission.'))
            if vals.get('state', 'draft') != 'draft':
                raise AccessError(_('Requests must start in draft.'))
            if vals.get('company_id', self.env.company.id) not in self.env.companies.ids and not self.env.su:
                raise AccessError(_('The request company must be active.'))
            unit = self.env['erp.organization.unit'].browse(vals.get('organization_id')).exists()
            if not unit:
                raise ValidationError(_('An organization is required.'))
            unit.check_access('read')
            if not unit.active:
                raise ValidationError(_('The organization must be active.'))
            if not self.env.su and vals.get('requested_by', self.env.uid) != self.env.uid:
                raise AccessError(_('Only the current user may be the requester.'))
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('erp.procurement.request') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        if {'state', 'review_ids', 'review_round'} & vals.keys():
            raise AccessError(_('Use the request workflow actions.'))
        self._lock_conversion()
        if any(r.state != 'draft' for r in self):
            raise UserError(_('Only draft requests can be edited.'))
        if {'company_id', 'organization_id', 'requested_by', 'name'} & vals.keys():
            raise ValidationError(_('Request identity cannot be changed after creation.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        if any(r.state != 'draft' or r.review_ids for r in self):
            raise UserError(_('Only draft requests without review history can be deleted.'))
        return super().unlink()

    def _budget_service(self):
        return self.env['erp.budget.control.service']

    def _lock_budget_rows(self, extra_po_lines=None):
        controls = self.env['erp.budget.control']
        extra_po_lines = extra_po_lines or self.env['purchase.order.line']
        activities = self.mapped('line_ids.activity_id') | extra_po_lines.mapped('erp_budget_activity_id')
        linked_by_line = {}
        for line in self.mapped('line_ids'):
            linked = line._confirmed_po_lines() if line.request_id._is_budget_approved() else self.env['purchase.order.line']
            linked |= extra_po_lines.filtered(lambda po: po.erp_request_line_id == line)
            linked_by_line[line.id] = linked
            activities |= linked.mapped('erp_budget_activity_id')
        activities._lock_activity_key()
        for line in self.mapped('line_ids'):
            controls |= line._budget_controls()
            linked = linked_by_line[line.id]
            for po_line in linked:
                controls |= po_line._erp_budget_controls()
            family = 'erp.procurement.request.line:%s' % line.id
            historic = self.env['erp.budget.move'].sudo().search([('family_key', '=', family)]).mapped('control_id').with_env(self.env)
            historic.check_access('read')
            controls |= historic
        controls |= self.env['erp.budget.control.service']._carry_lock_controls(['erp.procurement.request.line:%s' % line.id for line in self.mapped('line_ids')])
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        return controls

    def _check_budget(self):
        # Simulate all lines in one savepoint so shared controls see the sum.
        # Roll back the candidate moves after a successful check, like upstream.
        self.ensure_one()
        self._lock_budget_rows()
        class SimulationComplete(Exception):
            pass
        try:
            with self.env.cr.savepoint():
                for line in self.line_ids:
                    line._reconcile_budget(pr_eligible=True, simulate=True)
                raise SimulationComplete()
        except SimulationComplete:
            pass

    def _auto_init(self):
        self.env.cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name='erp_procurement_request' AND column_name='review_round'")
        new_round = not self.env.cr.fetchone()
        result = super()._auto_init()
        self.env.cr.execute("SELECT to_regclass('erp_procurement_review')")
        old_reviews = self.env.cr.fetchone()[0]
        if new_round and old_reviews:
            # Existing approvals are one legacy round; do not invent actors/dates.
            self.env.cr.execute('UPDATE erp_procurement_request r SET review_round=1 WHERE EXISTS (SELECT 1 FROM erp_procurement_review v WHERE v.request_id=r.id)')
        return result

    def _manager_check(self):
        self.check_access('write')
        if not self.env.su and not self.env.user.has_group('erp_procurement.group_procurement_manager'):
            raise AccessError(_('Procurement management capability is required.'))

    def _is_budget_approved(self):
        self.ensure_one()
        return self.state in ('approved', 'done')

    def _current_reviews(self):
        self.ensure_one()
        return self.review_ids.filtered(lambda r: r.round_number == self.review_round).sorted(lambda r: (r.sequence, r.id))

    def _review_snapshot(self):
        self.ensure_one()
        return {'name': self.name, 'company_id': self.company_id.id, 'organization_id': self.organization_id.id, 'requester_id': self.requested_by.id, 'date_start': str(self.date_start), 'currency_id': self.currency_id.id, 'company_rate': self._request_company_rate(),
                'lines': [{'id': l.id, 'name': l.name, 'product_id': l.product_id.id, 'quantity': l.product_qty, 'estimate': l.estimated_cost, 'company_estimate': l._budget_estimated_cost(), 'period_id': l.period_id.id, 'fund_id': l.fund_id.id, 'analytic_id': l.analytic_id.id, 'account_id': l.account_id.id, 'activity_id': l.activity_id.id, 'dimension_ids': l.dimension_ids.ids} for l in self.line_ids]}

    def action_submit(self):
        self.ensure_one()
        self.check_access('write')
        with self.env.cr.savepoint():
            self._lock_conversion()
            if self.state != 'draft' or not self.line_ids:
                raise UserError(_('A draft request with lines is required.'))
            amount = sum(line._budget_estimated_cost() for line in self.line_ids)
            tiers = self.env['erp.procurement.tier'].search([('company_id', '=', self.company_id.id), ('kind', '=', 'request'), '|', ('minimum_amount', '=', 0), ('minimum_amount', '<', amount)])
            if not tiers:
                raise ValidationError(_('No approval tier is configured for this request.'))
            for tier in tiers:
                if not tier.reviewer_id.active or not tier.reviewer_id.has_group('erp_procurement.group_procurement_user'):
                    raise ValidationError(_('Every reviewer must have active procurement capability.'))
                self.with_user(tier.reviewer_id).with_context(allowed_company_ids=self.company_id.ids).check_access('write')
            self._check_budget()
            number = max(self.review_ids.mapped('round_number'), default=0) + 1
            token = _review_internal.set(True)
            try:
                self.env['erp.procurement.review'].sudo().create([{'request_id': self.id, 'reviewer_id': tier.reviewer_id.id, 'sequence': tier.sequence, 'round_number': number, 'request_snapshot': self._review_snapshot()} for tier in tiers])
            finally:
                _review_internal.reset(token)
            return super(ProcurementRequest, self).write({'state': 'to_approve', 'review_round': number})

    def action_approve(self):
        self.ensure_one()
        self.check_access('write')
        with self.env.cr.savepoint():
            self._lock_conversion()
            reviews = self._current_reviews()
            if self._is_budget_approved() and self.env.user in reviews.reviewer_id:
                return True
            if self.state != 'to_approve':
                raise UserError(_('Only submitted requests can be approved.'))
            pending = reviews.filtered(lambda review: review.state == 'pending')[:1]
            if pending and pending.reviewer_id != self.env.user and self.env.user in reviews.filtered(lambda r: r.state == 'approved').reviewer_id:
                return True
            if not pending or pending.reviewer_id != self.env.user:
                raise AccessError(_('Only the next assigned reviewer may approve.'))
            self._check_budget()
            token = _review_internal.set(True)
            try:
                pending.sudo().write({'state': 'approved'})
            finally:
                _review_internal.reset(token)
            if all(review.state == 'approved' for review in reviews):
                self._lock_budget_rows()
                for line in self.line_ids:
                    line._reconcile_budget(pr_eligible=True)
                return super(ProcurementRequest, self).write({'state': 'approved'})
        return True

    def action_reject(self):
        self.ensure_one()
        self.check_access('write')
        with self.env.cr.savepoint():
            self._lock_conversion()
            if self.state == 'rejected':
                return True
            if self.state not in ('to_approve', 'approved', 'done'):
                raise UserError(_('Only submitted or approved requests can be rejected.'))
            pending = self._current_reviews().filtered(lambda review: review.state == 'pending')[:1]
            if self.state == 'to_approve' and (not pending or pending.reviewer_id != self.env.user):
                raise AccessError(_('Only the next assigned reviewer may reject.'))
            if self._is_budget_approved() or self.verified_by_id:
                self._manager_check()
            if self._is_budget_approved() and any(line._confirmed_po_lines() for line in self.line_ids):
                raise UserError(_('Cancel linked purchase orders before rejecting this request.'))
            self._lock_budget_rows()
            if self._is_budget_approved():
                for line in self.line_ids:
                    line._reconcile_budget(pr_eligible=False)
            elif pending:
                token = _review_internal.set(True)
                try:
                    pending.sudo().write({'state': 'rejected'})
                finally:
                    _review_internal.reset(token)
            return super(ProcurementRequest, self).write({'state': 'rejected'})

    def action_done(self):
        self._manager_check()
        with self.env.cr.savepoint():
            self._lock_conversion()
            if any(r.state not in ('approved', 'done') for r in self):
                raise UserError(_('Only approved purchase requests may be marked done.'))
            # Upstream _valid_commit_state includes done: no release of capacity.
            return super(ProcurementRequest, self).write({'state': 'done'})

    def _check_reset_dependencies(self):
        lines = self.line_ids
        if self.env['purchase.order.line'].sudo().search_count([('erp_request_line_id', 'in', lines.ids), ('order_id.state', '!=', 'cancel')]):
            raise UserError(_('Cancel linked purchase orders before resetting the request.'))
        if self.env['purchase.requisition.line'].sudo().search_count([('erp_request_line_id', 'in', lines.ids), ('requisition_id.state', '!=', 'cancel')]):
            raise UserError(_('Cancel sourced requisitions before resetting the request.'))

    def action_reset(self):
        self.ensure_one()
        self.check_access('write')
        with self.env.cr.savepoint():
            self._lock_conversion()
            if self.state == 'draft':
                return True
            if self._is_budget_approved() or self.verified_by_id or self.requested_by != self.env.user:
                self._manager_check()
            self._check_reset_dependencies()
            self._lock_budget_rows()
            for line in self.line_ids:
                line._reconcile_budget(pr_eligible=False)
            return super(ProcurementRequest, self).write({'state': 'draft'})


class ProcurementRequestLine(models.Model):
    _name = 'erp.procurement.request.line'
    _description = 'Purchase Request Line'
    _check_company_auto = True

    request_id = fields.Many2one('erp.procurement.request', required=True, ondelete='cascade', check_company=True, index=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='request_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    name = fields.Char(required=True)
    product_id = fields.Many2one('product.product', ondelete='restrict', check_company=True)
    product_qty = fields.Float(required=True, default=1)
    estimated_cost = fields.Monetary(required=True)
    period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict')
    fund_id = fields.Many2one('erp.budget.fund', required=True, check_company=True, ondelete='restrict')
    analytic_id = fields.Many2one('account.analytic.account', required=True, check_company=True, ondelete='restrict')
    account_id = fields.Many2one('account.account', required=True, check_company=True, ondelete='restrict')
    activity_id = fields.Many2one('erp.budget.activity', check_company=True, ondelete='restrict')
    dimension_ids = fields.Many2many('account.analytic.account', 'erp_pr_line_dimension_rel', 'line_id', 'analytic_id', check_company=True)
    purchase_line_ids = fields.One2many('purchase.order.line', 'erp_request_line_id')

    @api.onchange('activity_id')
    def _onchange_budget_activity(self):
        if self.activity_id:
            self.account_id = self.activity_id.account_id

    @api.constrains('activity_id', 'account_id')
    def _check_activity_account(self):
        if any(line.activity_id and line.activity_id.account_id != line.account_id for line in self):
            raise ValidationError(_('The request budget account must match its activity.'))

    @api.constrains('product_qty', 'estimated_cost')
    def _check_amount(self):
        for line in self:
            if not math.isfinite(line.product_qty) or not math.isfinite(line.estimated_cost) or line.product_qty <= 0 or line.estimated_cost <= 0:
                raise ValidationError(_('Quantity and estimated cost must be positive.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('activity_id'):
                activity = self.env['erp.budget.activity'].browse(vals['activity_id'])
                activity.check_access('read')
                vals.setdefault('account_id', activity.account_id.id)
            parent = self.env['erp.procurement.request'].browse(vals.get('request_id')).exists()
            parent.check_access('write')
            parent._lock_conversion()
            if not parent or parent.state != 'draft':
                raise UserError(_('Lines may be created only on draft requests.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        self.request_id._lock_conversion()
        if 'request_id' in vals or any(line.request_id.state != 'draft' for line in self):
            raise UserError(_('Only draft request lines can be edited.'))
        if vals.get('activity_id') and 'account_id' not in vals:
            activity = self.env['erp.budget.activity'].browse(vals['activity_id'])
            activity.check_access('read')
            vals = dict(vals, account_id=activity.account_id.id)
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.request_id._lock_conversion()
        if any(line.request_id.state != 'draft' for line in self):
            raise UserError(_('Only draft request lines can be deleted.'))
        return super().unlink()

    def _budget_controls(self):
        self.ensure_one()
        self.check_access('read')
        self.request_id.check_access('read')
        if self.product_id and not self.activity_id:
            expense = self.product_id.with_company(self.company_id).product_tmpl_id.get_product_accounts().get('expense')
            if not expense or expense != self.account_id:
                raise ValidationError(_('The request account must match the product expense account.'))
        return self.env['erp.budget.control.service']._resolve(self.period_id, self.organization_id, self.analytic_id, self.fund_id, self.account_id, self.dimension_ids, activity=self.activity_id)

    def _confirmed_po_lines(self):
        self.ensure_one()
        # Include every linked line, then require the caller to read them all;
        # silently filtering hidden POs would restore the wrong commitment.
        all_lines = self.env['purchase.order.line'].sudo().search([('erp_request_line_id', '=', self.id)]).with_env(self.env)
        all_lines.check_access('read')
        return all_lines.filtered(lambda line: line.order_id.state in ('purchase', 'done'))

    def _reconcile_budget(self, pr_eligible, simulate=False):
        self.ensure_one()
        self.check_access('read')
        controls = self._budget_controls()
        po_lines = self.env['purchase.order.line'] if simulate or not self.request_id._is_budget_approved() else self._confirmed_po_lines()
        for po_line in po_lines:
            po_line._validate_request_budget_key()
        orders = [('purchase.order.line:%s' % line.id, line._erp_budget_controls(), line._erp_budget_amount(), fields.Date.to_date(line.order_id.date_order)) for line in po_lines]
        return self.env['erp.budget.control.service']._reconcile_purchase_multi(controls, self.request_id.date_start, 'erp.procurement.request.line:%s' % self.id, 'erp.procurement.request.line:%s' % self.id, self._budget_estimated_cost(), pr_eligible, orders)


class BudgetMoveProcurement(models.Model):
    _inherit = 'erp.budget.move'

    def _planning_fallback_key(self):
        self.ensure_one()
        model, separator, identifier = (self.source_key or '').partition(':')
        if separator and model == 'purchase.order.line' and identifier.isdigit():
            line = self.env[model].browse(int(identifier)).exists().erp_request_line_id
            if line:
                line.check_access('read')
                return {'period': line.period_id, 'organization': line.organization_id, 'analytic': line.analytic_id, 'fund': line.fund_id, 'account': line.account_id, 'dimensions': line.dimension_ids, 'activity': line.activity_id}
        return super()._planning_fallback_key()

    def _planning_source(self):
        self.ensure_one()
        model, separator, identifier = (self.source_key or '').partition(':')
        if separator and identifier.isdigit() and model in ('erp.procurement.request.line', 'purchase.order.line'):
            line = self.env[model].browse(int(identifier)).exists()
            if line:
                if model == 'purchase.order.line':
                    return line, line.erp_budget_account_id, line.erp_budget_activity_id
                return line, line.account_id, line.activity_id
        return super()._planning_source()


class BudgetActivityProcurement(models.Model):
    _inherit = 'erp.budget.activity'

    def _has_document_usage(self):
        if super()._has_document_usage():
            return True
        requests = self.env['erp.procurement.request.line'].sudo().search([('activity_id', 'in', self.ids)])
        if any(line.request_id.state != 'draft' for line in requests):
            return True
        orders = self.env['purchase.order.line'].sudo().search([('erp_budget_activity_id', 'in', self.ids)])
        if any(line.order_id.state in ('purchase', 'done') for line in orders):
            return True
        pr_keys = ['erp.procurement.request.line:%s' % line.id for line in requests]
        po_keys = ['purchase.order.line:%s' % line.id for line in orders]
        return bool(self.env['erp.budget.move'].sudo().search_count(['|', ('family_key', 'in', pr_keys), '|', ('source_key', 'in', po_keys), ('purchase_source_key', 'in', po_keys)]))
