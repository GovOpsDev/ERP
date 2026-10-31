import math

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class Contract(models.Model):
    _name = 'erp.contract.contract'
    _description = 'Purchase Contract'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict', index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict', index=True)
    partner_id = fields.Many2one('res.partner', required=True, ondelete='restrict')
    journal_id = fields.Many2one('account.journal', required=True, check_company=True, domain="[('type', '=', 'purchase')]", ondelete='restrict')
    active = fields.Boolean(default=True)
    commit_budget = fields.Boolean(default=False, readonly=True, copy=False)
    line_ids = fields.One2many('erp.contract.line', 'contract_id')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('commit_budget') or vals.get('active', True) is False:
                raise AccessError(_('Contracts must begin active without a budget commitment.'))
            if not self.env.su and vals.get('company_id', self.env.company.id) not in self.env.companies.ids:
                raise AccessError(_('The contract company must be active.'))
            unit = self.env['erp.organization.unit'].browse(vals.get('organization_id')).exists()
            if not unit:
                raise ValidationError(_('A contract organization is required.'))
            unit.check_access('read')
        with self.env.cr.savepoint():
            records = super().create(vals_list)
            records._validate_identity()
            return records

    def _validate_identity(self):
        for contract in self:
            contract.journal_id.check_access('read')
            if not contract.organization_id.active or contract.organization_id.company_id != contract.company_id or contract.journal_id.company_id != contract.company_id or contract.journal_id.type != 'purchase':
                raise ValidationError(_('An active organization and purchase journal must belong to the contract company.'))

    def _checked_lines(self):
        lines = self.env['erp.contract.line'].sudo().search([('contract_id', 'in', self.ids)]).with_env(self.env) if self else self.env['erp.contract.line']
        if lines:
            lines.check_access('read')
        return lines

    def _editable_configuration_fields(self):
        return set()

    def write(self, vals):
        self.check_access('write')
        if {'commit_budget', 'active', 'company_id', 'organization_id', 'partner_id', 'journal_id'} & vals.keys():
            raise AccessError(_('Use contract actions; source identity cannot be changed.'))
        if vals.keys() - self._editable_configuration_fields() and (any(contract.commit_budget for contract in self) or self._checked_lines()._has_budget_history()):
            raise UserError(_('Committed contract history is immutable; create a new contract for amendments.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        if any(contract.commit_budget or contract.line_ids.mapped('invoice_line_ids') for contract in self) or self._checked_lines()._has_budget_history():
            raise UserError(_('Committed or invoiced contracts cannot be deleted.'))
        return super().unlink()

    def _manager_check(self):
        self.check_access('write')
        if not self.env.su and not self.env.user.has_group('erp_contract.group_contract_manager'):
            raise AccessError(_('Contract management capability is required.'))

    def _lock_budget_rows(self):
        controls = self.env['erp.budget.control']
        lines = self._checked_lines()
        lines.mapped('activity_id')._lock_activity_key()
        for line in lines:
            controls |= line._budget_controls()
            old = self.env['erp.budget.move'].sudo().search([('family_key', '=', line._family_key())]).mapped('control_id').with_env(self.env)
            if old:
                old.check_access('read')
                controls |= old
        controls |= self.env['erp.budget.control.service']._carry_lock_controls([line._family_key() for line in lines])
        if controls:
            self.env.cr.execute('SELECT id FROM erp_budget_control WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(controls.ids))])
        return controls

    def action_commit_budget(self):
        self._manager_check()
        self._validate_identity()
        today = fields.Date.context_today(self)
        if any(not rec.active or rec.commit_budget or not rec.line_ids or any(line.date_end < today for line in rec.line_ids) for rec in self):
            raise UserError(_('An active contract with uncommitted lines is required.'))
        with self.env.cr.savepoint():
            self._lock_budget_rows()
            result = super(Contract, self).write({'commit_budget': True})
            for line in self.mapped('line_ids'):
                line._reconcile_budget()
            return result

    def action_close_budget(self):
        self._manager_check()
        if any(not rec.commit_budget for rec in self):
            raise UserError(_('The contract has no active budget commitment.'))
        with self.env.cr.savepoint():
            self._lock_budget_rows()
            result = super(Contract, self).write({'commit_budget': False})
            for line in self.mapped('line_ids'):
                line._reconcile_budget()
            return result

    def action_archive_contract(self):
        self._manager_check()
        if any(rec.commit_budget for rec in self):
            raise UserError(_('Close the budget commitment before archiving the contract.'))
        return super(Contract, self).write({'active': False})


class ContractLine(models.Model):
    _name = 'erp.contract.line'
    _description = 'Purchase Contract Line'
    _check_company_auto = True

    contract_id = fields.Many2one('erp.contract.contract', required=True, check_company=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='contract_id.organization_id', store=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    name = fields.Char(required=True)
    product_id = fields.Many2one('product.product', required=True, check_company=True, ondelete='restrict')
    uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict')
    quantity = fields.Float(required=True, default=1)
    price_unit = fields.Monetary(required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    period_id = fields.Many2one('erp.budget.period', required=True, check_company=True, ondelete='restrict')
    fund_id = fields.Many2one('erp.budget.fund', required=True, check_company=True, ondelete='restrict')
    analytic_id = fields.Many2one('account.analytic.account', required=True, check_company=True, ondelete='restrict')
    account_id = fields.Many2one('account.account', required=True, check_company=True, ondelete='restrict')
    activity_id = fields.Many2one('erp.budget.activity', check_company=True, ondelete='restrict')
    dimension_ids = fields.Many2many('account.analytic.account', 'erp_contract_line_dimension_rel', 'line_id', 'analytic_id', check_company=True)
    invoice_line_ids = fields.One2many('account.move.line', 'erp_contract_line_id', readonly=True)

    @api.onchange('activity_id')
    def _onchange_budget_activity(self):
        if self.activity_id:
            self.account_id = self.activity_id.account_id

    @api.constrains('activity_id', 'account_id')
    def _check_activity_account(self):
        if any(line.activity_id and line.activity_id.account_id != line.account_id for line in self):
            raise ValidationError(_('The contract budget account must match its activity.'))

    @api.constrains('quantity', 'price_unit', 'date_start', 'date_end')
    def _check_values(self):
        for line in self:
            if not math.isfinite(line.quantity) or not math.isfinite(line.price_unit) or line.quantity <= 0 or line.price_unit <= 0 or line.date_start > line.date_end:
                raise ValidationError(_('Contract line quantity, price and dates must be valid.'))

    def _family_key(self):
        self.ensure_one()
        return 'erp.contract.line:%s' % self.id

    def _has_budget_history(self):
        keys = [line._family_key() for line in self]
        return bool(keys and self.env['erp.budget.move'].sudo().search_count([('family_key', 'in', keys)], limit=1))

    def _budget_controls(self):
        self.ensure_one()
        self.check_access('read')
        self.contract_id.check_access('read')
        expense = self.product_id.with_company(self.company_id).product_tmpl_id.get_product_accounts().get('expense')
        if not self.activity_id and (not expense or expense != self.account_id):
            raise ValidationError(_('The contract account must match the product expense account.'))
        return self.env['erp.budget.control.service']._resolve(self.period_id, self.organization_id, self.analytic_id, self.fund_id, self.account_id, self.dimension_ids, activity=self.activity_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('activity_id'):
                activity = self.env['erp.budget.activity'].browse(vals['activity_id'])
                activity.check_access('read')
                vals.setdefault('account_id', activity.account_id.id)
            contract = self.env['erp.contract.contract'].browse(vals.get('contract_id')).exists()
            contract.check_access('write')
            if not contract or not contract.active or contract.commit_budget:
                raise UserError(_('Lines require an active contract with budget commitment disabled.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        linked = self.env['account.move.line'].sudo().search_count([('erp_contract_line_id', 'in', self.ids)], limit=1) if self else 0
        if 'contract_id' in vals or linked or self._has_budget_history() or any(not line.contract_id.active or line.contract_id.commit_budget for line in self):
            raise UserError(_('Contract lines cannot be changed while committed, archived or invoiced.'))
        if vals.get('activity_id') and 'account_id' not in vals:
            activity = self.env['erp.budget.activity'].browse(vals['activity_id'])
            activity.check_access('read')
            vals = dict(vals, account_id=activity.account_id.id)
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        linked = self.env['account.move.line'].sudo().search_count([('erp_contract_line_id', 'in', self.ids)], limit=1) if self else 0
        if linked or self._has_budget_history() or any(line.contract_id.commit_budget for line in self):
            raise UserError(_('Committed or invoiced contract lines cannot be deleted.'))
        return super().unlink()

    def _reconcile_budget(self):
        self.ensure_one()
        controls = self._budget_controls()
        lines = self.env['account.move.line'].sudo().search([('erp_contract_line_id', '=', self.id), ('move_id.state', '=', 'posted')]).with_env(self.env)
        if lines:
            lines.check_access('read')
            lines.mapped('move_id').check_access('read')
        remaining = self.quantity
        billed = refunded = 0.0
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        actuals, provenance, refunded_by_bill = [], {}, {}
        for line in lines.sorted(key=lambda row: row.id):
            move = line.move_id
            if move.move_type not in ('in_invoice', 'in_refund') or move.company_id != self.company_id or move.partner_id != self.contract_id.partner_id or move.currency_id != self.currency_id:
                raise ValidationError(_('A contract bill must match the vendor, company and company currency.'))
            original_distribution = {','.join(map(str, sorted({self.analytic_id.id, *self.dimension_ids.ids}))): 100}
            expected_distribution = self.env['erp.budget.control.service']._source_distribution(self._family_key(), controls, original_distribution, move.date)
            expected = set(map(int, next(iter(expected_distribution)).split(',')))
            dist = line.analytic_distribution or {}
            if line.purchase_line_id or (not self.activity_id and line.account_id != self.account_id) or len(dist) != 1 or any(set(map(int, key.split(','))) != expected or value != 100 for key, value in dist.items()):
                raise ValidationError(_('Contract bills must use the contract key and cannot also link a purchase line.'))
            if line.product_id != self.product_id or not line.product_uom_id or not all(math.isfinite(x) and x > 0 for x in (line.quantity, line.price_unit, line.price_subtotal)):
                raise ValidationError(_('A positive quantity and matching product are required.'))
            if line.product_uom_id.parent_path.split('/')[0] != self.uom_id.parent_path.split('/')[0]:
                raise ValidationError(_('Bill and contract units must have the same reference unit.'))
            qty = line.product_uom_id._compute_quantity(line.quantity, self.uom_id, round=False)
            if move.move_type == 'in_refund':
                original = move.reversed_entry_id
                if not original or original.state != 'posted' or original.move_type != 'in_invoice' or move.currency_id != original.currency_id:
                    raise ValidationError(_('A contract refund must reference a posted bill.'))
                original.check_access('read')
                previous_qty, previous_amount = refunded_by_bill.get(original.id, (0.0, 0.0))
                refunded_by_bill[original.id] = (previous_qty + qty, previous_amount + line.price_subtotal)
                refunded += qty
                sign = -1
                if float_compare(self.currency_id.round(remaining * self.price_unit), 0, precision_rounding=self.currency_id.rounding) > 0:
                    remaining = min(self.quantity, remaining + qty)
            else:
                billed += qty
                sign = 1
                remaining = max(0.0, remaining - qty)
            amount = line._erp_actual_budget_amount()
            if not float_is_zero(amount, precision_rounding=self.currency_id.rounding):
                key = 'account.move.line:%s' % line.id
                actuals.append((key, controls, amount, move.date))
                provenance[key] = ('account.move:%s' % move.id, self._family_key())
        for bill_id, (qty, amount) in refunded_by_bill.items():
            originals = lines.filtered(lambda line: line.move_id.id == bill_id and line.move_id.move_type == 'in_invoice')
            original_qty = sum(line.product_uom_id._compute_quantity(line.quantity, self.uom_id, round=False) for line in originals)
            if float_compare(qty, original_qty, precision_digits=precision) > 0 or float_compare(amount, sum(originals.mapped('price_subtotal')), precision_rounding=self.currency_id.rounding) > 0:
                raise ValidationError(_('Contract refunds cannot exceed the original bill.'))
        if float_compare(billed - refunded, self.quantity, precision_digits=precision) > 0 or float_compare(billed - refunded, 0, precision_digits=precision) < 0:
            raise ValidationError(_('Contract invoiced quantity must remain within the contract quantity.'))
        amount = self._erp_budget_amount(remaining)
        return self.env['erp.budget.control.service']._reconcile_purchase_multi(controls, self.date_start, self._family_key(), self._family_key(), amount, self.contract_id.active and self.contract_id.commit_budget, [], actuals, provenance, primary_type='contract_commitment')

    def _invoice_analytic_distribution(self, date=None):
        self.ensure_one()
        original = {','.join(map(str, sorted({self.analytic_id.id, *self.dimension_ids.ids}))): 100}
        return self.env['erp.budget.control.service']._source_distribution(self._family_key(), self._budget_controls(), original, date or self.date_start, actual=bool(date))


class BudgetMoveContract(models.Model):
    _inherit = 'erp.budget.move'

    def _planning_source(self):
        self.ensure_one()
        model, separator, identifier = (self.source_key or '').partition(':')
        if separator and model == 'erp.contract.line' and identifier.isdigit():
            line = self.env[model].browse(int(identifier)).exists()
            if line:
                return line, line.account_id, line.activity_id
        return super()._planning_source()


class BudgetActivityContract(models.Model):
    _inherit = 'erp.budget.activity'

    def _has_document_usage(self):
        if super()._has_document_usage():
            return True
        lines = self.env['erp.contract.line'].sudo().search([('activity_id', 'in', self.ids)])
        return any(line.contract_id.commit_budget for line in lines) or lines._has_budget_history()
