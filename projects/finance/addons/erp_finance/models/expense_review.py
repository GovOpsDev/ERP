"""Reuse Budget's reviewer configuration and protected review audit records."""
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.erp_budget.models.budget_release import _review_internal

from .expense import _FINANCIAL

_expense_review = ContextVar('erp_expense_review', default=False)
_FIELDS = {'erp_review_ids', 'erp_review_round'}


class ExpenseReviewTier(models.Model):
    _inherit = 'erp.budget.kpi.tier'

    kind = fields.Selection(selection_add=[('expense', 'Expense approval'), ('advance', 'Employee advance approval')], ondelete={'expense': 'cascade', 'advance': 'cascade'})


class ExpenseReview(models.Model):
    _name = 'erp.finance.expense.review'
    _inherit = 'erp.budget.kpi.review'
    _description = 'Expense Approval Review'

    release_id = fields.Many2one(required=False)
    expense_id = fields.Many2one('hr.expense', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='expense_id.company_id', store=True)
    organization_id = fields.Many2one(related='expense_id.erp_budget_organization_id', store=True)
    _expense_review_unique = models.Constraint('unique(expense_id, round_number, sequence)', 'Review order must be unique within an expense submission.')


class ReviewedBudgetExpense(models.Model):
    _inherit = 'hr.expense'

    erp_review_ids = fields.One2many('erp.finance.expense.review', 'expense_id', readonly=True, copy=False)
    erp_review_round = fields.Integer(readonly=True, copy=False)

    def _expense_tier_kind(self):
        return 'expense'

    def _expense_tiers(self):
        self.ensure_one()
        return self.env['erp.budget.kpi.tier'].search([('company_id', '=', self.company_id.id), ('organization_id', '=', self.erp_budget_organization_id.id), ('kind', '=', self._expense_tier_kind())])

    def _expense_reviews(self):
        self.ensure_one()
        if not self._budget_expenses():
            return self.env['erp.finance.expense.review']
        return self.erp_review_ids.filtered(lambda review: review.round_number == self.erp_review_round).sorted(lambda review: (review.sequence, review.id))

    def _can_be_autovalidated(self):
        if self._budget_expenses() and self._expense_tiers():
            return False
        return super()._can_be_autovalidated()

    def action_submit(self):
        with self._budget_workflow():
            for expense in self._budget_expenses():
                if expense.approval_state:
                    raise UserError(_('Reset the expense before submitting another review round.'))
            result = super().action_submit()
            token = _review_internal.set(True)
            review_token = _expense_review.set(True)
            try:
                for expense in self._budget_expenses():
                    tiers = expense._expense_tiers()
                    if not tiers:
                        continue
                    for tier in tiers:
                        reviewer = tier.reviewer_id
                        if reviewer == expense.employee_id.user_id or not reviewer.has_group('erp_budget.group_budget_user'):
                            raise ValidationError(_('Expense reviewers require budget capability and cannot approve their own expense.'))
                        reviewed = expense.with_user(reviewer).with_context(allowed_company_ids=expense.company_id.ids)
                        reviewed.check_access('write')
                        reviewed._check_can_approve()
                        reviewed._budget_controls().check_access('read')
                    expense.write({'erp_review_round': expense.erp_review_round + 1})
                    self.env['erp.finance.expense.review'].sudo().create([{'expense_id': expense.id, 'reviewer_id': tier.reviewer_id.id, 'sequence': tier.sequence, 'round_number': expense.erp_review_round} for tier in tiers])
            finally:
                _expense_review.reset(review_token)
                _review_internal.reset(token)
            return result

    def _do_approve(self):
        for expense in self._budget_expenses():
            reviews = expense._expense_reviews()
            if expense._expense_tiers() and (not reviews or any(review.state != 'approved' for review in reviews)):
                raise AccessError(_('Complete the assigned expense review tiers before approval.'))
        return super()._do_approve()

    def action_approve(self):
        reviewed = self.filtered(lambda expense: expense._expense_reviews())
        if not reviewed:
            return super().action_approve()
        with self._budget_workflow():
            for expense in reviewed:
                expense._check_can_approve()
                reviews = expense._expense_reviews()
                approved = reviews.filtered(lambda review: review.state == 'approved' and review.reviewer_id == self.env.user)
                if approved:
                    continue
                pending = reviews.filtered(lambda review: review.state == 'pending')[:1]
                if expense.approval_state != 'submitted' or not pending or pending.reviewer_id != self.env.user:
                    raise AccessError(_('Only the next assigned expense reviewer may approve.'))
                token = _review_internal.set(True)
                try:
                    pending.sudo().write({'state': 'approved'})
                finally:
                    _review_internal.reset(token)
                # Recheck capacity at every source tier, without reserving it.
                with self.env.cr.savepoint() as check:
                    expense._reconcile_expense_budget(simulate=True)
                    self.env['erp.budget.control.service']._validate_accounting_totals(expense._lock_budget_expenses())
                    check.rollback()
                if all(review.state == 'approved' for review in reviews):
                    expense._do_approve()
            if self - reviewed:
                super(ReviewedBudgetExpense, self - reviewed).action_approve()
            return True

    def _do_refuse(self, reason):
        with self._budget_workflow():
            for expense in self:
                reviews = expense._expense_reviews()
                if reviews and expense.approval_state == 'submitted':
                    pending = reviews.filtered(lambda review: review.state == 'pending')[:1]
                    if not pending or pending.reviewer_id != self.env.user:
                        raise AccessError(_('Only the next assigned expense reviewer may reject.'))
                    token = _review_internal.set(True)
                    try:
                        pending.sudo().write({'state': 'rejected'})
                    finally:
                        _review_internal.reset(token)
            return super()._do_refuse(reason)

    @api.model_create_multi
    def create(self, vals_list):
        if any(_FIELDS & vals.keys() for vals in vals_list) or any('default_' + key in self.env.context for key in _FIELDS):
            raise AccessError(_('Expense reviews are created only by submission.'))
        return super().create(vals_list)

    def write(self, vals):
        if _FIELDS & vals.keys() and not _expense_review.get():
            raise AccessError(_('Expense reviews are managed by workflow actions.'))
        if _FINANCIAL & vals.keys() and any(expense.approval_state == 'submitted' and expense._expense_reviews() for expense in self):
            raise UserError(_('Reset the expense before changing a submitted review.'))
        return super().write(vals)
