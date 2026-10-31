from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from .test_budget_control import TestBudgetControl


@tagged('post_install', '-at_install')
class TestBudgetTransfer(TestBudgetControl):
    def _setup_transfer(self):
        env = self.env(user=self.user, context={'allowed_company_ids': self.company.ids})
        period = self.env['erp.budget.period'].create({'name': 'Transfer year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31', 'release_policy': 'formal', 'control_level': 'analytic'})
        analytic2 = self.env['account.analytic.account'].create({'name': 'Transfer destination', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        allocation = env['erp.budget.allocation'].create({'name': 'Transfer allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100}) for analytic in (self.analytic, analytic2)]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        allocation.line_ids.control_id.action_open()
        reviewers = self.env['res.users'].create([{'name': 'Transfer reviewer '+str(index), 'login': 'transfer_reviewer_'+str(index), 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, self.env.ref('erp_budget.group_budget_manager').ids)]} for index in (1, 2)])
        for index, reviewer in enumerate(reviewers, 1):
            self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
            for kind in ('planning', 'transfer'):
                self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': index * 10, 'reviewer_id': reviewer.id, 'kind': kind})
        controls = env['erp.budget.control']
        for analytic in (self.analytic, analytic2):
            control = env['erp.budget.control'].create({'name': analytic.name, 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': analytic.id, 'level': 'analytic', 'amount': 100})
            release = env['erp.budget.kpi.release'].create({'name': analytic.name, 'plan_line_id': allocation.plan_id.line_ids.filtered(lambda line: line.analytic_id == analytic).id, 'released_amount': 100, 'line_ids': [(0, 0, {'control_id': control.id})]})
            release.action_submit()
            for reviewer in reviewers:
                release.with_user(reviewer).action_approve()
            controls |= control
        doc = env['erp.budget.transfer'].create({'name': 'Transfer 30', 'allocation_id': allocation.id, 'organization_id': self.unit.id, 'line_ids': [(0, 0, {'source_id': allocation.line_ids[0].id, 'destination_id': allocation.line_ids[1].id, 'source_control_id': controls[0].id, 'destination_control_id': controls[1].id, 'amount': 30})]})
        return env, doc, controls, reviewers

    def _approve_transfer(self, doc, reviewers):
        doc.action_submit_planning()
        for reviewer in reviewers:
            doc.with_user(reviewer).action_approve()
            for planning in doc._planning():
                planning.with_user(reviewer).action_approve()
        doc.action_transfer()

    def test_transfer_and_reviewed_consumption_safe_reversal(self):
        env, doc, controls, reviewers = self._setup_transfer()
        funds = doc.allocation_id.line_ids.control_id
        service = env['erp.budget.control.service']
        service._commit(controls[:1] | funds[:1], 60, '2027-06-01', 'transfer:existing')
        doc.action_submit()
        self.assertEqual((controls.mapped('amount'), funds.mapped('amount')), ([100, 100], [100, 100]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.revision_id.action_activate()
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.with_user(reviewers[1]).action_approve()
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.action_approve()
        self._approve_transfer(doc, reviewers)
        doc.action_transfer()
        self.assertEqual((doc.state, controls.mapped('amount'), funds.mapped('amount')), ('done', [70, 130], [70, 130]))
        self.assertEqual(sum(doc.allocation_id.plan_id.line_ids.mapped('effective_amount')), 200)
        self.assertEqual(doc.approval_id.state, 'approved')
        self.assertFalse(doc.approval_id.line_ids)
        reverse = env['erp.budget.transfer'].browse(doc.action_reverse()['res_id'])
        self.assertEqual(doc.action_reverse()['res_id'], reverse.id)
        reverse.action_submit()
        self._approve_transfer(reverse, reviewers)
        self.assertEqual((doc.state, reverse.state, controls.mapped('amount')), ('reversed', 'done', [100, 100]))
        self.assertEqual(doc.line_ids.amount, 30)

    def test_reversal_rechecks_destination_and_keeps_original_history(self):
        env, doc, controls, reviewers = self._setup_transfer()
        doc.action_submit()
        self._approve_transfer(doc, reviewers)
        funds = doc.allocation_id.line_ids.control_id
        service = env['erp.budget.control.service']
        reverse = env['erp.budget.transfer'].browse(doc.action_reverse()['res_id'])
        reverse.action_submit()
        reverse.action_submit_planning()
        for reviewer in reviewers:
            reverse.with_user(reviewer).action_approve()
            for planning in reverse._planning():
                planning.with_user(reviewer).action_approve()
        service._commit(controls[1:] | funds[1:], 110, '2027-06-01', 'transfer:destination-consumed')
        with self.assertRaises(UserError), self.cr.savepoint():
            reverse.action_transfer()
        self.assertEqual((doc.state, reverse.state, controls.mapped('amount')), ('done', 'submit', [70, 130]))

    def test_rejection_resubmission_and_scope(self):
        env, doc, controls, reviewers = self._setup_transfer()
        doc.action_submit()
        old_revision, old_approval = doc.revision_id, doc.approval_id
        doc.with_user(reviewers[0]).action_reject()
        self.assertEqual((doc.state, old_revision.state, old_approval.state), ('cancel', 'cancel', 'cancel'))
        self.assertEqual(controls.mapped('amount'), [100, 100])
        doc.action_draft()
        doc.action_submit()
        self.assertNotEqual(doc.approval_id, old_approval)
        foreign = self.env['res.company'].create({'name': 'Foreign transfer company'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.with_user(reviewers[0]).with_context(allowed_company_ids=foreign.ids).action_approve()
        assignment = self.env['erp.organization.assignment'].search([('user_id', '=', reviewers[0].id), ('unit_id', '=', self.unit.id)])
        assignment.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.with_user(reviewers[0]).action_approve()
        self.assertEqual(doc.state, 'submit')

    def test_transfer_revises_unchanged_third_analytic_in_same_plan_chain(self):
        env, doc, controls, reviewers = self._setup_transfer()
        allocation = doc.allocation_id
        third = self.env['account.analytic.account'].create({'name': 'Unchanged third analytic', 'plan_id': self.analytic.plan_id.id, 'company_id': self.company.id})
        setup = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        setup.write({'reason': 'Add third analytic'})
        setup.action_add_dimension(self.unit.id, third.id, self.fund.id, 50)
        for release in env['erp.budget.kpi.release'].search([('plan_line_id.plan_id', '=', allocation.plan_id.id), ('state', '=', 'done')]):
            successor = env['erp.budget.kpi.release'].browse(release.action_prepare_revision(setup.id)['res_id'])
            successor.action_submit()
            for reviewer in reviewers:
                successor.with_user(reviewer).action_approve()
        setup.action_activate()
        control = env['erp.budget.control'].create({'name': 'Third unchanged control', 'company_id': self.company.id, 'period_id': allocation.period_id.id, 'organization_id': self.unit.id, 'analytic_id': third.id, 'level': 'analytic', 'amount': 50})
        release = env['erp.budget.kpi.release'].create({'name': 'Third planning', 'plan_line_id': allocation.plan_id.line_ids.filtered(lambda line: line.analytic_id == third).id, 'released_amount': 50, 'line_ids': [(0, 0, {'control_id': control.id})]})
        release.action_submit()
        for reviewer in reviewers:
            release.with_user(reviewer).action_approve()
        doc.action_submit()
        self.assertEqual(len(doc._planning()), 3)
        self._approve_transfer(doc, reviewers)
        self.assertEqual((doc.state, control.amount, control.state), ('done', 50, 'open'))
        self.assertEqual(sum(allocation.plan_id.line_ids.mapped('effective_amount')), 250)
