import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare
from .integration import lock_orders


class WorkAcceptance(models.Model):
    _name = 'erp.inventory.acceptance'
    _description = 'Purchase Work Acceptance'
    _check_company_auto = True
    _order = 'id desc'

    name = fields.Char(default='New', readonly=True, copy=False, required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True, ondelete='restrict')
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, index=True, ondelete='restrict')
    purchase_order_id = fields.Many2one('purchase.order', required=True, check_company=True, ondelete='restrict', index=True)
    partner_id = fields.Many2one(related='purchase_order_id.partner_id')
    acceptance_date = fields.Datetime(readonly=True, copy=False)
    requested_acceptance_date = fields.Datetime(string='Manual Acceptance Date', copy=False)
    responsible_id = fields.Many2one('res.users', string='Acceptance Representative', ondelete='restrict')
    state = fields.Selection([('draft', 'Draft'), ('accept', 'Accepted'), ('cancel', 'Cancelled')], default='draft', required=True, copy=False, index=True)
    line_ids = fields.One2many('erp.inventory.acceptance.line', 'acceptance_id')
    notes = fields.Text()
    _name_company_unique = models.Constraint('unique(company_id, name)', 'Acceptance number must be unique per company.')

    def _validate_source(self):
        for record in self:
            record.purchase_order_id.check_access('read')
            record.organization_id.check_access('read')
            if record.responsible_id and (record.responsible_id.share or record.company_id not in record.responsible_id.company_ids):
                raise ValidationError(_('The acceptance representative must belong to the document company.'))
            po = record.purchase_order_id
            if not record.organization_id.active or po.erp_request_organization_id != record.organization_id:
                raise ValidationError(_('The active organization must match the purchase request organization.'))
            if po.company_id != record.company_id or record.organization_id.company_id != record.company_id:
                raise ValidationError(_('Purchase order, organization and acceptance companies must match.'))
            if po.state not in ('purchase', 'done'):
                raise ValidationError(_('A confirmed purchase order is required.'))
            for line in record.line_ids:
                if line.purchase_line_id.order_id != po or not line.purchase_line_id.product_id or not math.isfinite(line.quantity) or line.quantity <= 0:
                    raise ValidationError(_('Every line requires a positive quantity and a product line from the purchase order.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company_id = vals.get('company_id', self.env.company.id)
            vals.setdefault('responsible_id', self.env.uid if company_id in self.env.user.company_ids.ids else False)
            if (vals.get('requested_acceptance_date') or self.env.context.get('default_requested_acceptance_date')) and not self.env.su and not self.env.user.has_group('erp_inventory.group_acceptance_manager'):
                raise AccessError(_('Acceptance management is required to select a manual accepted date.'))
            if vals.get('state', 'draft') != 'draft' or vals.get('acceptance_date'):
                raise AccessError(_('Acceptance must start in draft.'))
            company = vals.get('company_id', self.env.company.id)
            if not self.env.su and company not in self.env.companies.ids:
                raise AccessError(_('The company must be active.'))
            if vals.get('name', 'New') != 'New':
                raise AccessError(_('The acceptance number is generated automatically.'))
            vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code('erp.inventory.acceptance') or 'New'
        with self.env.cr.savepoint():
            records = super().create(vals_list)
            records._validate_source()
            return records

    def write(self, vals):
        self.check_access('write')
        if 'requested_acceptance_date' in vals and not self.env.su and not self.env.user.has_group('erp_inventory.group_acceptance_manager'):
            raise AccessError(_('Acceptance management is required to select a manual accepted date.'))
        if {'state', 'acceptance_date', 'name', 'company_id', 'organization_id', 'purchase_order_id'} & vals.keys():
            raise AccessError(_('Identity and state cannot be edited directly.'))
        lock_orders(self.mapped('purchase_order_id'))
        self.invalidate_recordset(['state'])
        if any(record.state != 'draft' for record in self):
            raise UserError(_('Only draft acceptances can be edited.'))
        with self.env.cr.savepoint():
            result = super().write(vals)
            self._validate_source()
            return result

    def unlink(self):
        self.check_access('unlink')
        lock_orders(self.mapped('purchase_order_id'))
        self.invalidate_recordset(['state'])
        if any(record.state != 'draft' for record in self):
            raise UserError(_('Only draft acceptances can be deleted.'))
        return super().unlink()

    def action_accept(self):
        self.check_access('write')
        if not self.env.user.has_group('erp_inventory.group_acceptance_manager'):
            raise AccessError(_('Acceptance manager capability is required.'))
        lock_orders(self.mapped('purchase_order_id'))
        self.invalidate_recordset()
        self._validate_source()
        if any(record.state != 'draft' or not record.line_ids for record in self):
            raise UserError(_('A draft acceptance with lines is required.'))
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        for po_line in self.mapped('line_ids.purchase_line_id'):
            accepted = self.env['erp.inventory.acceptance.line'].sudo().search([('purchase_line_id', '=', po_line.id), ('acceptance_id.state', '=', 'accept')])
            new_lines = self.mapped('line_ids').filtered(lambda line: line.purchase_line_id == po_line)
            quantity = sum((accepted | new_lines).mapped('quantity'))
            if float_compare(quantity, po_line.product_qty, precision_digits=precision) > 0:
                raise ValidationError(_('Accepted quantity cannot exceed the ordered quantity.'))
        for record in self:
            super(WorkAcceptance, record).write({'state': 'accept', 'acceptance_date': record.requested_acceptance_date or fields.Datetime.now()})
        return True

    def action_cancel(self):
        self.check_access('write')
        if not self.env.user.has_group('erp_inventory.group_acceptance_manager'):
            raise AccessError(_('Acceptance manager capability is required.'))
        lock_orders(self.mapped('purchase_order_id'))
        self.invalidate_recordset(['state'])
        if any(record.state != 'draft' for record in self):
            raise UserError(_('Only draft acceptances can be cancelled.'))
        return super(WorkAcceptance, self).write({'state': 'cancel'})


class WorkAcceptanceLine(models.Model):
    _name = 'erp.inventory.acceptance.line'
    _description = 'Purchase Work Acceptance Line'
    _check_company_auto = True

    acceptance_id = fields.Many2one('erp.inventory.acceptance', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='acceptance_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='acceptance_id.organization_id', store=True, index=True)
    purchase_line_id = fields.Many2one('purchase.order.line', required=True, check_company=True, ondelete='restrict', index=True)
    product_id = fields.Many2one(related='purchase_line_id.product_id')
    uom_id = fields.Many2one(related='purchase_line_id.uom_id')
    quantity = fields.Float(required=True, digits='Product Unit')

    @api.model_create_multi
    def create(self, vals_list):
        parents = self.env['erp.inventory.acceptance'].browse([v['acceptance_id'] for v in vals_list if v.get('acceptance_id')])
        parents.check_access('write')
        lock_orders(parents.mapped('purchase_order_id'))
        parents.invalidate_recordset(['state'])
        if any(p.state != 'draft' for p in parents):
            raise UserError(_('Only draft acceptance lines can be edited.'))
        with self.env.cr.savepoint():
            lines = super().create(vals_list)
            lines.mapped('acceptance_id')._validate_source()
            return lines

    def write(self, vals):
        self.check_access('write')
        lock_orders(self.mapped('acceptance_id.purchase_order_id'))
        self.mapped('acceptance_id').invalidate_recordset(['state'])
        if 'acceptance_id' in vals or any(line.acceptance_id.state != 'draft' for line in self):
            raise UserError(_('Only draft acceptance lines can be edited.'))
        with self.env.cr.savepoint():
            result = super().write(vals)
            self.mapped('acceptance_id')._validate_source()
            return result

    def unlink(self):
        self.check_access('unlink')
        lock_orders(self.mapped('acceptance_id.purchase_order_id'))
        self.mapped('acceptance_id').invalidate_recordset(['state'])
        if any(line.acceptance_id.state != 'draft' for line in self):
            raise UserError(_('Only draft acceptance lines can be deleted.'))
        return super().unlink()


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _check_accepted_work(self):
        lock_orders(self)
        if self.env['erp.inventory.acceptance'].sudo().search_count([('purchase_order_id', 'in', self.ids), ('state', '=', 'accept')]):
            raise UserError(_('A purchase order with accepted work cannot be cancelled or reset.'))

    def button_cancel(self):
        self._check_accepted_work()
        return super().button_cancel()

    def button_draft(self):
        self._check_accepted_work()
        return super().button_draft()
