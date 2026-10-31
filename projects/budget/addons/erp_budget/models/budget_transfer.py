"""Reviewed transfers use allocation/planning successors, never a second cap."""
import math
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .budget_release import _planning_internal, _tier_approved

_transfer_internal = ContextVar('budget_transfer_internal', default=False)


class BudgetTransfer(models.Model):
    _name = 'erp.budget.transfer'
    _description = 'Reviewed Budget Transfer'
    _check_company_auto = True

    name = fields.Char(required=True)
    allocation_id = fields.Many2one('erp.budget.allocation', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='allocation_id.company_id', store=True, index=True)
    period_id = fields.Many2one(related='allocation_id.period_id', store=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict')
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([('draft', 'Draft'), ('submit', 'Submitted'), ('done', 'Transferred'), ('cancel', 'Cancelled'), ('reversed', 'Reversed')], default='draft', required=True, readonly=True)
    line_ids = fields.One2many('erp.budget.transfer.line', 'transfer_id')
    revision_id = fields.Many2one('erp.budget.allocation.revision', readonly=True, check_company=True, ondelete='restrict')
    approval_id = fields.Many2one('erp.budget.kpi.release', readonly=True, check_company=True, ondelete='restrict')
    reversal_of_id = fields.Many2one('erp.budget.transfer', readonly=True, check_company=True, ondelete='restrict')
    planning_ids = fields.Many2many('erp.budget.kpi.release', compute='_compute_planning')
    review_ids = fields.One2many(related='approval_id.review_ids')
    transferred_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    transferred_at = fields.Datetime(readonly=True)
    _reversal_unique = models.Constraint('unique(reversal_of_id)', 'A transfer has one reversal document.')

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'state', 'revision_id', 'approval_id', 'reversal_of_id', 'transferred_by_id', 'transferred_at', 'company_id', 'period_id'}
        if not _transfer_internal.get() and (any(protected & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in protected)):
            raise AccessError(_('Transfer history is assigned by its workflow.'))
        result = super().create(vals_list)
        result._check_scope()
        return result

    def _check_scope(self):
        for doc in self:
            doc.allocation_id.check_access('write')
            doc.organization_id.check_access('read')
            if doc.company_id not in self.env.companies or doc.organization_id.company_id != doc.company_id or not doc.organization_id.active:
                raise AccessError(_('Transfer organization must belong to the active company.'))

    def write(self, vals):
        self.check_access('write')
        for doc in self:
            doc._lock_scope()
        if not _transfer_internal.get() and (set(vals) - {'name', 'line_ids'} or any(doc.state != 'draft' for doc in self)):
            raise AccessError(_('Only draft transfer descriptions and items may be edited.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Transfer documents are retained for audit.'))

    def _lock_scope(self):
        self.ensure_one()
        self._check_scope()
        self.allocation_id._lock_revision_scope()
        self.invalidate_recordset()
        all_lines = self.env['erp.budget.transfer.line'].sudo().search([('transfer_id', '=', self.id)])
        if set(all_lines.ids) != set(self.line_ids.ids):
            raise AccessError(_('Access to every transfer item is required.'))
        controls = self.line_ids.mapped('source_control_id') | self.line_ids.mapped('destination_control_id')
        controls.check_access('write')
        return controls

    def _deltas(self):
        fund, analytic = {}, {}
        for item in self.line_ids:
            item._validate_item()
            for line, control, sign in ((item.source_id, item.source_control_id, -1), (item.destination_id, item.destination_control_id, 1)):
                fund[line.id] = fund.get(line.id, 0) + sign * item.amount
                analytic[control.id] = analytic.get(control.id, 0) + sign * item.amount
        return fund, analytic

    def _validate_transfer(self):
        self.ensure_one()
        if self.allocation_id.state != 'done' or not self.line_ids:
            raise UserError(_('A completed allocation and transfer items are required.'))
        if self.organization_id != self.line_ids[0].source_id.organization_id:
            raise ValidationError(_('The submitting organization must own the first source dimension.'))
        fund, analytic = self._deltas()
        for model, changes in (('erp.budget.allocation.line', fund), ('erp.budget.control', analytic)):
            for identifier, delta in changes.items():
                record = self.env[model].browse(identifier)
                control = record.control_id if model == 'erp.budget.allocation.line' else record
                control.check_access('write')
                if control.state != 'open':
                    raise UserError(_('Transfer controls must remain open.'))
                self.env['erp.budget.move'].flush_model(['control_id', 'amount'])
                self.env.cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [control.id])
                if float_compare(control.amount + delta, max(0, self.env.cr.fetchone()[0]), precision_rounding=self.currency_id.rounding) < 0:
                    raise UserError(_('A transfer cannot remove consumed capacity.'))
        return fund, analytic

    def action_submit(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state != 'draft':
            raise UserError(_('Only draft transfers may be submitted.'))
        fund, analytic = self._validate_transfer()
        with self.env.cr.savepoint():
            revision = self.env['erp.budget.allocation.revision'].browse(self.allocation_id.action_prepare_allocation_revision()['res_id'])
            revision.write({'reason': self.name})
            for row in revision.line_ids:
                row.write({'amount': row.base_amount + fund.get(row.allocation_line_id.id, 0)})
            affected = (self.line_ids.mapped('source_control_id') | self.line_ids.mapped('destination_control_id')).mapped('analytic_id')
            releases = self.env['erp.budget.kpi.release'].search([('plan_line_id.plan_id', '=', self.allocation_id.plan_id.id), ('state', '=', 'done')])
            for analytic_account in releases.plan_line_id.analytic_id:
                effective = releases.filtered(lambda release: release.plan_line_id.analytic_id == analytic_account)
                if len(effective) != 1:
                    raise UserError(_('Prepare canonical reviewed planning for every transferred analytic first.'))
                planning = self.env['erp.budget.kpi.release'].browse(effective.action_prepare_revision(revision.id)['res_id'])
                for row in planning.line_ids:
                    delta = analytic.get(row.control_id.id, 0)
                    if delta:
                        row.write({'amount': row.amount + delta})
                        # One full-year slice can follow the amount automatically.
                        # Multiple date/KPI slices require an explicit reviewed edit.
                planning.write({'released_amount': sum(planning.line_ids.mapped('amount'))})
            token = _transfer_internal.set(True)
            try:
                proxy = self.env['erp.budget.kpi.release'].create({'name': self.name, 'plan_line_id': releases.filtered(lambda release: release.plan_line_id.analytic_id == self.line_ids[0].source_id.analytic_id).plan_line_id.id, 'released_amount': 0, 'transfer_id': self.id})
                self.write({'revision_id': revision.id, 'approval_id': proxy.id, 'state': 'submit'})
            finally:
                _transfer_internal.reset(token)
            proxy.action_submit()
        return True

    @api.depends('revision_id')
    def _compute_planning(self):
        for doc in self:
            doc.planning_ids = doc._planning() if doc.revision_id else self.env['erp.budget.kpi.release']

    def _planning(self):
        return self.env['erp.budget.kpi.release'].search([('allocation_revision_id', '=', self.revision_id.id)])

    def action_submit_planning(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state != 'submit':
            raise UserError(_('The transfer must be submitted.'))
        for planning in self._planning().filtered(lambda release: release.state == 'draft'):
            planning.action_submit()
        return True

    def action_approve(self):
        self.ensure_one()
        self.check_access('read')
        return self.approval_id.action_approve()

    def action_reject(self):
        self.ensure_one()
        self.check_access('read')
        return self.approval_id.action_reject()

    def action_transfer(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state in ('done', 'reversed'):
            return True
        if self.state != 'submit' or self.approval_id.state != 'approved':
            raise UserError(_('The transfer must complete every transfer review.'))
        fund, analytic = self._validate_transfer()
        for row in self.revision_id.line_ids:
            if float_compare(row.amount, row.base_amount + fund.get(row.allocation_line_id.id, 0), precision_rounding=self.currency_id.rounding):
                raise UserError(_('The allocation successor differs from the reviewed transfer.'))
        planning = self._planning()
        for control_id, delta in analytic.items():
            control = self.env['erp.budget.control'].browse(control_id)
            row = planning.line_ids.filtered(lambda row: row.control_id == control)
            if len(row) != 1 or float_compare(row.amount, control.amount + delta, precision_rounding=self.currency_id.rounding):
                raise UserError(_('The planning successor differs from the transfer items.'))
        token = _transfer_internal.set(True)
        try:
            with self.env.cr.savepoint():
                self.revision_id.action_activate()
                self.write({'state': 'done', 'transferred_by_id': self.env.user.id, 'transferred_at': fields.Datetime.now()})
                if self.reversal_of_id:
                    self.reversal_of_id.write({'state': 'reversed'})
        finally:
            _transfer_internal.reset(token)
        return True

    def action_cancel(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state not in ('draft', 'submit'):
            raise UserError(_('Only unapplied transfers may be cancelled.'))
        token = _transfer_internal.set(True)
        planning_token = _planning_internal.set(True)
        try:
            with self.env.cr.savepoint():
                if self.revision_id:
                    self.revision_id.action_cancel()
                if self.approval_id:
                    self.approval_id.write({'state': 'cancel'})
                return self.write({'state': 'cancel'})
        finally:
            _planning_internal.reset(planning_token)
            _transfer_internal.reset(token)

    def action_draft(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        if self.state != 'cancel':
            raise UserError(_('Only cancelled transfers may be reset.'))
        token = _transfer_internal.set(True)
        try:
            return self.write({'state': 'draft', 'revision_id': False, 'approval_id': False})
        finally:
            _transfer_internal.reset(token)

    def action_reverse(self):
        self.ensure_one()
        self.check_access('write')
        self._lock_scope()
        existing = self.search([('reversal_of_id', '=', self.id)])
        if existing:
            return {'type': 'ir.actions.act_window', 'res_model': self._name, 'view_mode': 'form', 'res_id': existing.id}
        if self.state != 'done' or self.reversal_of_id:
            raise UserError(_('Only an applied original transfer may be reversed.'))
        token = _transfer_internal.set(True)
        try:
            reverse = self.create({'name': _('Reverse %s') % self.name, 'allocation_id': self.allocation_id.id, 'organization_id': self.line_ids[0].destination_id.organization_id.id, 'reversal_of_id': self.id, 'line_ids': [(0, 0, {'source_id': item.destination_id.id, 'destination_id': item.source_id.id, 'source_control_id': item.destination_control_id.id, 'destination_control_id': item.source_control_id.id, 'amount': item.amount}) for item in self.line_ids]})
        finally:
            _transfer_internal.reset(token)
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'view_mode': 'form', 'res_id': reverse.id}


class BudgetTransferLine(models.Model):
    _name = 'erp.budget.transfer.line'
    _description = 'Budget Transfer Item'
    _check_company_auto = True

    transfer_id = fields.Many2one('erp.budget.transfer', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='transfer_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    source_id = fields.Many2one('erp.budget.allocation.line', required=True, check_company=True, ondelete='restrict')
    destination_id = fields.Many2one('erp.budget.allocation.line', required=True, check_company=True, ondelete='restrict')
    source_control_id = fields.Many2one('erp.budget.control', required=True, check_company=True, ondelete='restrict')
    destination_control_id = fields.Many2one('erp.budget.control', required=True, check_company=True, ondelete='restrict')
    amount = fields.Monetary(required=True)

    @api.constrains('source_id', 'destination_id', 'source_control_id', 'destination_control_id', 'amount', 'transfer_id')
    def _validate_item(self):
        for item in self:
            if item.source_id == item.destination_id or not math.isfinite(item.amount) or item.amount <= 0 or abs(item.amount - item.currency_id.round(item.amount)) > 1e-9:
                raise ValidationError(_('Distinct allocation dimensions and a positive precise amount are required.'))
            for line, control in ((item.source_id, item.source_control_id), (item.destination_id, item.destination_control_id)):
                line.check_access('write')
                control.check_access('write')
                if line.allocation_id != item.transfer_id.allocation_id or control.period_id != item.transfer_id.period_id or control.company_id != item.company_id or control.level != 'analytic' or control.organization_id != line.organization_id or control.analytic_id != line.analytic_id:
                    raise ValidationError(_('Transfer keys must match their allocation, company, organization and analytic.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            doc = self.env['erp.budget.transfer'].browse(vals.get('transfer_id'))
            doc.check_access('write')
            doc._lock_scope()
            if doc.state != 'draft':
                raise AccessError(_('Only draft transfer items may be added.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        for doc in self.mapped('transfer_id'):
            doc._lock_scope()
        if set(vals) - {'source_id', 'destination_id', 'source_control_id', 'destination_control_id', 'amount'} or any(item.transfer_id.state != 'draft' for item in self):
            raise AccessError(_('Only draft transfer items may be edited.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        for doc in self.mapped('transfer_id'):
            doc._lock_scope()
        if any(item.transfer_id.state != 'draft' for item in self):
            raise AccessError(_('Only draft transfer items may be removed.'))
        return super().unlink()


class BudgetTransferApproval(models.Model):
    _inherit = 'erp.budget.kpi.release'

    transfer_id = fields.Many2one('erp.budget.transfer', readonly=True, check_company=True, ondelete='restrict')

    @api.model_create_multi
    def create(self, vals_list):
        if not _transfer_internal.get() and (any('transfer_id' in vals for vals in vals_list) or 'default_transfer_id' in self.env.context):
            raise AccessError(_('Transfer reviews are created by submission.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _transfer_internal.get() and 'transfer_id' in vals:
            raise AccessError(_('The transfer review origin is immutable.'))
        return super().write(vals)

    def _lock_controls(self):
        self.ensure_one()
        if self.transfer_id:
            return self.transfer_id._lock_scope()
        return super()._lock_controls()

    def action_submit(self):
        self.ensure_one()
        if not self.transfer_id:
            return super().action_submit()
        self.check_access('write')
        controls = self._lock_controls()
        if self.state != 'draft' or self.line_ids or self.released_amount:
            raise UserError(_('A draft transfer approval cannot authorize capacity.'))
        self.transfer_id._validate_transfer()
        tiers = self.env['erp.budget.kpi.tier'].search([('company_id', '=', self.company_id.id), ('organization_id', '=', self.transfer_id.organization_id.id), ('kind', '=', 'transfer'), ('active', '=', True)], order='sequence,id')
        return self._submit_tiers(tiers, controls)

    def action_release(self):
        self.ensure_one()
        if not self.transfer_id:
            return super().action_release()
        self.check_access('write')
        self._lock_controls()
        if not _tier_approved.get() or self.state != 'submit':
            raise AccessError(_('Transfer review tiers must approve the document.'))
        token = _planning_internal.set(True)
        try:
            return self.write({'state': 'approved'})
        finally:
            _planning_internal.reset(token)

    def action_reject(self):
        result = super().action_reject()
        if self.transfer_id:
            self.transfer_id.action_cancel()
        return result

    def action_prepare_revision(self, allocation_revision_id=None):
        if self.transfer_id:
            raise AccessError(_('Transfer approvals do not have planning capacity.'))
        return super().action_prepare_revision(allocation_revision_id)


class BudgetTransferApprovalLine(models.Model):
    _inherit = 'erp.budget.kpi.release.line'

    @api.model_create_multi
    def create(self, vals_list):
        if any(self.env['erp.budget.kpi.release'].browse(vals.get('release_id')).transfer_id for vals in vals_list):
            raise AccessError(_('Transfer approvals cannot contain released capacity.'))
        return super().create(vals_list)


class BudgetTransferAllocationRevision(models.Model):
    _inherit = 'erp.budget.allocation.revision'

    def action_activate(self):
        if not _transfer_internal.get() and self.env['erp.budget.transfer'].search_count([('revision_id', 'in', self.ids)]):
            raise AccessError(_('Activate transfer successors through the approved transfer document.'))
        return super().action_activate()
