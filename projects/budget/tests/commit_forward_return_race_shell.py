# Disposable full-stack database only: real PR versus forward/return transactions.
import threading
from types import SimpleNamespace
from odoo import api
from odoo.addons.erp_budget.tests.test_budget_transfer import TestBudgetTransfer

company = env['res.company'].create({'name': 'Commit forward return concurrency'})
unit = env['erp.organization.unit'].create({'name': 'Carry race OU', 'code': 'CFRC', 'company_id': company.id})
user = env['res.users'].create({'name': 'Carry race manager', 'login': 'carry_return_race_manager', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref(xml).id for xml in ('erp_procurement.group_procurement_manager', 'erp_budget.group_budget_manager')])]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
env['erp.procurement.tier'].create({'name': 'Carry race PR review', 'company_id': company.id, 'reviewer_id': user.id, 'sequence': 10, 'minimum_amount': 0})
group = env['erp.budget.fund.group'].create({'name': 'Carry race fund group', 'company_id': company.id})
fund = env['erp.budget.fund'].create({'name': 'Carry race fund', 'company_id': company.id, 'group_id': group.id})
root = env['account.analytic.plan'].create({'name': 'Carry race analytic root'})
analytic = env['account.analytic.account'].create({'name': 'Carry race analytic', 'company_id': company.id, 'plan_id': root.id})
account = env['account.account'].create({'name': 'Carry race expense', 'code': 'CFRC', 'account_type': 'expense', 'company_ids': [(6, 0, company.ids)]})
case = SimpleNamespace(env=env, user=user, company=company, unit=unit, analytic=analytic, fund=fund)
e, unused_transfer, source_controls, reviewers = TestBudgetTransfer._setup_transfer(case)
source_allocation = unused_transfer.allocation_id
for reviewer in reviewers:
    reviewer.write({'group_ids': [(4, env.ref('erp_procurement.group_procurement_user').id)]})
period = env['erp.budget.period'].create({'name': 'Carry race destination year', 'company_id': company.id, 'date_from': '2028-01-01', 'date_to': '2028-12-31', 'release_policy': 'formal', 'control_level': 'analytic'})
allocation = e['erp.budget.allocation'].create({'name': 'Carry race destination allocation', 'company_id': company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': unit.id, 'analytic_id': line.analytic_id.id, 'fund_id': fund.id, 'allocated_amount': 100}) for line in source_allocation.line_ids]})
allocation.action_done()
allocation.plan_id.action_confirm()
allocation.line_ids.control_id.action_open()
controls = e['erp.budget.control']
for line in allocation.plan_id.line_ids:
    control = e['erp.budget.control'].create({'name': 'Carry race '+line.analytic_id.name, 'company_id': company.id, 'period_id': period.id, 'organization_id': unit.id, 'analytic_id': line.analytic_id.id, 'level': 'analytic', 'amount': 100})
    release = e['erp.budget.kpi.release'].create({'name': 'Carry race destination planning', 'plan_line_id': line.id, 'released_amount': 100, 'line_ids': [(0, 0, {'control_id': control.id})]})
    release.action_submit()
    for reviewer in reviewers:
        release.with_user(reviewer).action_approve()
    controls |= control
request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2027-06-01'})
e['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Carry race PR line', 'product_qty': 1, 'estimated_cost': 40, 'period_id': source_allocation.period_id.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'account_id': account.id})
request.action_submit()
request.action_approve()
forward = e['erp.budget.commit.forward'].create({'name': 'Carry race outstanding PR', 'company_id': company.id, 'source_period_id': source_allocation.period_id.id, 'destination_period_id': period.id})
forward.action_review()
forward._current_lines().write({'destination_analytic_control_id': controls.filtered(lambda control: control.analytic_id == analytic).id, 'destination_fund_control_id': allocation.line_ids.filtered(lambda line: line.analytic_id == analytic).control_id.id})
uid, company_id, forward_id, request_id, registry = user.id, company.id, forward.id, request.id, env.registry
reviewer_ids = reviewers.ids
env.cr.commit()

source_analytic_id = source_controls[0].id
destination_analytic_id = controls.filtered(lambda control: control.analytic_id == analytic).id

def race(label, method, expected_state, source_consumed, destination_cap, destination_consumed, model='erp.budget.commit.forward', document_id=None):
    ready, proceed = threading.Event(), threading.Event()
    results = {}
    def worker(index):
        try:
            with registry.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                if index:
                    cr.execute('SELECT COUNT(*) FROM erp_budget_move')
                    assert ready.wait(30)
                    proceed.set()
                    e['erp.procurement.request'].browse(request_id).action_reject()
                else:
                    getattr(e[model].browse(document_id or forward_id), method)()
                    ready.set()
                    assert proceed.wait(30)
                cr.commit()
            results[index] = 'committed'
        except Exception as exc:
            results[index] = type(exc).__name__
            ready.set()
    threads = [threading.Thread(target=worker, args=(index,)) for index in (1, 0)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(40)
        assert not thread.is_alive()
    with registry.cursor() as cr:
        e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
        doc = e[model].browse(document_id or forward_id)
        source = e['erp.budget.control'].browse(source_analytic_id)
        destination = e['erp.budget.control'].browse(destination_analytic_id)
        total = lambda control: sum(e['erp.budget.move'].search([('control_id', '=', control.id)]).mapped('amount'))
        print(label, results, doc.state, total(source), destination.amount, total(destination))
        assert results == {0: 'committed', 1: 'SerializationFailure'}
        assert (doc.state, total(source), destination.amount, total(destination)) == (expected_state, source_consumed, destination_cap, destination_consumed)
        assert e['erp.procurement.request'].browse(request_id).state == 'approved'

race('COMMIT_FORWARD_REAL_PR_RACE', 'action_forward', 'done', 0, 100, 40)
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    forward = e['erp.budget.commit.forward'].browse(forward_id)
    forward.action_prepare_return()
    forward.action_submit_return_planning()
    for reviewer_id in reviewer_ids:
        forward.with_user(reviewer_id).action_approve_return()
        for planning in forward.return_planning_ids:
            planning.with_user(reviewer_id).action_approve()
    cr.commit()
race('COMMIT_RETURN_REAL_PR_RACE', 'action_apply_return', 'cancel', 40, 60, 0)

with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    prior = e['erp.budget.commit.forward'].browse(forward_id)
    balance = e['erp.budget.balance.forward'].create({'name': 'Carry race unused balance', 'company_id': company_id, 'source_period_id': prior.source_period_id.id, 'destination_period_id': prior.destination_period_id.id})
    balance.action_review()
    balance.action_forward()
    balance.action_prepare_return()
    balance.action_submit_return_planning()
    for reviewer_id in reviewer_ids:
        balance.with_user(reviewer_id).action_approve_return()
        for planning in balance.return_planning_ids:
            planning.with_user(reviewer_id).action_approve()
    balance_id = balance.id
    cr.commit()
race('BALANCE_RETURN_REAL_PR_RACE', 'action_apply_return', 'cancel', 40, 0, 0, model='erp.budget.balance.forward', document_id=balance_id)
