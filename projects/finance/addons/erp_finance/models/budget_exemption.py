from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class BudgetExemptionJournal(models.Model):
    _inherit = 'account.journal'

    erp_budget_exempt = fields.Boolean(string='Exclude Direct Entries from Budget', groups='account.group_account_manager', help='Default for new direct accounting documents. Controlled purchase and contract bills still require Budget reconciliation.')


class BudgetExemptionMove(models.Model):
    _inherit = 'account.move'

    erp_budget_exempt = fields.Boolean(string='Exclude from Budget', copy=True)

    def _check_budget_exemption_value(self, journal, value):
        if bool(value) == bool(journal.sudo().erp_budget_exempt):
            return
        if not self.env.su and not (self.env.user.has_group('account.group_account_manager') or self.env.user.has_group('erp_budget.group_budget_manager')):
            raise AccessError(_('Budget or accounting management authority is required to override the journal budget policy.'))

    @api.model_create_multi
    def create(self, vals_list):
        values_list, explicit = [], []
        for values in vals_list:
            values = dict(values)
            flag_given = 'erp_budget_exempt' in values or 'default_erp_budget_exempt' in self.env.context
            journal = self.env['account.journal'].browse(values.get('journal_id') or self.env.context.get('default_journal_id')).exists()
            if flag_given:
                value = values.get('erp_budget_exempt', self.env.context.get('default_erp_budget_exempt'))
                self._check_budget_exemption_value(journal, value)
            elif journal:
                values['erp_budget_exempt'] = journal.sudo().erp_budget_exempt
            explicit.append(flag_given)
            values_list.append(values)
        with self.env.cr.savepoint():
            moves = super().create(values_list)
            for move, flag_given in zip(moves, explicit):
                if not flag_given and move.erp_budget_exempt != move.journal_id.sudo().erp_budget_exempt:
                    move.write({'erp_budget_exempt': move.journal_id.sudo().erp_budget_exempt})
            return moves

    def write(self, vals):
        if 'erp_budget_exempt' in vals:
            if any(move.state == 'posted' for move in self):
                raise UserError(_('Reset the accounting document before changing its budget policy.'))
            for move in self:
                journal = self.env['account.journal'].browse(vals.get('journal_id')) if vals.get('journal_id') else move.journal_id
                move._check_budget_exemption_value(journal, vals['erp_budget_exempt'])
        return super().write(vals)

    @api.onchange('journal_id')
    def _onchange_budget_exempt(self):
        for move in self:
            move.erp_budget_exempt = move.journal_id.sudo().erp_budget_exempt

    def _post(self, soft=True):
        exempt = self.filtered('erp_budget_exempt')
        if exempt._erp_finance_requests() or ('erp_contract_line_id' in self.env['account.move.line']._fields and exempt._erp_contract_lines()):
            raise UserError(_('A purchase or contract commitment must be reconciled; use a separate direct entry for an exempt accounting adjustment.'))
        return super()._post(soft=soft)
