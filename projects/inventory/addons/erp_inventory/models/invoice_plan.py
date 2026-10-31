"""One accepted work document per selected native purchase installment."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from .integration import compare_quantities


class AcceptancePlan(models.Model):
    _inherit = 'erp.inventory.acceptance'
    installment_id = fields.Many2one('erp.procurement.invoice.plan', check_company=True, ondelete='restrict')

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute("CREATE UNIQUE INDEX IF NOT EXISTS erp_acceptance_live_installment ON erp_inventory_acceptance(installment_id) WHERE installment_id IS NOT NULL AND state != 'cancel'")
        return result

    @api.constrains('installment_id', 'purchase_order_id')
    def _check_installment(self):
        for wa in self.filtered('installment_id'):
            if wa.installment_id.purchase_id != wa.purchase_order_id or wa.installment_id.invoice_type != 'installment':
                raise ValidationError(_('Acceptance must use a regular installment on its purchase order.'))

    def action_create_invoice(self):
        self.ensure_one()
        self._manager()
        with self.env.cr.savepoint():
            self._lock_workflow()
            if self.state != 'accept' or not self.installment_id:
                raise UserError(_('Accept a planned work document before creating its installment bill.'))
            action = self.installment_id.action_create_invoice()
            move = self.env['account.move'].browse(action['res_id'])
            if move.erp_acceptance_id and move.erp_acceptance_id != self:
                raise UserError(_('The installment already has a different acceptance.'))
            if move.state == 'draft':
                move.erp_acceptance_id = self
            elif move.erp_acceptance_id != self:
                raise UserError(_('Reset the posted installment bill before linking acceptance.'))
            return action


class PlannedAcceptance(models.Model):
    _inherit = 'erp.procurement.invoice.plan'
    acceptance_ids = fields.One2many('erp.inventory.acceptance', 'installment_id', readonly=True)

    def action_create_acceptance(self):
        self.ensure_one()
        self.check_access('read')
        self._lock_plan()
        existing = self.acceptance_ids.filtered(lambda w: w.state != 'cancel')
        if existing:
            existing.check_access('read')
            return {'type': 'ir.actions.act_window', 'res_model': 'erp.inventory.acceptance', 'res_id': existing.id, 'view_mode': 'form'}
        if not self._source_ready() or self.invoice_type != 'installment':
            raise UserError(_('Select a regular installment on a confirmed purchase order.'))
        lines = []
        last = self == self._regular_plans()[-1]
        for line in self.purchase_id.order_line.filtered(lambda l: not l.display_type and not l.is_downpayment):
            previous = self.env['erp.inventory.acceptance.line'].search([('purchase_line_id', '=', line.id), ('acceptance_id.state', '!=', 'cancel')])
            quantity = line.product_qty - sum(previous.mapped('quantity')) if last else line.product_qty * self.percent / 100
            if quantity > 0:
                lines.append((0, 0, {'purchase_line_id': line.id, 'quantity': quantity}))
        if not lines:
            raise UserError(_('No quantity remains for this acceptance.'))
        wa = self.env['erp.inventory.acceptance'].create({'company_id': self.company_id.id, 'organization_id': self.organization_id.id, 'purchase_order_id': self.purchase_id.id, 'installment_id': self.id, 'date_due': self.plan_date, 'line_ids': lines})
        return {'type': 'ir.actions.act_window', 'res_model': 'erp.inventory.acceptance', 'res_id': wa.id, 'view_mode': 'form'}

    def write(self, vals):
        if any(plan._siblings().acceptance_ids for plan in self):
            raise UserError(_('A plan with acceptance history retains its dates and percentages.'))
        return super().write(vals)

    def unlink(self):
        if any(plan._siblings().acceptance_ids for plan in self):
            raise UserError(_('A plan with acceptance history cannot be deleted.'))
        return super().unlink()

    def _invoice_values(self):
        vals = super()._invoice_values()
        accepted = self.acceptance_ids.filtered(lambda w: w.state == 'accept')
        if accepted:
            if len(accepted) != 1:
                raise ValidationError(_('One accepted work document is required per installment.'))
            quantities = {l.purchase_line_id.id: l.quantity for l in accepted.line_ids}
            for command in vals['invoice_line_ids']:
                line_values = command[2]
                if line_values.get('purchase_line_id') in quantities and not line_values.get('is_downpayment'):
                    line_values['quantity'] = quantities[line_values['purchase_line_id']]
            vals['erp_acceptance_id'] = accepted.id
        return vals
