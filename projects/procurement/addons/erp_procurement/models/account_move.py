from odoo import api, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _check_erp_budget_posting_ready(self):
        # Only inspect after ordinary document access has been checked. The
        # elevated search prevents a hidden linked PO line from bypassing this
        # guard; no linked-record details are disclosed by the error.
        if any(move.sudo().invoice_line_ids.mapped('purchase_line_id.erp_request_line_id') for move in self):
            self.check_access('write')
            raise UserError(_('Posting a bill linked to a budget-controlled request requires the Finance budget integration, which is not available yet.'))

    def _post(self, soft=True):
        self._check_erp_budget_posting_ready()
        return super()._post(soft=soft)

    def write(self, vals):
        if vals.get('state') == 'posted':
            with self.env.cr.savepoint():
                self._check_erp_budget_posting_ready()
                result = super().write(vals)
                self._check_erp_budget_posting_ready()
                return result
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        with self.env.cr.savepoint():
            moves = super().create(vals_list)
            posted = moves.filtered(lambda move: move.state == 'posted')
            if posted:
                posted._check_erp_budget_posting_ready()
            return moves


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        with self.env.cr.savepoint():
            lines = super().create(vals_list)
            posted = lines.filtered(lambda line: line.move_id.state == 'posted').mapped('move_id')
            if posted:
                posted._check_erp_budget_posting_ready()
            return lines

    def write(self, vals):
        if 'purchase_line_id' in vals or 'move_id' in vals:
            with self.env.cr.savepoint():
                result = super().write(vals)
                posted = self.filtered(lambda line: line.move_id.state == 'posted').mapped('move_id')
                if posted:
                    posted._check_erp_budget_posting_ready()
                return result
        return super().write(vals)
