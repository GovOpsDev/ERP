from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from .test_budget_control import TestBudgetControl


@tagged('post_install', '-at_install')
class TestBudgetPlan(TestBudgetControl):
    def _setup_plan(self, amount=100):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        plan = env['erp.budget.plan'].create({'name': 'Shared plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': amount})]})
        plan.action_confirm()
        return env, plan, plan.line_ids

    def test_shared_limit_and_revisions(self):
        env, plan, line = self._setup_plan()
        Control = env['erp.budget.control']
        kpi = self.env['erp.budget.kpi'].create({'name': 'Second KPI', 'company_id': self.company.id})
        other = Control.create({'name': 'KPI B', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 80, 'level': 'analytic', 'kpi_id': kpi.id})
        other.action_open()
        service = env['erp.budget.control.service']
        first, second = env['erp.budget.control'].browse(self.a.id) | env['erp.budget.control'].browse(self.f.id), other | env['erp.budget.control'].browse(self.f.id)
        with self.assertRaises(UserError), self.cr.savepoint():
            service._check_available(second, 81, self.day)
        service._commit(first, 60, self.day, 'plan:first')
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(second, 41, self.day, 'plan:overflow')
        service._commit(second, 40, self.day, 'plan:second')
        self.assertEqual(line._consumed(), 100)
        with self.assertRaises(UserError), self.cr.savepoint():
            line.action_decrease(1, 'under consumption')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            line.action_increase(0.001, 'fractional currency')
        line.action_increase(50, 'supplement')
        self.assertEqual(line._ceiling(), 150)
        service._reverse(first, 'plan:first')
        self.assertEqual(line._consumed(), 40)
        line.action_decrease(10, 'reduction')
        self.assertEqual(line._ceiling(), 140)
        with self.assertRaises(AccessError), self.cr.savepoint():
            line.write({'initial_amount': 999})
        events = self.env['erp.budget.plan.event'].sudo().search([('period_id', '=', self.period.id)])
        self.assertEqual(len(events), 2)
        with self.assertRaises(AccessError), self.cr.savepoint():
            events.write({'amount': 999})

    def test_transfer_and_existing_consumption_gate(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        service = env['erp.budget.control.service']
        controls = env['erp.budget.control'].browse((self.a | self.f).ids)
        service._commit(controls, 80, self.day, 'legacy:1')
        analytic2 = self.env['account.analytic.account'].create({'name': 'Second analytic', 'plan_id': self.plan.id, 'company_id': self.company.id})
        plan = env['erp.budget.plan'].create({'name': 'Plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 70}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': analytic2.id, 'initial_amount': 20})]})
        with self.assertRaises(UserError), self.cr.savepoint():
            plan.action_confirm()
        first = plan.line_ids.filtered(lambda line: line.analytic_id == self.analytic)
        second = plan.line_ids - first
        first.initial_amount = 100
        plan.action_confirm()
        first.action_increase(50, 'revision increase')
        self.assertEqual((first._ceiling(), first._ceiling() - first._consumed()), (150, 70))
        first.action_decrease(50, 'return to original')
        with self.assertRaises(UserError), self.cr.savepoint():
            first.action_transfer(second.id, 21, 'exceeds availability')
        first.action_transfer(second.id, 20, 'reallocate')
        self.assertEqual((first._ceiling(), second._ceiling()), (80, 40))
        self.assertEqual(first._ceiling() + second._ceiling(), 120)
        self.assertEqual(first._consumed(), 80)
        self.assertEqual(self.env['erp.budget.move'].sudo().search_count([('origin_key', '=', 'legacy:1')]), 2)
        later = env['erp.budget.period'].create({'name': 'Later period', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        future_plan = env['erp.budget.plan'].create({'name': 'Later plan', 'company_id': self.company.id, 'period_id': later.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 10})]})
        future_plan.action_confirm()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            first.action_transfer(future_plan.line_ids.id, 1, 'cross-period')

    def test_allocated_children_cannot_exceed_parent(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        plan = env['erp.budget.plan'].create({'name': 'Allocated plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100, 'allocation_mode': 'allocated'})]})
        plan.action_confirm()
        line = plan.line_ids
        kpi = self.env['erp.budget.kpi'].create({'name': 'Allocated KPI', 'company_id': self.company.id})
        extra = env['erp.budget.control'].create({'name': 'Extra allocation', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 10, 'level': 'analytic', 'kpi_id': kpi.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            extra.action_open()
        with self.assertRaises(UserError), self.cr.savepoint():
            line.action_decrease(1)
        line.action_increase(10)
        extra.action_open()
        self.assertEqual(line._allocated(), 110)

    def test_multi_reconciliation_counts_parent_once(self):
        env, plan, line = self._setup_plan()
        kpi = self.env['erp.budget.kpi'].create({'name': 'Alternate KPI', 'company_id': self.company.id})
        extra = env['erp.budget.control'].create({'name': 'Alternate', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 100, 'level': 'analytic', 'kpi_id': kpi.id})
        extra.action_open()
        fund = env['erp.budget.control'].browse(self.f.id)
        first = env['erp.budget.control'].browse(self.a.id) | fund
        second = extra | fund
        service = env['erp.budget.control.service']
        service._reconcile_purchase_multi(first, self.day, 'plan-family', 'plan-pr', 80, True, [])
        self.assertEqual(line._consumed(), 80)
        service._reconcile_purchase_multi(first, self.day, 'plan-family', 'plan-pr', 80, True, [('plan-po', second, 50, self.day)], [('actual:1', second, 30, self.day)])
        self.assertEqual(line._consumed(), 80)
        with self.assertRaises(UserError), self.cr.savepoint():
            service._reconcile_purchase_multi(first, self.day, 'plan-family', 'plan-pr', 80, True, [('plan-po', second, 75, self.day)], [('actual:1', second, 30, self.day)])
        self.assertEqual(line._consumed(), 80)
        service._reconcile_purchase_multi(first, self.day, 'contract-family', 'contract-line', 20, True, [], primary_type='contract_commitment')
        self.assertEqual(line._consumed(), 100)

    def test_security_cross_company_and_unmapped_scope(self):
        env, plan, line = self._setup_plan()
        reader = self.env['res.users'].create({'name': 'Plan reader', 'login': 'plan_reader', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reader.id, 'unit_id': self.unit.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            line.with_user(reader).with_context(allowed_company_ids=[self.company.id]).action_increase(10)
        analytic2 = self.env['account.analytic.account'].create({'name': 'Unmapped analytic', 'plan_id': self.plan.id, 'company_id': self.company.id})
        extra = env['erp.budget.control'].create({'name': 'Unmapped', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': analytic2.id, 'amount': 50, 'level': 'analytic'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            extra.action_open()
        other = self.env['res.company'].create({'name': 'Other plan company'})
        self.user.write({'company_ids': [(4, other.id)]})
        other_unit = self.env['erp.organization.unit'].create({'name': 'Other plan OU', 'code': 'OTHER', 'company_id': other.id})
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': other_unit.id})
        other_period = self.env['erp.budget.period'].create({'name': 'Other plan period', 'company_id': other.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
        other_analytic = self.env['account.analytic.account'].create({'name': 'Other company analytic', 'plan_id': self.plan.id, 'company_id': other.id})
        both = self.env(user=self.user, context={'allowed_company_ids': [self.company.id, other.id]})
        foreign_plan = both['erp.budget.plan'].create({'name': 'Other plan', 'company_id': other.id, 'period_id': other_period.id, 'line_ids': [(0, 0, {'organization_id': other_unit.id, 'analytic_id': other_analytic.id, 'initial_amount': 100})]})
        foreign_plan.action_confirm()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            line.with_context(allowed_company_ids=[self.company.id, other.id]).action_transfer(foreign_plan.line_ids.id, 1)
        self.assertEqual(line._ceiling(), 100)

    def test_same_analytic_shared_across_organizations(self):
        env, plan, line = self._setup_plan()
        other_unit = self.env['erp.organization.unit'].create({'name': 'Other budget OU', 'code': 'OU2', 'company_id': self.company.id})
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': other_unit.id})
        other_fund = self.env['erp.budget.fund'].create({'name': 'Other OU fund', 'company_id': self.company.id, 'group_id': self.group.id})
        values = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': other_unit.id, 'analytic_id': self.analytic.id, 'amount': 100}
        second = env['erp.budget.control'].create([dict(values, name='Other OU analytic', level='analytic'), dict(values, name='Other OU fund', level='fund', fund_id=other_fund.id)])
        second.action_open()
        service = env['erp.budget.control.service']
        service._commit(env['erp.budget.control'].browse((self.a | self.f).ids), 60, self.day, 'shared-ou:A')
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(second, 41, self.day, 'shared-ou:B')
        service._commit(second, 40, self.day, 'shared-ou:C')
        self.assertEqual(line._consumed(), 100)
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id), ('unit_id', '=', other_unit.id)]).unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            line._consumed()
        with self.assertRaises(AccessError), self.cr.savepoint():
            line.action_increase(10)

    def test_draft_states_and_adjustment_wizard(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        plan = env['erp.budget.plan'].create({'name': 'Plan workflow', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        plan.action_cancel()
        self.assertEqual(plan.state, 'cancel')
        plan.action_draft()
        plan.action_confirm()
        with self.assertRaises(UserError), self.cr.savepoint():
            plan.action_cancel()
        line = plan.line_ids
        adjustment = env['erp.budget.plan.adjustment'].create({'source_id': line.id, 'kind': 'increase', 'amount': 50, 'reference': 'approved supplement'})
        adjustment.action_apply()
        self.assertEqual(line._ceiling(), 150)
        self.assertEqual(self.env['erp.budget.plan.event'].sudo().search_count([('destination_id', '=', line.id), ('kind', '=', 'increase')]), 1)

    def test_transfer_reversal_is_atomic_and_idempotent(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        second_analytic = self.env['account.analytic.account'].create({'name': 'Reversal analytic', 'plan_id': self.plan.id, 'company_id': self.company.id})
        plan = env['erp.budget.plan'].create({'name': 'Transfer reversal plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': second_analytic.id, 'initial_amount': 0})]})
        plan.action_confirm()
        first = plan.line_ids.filtered(lambda line: line.analytic_id == self.analytic)
        second = plan.line_ids - first
        first.action_transfer(second.id, 20, 'transfer reference')
        event = env['erp.budget.plan.event'].search([('source_id', '=', first.id), ('kind', '=', 'transfer')])
        self.assertEqual(len(event), 1)
        vals = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': second_analytic.id, 'amount': 20}
        controls = env['erp.budget.control'].create([dict(vals, name='Destination analytic', level='analytic'), dict(vals, name='Destination fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        service = env['erp.budget.control.service']
        service._commit(controls, 20, self.day, 'transfer:consumption')
        with self.assertRaises(UserError), self.cr.savepoint():
            event.action_reverse_transfer()
        self.assertEqual((first._ceiling(), second._ceiling()), (80, 20))
        service._reverse(controls, 'transfer:consumption')
        event.action_reverse_transfer()
        event.action_reverse_transfer()
        self.assertEqual((first._ceiling(), second._ceiling()), (100, 0))
        reverse = env['erp.budget.plan.event'].search([('reversal_of_id', '=', event.id)])
        self.assertEqual(len(reverse), 1)
        self.assertEqual((reverse.kind, reverse.amount, reverse.source_id, reverse.destination_id), ('transfer_reversal', 20, second, first))
        with self.assertRaises(UserError), self.cr.savepoint():
            reverse.action_reverse_transfer()
        with self.assertRaises(AccessError), self.cr.savepoint():
            reverse.write({'amount': 1})

    def test_version_snapshot_stale_and_consumption(self):
        env, plan, line = self._setup_plan()
        controls = env['erp.budget.control'].browse((self.a | self.f).ids)
        env['erp.budget.control.service']._commit(controls, 80, self.day, 'version:committed')
        first_action = plan.with_context(default_approved_by_id=self.user.id, default_is_baseline=True).action_prepare_revision()
        first = env['erp.budget.plan.version'].browse(first_action['res_id'])
        competing = env['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
        baseline = first.base_version_id
        self.assertTrue(baseline.is_baseline)
        self.assertEqual(baseline.approved_by_id, self.user)
        self.assertEqual((baseline.state, baseline.line_ids.amount), ('effective', 100))
        first.write({'reason': 'Increase appropriation'})
        first.line_ids.write({'amount': 150})
        first.action_activate()
        self.assertEqual((baseline.state, first.state, line._ceiling(), line._consumed()), ('superseded', 'effective', 150, 80))
        self.assertEqual(first.approved_by_id, self.user)
        self.assertEqual(env['erp.budget.plan.version'].search_count([('plan_id', '=', plan.id), ('state', '=', 'effective')]), 1)
        competing.write({'reason': 'Old competing revision'})
        with self.assertRaises(UserError), self.cr.savepoint():
            competing.action_activate()
        with self.assertRaises(AccessError), self.cr.savepoint():
            baseline.line_ids.write({'amount': 1})
        next_version = env['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
        next_version.write({'reason': 'Decrease below commitments'})
        next_version.line_ids.write({'amount': 60})
        with self.assertRaises(UserError), self.cr.savepoint():
            next_version.action_activate()
        self.assertEqual((line._ceiling(), line._consumed()), (150, 80))
        self.assertEqual(env['erp.budget.plan.event'].search_count([('version_id', '=', first.id)]), 1)
        next_version.action_cancel()
        self.assertEqual(next_version.state, 'cancel')

    def test_version_stale_after_adjustment(self):
        env, plan, line = self._setup_plan()
        draft = env['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
        draft.write({'reason': 'Prepared revision'})
        line.action_increase(10, 'Intervening amendment')
        with self.assertRaises(UserError), self.cr.savepoint():
            draft.action_activate()
        self.assertEqual(line._ceiling(), 110)

    def test_formal_kpi_release_and_reversal(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        analytic = self.env['account.analytic.account'].create({'name': 'Release analytic', 'plan_id': self.plan.id, 'company_id': self.company.id})
        plan = env['erp.budget.plan'].create({'name': 'Release plan', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': analytic.id, 'initial_amount': 100, 'allocation_mode': 'allocated', 'release_required': True})]})
        plan.action_confirm()
        cap = plan.line_ids.filtered(lambda row: row.analytic_id == analytic)
        kpis = self.env['erp.budget.kpi'].create([{'name': 'Release A', 'company_id': self.company.id}, {'name': 'Release B', 'company_id': self.company.id}])
        vals = {'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': analytic.id}
        a, b, fund = env['erp.budget.control'].create([dict(vals, name='KPI A', level='analytic', kpi_id=kpis[0].id, amount=40), dict(vals, name='KPI B', level='analytic', kpi_id=kpis[1].id, amount=30), dict(vals, name='Release fund', level='fund', fund_id=self.fund.id, amount=100)])
        fund.action_open()
        with self.assertRaises(AccessError), self.cr.savepoint():
            a.action_open()
        reviewer_group = self.env.ref('erp_budget.group_budget_manager')
        reviewers = self.env['res.users'].create([{'name': 'Budget reviewer A', 'login': 'budget_review_a', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [reviewer_group.id])]}, {'name': 'Budget reviewer B', 'login': 'budget_review_b', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [reviewer_group.id])]}])
        for reviewer in reviewers:
            self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.budget.kpi.tier'].create([{'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': 10, 'reviewer_id': reviewers[0].id}, {'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': 20, 'reviewer_id': reviewers[1].id}])
        release = env['erp.budget.kpi.release'].create({'name': 'Release 70', 'plan_line_id': cap.id, 'released_amount': 71, 'line_ids': [(0, 0, {'control_id': a.id}), (0, 0, {'control_id': b.id})]})
        self.assertEqual((a.state, b.state), ('draft', 'draft'))
        with self.assertRaises(AccessError), self.cr.savepoint():
            release.action_release()
        with self.assertRaises(AccessError), self.cr.savepoint():
            env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': 30, 'reviewer_id': self.user.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            release.with_context(default_state='approved').action_submit()
        release.released_amount = 70
        release.with_context(default_state='approved').action_submit()
        self.assertEqual(set(release.review_ids.mapped('state')), {'pending'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            release.action_approve()
        wrong_company = self.env['res.company'].create({'name': 'Wrong reviewer company'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            release.with_user(reviewers[0]).with_context(allowed_company_ids=[wrong_company.id]).action_approve()
        rev1 = release.with_user(reviewers[0]).with_context(allowed_company_ids=[self.company.id])
        rev2 = release.with_user(reviewers[1]).with_context(allowed_company_ids=[self.company.id])
        with self.assertRaises(AccessError), self.cr.savepoint():
            rev2.action_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            a.write({'amount': 41})
        rev1.action_approve()
        # Simulate out-of-band corruption: final review must recheck totals too.
        self.env.cr.execute('UPDATE erp_budget_kpi_release SET released_amount = 71 WHERE id = %s', [release.id])
        release.invalidate_recordset(['released_amount'])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rev2.action_approve()
        self.assertEqual(release.state, 'submit')
        rev2.action_reject()
        release.action_draft()
        release.released_amount = 70
        release.action_submit()
        rev1.action_approve()
        rev1.action_approve()
        rev2.action_approve()
        rev2.action_approve()
        self.assertEqual(len(release.review_ids), 4)
        with self.assertRaises(AccessError), self.cr.savepoint():
            release.review_ids.sudo().write({'state': 'approved'})
        self.assertEqual((release.state, a.state, b.state, cap._allocated()), ('done', 'open', 'open', 70))
        with self.assertRaises(AccessError), self.cr.savepoint():
            a.action_close()
        service = env['erp.budget.control.service']
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(a | fund, 50, self.day, 'release:too-much')
        service._commit(a | fund, 40, self.day, 'release:use')
        with self.assertRaises(UserError), self.cr.savepoint():
            release.action_reverse()
        self.assertEqual((release.state, a.state, cap._consumed()), ('done', 'open', 40))
        service._reverse(a | fund, 'release:use')
        release.action_reverse()
        release.action_reverse()
        self.assertEqual((release.state, a.state, b.state, cap._allocated()), ('reversed', 'closed', 'closed', 0))
        with self.assertRaises(AccessError), self.cr.savepoint():
            release.write({'released_amount': 1})

    def test_formal_period_policy_cannot_be_bypassed(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            env['erp.budget.period'].browse(self.period.id).write({'release_policy': 'formal'})
        self.period.write({'release_policy': 'formal'})
        plan = env['erp.budget.plan'].create({'name': 'Required releases', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            plan.action_confirm()
        self.assertFalse(self.period.plan_enforced)

    def test_hidden_archived_control_is_in_scope_for_plan_changes(self):
        env, plan, line = self._setup_plan()
        other = self.env['erp.organization.unit'].create({'name': 'Hidden archive OU', 'code': 'HAOU', 'company_id': self.company.id})
        self.env['erp.budget.control'].sudo().create({'name': 'Hidden inactive analytic', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': other.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'amount': 10, 'active': False})
        with self.assertRaises(AccessError), self.cr.savepoint():
            line.action_increase(1)

    def test_effective_snapshot_is_anchor_for_capacity(self):
        env, plan, line = self._setup_plan()
        line.action_increase(20, 'Prior event')
        version = env['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
        self.assertEqual((version.base_version_id.snapshot_anchor, version.base_version_id.line_ids.amount, line._ceiling()), (True, 100, 120))
        version.write({'reason': 'Replace full snapshot'})
        version.line_ids.write({'amount': 150})
        version.action_activate()
        self.assertTrue(version.snapshot_anchor)
        self.assertEqual(line._ceiling(), 150)
        # Simulate a stale stored initial value; effective capacity must use the snapshot.
        self.env.cr.execute('UPDATE erp_budget_plan_line SET initial_amount = 1 WHERE id = %s', [line.id])
        line.invalidate_recordset(['initial_amount'])
        self.assertEqual(line._ceiling(), 150)
        line.action_increase(10, 'Subsequent event')
        self.assertEqual(line._ceiling(), 160)
        later = env['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
        later.write({'reason': 'Next snapshot'})
        later.line_ids.write({'amount': 170})
        later.action_activate()
        self.assertEqual((version.state, later.state, line._ceiling()), ('superseded', 'effective', 170))

    def test_existing_unanchored_version_preserves_legacy_capacity(self):
        env, plan, line = self._setup_plan()
        version = env['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
        version.write({'reason': 'Old effective revision'})
        version.line_ids.write({'amount': 150})
        version.action_activate()
        line.action_increase(10, 'Later legacy event')
        self.env.cr.execute('UPDATE erp_budget_plan_version SET snapshot_anchor = FALSE, event_cutoff = 0 WHERE id = %s', [version.id])
        version.invalidate_recordset(['snapshot_anchor', 'event_cutoff'])
        self.assertEqual(line._ceiling(), 160)
        later = env['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
        self.assertEqual(later.line_ids.amount, 160)
        later.write({'reason': 'Explicit new snapshot'})
        later.action_activate()
        self.assertTrue(later.snapshot_anchor)
        self.assertEqual(line._ceiling(), 160)

    def test_initial_fund_allocation_creates_protected_plan_and_controls(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        period = env['erp.budget.period'].create({'name': 'Initial allocation year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        second_fund = env['erp.budget.fund'].create({'name': 'Second allocation fund', 'company_id': self.company.id, 'group_id': self.group.id})
        doc = env['erp.budget.allocation'].create({'name': 'Source allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 40}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': second_fund.id, 'allocated_amount': 30})]})
        self.assertFalse(doc.plan_id)
        self.assertEqual(doc.line_ids.mapped('released_amount'), [0, 0])
        doc.action_done()
        self.assertEqual((doc.state, doc.plan_id.state, doc.plan_id.line_ids.initial_amount), ('done', 'draft', 70))
        self.assertEqual(sorted(doc.line_ids.mapped('released_amount')), [30, 40])
        self.assertEqual(set(doc.line_ids.mapped('control_id.state')), {'draft'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.plan_id.line_ids.write({'initial_amount': 100})
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.line_ids[0].control_id.write({'amount': 100})
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.line_ids[0].write({'allocated_amount': 100})
        with self.assertRaises(UserError), self.cr.savepoint():
            doc.line_ids.mapped('control_id').action_open()
        doc.plan_id.action_confirm()
        with self.assertRaises(UserError), self.cr.savepoint():
            doc.plan_id.action_prepare_revision()
        with self.assertRaises(UserError), self.cr.savepoint():
            doc.plan_id.line_ids.action_increase(1)
        doc.line_ids.mapped('control_id').action_open()
        analytic = env['erp.budget.control'].create({'name': 'Analytic allocation', 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'amount': 70})
        analytic.action_open()
        fund = doc.line_ids.filtered(lambda x: x.fund_id == self.fund).control_id
        service = env['erp.budget.control.service']
        service._commit(analytic | fund, 40, '2027-06-01', 'initial-allocation:commit')
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(analytic | fund, 1, '2027-06-01', 'initial-allocation:excess')
        self.assertEqual((doc.plan_id.line_ids._ceiling(), doc.plan_id.line_ids._consumed()), (70, 40))
        rogue = env['erp.budget.control'].create({'name': 'Unbacked fund', 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'fund', 'fund_id': self.fund.id, 'amount': 100})
        with self.assertRaises(AccessError), self.cr.savepoint():
            rogue.action_open()
        with self.assertRaises(UserError), self.cr.savepoint():
            doc.action_cancel()

    def test_allocation_rejects_existing_period_configuration(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        doc = env['erp.budget.allocation'].create({'name': 'Existing period', 'company_id': self.company.id, 'period_id': self.period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 50})]})
        with self.assertRaises(UserError), self.cr.savepoint():
            doc.action_done()
        self.assertEqual((doc.state, bool(doc.plan_id), doc.line_ids.released_amount), ('draft', False, 0))

    def test_allocation_rejects_hidden_organization_and_foreign_fund(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        period = env['erp.budget.period'].create({'name': 'Allocation security year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        doc = env['erp.budget.allocation'].create({'name': 'Scoped allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 40})]})
        other_unit = self.env['erp.organization.unit'].create({'name': 'Hidden allocation unit', 'code': 'HIDA', 'company_id': self.company.id})
        analytic = self.env['account.analytic.account'].create({'name': 'Hidden allocation analytic', 'plan_id': self.plan.id, 'company_id': self.company.id})
        self.env['erp.budget.allocation.line'].sudo().create({'allocation_id': doc.id, 'organization_id': other_unit.id, 'analytic_id': analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 20})
        with self.assertRaises(AccessError), self.cr.savepoint():
            doc.action_done()
        self.assertEqual((doc.state, bool(doc.plan_id)), ('draft', False))
        other_company = self.env['res.company'].create({'name': 'Foreign allocation company'})
        other_group = self.env['erp.budget.fund.group'].create({'name': 'Foreign allocation group', 'company_id': other_company.id})
        other_fund = self.env['erp.budget.fund'].create({'name': 'Foreign allocation fund', 'company_id': other_company.id, 'group_id': other_group.id})
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            env['erp.budget.allocation.line'].create({'allocation_id': doc.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': other_fund.id, 'allocated_amount': 1})

    def test_allocation_revision_preserves_consumption_and_history(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        period = env['erp.budget.period'].create({'name': 'Revision allocation year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        doc = env['erp.budget.allocation'].create({'name': 'Revised allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        doc.action_done()
        doc.plan_id.action_confirm()
        fund = doc.line_ids.control_id
        fund.action_open()
        analytic = env['erp.budget.control'].create({'name': 'Revised analytic', 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'amount': 80})
        analytic.action_open()
        env['erp.budget.control.service']._commit(analytic | fund, 60, '2027-06-01', 'allocation-revision:commit')
        moves = self.env['erp.budget.move'].sudo().search([('origin_key', '=', 'allocation-revision:commit')]).ids
        version = env['erp.budget.allocation.revision'].browse(doc.with_context(default_activated_by_id=self.user.id).action_prepare_allocation_revision()['res_id'])
        competing = env['erp.budget.allocation.revision'].browse(doc.action_prepare_allocation_revision()['res_id'])
        self.assertFalse(version.activated_by_id)
        self.assertEqual((version.line_ids.amount, fund.amount, doc.plan_id.line_ids._ceiling()), (100, 100, 100))
        version.write({'reason': 'Reduce to 80'})
        version.line_ids.write({'amount': 80})
        with self.assertRaises(AccessError), self.cr.savepoint():
            version.plan_version_id.action_activate()
        version.action_activate()
        self.assertEqual((version.state, version.plan_version_id.state, fund.amount, doc.plan_id.line_ids._ceiling(), doc.plan_id.line_ids._consumed()), ('effective', 'effective', 80, 80, 60))
        self.assertEqual((doc.line_ids.allocated_amount, doc.line_ids.released_amount), (100, 100))
        self.assertEqual(self.env['erp.budget.move'].sudo().search([('origin_key', '=', 'allocation-revision:commit')]).ids, moves)
        with self.assertRaises(AccessError), self.cr.savepoint():
            version.line_ids.write({'amount': 1})
        competing.write({'reason': 'Stale revision'})
        with self.assertRaises(UserError), self.cr.savepoint():
            competing.action_activate()
        next_version = env['erp.budget.allocation.revision'].browse(doc.action_prepare_allocation_revision()['res_id'])
        self.assertEqual((next_version.previous_id, next_version.line_ids.base_amount), (version, 80))
        next_version.write({'reason': 'Unsafe decrease'})
        next_version.line_ids.write({'amount': 50})
        with self.assertRaises(UserError), self.cr.savepoint():
            next_version.action_activate()
        self.assertEqual((fund.amount, doc.plan_id.line_ids._ceiling()), (80, 80))
        next_version.line_ids.write({'amount': 120})
        next_version.write({'reason': 'Increase'})
        next_version.action_activate()
        self.assertEqual((version.state, next_version.state, fund.amount, doc.plan_id.line_ids._ceiling()), ('superseded', 'effective', 120, 120))
        self.assertEqual(env['erp.budget.allocation.revision'].search_count([('allocation_id', '=', doc.id), ('state', '=', 'effective')]), 1)
        removal = env['erp.budget.allocation.revision'].browse(doc.action_prepare_allocation_revision()['res_id'])
        removal.write({'reason': 'Remove fund capacity'})
        removal.line_ids.write({'amount': 0})
        with self.assertRaises(UserError), self.cr.savepoint():
            removal.action_activate()
        self.assertEqual((fund.amount, doc.plan_id.line_ids._consumed()), (120, 60))
        env['erp.budget.control.service']._reverse(analytic | fund, 'allocation-revision:commit')
        removal.action_activate()
        self.assertEqual((fund.amount, doc.plan_id.line_ids._ceiling(), doc.plan_id.line_ids._consumed()), (0, 0, 0))
        with self.assertRaises(UserError), self.cr.savepoint():
            env['erp.budget.control.service']._commit(analytic | fund, 1, '2027-06-01', 'allocation-revision:removed')
        self.assertEqual((doc.line_ids.allocated_amount, doc.line_ids.released_amount), (100, 100))

    def test_source_allocation_requires_complete_kpi_planning(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        period = self.env['erp.budget.period'].create({'name': 'Source KPI planning year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31', 'release_policy': 'formal'})
        allocation = env['erp.budget.allocation'].create({'name': 'Source KPI allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        cap = allocation.plan_id.line_ids
        kpis = self.env['erp.budget.kpi'].create([{'name': 'Planning A', 'company_id': self.company.id}, {'name': 'Planning B', 'company_id': self.company.id}, {'name': 'Planning C', 'company_id': self.company.id}])
        base = {'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic'}
        controls = env['erp.budget.control'].create([dict(base, name='Planning A', kpi_id=kpis[0].id, amount=40), dict(base, name='Planning B', kpi_id=kpis[1].id, amount=30), dict(base, name='Planning C', kpi_id=kpis[2].id, amount=30)])
        reviewer = self.env['res.users'].create({'name': 'Planning reviewer', 'login': 'source_planning_reviewer', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': 10, 'reviewer_id': reviewer.id})
        release = env['erp.budget.kpi.release'].create({'name': 'Incomplete KPI plan', 'plan_line_id': cap.id, 'released_amount': 70, 'line_ids': [(0, 0, {'control_id': controls[0].id}), (0, 0, {'control_id': controls[1].id})]})
        with self.assertRaises(UserError), self.cr.savepoint():
            release.action_submit()
        self.assertEqual((release.state, cap._allocated()), ('draft', 0))
        release.write({'released_amount': 100, 'line_ids': [(0, 0, {'control_id': controls[2].id})]})
        release.action_submit()
        release.with_user(reviewer).with_context(allowed_company_ids=[self.company.id]).action_approve()
        self.assertEqual((release.state, cap._allocated(), cap._ceiling()), ('done', 100, 100))
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Increase requires new KPI planning'})
        revision.line_ids.write({'amount': 120})
        with self.assertRaises(UserError), self.cr.savepoint():
            revision.action_activate()
        self.assertEqual((revision.state, cap._ceiling(), allocation.line_ids.control_id.amount), ('draft', 100, 100))

    def _setup_dimension_allocation(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        period = env['erp.budget.period'].create({'name': 'Dimension revision year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        allocation = env['erp.budget.allocation'].create({'name': 'Dimension allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        allocation.line_ids.control_id.action_open()
        return env, allocation

    def test_revision_adds_new_analytic_without_changing_draft_capacity(self):
        env, allocation = self._setup_dimension_allocation()
        old_line, old_control = allocation.line_ids, allocation.line_ids.control_id
        analytic = self.env['account.analytic.account'].create({'name': 'Added analytic', 'company_id': self.company.id, 'plan_id': self.plan.id})
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        row = env['erp.budget.allocation.revision.line'].browse(revision.action_add_dimension(self.unit.id, analytic.id, self.fund.id, 50))
        self.assertFalse(row.allocation_line_id.control_id)
        self.assertEqual((len(allocation.plan_id.line_ids), old_control.amount), (1, 100))
        revision.write({'reason': 'Add funded analytic'})
        revision.action_activate()
        new_control = row.allocation_line_id.control_id
        new_cap = allocation.plan_id.line_ids.filtered(lambda line: line.analytic_id == analytic)
        self.assertEqual((new_control.state, new_control.amount, new_cap._ceiling(), new_cap.initial_amount), ('open', 50, 50, 0))
        self.assertEqual((old_control.amount, old_line.allocated_amount, len(revision.plan_version_id.base_version_id.line_ids)), (100, 100, 1))
        later = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        self.assertEqual(set(later.line_ids.mapped('allocation_line_id').ids), set(allocation.line_ids.ids))
        self.assertEqual(len(later.plan_version_id.line_ids), 2)
        with self.assertRaises(AccessError), self.cr.savepoint():
            new_cap.write({'initial_amount': 500})

    def test_dimension_replacement_preserves_consumed_history(self):
        env, allocation = self._setup_dimension_allocation()
        source, fund_control = allocation.line_ids, allocation.line_ids.control_id
        analytic_control = env['erp.budget.control'].create({'name': 'Dimension analytic', 'company_id': self.company.id, 'period_id': allocation.period_id.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'amount': 100})
        analytic_control.action_open()
        service = env['erp.budget.control.service']
        service._commit(analytic_control | fund_control, 60, '2027-06-01', 'dimension:consumed')
        old_moves = self.env['erp.budget.move'].sudo().search([('origin_key', '=', 'dimension:consumed')]).ids
        new_fund = env['erp.budget.fund'].create({'name': 'Replacement fund', 'company_id': self.company.id, 'group_id': self.group.id})
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Replace fund'})
        revision.line_ids.write({'amount': 0, 'excluded': True})
        row = env['erp.budget.allocation.revision.line'].browse(revision.action_add_dimension(self.unit.id, self.analytic.id, new_fund.id, 100))
        with self.assertRaises(UserError), self.cr.savepoint():
            revision.action_activate()
        self.assertFalse(row.allocation_line_id.control_id)
        self.assertEqual(fund_control.amount, 100)
        service._reverse(analytic_control | fund_control, 'dimension:consumed')
        revision.action_activate()
        self.assertEqual((source.allocated_amount, source.released_amount, fund_control.amount), (100, 100, 0))
        self.assertEqual(self.env['erp.budget.move'].sudo().browse(old_moves).exists().ids, old_moves)
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(analytic_control | fund_control, 1, '2027-06-01', 'dimension:removed')
        service._commit(analytic_control | row.allocation_line_id.control_id, 100, '2027-06-01', 'dimension:replacement')
        self.assertEqual(allocation.plan_id.line_ids._consumed(), 100)
        later = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        self.assertTrue(later.line_ids.filtered(lambda line: line.allocation_line_id == source).excluded)

    def test_new_dimension_security_uniqueness_and_cancel(self):
        env, allocation = self._setup_dimension_allocation()
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            revision.action_add_dimension(self.unit.id, self.analytic.id, self.fund.id, 50)
        hidden = self.env['erp.organization.unit'].create({'name': 'Hidden revision OU', 'code': 'HREV', 'company_id': self.company.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            revision.action_add_dimension(hidden.id, self.analytic.id, self.fund.id, 50)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            revision.action_add_dimension(self.unit.id, self.analytic.id, self.fund.id, 50, [self.analytic.id])
        dimension_plan = self.env['account.analytic.plan'].create({'name': 'Allocation dimension root'})
        dimension = self.env['account.analytic.account'].create({'name': 'Allocation extra dimension', 'plan_id': dimension_plan.id, 'company_id': self.company.id})
        row = env['erp.budget.allocation.revision.line'].browse(revision.action_add_dimension(self.unit.id, self.analytic.id, self.fund.id, 50, [dimension.id]))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            revision.action_add_dimension(self.unit.id, self.analytic.id, self.fund.id, 50, [dimension.id])
        revision.action_cancel()
        self.assertFalse(row.allocation_line_id.control_id)
        self.assertEqual((allocation.plan_id.line_ids._ceiling(), len(allocation.line_ids.filtered('control_id'))), (100, 1))
        later = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        self.assertEqual(len(later.line_ids), 1)
        replacement = env['erp.budget.allocation.revision.line'].browse(later.action_add_dimension(self.unit.id, self.analytic.id, self.fund.id, 25, [dimension.id]))
        self.assertEqual(replacement.allocation_line_id, row.allocation_line_id)
        later.write({'reason': 'Retry cancelled dimension'})
        later.action_activate()
        self.assertEqual(replacement.allocation_line_id.control_id.amount, 25)
        self.assertEqual((revision.state, row.amount), ('cancel', 50))
        with self.assertRaises(UserError), self.cr.savepoint():
            revision.action_add_dimension(self.unit.id, self.analytic.id, self.fund.id, 50, [])

    def test_initial_balance_is_floor_without_adding_capacity(self):
        env, plan, cap = self._setup_plan(100)
        opening = env['erp.budget.opening.balance'].create({'reference': 'opening:source-1', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_available': 30, 'initial_commit': 20})
        self.assertEqual(cap._opening_minimum(), 0)
        opening.action_confirm()
        opening.action_confirm()
        self.assertEqual((cap._opening_minimum(), cap._ceiling(), cap._consumed()), (50, 100, 0))
        service = env['erp.budget.control.service']
        service._check_available(env['erp.budget.control'].browse((self.a | self.f).ids), 100, self.day)
        with self.assertRaises(UserError), self.cr.savepoint():
            service._check_available(env['erp.budget.control'].browse((self.a | self.f).ids), 101, self.day)
        with self.assertRaises(UserError), self.cr.savepoint():
            cap.action_decrease(51)
        version = env['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
        version.write({'reason': 'Opening lower bound'})
        version.line_ids.write({'amount': 49})
        with self.assertRaises(UserError), self.cr.savepoint():
            version.action_activate()
        self.assertEqual((cap._ceiling(), opening.state), (100, 'done'))
        with self.assertRaises(AccessError), self.cr.savepoint():
            opening.write({'initial_available': 0})
        with self.assertRaises(UserError), self.cr.savepoint():
            opening.action_cancel()

    def test_initial_balance_before_allocation_and_revision(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        period = env['erp.budget.period'].create({'name': 'Opening allocation year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        opening = env['erp.budget.opening.balance'].create({'reference': 'opening:carry-1', 'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_available': 30, 'initial_commit': 20})
        opening.action_confirm()
        allocation = env['erp.budget.allocation'].create({'name': 'Opening supported allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Opening reconciliation decrease'})
        revision.line_ids.write({'amount': 40})
        with self.assertRaises(UserError), self.cr.savepoint():
            revision.action_activate()
        self.assertEqual((allocation.plan_id.line_ids._ceiling(), allocation.line_ids.control_id.amount), (100, 100))
        revision.line_ids.write({'amount': 50})
        revision.action_activate()
        self.assertEqual((allocation.plan_id.line_ids._ceiling(), allocation.line_ids.control_id.amount), (50, 50))

    def test_opening_confirmation_checks_company_scope_and_floor(self):
        env, plan, cap = self._setup_plan(100)
        vals = {'reference': 'opening:oversized', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_available': 101, 'initial_commit': 0}
        opening = env['erp.budget.opening.balance'].create(vals)
        with self.assertRaises(UserError), self.cr.savepoint():
            opening.action_confirm()
        self.assertEqual((opening.state, cap._ceiling(), cap._opening_minimum()), ('draft', 100, 0))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            opening.write({'initial_commit': -1})
        hidden = self.env['erp.organization.unit'].create({'name': 'Hidden opening unit', 'code': 'HOPEN', 'company_id': self.company.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            env['erp.budget.opening.balance'].create(dict(vals, reference='opening:hidden', organization_id=hidden.id))
        other_company = self.env['res.company'].create({'name': 'Opening foreign company'})
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            env['erp.budget.opening.balance'].create(dict(vals, reference='opening:foreign', company_id=other_company.id))
        with self.assertRaises(AccessError), self.cr.savepoint():
            opening.with_context(default_state='done').create(dict(vals, reference='opening:forged'))

    def _setup_source_planning_versions(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        period = self.env['erp.budget.period'].create({'name': 'Canonical planning year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31', 'release_policy': 'formal'})
        allocation = env['erp.budget.allocation'].create({'name': 'Canonical allocation', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'fund_id': self.fund.id, 'allocated_amount': 100})]})
        allocation.action_done()
        allocation.plan_id.action_confirm()
        allocation.line_ids.control_id.action_open()
        kpis = self.env['erp.budget.kpi'].create([{'name': name, 'company_id': self.company.id} for name in ('Canonical A', 'Canonical B')])
        base = {'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic'}
        controls = env['erp.budget.control'].create([dict(base, name='Canonical A', kpi_id=kpis[0].id, amount=40), dict(base, name='Canonical B', kpi_id=kpis[1].id, amount=60)])
        reviewers = self.env['res.users'].create([{'name': 'Canonical reviewer '+str(index), 'login': 'canonical_planning_reviewer_'+str(index), 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_budget.group_budget_manager').id])]} for index in (1, 2)])
        for index, reviewer in enumerate(reviewers, 1):
            self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
            self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'sequence': index * 10, 'reviewer_id': reviewer.id})
        release = env['erp.budget.kpi.release'].create({'name': 'Canonical initial control', 'plan_line_id': allocation.plan_id.line_ids.id, 'released_amount': 100, 'line_ids': [(0, 0, {'control_id': control.id}) for control in controls]})
        release.action_submit()
        for reviewer in reviewers:
            release.with_user(reviewer).with_context(allowed_company_ids=[self.company.id]).action_approve()
        return env, allocation, release, reviewers

    def test_ordered_control_revision_preserves_snapshot_and_ledger(self):
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        controls, fund = release.line_ids.mapped('control_id'), allocation.line_ids.control_id
        service = env['erp.budget.control.service']
        service._commit(controls[:1] | fund, 35, '2027-06-01', 'planning:existing')
        moves = self.env['erp.budget.move'].sudo().search([('origin_key', '=', 'planning:existing')]).ids
        revision = env['erp.budget.kpi.release'].browse(release.with_context(default_state='done', default_released_by_id=self.user.id, default_review_round=99).action_prepare_revision()['res_id'])
        self.assertEqual((revision.state, revision.review_round, revision.released_by_id.id), ('draft', 0, False))
        competing = env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        revision.line_ids[0].write({'amount': 50})
        revision.line_ids[1].write({'amount': 50})
        revision.action_submit()
        with self.assertRaises(AccessError), self.cr.savepoint():
            revision.action_release()
        with self.assertRaises(AccessError), self.cr.savepoint():
            revision.with_user(reviewers[1]).action_approve()
        with self.assertRaises(AccessError), self.cr.savepoint():
            revision.action_approve()
        revision.with_user(reviewers[0]).action_approve()
        self.assertEqual((revision.state, controls.mapped('amount')), ('submit', [40, 60]))
        revision.with_user(reviewers[1]).action_approve()
        revision.with_user(reviewers[1]).action_approve()
        self.assertEqual((revision.state, release.state, revision.version_number, controls.mapped('amount')), ('done', 'superseded', 1, [50, 50]))
        self.assertEqual(release.line_ids.mapped('amount'), [40, 60])
        self.assertEqual(self.env['erp.budget.move'].sudo().browse(moves).exists().ids, moves)
        with self.assertRaises(UserError), self.cr.savepoint():
            competing.action_submit()
        lower = env['erp.budget.kpi.release'].browse(revision.action_prepare_revision()['res_id'])
        lower.line_ids[0].write({'amount': 30})
        lower.line_ids[1].write({'amount': 70})
        with self.assertRaises(UserError), self.cr.savepoint():
            lower.action_submit()
        self.assertEqual((controls.mapped('amount'), allocation.plan_id.line_ids._ceiling()), ([50, 50], 100))

    def test_coordinated_allocation_and_planning_revision(self):
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Coordinated increase'})
        revision.line_ids.write({'amount': 120})
        planning = env['erp.budget.kpi.release'].browse(release.action_prepare_revision(revision.id)['res_id'])
        planning.write({'released_amount': 120})
        planning.line_ids[0].write({'amount': 50})
        planning.line_ids[1].write({'amount': 70})
        planning.action_submit()
        with self.assertRaises(UserError), self.cr.savepoint():
            revision.action_activate()
        for reviewer in reviewers:
            planning.with_user(reviewer).action_approve()
        self.assertEqual((planning.state, allocation.plan_id.line_ids._ceiling(), release.line_ids.mapped('control_id.amount')), ('approved', 100, [40, 60]))
        revision.action_activate()
        self.assertEqual((planning.state, release.state, allocation.plan_id.line_ids._ceiling(), allocation.line_ids.control_id.amount), ('done', 'superseded', 120, 120))
        self.assertEqual(planning.line_ids.mapped('control_id.amount'), [50, 70])
        self.assertEqual(planning.plan_version_id, revision.plan_version_id)
        decrease = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        decrease.write({'reason': 'Coordinated decrease'})
        decrease.line_ids.write({'amount': 80})
        successor = env['erp.budget.kpi.release'].browse(planning.action_prepare_revision(decrease.id)['res_id'])
        successor.write({'released_amount': 80})
        successor.line_ids.write({'amount': 40})
        successor.action_submit()
        for reviewer in reviewers:
            successor.with_user(reviewer).action_approve()
        decrease.action_activate()
        self.assertEqual((allocation.plan_id.line_ids._ceiling(), allocation.line_ids.control_id.amount, successor.line_ids.mapped('control_id.amount')), (80, 80, [40, 40]))

    def test_planning_dates_are_metadata_and_past_lock_is_enforced(self):
        from unittest.mock import patch
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        revision = env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        row = revision.line_ids[0]
        row.write({'planning_ids': [(5, 0, 0), (0, 0, {'date_from': '2027-01-01', 'date_to': '2027-06-30', 'amount': 20}), (0, 0, {'date_from': '2027-07-01', 'date_to': '2027-12-31', 'amount': 20})]})
        revision.action_submit()
        for reviewer in reviewers:
            revision.with_user(reviewer).action_approve()
        env['erp.budget.control.service']._check_available(row.control_id | allocation.line_ids.control_id, 40, '2027-12-01')
        self.company.write({'erp_budget_planning_lock': 'last'})
        later = env['erp.budget.kpi.release'].browse(revision.action_prepare_revision()['res_id'])
        with patch('odoo.fields.Date.context_today', return_value=self.day.replace(year=2027)):
            with self.assertRaises(UserError), self.cr.savepoint():
                later.line_ids[0].planning_ids[0].with_context(edit_amount=1).write({'amount': 1})
        self.assertEqual(later.line_ids[0].planning_ids.mapped('amount'), [20, 20])

    def test_control_revision_adds_and_removes_kpi_with_current_access(self):
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        revision = env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        omitted_control = revision.line_ids[1].control_id
        revision.line_ids[1].unlink()
        kpi = env['erp.budget.kpi'].create({'name': 'Replacement KPI', 'company_id': self.company.id})
        control = env['erp.budget.control'].create({'name': 'Replacement planning control', 'company_id': self.company.id, 'period_id': allocation.period_id.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'kpi_id': kpi.id, 'amount': 60})
        env['erp.budget.kpi.release.line'].create({'release_id': revision.id, 'control_id': control.id})
        revision.action_submit()
        revision.with_user(reviewers[0]).action_reject()
        self.assertEqual((revision.state, release.state, omitted_control.amount, control.state), ('cancel', 'done', 60, 'draft'))
        revision.action_draft()
        revision.action_submit()
        wrong_company = self.env['res.company'].create({'name': 'Wrong planning review company'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            revision.with_user(reviewers[0]).with_context(allowed_company_ids=[wrong_company.id]).action_approve()
        revision.with_user(reviewers[0]).action_approve()
        assignment = self.env['erp.organization.assignment'].search([('user_id', '=', reviewers[1].id), ('unit_id', '=', self.unit.id)])
        assignment.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            revision.with_user(reviewers[1]).action_approve()
        self.env['erp.organization.assignment'].create({'user_id': reviewers[1].id, 'unit_id': self.unit.id})
        revision.with_user(reviewers[1]).action_approve()
        self.assertEqual((omitted_control.amount, omitted_control.state, control.amount, control.state), (0, 'closed', 60, 'open'))
        self.assertEqual((release.line_ids[1].amount, allocation.plan_id.line_ids._allocated()), (60, 100))

    def test_planning_overlap_and_declared_amount_fail_before_review(self):
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        revision = env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        row = revision.line_ids[0]
        row.write({'planning_ids': [(5, 0, 0), (0, 0, {'date_from': '2027-01-01', 'date_to': '2027-06-30', 'amount': 20}), (0, 0, {'date_from': '2027-06-01', 'date_to': '2027-12-31', 'amount': 20})]})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            revision.action_submit()
        self.assertFalse(revision.review_ids)
        self.assertEqual((release.state, row.control_id.amount), ('done', 40))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            row.planning_ids[-1].write({'date_to': '2028-01-01'})

    def test_cancelling_joint_revision_keeps_effective_planning(self):
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        planning = env['erp.budget.kpi.release'].browse(release.action_prepare_revision(revision.id)['res_id'])
        planning.action_submit()
        for reviewer in reviewers:
            planning.with_user(reviewer).action_approve()
        planning.with_user(reviewers[-1]).action_approve()
        self.assertEqual(planning.state, 'approved')
        revision.action_cancel()
        self.assertEqual((planning.state, revision.state, release.state, release.line_ids.mapped('control_id.amount')), ('cancel', 'cancel', 'done', [40, 60]))
        self.assertEqual(set(planning.review_ids.mapped('state')), {'approved'})
        later = env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        self.assertEqual((planning.root_id, later.root_id, planning.version_number, later.version_number), (release, release, 1, 2))

    def test_initializing_commitments_changes_only_earliest_draft_planning(self):
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        control, fund = release.line_ids[0].control_id, allocation.line_ids.control_id
        env['erp.budget.control.service']._commit(control | fund, 15, '2027-06-01', 'planning:init-commitment')
        moves = self.env['erp.budget.move'].sudo().search([('origin_key', '=', 'planning:init-commitment')]).ids
        revision = env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        row = revision.line_ids[0]
        row.write({'planning_ids': [(5, 0, 0), (0, 0, {'date_from': '2027-01-01', 'date_to': '2027-06-30', 'amount': 20}), (0, 0, {'date_from': '2027-07-01', 'date_to': '2027-12-31', 'amount': 20})]})
        revision.action_initialize_commitments()
        self.assertEqual((row.amount, row.planning_ids.mapped('amount')), (35, [15, 20]))
        self.assertEqual((control.amount, allocation.plan_id.line_ids._consumed()), (40, 15))
        self.assertEqual(self.env['erp.budget.move'].sudo().browse(moves).exists().ids, moves)
        with self.assertRaises(UserError), self.cr.savepoint():
            revision.action_submit()

    def test_control_revision_rechecks_all_units_in_shared_analytic(self):
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        other_unit = self.env['erp.organization.unit'].create({'name': 'Shared planning unit', 'code': 'SPLAN', 'company_id': self.company.id})
        for user in self.user | reviewers[:1]:
            self.env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': other_unit.id})
        revision = env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        revision.line_ids[1].unlink()
        control = env['erp.budget.control'].create({'name': 'Shared-unit planning control', 'company_id': self.company.id, 'period_id': allocation.period_id.id, 'organization_id': other_unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'kpi_id': release.line_ids[0].control_id.kpi_id.id, 'amount': 60})
        env['erp.budget.kpi.release.line'].create({'release_id': revision.id, 'control_id': control.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            revision.action_submit()
        self.assertFalse(revision.review_ids)
        assignment = self.env['erp.organization.assignment'].create({'user_id': reviewers[1].id, 'unit_id': other_unit.id})
        revision.action_submit()
        revision.with_user(reviewers[0]).action_approve()
        assignment.unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            revision.with_user(reviewers[1]).action_approve()
        self.env['erp.organization.assignment'].create({'user_id': reviewers[1].id, 'unit_id': other_unit.id})
        revision.with_user(reviewers[1]).action_approve()
        self.assertEqual((revision.state, control.state, allocation.plan_id.line_ids._allocated()), ('done', 'open', 100))

    def test_source_allocation_cancel_and_reviewed_restoration(self):
        env, allocation, release, reviewers = self._setup_source_planning_versions()
        controls, fund = release.line_ids.mapped('control_id'), allocation.line_ids.control_id
        service = env['erp.budget.control.service']
        service._commit(controls[:1] | fund, 30, '2027-06-01', 'cancel:consumed')
        with self.assertRaises(UserError), self.cr.savepoint():
            allocation.action_cancel()
        service._reverse(controls[:1] | fund, 'cancel:consumed')
        moves = self.env['erp.budget.move'].sudo().search([('control_id', 'in', (controls | fund).ids)]).ids
        cancellation = env['erp.budget.allocation.revision'].browse(allocation.action_cancel()['res_id'])
        self.assertEqual((cancellation.revision_kind, allocation.state, fund.amount), ('cancel', 'done', 100))
        with self.assertRaises(UserError), self.cr.savepoint():
            cancellation.action_activate()
        zero = env['erp.budget.kpi.release'].browse(release.action_prepare_revision(cancellation.id)['res_id'])
        zero.write({'released_amount': 0})
        zero.line_ids.write({'amount': 0})
        zero.action_submit()
        for reviewer in reviewers:
            zero.with_user(reviewer).action_approve()
        cancellation.action_activate()
        self.assertEqual((allocation.state, allocation.plan_id.line_ids._ceiling(), fund.amount, fund.state), ('cancel', 0, 0, 'closed'))
        self.assertEqual(controls.mapped('state'), ['closed', 'closed'])
        self.assertEqual(set(cancellation.cancelled_control_ids.ids), set((controls | fund).ids))
        with self.assertRaises(UserError), self.cr.savepoint():
            allocation.plan_id.line_ids.action_increase(1)
        with self.assertRaises(UserError), self.cr.savepoint():
            allocation.plan_id.action_prepare_revision()
        with self.assertRaises(UserError), self.cr.savepoint():
            fund.action_open()
        restoration = env['erp.budget.allocation.revision'].browse(allocation.action_draft()['res_id'])
        self.assertEqual((restoration.revision_kind, restoration.line_ids.amount, allocation.state), ('restore', 100, 'cancel'))
        planning = env['erp.budget.kpi.release'].browse(zero.action_prepare_revision(restoration.id)['res_id'])
        planning.write({'released_amount': 100})
        planning.line_ids[0].write({'amount': 40})
        planning.line_ids[1].write({'amount': 60})
        planning.action_submit()
        for reviewer in reviewers:
            planning.with_user(reviewer).action_approve()
        restoration.action_activate()
        self.assertEqual((allocation.state, allocation.plan_id.line_ids._ceiling(), fund.amount, fund.state), ('done', 100, 100, 'open'))
        self.assertEqual(controls.mapped('amount'), [40, 60])
        self.assertEqual(controls.mapped('state'), ['open', 'open'])
        self.assertEqual((release.line_ids.mapped('amount'), zero.line_ids.mapped('amount')), ([40, 60], [0, 0]))
        self.assertEqual(self.env['erp.budget.move'].sudo().browse(moves).exists().ids, moves)
        service._commit(controls[1:] | fund, 50, '2027-06-01', 'restore:new-consumption')
        self.assertEqual(allocation.plan_id.line_ids._consumed(), 50)

    def test_legacy_allocation_cancel_restore_keeps_source_identity(self):
        env, allocation = self._setup_dimension_allocation()
        source = allocation.line_ids
        fund = source.control_id
        analytic = env['erp.budget.control'].create({'name': 'Legacy cancellation analytic', 'company_id': self.company.id, 'period_id': allocation.period_id.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'analytic', 'amount': 100})
        analytic.action_open()
        cancellation = env['erp.budget.allocation.revision'].browse(allocation.action_cancel()['res_id'])
        cancellation.action_activate()
        self.assertEqual((allocation.state, fund.state, analytic.state), ('cancel', 'closed', 'closed'))
        with self.assertRaises(UserError), self.cr.savepoint():
            allocation.plan_id.line_ids.action_increase(100)
        restored = env['erp.budget.allocation.revision'].browse(allocation.action_draft()['res_id'])
        restored.action_activate()
        self.assertEqual((allocation.state, fund.id, source.control_id.id, source.allocated_amount, source.released_amount), ('done', fund.id, fund.id, 100, 100))
        self.assertEqual((fund.state, analytic.state, allocation.plan_id.line_ids._ceiling()), ('open', 'open', 100))

    def test_restoration_uses_last_effective_dimensions(self):
        env, allocation = self._setup_dimension_allocation()
        original = allocation.line_ids
        replacement = env['erp.budget.fund'].create({'name': 'Restoration replacement fund', 'company_id': self.company.id, 'group_id': self.group.id})
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        self.assertEqual(revision.revision_kind, 'revision')
        revision.write({'reason': 'Replace original allocation'})
        revision.line_ids.write({'amount': 0, 'excluded': True})
        row = env['erp.budget.allocation.revision.line'].browse(revision.action_add_dimension(self.unit.id, self.analytic.id, replacement.id, 50))
        revision.action_activate()
        cancellation = env['erp.budget.allocation.revision'].browse(allocation.action_cancel()['res_id'])
        cancellation.action_activate()
        restoration = env['erp.budget.allocation.revision'].browse(allocation.action_draft()['res_id'])
        restoration.action_activate()
        self.assertEqual((original.control_id.amount, row.allocation_line_id.control_id.amount, allocation.plan_id.line_ids._ceiling()), (0, 50, 50))
        self.assertEqual(original.allocated_amount, 100)

    def test_activity_selects_distinct_kpis_for_one_budget_account(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        kpis = env['erp.budget.kpi'].create([{'name': name, 'company_id': self.company.id} for name in ('Activity A KPI', 'Activity B KPI')])
        activities = env['erp.budget.activity'].create([{'name': name, 'company_id': self.company.id, 'account_id': self.account.id, 'kpi_id': kpi.id} for name, kpi in zip(('Activity A', 'Activity B'), kpis)])
        template = env['erp.budget.template'].create({'name': 'Activity selection', 'company_id': self.company.id, 'line_ids': [(0, 0, {'account_id': self.account.id, 'kpi_id': kpis[0].id})], 'activity_line_ids': [(0, 0, {'activity_id': activity.id, 'kpi_id': kpi.id}) for activity, kpi in zip(activities, kpis)]})
        period = env['erp.budget.period'].create({'name': 'Activity year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31', 'template_id': template.id})
        base = {'company_id': self.company.id, 'period_id': period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id}
        controls = env['erp.budget.control'].create([dict(base, name='Activity KPI A', level='analytic', kpi_id=kpis[0].id, amount=40), dict(base, name='Activity KPI B', level='analytic', kpi_id=kpis[1].id, amount=60), dict(base, name='Activity common fund', level='fund', fund_id=self.fund.id, amount=100)])
        controls.action_open()
        plan = env['erp.budget.plan'].create({'name': 'Activity shared parent', 'company_id': self.company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        plan.action_confirm()
        service = env['erp.budget.control.service']
        dimensions = env['account.analytic.account']
        a = service._resolve(period, self.unit, self.analytic, self.fund, self.account, dimensions, activity=activities[0])
        b = service._resolve(period, self.unit, self.analytic, self.fund, self.account, dimensions, activity=activities[1])
        self.assertEqual(a.filtered(lambda control: control.level == 'analytic').kpi_id, kpis[0])
        self.assertEqual(b.filtered(lambda control: control.level == 'analytic').kpi_id, kpis[1])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            service._resolve(period, self.unit, self.analytic, self.fund, self.account, dimensions)
        service._commit(a, 40, '2027-06-01', 'activity:first')
        service._commit(b, 60, '2027-06-01', 'activity:second')
        self.assertEqual((plan.line_ids._consumed(), plan.line_ids._ceiling()), (100, 100))
        with self.assertRaises(UserError), self.cr.savepoint():
            service._check_available(b, 1, '2027-06-01')
        other_account = self.env['account.account'].create({'name': 'Unused activity account', 'code': 'ACUNUSED', 'account_type': 'expense', 'company_ids': [(6, 0, [self.company.id])]})
        with self.assertRaises(UserError), self.cr.savepoint():
            activities[0].write({'account_id': other_account.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            template.activity_line_ids[0].write({'kpi_id': kpis[1].id})
        with self.assertRaises(UserError), self.cr.savepoint():
            period.write({'template_id': False})

    def test_activity_company_security_and_account_binding(self):
        env = self.env(user=self.user, context={'allowed_company_ids': [self.company.id]})
        activity = env['erp.budget.activity'].create({'name': 'Scoped activity', 'company_id': self.company.id, 'account_id': self.account.id})
        other_company = self.env['res.company'].create({'name': 'Activity foreign company'})
        account = self.env['account.account'].create({'name': 'Activity foreign account', 'code': 'ACTFOREIGN', 'account_type': 'expense', 'company_ids': [(6, 0, [other_company.id])]})
        foreign = self.env['erp.budget.activity'].create({'name': 'Scoped activity', 'company_id': other_company.id, 'account_id': account.id})
        self.assertNotIn(foreign, env['erp.budget.activity'].search([]))
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            env['erp.budget.activity'].create({'name': 'Foreign binding', 'company_id': self.company.id, 'account_id': account.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            env['erp.budget.activity'].create({'name': 'Foreign creation', 'company_id': other_company.id, 'account_id': account.id})
        with self.assertRaises((AccessError, ValidationError)), self.cr.savepoint():
            env['erp.budget.control.service']._resolve(self.period, self.unit, self.analytic, self.fund, self.account, env['account.analytic.account'], activity=foreign.sudo())
        activity.active = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            env['erp.budget.control.service']._resolve(self.period, self.unit, self.analytic, self.fund, self.account, env['account.analytic.account'], activity=activity)

    def test_analytic_total_keeps_kpi_planning_without_kpi_caps(self):
        from .common_activity import source_activity_allocation
        data = source_activity_allocation(self, self.user, self.company, self.unit, self.analytic, self.fund, self.account, 'Total control', control_level='analytic')
        service = data.env['erp.budget.control.service']
        keys = [service._resolve(data.period, self.unit, self.analytic, self.fund, self.account, data.env['account.analytic.account'], activity=activity) for activity in data.activities]
        self.assertEqual(keys[0], keys[1])
        service._commit(keys[0], 60, '2027-06-01', 'total:activity-a')
        service._commit(keys[1], 40, '2027-06-01', 'total:activity-b')
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(keys[0], 1, '2027-06-01', 'total:overflow')
        release = data.env['erp.budget.kpi.release'].search([('period_id', '=', data.period.id), ('state', '=', 'done')])
        self.assertEqual(release.line_ids.planning_ids.mapped('amount'), [40, 60])
        successor = data.env['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
        with self.assertRaises(UserError), self.cr.savepoint():
            successor.action_initialize_commitments()
        self.assertEqual(successor.line_ids.planning_ids.mapped('amount'), [40, 60])
        with self.assertRaises(UserError), self.cr.savepoint():
            data.period.sudo().write({'control_level': 'analytic_kpi'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            data.env['erp.budget.period'].with_context(default_control_level='analytic').create({'name': 'Forged granularity', 'company_id': self.company.id, 'date_from': '2028-01-01', 'date_to': '2028-12-31'})

    def test_explicit_kpi_mode_never_uses_aggregate_control(self):
        from .common_activity import source_activity_allocation
        data = source_activity_allocation(self, self.user, self.company, self.unit, self.analytic, self.fund, self.account, 'KPI control', control_level='analytic_kpi')
        service = data.env['erp.budget.control.service']
        controls = service._resolve(data.period, self.unit, self.analytic, self.fund, self.account, data.env['account.analytic.account'], activity=data.activities[0])
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(controls, 41, '2027-06-01', 'kpi:overflow')
        self.assertEqual(data.allocation.plan_id.line_ids._consumed(), 0)

    def test_explicit_legacy_capture_and_reviewed_canonical_successor(self):
        env, plan, line = self._setup_plan()
        controls = env['erp.budget.control'].browse((self.a | self.f).ids)
        env['erp.budget.control.service']._commit(controls, 30, self.day, 'legacy:capture')
        move_ids = self.env['erp.budget.move'].sudo().search([('control_id', 'in', controls.ids)]).ids
        action = plan.action_capture_legacy_allocation()
        allocation = env['erp.budget.allocation'].browse(action['res_id'])
        self.assertEqual(plan.action_capture_legacy_allocation()['res_id'], allocation.id)
        self.assertTrue(allocation.legacy_baseline)
        self.assertEqual((allocation.captured_by_id, allocation.line_ids.control_id, controls.mapped('amount')), (self.user, env['erp.budget.control'].browse(self.f.id), [100, 100]))
        baseline = env['erp.budget.kpi.release'].search([('plan_line_id', '=', line.id), ('state', '=', 'done')])
        self.assertTrue(baseline.legacy_baseline)
        self.assertFalse(baseline.released_at or baseline.released_by_id or baseline.review_ids or baseline.line_ids.planning_ids)
        reviewer = self.env['res.users'].create({'name': 'Legacy capture reviewer', 'login': 'legacy_capture_reviewer', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, self.env.ref('erp_budget.group_budget_manager').ids)]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'reviewer_id': reviewer.id})
        revision = env['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
        revision.write({'reason': 'Reviewed canonical conversion'})
        planning = env['erp.budget.kpi.release'].browse(baseline.action_prepare_revision(revision.id)['res_id'])
        self.assertFalse(planning.legacy_baseline or planning.captured_at)
        with self.assertRaises(UserError), self.cr.savepoint():
            revision.action_activate()
        planning.action_submit()
        planning.with_user(reviewer).action_approve()
        revision.action_activate()
        self.assertEqual((baseline.state, planning.state, line.allocation_mode, line.release_required), ('superseded', 'done', 'allocated', True))
        self.assertTrue(planning.released_at)
        self.assertEqual((line._ceiling(), line._consumed(), controls.mapped('amount')), (100, 30, [100, 100]))
        self.assertEqual(self.env['erp.budget.move'].sudo().browse(move_ids).exists().ids, move_ids)
        with self.assertRaises(AccessError), self.cr.savepoint():
            env['erp.budget.allocation'].with_context(default_legacy_baseline=True).create({'name': 'Forged capture', 'company_id': self.company.id, 'period_id': self.period.id})

    def test_legacy_capture_requires_all_units_and_preserves_zero_funds(self):
        env, plan, line = self._setup_plan()
        other_fund = env['erp.budget.fund'].create({'name': 'Unused legacy fund', 'company_id': self.company.id, 'group_id': self.group.id})
        zero = env['erp.budget.control'].create({'name': 'Zeroed legacy fund', 'company_id': self.company.id, 'period_id': self.period.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'level': 'fund', 'fund_id': other_fund.id, 'amount': 0})
        zero.action_open()
        allocation = env['erp.budget.allocation'].browse(plan.action_capture_legacy_allocation()['res_id'])
        self.assertEqual(allocation.line_ids.filtered(lambda item: item.control_id == zero).allocated_amount, 0)
        self.assertEqual(zero.amount, 0)
        self.assertEqual(line._ceiling(), 100)

    def test_balance_forward_floor_split_and_no_double_spending(self):
        env, plan, line = self._setup_plan()
        controls = env['erp.budget.control'].browse((self.a | self.f).ids)
        service = env['erp.budget.control.service']
        service._commit(controls, 60, self.day, 'balance:prior-consumption')
        later = self.env['erp.budget.period'].create({'name': 'Balance next year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        analytic2 = self.env['account.analytic.account'].create({'name': 'Accumulated balance', 'plan_id': self.plan.id, 'company_id': self.company.id})
        doc = env['erp.budget.balance.forward'].create({'name': 'Forward balance', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        doc.action_review()
        row = doc._current_lines()
        self.assertEqual(row.balance_amount, 40)
        row.write({'forward_amount': 30, 'accumulate_analytic_id': analytic2.id})
        duplicate = env['erp.budget.balance.forward'].create({'name': 'Duplicate balance', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            duplicate.action_review()
        doc.action_forward()
        doc.action_forward()
        self.assertEqual(sorted(row.opening_ids.mapped('initial_available')), [10, 30])
        self.assertEqual((line._ceiling(), line._consumed()), (100, 60))
        with self.assertRaises(UserError), self.cr.savepoint():
            service._commit(controls, 1, self.day, 'balance:double-spend')
        with self.assertRaises(UserError), self.cr.savepoint():
            next_plan = env['erp.budget.plan'].create({'name': 'Below opening', 'company_id': self.company.id, 'period_id': later.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 29}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': analytic2.id, 'initial_amount': 10})]})
            next_plan.action_confirm()
        next_plan = env['erp.budget.plan'].create({'name': 'Exact opening', 'company_id': self.company.id, 'period_id': later.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 30}), (0, 0, {'organization_id': self.unit.id, 'analytic_id': analytic2.id, 'initial_amount': 10})]})
        next_plan.action_confirm()
        self.assertEqual(sum(next_plan.line_ids.mapped('effective_amount')), 40)
        with self.assertRaises(UserError), self.cr.savepoint():
            doc.action_cancel()
        self.assertEqual(doc.state, 'done')

    def test_balance_forward_cancel_and_fresh_round_keep_origins(self):
        env, plan, line = self._setup_plan()
        later = self.env['erp.budget.period'].create({'name': 'Cancel next year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        doc = env['erp.budget.balance.forward'].create({'name': 'Cancel balance', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        doc.action_review()
        first = doc._current_lines()
        doc.action_forward()
        opening = first.opening_ids
        doc.action_cancel()
        self.assertEqual((first.reserved, opening.state), (False, 'cancel'))
        doc.action_draft()
        doc.action_review()
        second = doc._current_lines()
        self.assertNotEqual(first, second)
        doc.action_forward()
        self.assertEqual((len(doc.line_ids), first.opening_ids.state, second.opening_ids.state), (2, 'cancel', 'done'))
        self.assertEqual(sum(doc.line_ids.opening_ids.filtered(lambda item: item.state == 'done').mapped('initial_available')), 100)

    def test_reviewed_balance_return_withdraws_effective_capacity_before_unsealing(self):
        env, source_plan, source_line = self._setup_plan()
        later = self.env['erp.budget.period'].create({'name': 'Economic balance return year', 'company_id': self.company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
        balance = env['erp.budget.balance.forward'].create({'name': 'Return unused 100', 'company_id': self.company.id, 'source_period_id': self.period.id, 'destination_period_id': later.id})
        balance.action_review()
        balance.action_forward()
        plan = env['erp.budget.plan'].create({'name': 'Balance return effective destination', 'company_id': self.company.id, 'period_id': later.id, 'line_ids': [(0, 0, {'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'initial_amount': 100})]})
        plan.action_confirm()
        values = {'company_id': self.company.id, 'period_id': later.id, 'organization_id': self.unit.id, 'analytic_id': self.analytic.id, 'amount': 100}
        controls = env['erp.budget.control'].create([dict(values, name='Balance return analytic', level='analytic'), dict(values, name='Balance return fund', level='fund', fund_id=self.fund.id)])
        controls.action_open()
        reviewer = self.env['res.users'].create({'name': 'Balance return reviewer', 'login': 'balance_return_reviewer', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, self.env.ref('erp_budget.group_budget_manager').ids)]})
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        for kind in ('planning', 'transfer'):
            self.env['erp.budget.kpi.tier'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'kind': kind, 'reviewer_id': reviewer.id})
        self.assertNotIn('return_mapping_ids', env['erp.budget.commit.forward']._fields)
        self.assertEqual(env['erp.budget.commit.forward']._fields['line_ids'].comodel_name, 'erp.budget.commit.forward.line')
        balance.action_cancel()
        self.assertEqual((balance.state, controls.mapped('amount')), ('done', [100, 100]))
        self.assertEqual(balance.return_mapping_ids.amount, 100)
        with self.assertRaises(AccessError), self.cr.savepoint():
            env['erp.budget.kpi.release'].create({'name': 'Forged balance approval', 'plan_line_id': plan.line_ids.id, 'released_amount': 0, 'balance_return_id': balance.id})
        foreign = self.env['res.company'].create({'name': 'Wrong balance return company'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            balance.with_context(allowed_company_ids=foreign.ids).action_apply_return()
        service = env['erp.budget.control.service']
        service._commit(controls, 1, '2027-06-01', 'balance:return-underfund')
        with self.assertRaises(UserError), self.cr.savepoint():
            balance.action_submit_return_planning()
        service._reverse(controls, 'balance:return-underfund')
        balance.action_submit_return_planning()
        balance.with_user(reviewer).action_approve_return()
        for planning in balance.return_planning_ids:
            planning.with_user(reviewer).action_approve()
        balance.action_apply_return()
        balance.action_apply_return()
        self.assertEqual((balance.state, controls.mapped('amount'), plan.line_ids._ceiling()), ('cancel', [0, 0], 0))
        self.assertEqual(plan.line_ids._opening_minimum(), 0)
        env['erp.budget.control.service']._commit(env['erp.budget.control'].browse((self.a | self.f).ids), 100, self.day, 'balance:return-unsealed')
        self.assertEqual(source_line._consumed(), 100)
        self.assertTrue(balance.line_ids.opening_ids.exists())
        self.assertEqual(balance.line_ids.opening_ids.state, 'cancel')
