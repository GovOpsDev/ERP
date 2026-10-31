"""Manager-owned source budget.move.adjustment with immutable ledger history."""
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_AUDIT = {'state', 'confirmed_by_id', 'confirmed_at', 'scope_version'}


class BudgetAdjustment(models.Model):
    _name = 'erp.budget.adjustment'
    _inherit = 'erp.budget.company.mixin'
    _description = 'Budget Actual Adjustment'
    _check_company_auto = True

    name = fields.Char(required=True, default='New', readonly=True, copy=False)
    description = fields.Text(required=True, string='Reason')
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict', index=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    currency_id = fields.Many2one(related='company_id.currency_id')
    line_ids = fields.One2many('erp.budget.adjustment.line', 'adjustment_id', copy=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Adjusted'), ('cancel', 'Cancelled')], required=True, default='draft', readonly=True, copy=False)
    confirmed_by_id = fields.Many2one('res.users', readonly=True, copy=False, ondelete='restrict')
    confirmed_at = fields.Datetime(readonly=True, copy=False)
    scope_version = fields.Integer(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any((_AUDIT - {'state'}) & vals.keys() or vals.get('state', 'draft') != 'draft' for vals in vals_list) or any('default_' + key in self.env.context for key in _AUDIT):
            raise AccessError(_('Budget adjustments begin in draft without approval history.'))
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('erp.budget.adjustment') or 'New'
        return super().create(vals_list)

    def _lock_document(self):
        self.check_access('write')
        if self:
            self.env.cr.execute('SELECT id FROM erp_budget_adjustment WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE erp_budget_adjustment SET scope_version = COALESCE(scope_version, 0) + 1 WHERE id IN %s', [tuple(sorted(self.ids))])

    def write(self, vals):
        if _AUDIT & vals.keys():
            raise AccessError(_('Use the budget adjustment workflow actions.'))
        if {'company_id', 'organization_id', 'name'} & vals.keys():
            raise ValidationError(_('An adjustment source identity cannot be changed.'))
        self._lock_document()
        if any(item.state != 'draft' or item.confirmed_at for item in self):
            raise UserError(_('Applied adjustment history is immutable; copy it for a new correction.'))
        return super().write(vals)

    def unlink(self):
        self._lock_document()
        if any(item.state != 'draft' or item.confirmed_at for item in self):
            raise UserError(_('Only unused draft adjustments can be deleted.'))
        return super().unlink()

    def _manager_check(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_budget.group_budget_manager'):
            raise AccessError(_('Budget management authority is required.'))

    def _lock_scope(self):
        lines = self.sudo().line_ids.with_env(self.env)
        lines.check_access('read')
        lines.activity_id._lock_activity_key()
        controls = self.env['erp.budget.control']
        for line in lines:
            controls |= line._budget_controls()
        if lines:
            old = self.env['erp.budget.move'].sudo().search([('family_key', 'in', [line._family_key() for line in lines])]).control_id.with_env(self.env)
            old.check_access('read')
            controls |= old
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
            controls.period_id._lock_plan_periods()
        self._lock_document()
        return controls

    def _reconcile_adjustment(self, effective):
        service = self.env['erp.budget.control.service']
        for line in self.line_ids:
            controls = line._budget_controls()
            key = line._family_key()
            amount = line.amount * (-1 if line.direction == 'release' else 1)
            actuals = [(key, controls, amount, self.date)] if effective else []
            service._reconcile_actual(controls, self.date, key, actuals, {key: ('erp.budget.adjustment:%s' % self.id, False)})

    def action_adjust(self):
        self._manager_check()
        if self.state == 'done':
            return True
        if self.state != 'draft' or not self.line_ids or not (self.description or '').strip():
            raise UserError(_('A draft adjustment with a reason and lines is required.'))
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._lock_scope()):
            self._reconcile_adjustment(True)
            values = {'state': 'done'}
            if not self.confirmed_at:
                values.update(confirmed_by_id=self.env.uid, confirmed_at=fields.Datetime.now())
            return super(BudgetAdjustment, self).write(values)

    def action_cancel(self):
        self._manager_check()
        if self.state == 'cancel':
            return True
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._lock_scope()):
            if self.state == 'done':
                self._reconcile_adjustment(False)
            return super(BudgetAdjustment, self).write({'state': 'cancel'})

    def action_draft(self):
        self._manager_check()
        self._lock_document()
        if self.state != 'cancel':
            raise UserError(_('Cancel the adjustment before resetting it.'))
        return super(BudgetAdjustment, self).write({'state': 'draft'})


class BudgetAdjustmentLine(models.Model):
    _name = 'erp.budget.adjustment.line'
    _description = 'Budget Actual Adjustment Line'
    _check_company_auto = True

    adjustment_id = fields.Many2one('erp.budget.adjustment', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='adjustment_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='adjustment_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    name = fields.Char(required=True)
    direction = fields.Selection([('consume', 'Consume'), ('release', 'Release')], required=True, default='consume')
    amount = fields.Monetary(required=True)
    period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict')
    fund_id = fields.Many2one('erp.budget.fund', required=True, check_company=True, ondelete='restrict')
    analytic_id = fields.Many2one('account.analytic.account', required=True, check_company=True, ondelete='restrict')
    account_id = fields.Many2one('account.account', required=True, check_company=True, ondelete='restrict')
    activity_id = fields.Many2one('erp.budget.activity', check_company=True, ondelete='restrict')
    dimension_ids = fields.Many2many('account.analytic.account', 'erp_adjustment_dimension_rel', 'line_id', 'analytic_id', check_company=True)

    @api.constrains('amount')
    def _check_amount(self):
        for line in self:
            if not math.isfinite(line.amount) or line.amount <= 0 or abs(line.amount - line.currency_id.round(line.amount)) > 1e-9:
                raise ValidationError(_('An adjustment amount must be positive and use company currency precision.'))

    def _check_editable(self):
        documents = self.adjustment_id
        documents._lock_document()
        if any(doc.state != 'draft' or doc.confirmed_at for doc in documents):
            raise UserError(_('Applied adjustment lines are immutable; copy the document for a new correction.'))

    @api.model_create_multi
    def create(self, vals_list):
        documents = self.env['erp.budget.adjustment'].browse([vals.get('adjustment_id') or self.env.context.get('default_adjustment_id') for vals in vals_list]).exists()
        documents._lock_document()
        if any(doc.state != 'draft' or doc.confirmed_at for doc in documents):
            raise UserError(_('New lines require an unused draft adjustment.'))
        for vals in vals_list:
            if {'company_id', 'organization_id', 'currency_id'} & vals.keys():
                raise AccessError(_('Adjustment line scope is derived from its document.'))
            if vals.get('activity_id') and not vals.get('account_id'):
                activity = self.env['erp.budget.activity'].browse(vals['activity_id'])
                activity.check_access('read')
                vals['account_id'] = activity.account_id.id
        return super().create(vals_list)

    def write(self, vals):
        if {'adjustment_id', 'company_id', 'organization_id', 'currency_id'} & vals.keys():
            raise AccessError(_('Adjustment line source identity is immutable.'))
        self._check_editable()
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()

    def _family_key(self):
        self.ensure_one()
        return 'erp.budget.adjustment.line:%s' % self.id

    def _budget_controls(self):
        self.ensure_one()
        self.check_access('read')
        return self.env['erp.budget.control.service']._resolve(self.period_id, self.organization_id, self.analytic_id, self.fund_id, self.account_id, self.dimension_ids, activity=self.activity_id)


class BudgetAdjustmentMove(models.Model):
    _inherit = 'erp.budget.move'

    def _source_amount_snapshot(self, values):
        model, separator, identifier = (values.get('source_key') or '').partition(':')
        if model == 'erp.budget.adjustment.line' and separator and identifier.isdigit():
            line = self.env[model].browse(int(identifier)).exists()
            if line:
                return {'scope': 'adjustment', 'amount': line.amount, 'direction': line.direction, 'date': str(line.adjustment_id.date), 'reason': line.adjustment_id.description, 'account_id': line.account_id.id, 'activity_id': line.activity_id.id, 'dimension_ids': sorted(line.dimension_ids.ids)}
        return super()._source_amount_snapshot(values)


class BudgetAdjustmentActivity(models.Model):
    _inherit = 'erp.budget.activity'

    def _has_document_usage(self):
        return super()._has_document_usage() or bool(self.env['erp.budget.adjustment.line'].sudo().search_count([('activity_id', 'in', self.ids)], limit=1))
