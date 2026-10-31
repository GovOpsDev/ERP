"""Source Employee Advance KPI falls back to the shared analytic ceiling."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class AdvanceReservationKpi(models.Model):
    _inherit = 'erp.budget.kpi'

    advance_reservation = fields.Boolean(string='Employee Advance Reservation', help='This KPI tracks advance commitments under the shared analytic plan and fund allocation; it grants no separate KPI capacity.')

    def write(self, vals):
        if 'advance_reservation' in vals and any(kpi.advance_reservation != vals['advance_reservation'] for kpi in self):
            controls = self.env['erp.budget.control'].sudo().with_context(active_test=False).search([('kpi_id', 'in', self.ids)])
            controls.period_id._lock_plan_periods()
            if controls:
                raise UserError(_('The reservation classification of a KPI with controls cannot change.'))
        return super().write(vals)


class AdvanceReservationControl(models.Model):
    _inherit = 'erp.budget.control'

    @api.constrains('kpi_id', 'amount')
    def _check_advance_reservation_amount(self):
        if any(control.kpi_id.advance_reservation and control.amount for control in self):
            raise ValidationError(_('Advance KPI tracking controls must have zero separate capacity.'))


class AdvanceReservationPlanning(models.Model):
    _inherit = 'erp.budget.kpi.release.line'

    @api.constrains('control_id', 'amount', 'planning_ids')
    def _check_advance_planning(self):
        if any(line.control_id.kpi_id.advance_reservation and (line.amount or any(line.planning_ids.mapped('amount'))) for line in self):
            raise ValidationError(_('An advance KPI reservation does not add planning capacity.'))


class AdvanceReservationLedger(models.Model):
    _inherit = 'erp.budget.move'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            control = self.env['erp.budget.control'].browse(vals.get('control_id'))
            if control.kpi_id.advance_reservation and vals.get('move_type') not in ('advance_commitment', 'advance_reversal'):
                raise ValidationError(_('Only employee advance commitments may use the advance reservation KPI.'))
        return super().create(vals_list)
