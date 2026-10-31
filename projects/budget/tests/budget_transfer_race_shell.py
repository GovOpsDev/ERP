# Disposable full-stack database only: real transfer vs real PR approval race.
import threading
from types import SimpleNamespace
from odoo import api
from odoo.addons.erp_budget.tests.test_budget_transfer import TestBudgetTransfer

company = env['res.company'].create({'name': 'Transfer real concurrency'})
unit = env['erp.organization.unit'].create({'name': 'Transfer race OU', 'code': 'TRACE', 'company_id': company.id})
user = env['res.users'].create({'name': 'Transfer race manager', 'login': 'transfer_race_manager', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref('erp_procurement.group_procurement_manager').id, env.ref('erp_budget.group_budget_manager').id])]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
env['erp.procurement.tier'].create({'name': 'Transfer race PR review', 'company_id': company.id, 'reviewer_id': user.id, 'sequence': 10, 'minimum_amount': 0})
group = env['erp.budget.fund.group'].create({'name': 'Transfer race group', 'company_id': company.id})
fund = env['erp.budget.fund'].create({'name': 'Transfer race fund', 'company_id': company.id, 'group_id': group.id})
root = env['account.analytic.plan'].create({'name': 'Transfer race root'})
analytic = env['account.analytic.account'].create({'name': 'Transfer race analytic', 'company_id': company.id, 'plan_id': root.id})
account = env['account.account'].create({'name': 'Transfer race expense', 'code': 'TRACE', 'account_type': 'expense', 'company_ids': [(6, 0, company.ids)]})
case = SimpleNamespace(env=env, user=user, company=company, unit=unit, analytic=analytic, fund=fund)
e, doc, controls, reviewers = TestBudgetTransfer._setup_transfer(case)
def make_request(amount, analytic):
    request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2027-06-01'})
    e['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Transfer race request', 'product_qty': 1, 'estimated_cost': amount, 'period_id': doc.period_id.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'account_id': account.id})
    return request
existing = make_request(60, analytic)
existing.action_submit()
existing.action_approve()
request = make_request(20, analytic)
doc.action_submit()
doc.action_submit_planning()
for reviewer in reviewers:
    doc.with_user(reviewer).action_approve()
    for planning in doc._planning():
        planning.with_user(reviewer).action_approve()
uid, company_id, doc_id, request_id, registry = user.id, company.id, doc.id, request.id, env.registry
env.cr.commit()
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
                request = e['erp.procurement.request'].browse(request_id)
                request.action_submit()
                request.action_approve()
            else:
                e['erp.budget.transfer'].browse(doc_id).action_transfer()
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
    doc = e['erp.budget.transfer'].browse(doc_id)
    source = doc.line_ids.source_control_id
    amount = sum(e['erp.budget.move'].search([('control_id', '=', source.id)]).mapped('amount'))
    print('TRANSFER_REAL_PR_RACE', results, doc.state, source.amount, amount)
    assert results == {0: 'committed', 1: 'SerializationFailure'}
    assert doc.state == 'done' and source.amount == 70 and amount == 60
    assert e['erp.procurement.request'].browse(request_id).state == 'draft'
