"""Native withholding payments for employee receipts and advance clearings.

The supplier owns the tax certificate; the employee owns the payable. Withhold
before settling an advance so the unused withholding cash remains returnable.
"""
from contextvars import ContextVar
from contextlib import contextmanager

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from .expense import _expense_access

_withholding_workflow = ContextVar('erp_expense_withholding', default=False)


class ExpenseWithholding(models.Model):
    _inherit = 'hr.expense'

    erp_withholding_payment_ids = fields.One2many('account.payment', 'erp_withholding_expense_id', readonly=True, string='Withholding Payments')
    erp_tax_invoice_reference = fields.Char(string='Supplier Tax Invoice Reference')
    erp_tax_invoice_date = fields.Date(string='Supplier Tax Invoice Date')

    def _check_withholding_vendor(self):
        for expense in self.filtered(lambda item: item.tax_ids.filtered('is_withholding_tax')):
            if not expense.vendor_id or expense.vendor_id.company_id and expense.vendor_id.company_id != expense.company_id:
                raise ValidationError(_('Withholding requires a supplier belonging to this company or shared across companies.'))
            if expense.erp_is_advance:
                raise ValidationError(_('Withhold on the clearing expense, not on the advance.'))

    def _do_approve(self):
        self._check_withholding_vendor()
        return super()._do_approve()

    def _create_move(self):
        token = _withholding_workflow.set(True)
        try:
            return super()._create_move()
        finally:
            _withholding_workflow.reset(token)

    def _prepare_receipts_vals(self):
        withholding = self.filtered(lambda expense: expense.tax_ids.filtered('is_withholding_tax'))
        values = super(ExpenseWithholding, self - withholding)._prepare_receipts_vals()
        for expense in withholding:
            values.extend(super(ExpenseWithholding, expense)._prepare_receipts_vals())
        return values

    def _withholding_base_line(self):
        self.ensure_one()
        rate = self.total_amount_currency / self.total_amount if self.total_amount else 1
        currency = self.currency_id
        if self.payment_mode == 'own_account':
            rate, currency = 1, self.company_currency_id
        return self.env['account.tax']._prepare_base_line_for_taxes_computation(
            self, tax_ids=self.tax_ids.flatten_taxes_hierarchy().filtered('is_withholding_tax'),
            price_unit=currency.round(self.untaxed_amount * rate),
            quantity=1, discount=0, special_mode=False, account_id=self.account_id,
            currency_id=currency, rate=rate,
        )

    def _prepare_payments_vals(self):
        move_vals, payment_vals = super()._prepare_payments_vals()
        if self.tax_ids.filtered('is_withholding_tax') and not self.has_existing_bill:
            self._check_withholding_vendor()
            base = self._withholding_base_line()
            payment_vals.update(
                withhold='withhold_pay', erp_withholding_expense_id=self.id,
                withholding_line_ids=self.env['account.payment.withholding.line']._prepare_withholding_lines_commands([base], self.company_id),
            )
        return move_vals, payment_vals

    def _advance_clearing_amount(self):
        amount = super()._advance_clearing_amount()
        payments = self.erp_withholding_payment_ids.filtered(lambda payment: payment.move_id.state == 'posted')
        withheld = sum(payments.move_id.line_ids.filtered(lambda line: line.account_type == 'liability_payable').mapped('balance'))
        return max(0, amount - withheld)

    def _create_advance_settlement(self):
        self._create_expense_withholding()
        return super()._create_advance_settlement()

    def _create_expense_withholding(self):
        self.ensure_one()
        bill = self.account_move_id
        if self.payment_mode != 'own_account' or not bill.withholding_residual_amount_currency:
            return
        self._check_withholding_vendor()
        if self.erp_withholding_payment_ids.filtered(lambda payment: payment.move_id.state == 'posted'):
            return
        if bill.state != 'posted' or self.approval_state != 'approved':
            raise UserError(_('Approve and post the original expense before withholding.'))
        journal = self.company_id.sudo().erp_employee_advance_journal_id.with_env(self.env)
        if not journal:
            journal = self.env['account.journal'].search([('company_id', '=', self.company_id.id), ('type', '=', 'general')], limit=1)
        if not journal or journal.type != 'general' or journal.company_id != self.company_id:
            raise ValidationError(_('Configure a general journal for expense withholding.'))
        payable = bill.line_ids.filtered(lambda line: line.account_type == 'liability_payable')
        if len(payable.account_id) != 1 or len(payable.partner_id) != 1:
            raise ValidationError(_('Withholding requires one employee payable account and partner.'))
        wizard = self.env['account.payment.register'].with_context(active_model='account.move', active_ids=bill.ids).create({'withhold': 'withhold', 'journal_id': journal.id, 'payment_date': bill.date, 'withholding_line_ids': self.env['account.payment.register.withholding.line']._prepare_withholding_lines_commands(bill._expense_withholding_base_lines(), self.company_id)})
        values = wizard._create_payment_vals_from_wizard(wizard._get_batches()[0])
        values.update(erp_withholding_expense_id=self.id, partner_id=self.vendor_id.commercial_partner_id.id, destination_account_id=payable.account_id.id, invoice_ids=[(6, 0, bill.ids)])
        token = _withholding_workflow.set(True)
        try:
            payment = self.env['account.payment'].create(values)
            payment.action_post()
            (payable | payment.move_id.line_ids.filtered(lambda line: line.account_id == payable.account_id)).filtered(lambda line: not line.reconciled).reconcile()
        finally:
            _withholding_workflow.reset(token)

    def write(self, vals):
        if 'erp_withholding_payment_ids' in vals:
            raise AccessError(_('Withholding history is generated by expense posting.'))
        if {'vendor_id', 'erp_tax_invoice_reference', 'erp_tax_invoice_date'} & vals.keys():
            self._lock_expense_identity()
            if any(expense.approval_state in ('submitted', 'approved') or expense._has_budget_history() or expense.erp_withholding_payment_ids for expense in self) or self.env['l10n_th.tax.invoice'].sudo().search_count([('invoice_move_id.line_ids.expense_id', 'in', self.ids)], limit=1):
                raise UserError(_('Supplier tax identity with approval history cannot be changed.'))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if any('erp_withholding_payment_ids' in vals for vals in vals_list) or 'default_erp_withholding_payment_ids' in self.env.context:
            raise AccessError(_('Withholding history cannot be supplied by clients.'))
        return super().create(vals_list)


class ExpenseWithholdingPayment(models.Model):
    _inherit = 'account.payment'

    erp_withholding_expense_id = fields.Many2one('hr.expense', check_company=True, ondelete='restrict', readonly=True, copy=False, index=True)

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('erp_withholding_expense_id', 'not any!', ~_expense_access(self.env.uid))

    def _get_outstanding_account(self, payment_type):
        if self.erp_withholding_expense_id and self.withhold == 'withhold':
            # Native Community create() asks for an outstanding account even
            # though its withholding-only engine intentionally has no liquidity.
            return self.env['account.account']
        return super()._get_outstanding_account(payment_type)

    def _prepare_move_counterpart_lines(self, default_values):
        lines = super()._prepare_move_counterpart_lines(default_values)
        if self.erp_withholding_expense_id.payment_mode == 'own_account':
            payable = self.erp_withholding_expense_id.account_move_id.line_ids.filtered(lambda line: line.account_type == 'liability_payable')
            for line in lines:
                line.update(partner_id=payable.partner_id.id, account_id=payable.account_id.id)
        return lines

    @api.model_create_multi
    def create(self, vals_list):
        if not _withholding_workflow.get() and (any('erp_withholding_expense_id' in vals for vals in vals_list) or 'default_erp_withholding_expense_id' in self.env.context):
            raise AccessError(_('Expense withholding is generated by native expense posting.'))
        payments = super().create(vals_list)
        for payment in payments.filtered(lambda item: item.erp_withholding_expense_id.payment_mode == 'company_account'):
            expense = payment.erp_withholding_expense_id
            lines = payment.withholding_line_ids._prepare_withholding_amls_create_values()
            offset = payment.move_id.line_ids.filtered(lambda line: line.account_id.id == expense._get_expense_account_destination())
            if len(offset) != 1 or payment.move_id.state != 'draft':
                raise ValidationError(_('Company-paid withholding requires the original draft payment entry.'))
            # Native HR creates a complete gross expense entry. Add the native
            # WHT base/tax lines and reduce only its outstanding payment line.
            with self.env.cr.savepoint(), payment.move_id._check_balanced({'records': payment.move_id}):
                payment.move_id.with_context(check_move_validity=False).write({'line_ids': [(0, 0, line) for line in lines] + [(1, offset.id, {'balance': offset.balance - sum(line['balance'] for line in lines), 'amount_currency': offset.amount_currency - sum(line['amount_currency'] for line in lines)})]})
        return payments

    def _synchronize_to_moves(self, changed_fields):
        ordinary = self.filtered(lambda payment: payment.erp_withholding_expense_id.payment_mode != 'company_account')
        return super(ExpenseWithholdingPayment, ordinary)._synchronize_to_moves(changed_fields)

    def write(self, vals):
        if not _withholding_workflow.get() and ('erp_withholding_expense_id' in vals or self.filtered('erp_withholding_expense_id') and set(vals) - {'message_follower_ids', 'message_ids', 'is_sent'}):
            raise AccessError(_('Reset the source expense to cancel its withholding.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('erp_withholding_expense_id'):
            raise UserError(_('Expense withholding history cannot be deleted.'))
        return super().unlink()


class ExpenseWithholdingPaymentLine(models.Model):
    _inherit = 'account.payment.withholding.line'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('payment_id', 'any!', Domain('erp_withholding_expense_id', 'not any!', ~_expense_access(self.env.uid)))

    @api.model_create_multi
    def create(self, vals_list):
        payments = self.env['account.payment'].browse([vals.get('payment_id', self.env.context.get('default_payment_id')) for vals in vals_list if vals.get('payment_id', self.env.context.get('default_payment_id'))])
        if payments.filtered('erp_withholding_expense_id') and not _withholding_workflow.get():
            raise AccessError(_('Expense withholding lines are immutable.'))
        return super().create(vals_list)

    def write(self, vals):
        destination = self.env['account.payment'].browse(vals.get('payment_id'))
        if (self.payment_id | destination).filtered('erp_withholding_expense_id') and not _withholding_workflow.get():
            raise AccessError(_('Expense withholding lines are immutable.'))
        return super().write(vals)

    def unlink(self):
        if self.payment_id.filtered('erp_withholding_expense_id'):
            raise UserError(_('Expense withholding history cannot be deleted.'))
        return super().unlink()


class ExpenseWithholdingMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('origin_payment_id', 'not any!', Domain('erp_withholding_expense_id', 'any!', ~_expense_access(self.env.uid)))

    def _expense_withholding_base_lines(self):
        self.ensure_one()
        return [self.env['account.tax']._prepare_base_line_for_taxes_computation(
            line, tax_ids=line.tax_ids.flatten_taxes_hierarchy().filtered('is_withholding_tax'),
            price_unit=line.price_subtotal, quantity=1, discount=0, special_mode=False,
            currency_id=self.currency_id, rate=self.invoice_currency_rate or 1,
        ) for line in self.invoice_line_ids if line.expense_id and line.tax_ids.filtered('is_withholding_tax') and not line.tax_line_id]

    @api.depends('line_ids.price_subtotal', 'line_ids.expense_id', 'line_ids.tax_ids', 'invoice_currency_rate')
    def _compute_withholding_total_amount(self):
        super()._compute_withholding_total_amount()
        for move in self:
            if move.is_invoice(include_receipts=True) and move.invoice_line_ids.expense_id:
                commands = self.env['account.payment.withholding.line']._prepare_withholding_lines_commands(move._expense_withholding_base_lines(), move.company_id)
                # Native HR receipt unit prices include VAT. Compute WHT on the
                # recorded untaxed receipt amount, including retained history.
                move.withholding_total_amount_currency = move.currency_id.round(sum(command[2]['source_tax_amount_currency'] for command in commands if command[0] == 0))

    @contextmanager
    def _company_withholding_transition(self):
        enabled = self.origin_payment_id.filtered(lambda payment: payment.erp_withholding_expense_id.payment_mode == 'company_account')
        if enabled:
            self.check_access('write')
            enabled.erp_withholding_expense_id.check_access('read')
        token = _withholding_workflow.set(_withholding_workflow.get() or bool(enabled))
        try:
            yield
        finally:
            _withholding_workflow.reset(token)

    def _withholding_source_expenses(self):
        expenses = self.sudo().line_ids.expense_id.with_env(self.env)
        expenses.check_access('read')
        return expenses.filtered(lambda expense: expense.account_move_id in self)

    def _post(self, soft=True):
        if self.origin_payment_id.filtered(lambda payment: payment.erp_withholding_expense_id.payment_mode == 'own_account') and not _withholding_workflow.get():
            raise AccessError(_('Post withholding through the original expense.'))
        expenses = self._withholding_source_expenses()
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()), self._company_withholding_transition():
            posted = super()._post(soft=soft)
            for expense in expenses.filtered(lambda expense: not expense.erp_advance_ids and expense.account_move_id in posted):
                expense._create_expense_withholding()
            token = _withholding_workflow.set(True)
            try:
                for expense in expenses.filtered(lambda item: item.account_move_id in posted and item.company_id.country_id.code == 'TH' and item.company_id.l10n_th_is_vat_registered):
                    bill = expense.account_move_id
                    bill._update_or_create_l10n_th_tax_invoice()
                    bill.l10n_th_tax_invoice_ids.filtered(lambda invoice: invoice.state == 'draft').write({'state': 'posted'})
            finally:
                _withholding_workflow.reset(token)
            return posted

    def _cancel_expense_withholding(self):
        payments = self._withholding_source_expenses().erp_withholding_payment_ids.filtered(lambda payment: payment.erp_withholding_expense_id.payment_mode == 'own_account' and payment.move_id.state == 'posted')
        token = _withholding_workflow.set(True)
        try:
            invoices = self._withholding_source_expenses().account_move_id.l10n_th_tax_invoice_ids.filtered(lambda invoice: invoice.state != 'cancel')
            invoices.write({'state': 'cancel'})
            for payment in payments:
                payment.move_id.button_draft()
                payment.move_id.button_cancel()
                payment.write({'state': 'canceled'})
        finally:
            _withholding_workflow.reset(token)

    def button_draft(self):
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()), self._company_withholding_transition():
            self._cancel_expense_withholding()
            return super().button_draft()

    def button_cancel(self):
        with self.env.cr.savepoint(), self.env['erp.budget.control.service']._accounting_transaction(self._prelock_budget_sources()), self._company_withholding_transition():
            self._cancel_expense_withholding()
            return super().button_cancel()

    def write(self, vals):
        protected = self.origin_payment_id.erp_withholding_expense_id
        if not _withholding_workflow.get() and (protected and {'state', 'line_ids', 'date', 'company_id', 'currency_id', 'journal_id', 'partner_id', 'move_type', 'origin_payment_id', 'erp_budget_exempt'} & vals.keys() or 'origin_payment_id' in vals and self.env['account.payment'].browse(vals['origin_payment_id']).erp_withholding_expense_id):
            raise AccessError(_('Expense withholding accounting is controlled by its source.'))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        ids = [vals.get('origin_payment_id', self.env.context.get('default_origin_payment_id')) for vals in vals_list]
        if not _withholding_workflow.get() and self.env['account.payment'].browse([value for value in ids if value]).erp_withholding_expense_id:
            raise AccessError(_('Expense withholding accounting is controlled by its source.'))
        return super().create(vals_list)

    def unlink(self):
        if self.origin_payment_id.erp_withholding_expense_id:
            raise UserError(_('Expense withholding entries are retained for audit.'))
        return super().unlink()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        if self.origin_payment_id.erp_withholding_expense_id or self._erp_expense_lines().expense_id.erp_withholding_payment_ids:
            raise UserError(_('Reset the expense to reverse its withholding and accounting together.'))
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)


class ExpenseWithholdingMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('move_id', 'any!', Domain('origin_payment_id', 'not any!', Domain('erp_withholding_expense_id', 'any!', ~_expense_access(self.env.uid))))

    @api.model_create_multi
    def create(self, vals_list):
        ids = [vals.get('move_id', self.env.context.get('default_move_id')) for vals in vals_list]
        if not _withholding_workflow.get() and self.env['account.move'].browse([value for value in ids if value]).origin_payment_id.erp_withholding_expense_id:
            raise AccessError(_('Expense withholding accounting lines are immutable.'))
        return super().create(vals_list)

    def write(self, vals):
        moves = self.move_id | self.env['account.move'].browse(vals.get('move_id'))
        sensitive = {'move_id', 'account_id', 'partner_id', 'balance', 'debit', 'credit', 'amount_currency', 'currency_id', 'tax_ids', 'tax_repartition_line_id', 'analytic_distribution', 'expense_id', 'purchase_line_id', 'quantity', 'price_unit', 'display_type', 'company_id', 'tax_base_amount', 'tax_tag_ids', 'date'}
        if moves.origin_payment_id.erp_withholding_expense_id and (sensitive & vals.keys() or any(key.startswith('erp_budget_') for key in vals)) and not _withholding_workflow.get():
            raise AccessError(_('Expense withholding accounting lines are immutable.'))
        return super().write(vals)

    def unlink(self):
        if self.move_id.origin_payment_id.erp_withholding_expense_id and not _withholding_workflow.get():
            raise UserError(_('Expense withholding accounting history cannot be deleted.'))
        return super().unlink()


class ExpenseTaxInvoice(models.Model):
    _inherit = 'l10n_th.tax.invoice'

    erp_expense_vendor_id = fields.Many2one('res.partner', readonly=True, copy=False, check_company=True, string='Expense Supplier')

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('invoice_move_id', 'any!', Domain('line_ids', 'not any!', Domain('expense_id', 'any!', ~_expense_access(self.env.uid))))

    @api.model_create_multi
    def create(self, vals_list):
        values = []
        for vals in vals_list:
            vals = dict(vals)
            expense = self.env['account.move'].browse(vals.get('invoice_move_id')).line_ids.expense_id
            if not _withholding_workflow.get() and (expense or 'erp_expense_vendor_id' in vals or 'default_erp_expense_vendor_id' in self.env.context):
                raise AccessError(_('Supplier tax evidence is created by expense posting.'))
            if len(expense) == 1:
                vals['erp_expense_vendor_id'] = expense.vendor_id.id
                if expense.erp_tax_invoice_reference:
                    vals['tax_invoice_number'] = expense.erp_tax_invoice_reference
                vals['date'] = expense.erp_tax_invoice_date or expense.date
            values.append(vals)
        return super().create(values)

    def write(self, vals):
        for invoice in self:
            values = dict(vals)
            expense = invoice.invoice_move_id.line_ids.expense_id | self.env['account.move'].browse(vals.get('invoice_move_id')).line_ids.expense_id
            if expense and not _withholding_workflow.get() and set(vals) & {'invoice_move_id', 'payment_move_id', 'date', 'tax_invoice_number', 'total_amount', 'vat_amount', 'tax_group_amounts', 'tax_invoice_lines', 'state', 'erp_expense_vendor_id'}:
                raise AccessError(_('Supplier tax evidence is controlled by expense posting.'))
            if len(expense) == 1:
                if 'tax_invoice_number' in values and expense.erp_tax_invoice_reference:
                    values['tax_invoice_number'] = expense.erp_tax_invoice_reference
                if 'date' in values:
                    values['date'] = expense.erp_tax_invoice_date or expense.date
            super(ExpenseTaxInvoice, invoice).write(values)
        return True

    def unlink(self):
        if self.invoice_move_id.line_ids.expense_id:
            raise UserError(_('Supplier tax evidence is retained for audit.'))
        return super().unlink()


class ExpenseWithholdingSnapshot(models.Model):
    _inherit = 'account.move.line'

    def _amount_snapshot_values(self, amount):
        snapshot = super()._amount_snapshot_values(amount)
        if self.expense_id:
            snapshot.update(expense_vendor_id=self.expense_id.vendor_id.id,
                            supplier_tax_invoice_reference=self.expense_id.erp_tax_invoice_reference,
                            supplier_tax_invoice_date=str(self.expense_id.erp_tax_invoice_date or self.expense_id.date))
        return snapshot


class ExpenseWithholdingReconciliation(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model
    def _access_domain(self, operation):
        invalid = Domain('move_id', 'any!', Domain('origin_payment_id', 'any!', Domain('erp_withholding_expense_id', 'any!', ~_expense_access(self.env.uid))))
        return super()._access_domain(operation) & Domain('debit_move_id', 'not any!', invalid) & Domain('credit_move_id', 'not any!', invalid)

    def unlink(self):
        payments = (self.debit_move_id | self.credit_move_id).move_id.origin_payment_id
        if payments.filtered(lambda payment: payment.erp_withholding_expense_id.payment_mode == 'own_account') and not _withholding_workflow.get():
            raise AccessError(_('Reset the expense to remove its withholding reconciliation.'))
        return super().unlink()
