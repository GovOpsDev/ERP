import threading
from odoo import api
reg = env.registry
company = env['res.company'].create({'name': 'Concurrent PR Company'})
unit = env['erp.organization.unit'].create({'name': 'Concurrent PR Unit', 'code': 'PRRACE', 'company_id': company.id})
user = env['res.users'].create({'name': 'Concurrent PR Reviewer', 'login': 'concurrent_pr_reviewer', 'company_id': company.id, 'company_ids': [(6, 0, [company.id])], 'group_ids': [(6, 0, [env.ref('erp_procurement.group_procurement_manager').id])]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
env['erp.procurement.tier'].create({'name': 'Concurrent PR tier', 'company_id': company.id, 'reviewer_id': user.id})
group = env['erp.budget.fund.group'].create({'name': 'Race group', 'company_id': company.id})
fund = env['erp.budget.fund'].create({'name': 'Race fund', 'company_id': company.id, 'group_id': group.id})
period = env['erp.budget.period'].create({'name': 'Race period', 'company_id': company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
plan = env['account.analytic.plan'].create({'name': 'Race plan'})
analytic = env['account.analytic.account'].create({'name': 'Race analytic', 'plan_id': plan.id, 'company_id': company.id})
account = env['account.account'].create({'name': 'Race expense', 'code': 'RACE01', 'account_type': 'expense', 'company_ids': [(6, 0, [company.id])]})
vals = {'company_id': company.id, 'period_id': period.id, 'organization_id': unit.id, 'analytic_id': analytic.id, 'amount': 100}
a = env['erp.budget.control'].create(dict(vals, name='Race analytic control', level='analytic'))
f = env['erp.budget.control'].create(dict(vals, name='Race fund control', level='fund', fund_id=fund.id))
(a | f).action_open()
e = env(user=user, context={'allowed_company_ids': [company.id]})
requests = e['erp.procurement.request']
for num in range(2):
    request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2026-06-01'})
    e['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Race PR %s' % num, 'product_qty': 1, 'estimated_cost': 80, 'period_id': period.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'account_id': account.id})
    request.action_submit()
    requests |= request
request_ids, company_id, uid, control_ids = requests.ids, company.id, user.id, (a.id, f.id)
env.cr.commit()
ready = threading.Event()
release = threading.Event()
results = {}
def first():
    try:
        with reg.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e['erp.procurement.request'].browse(request_ids[0]).action_approve()
            ready.set()
            if not release.wait(10):
                raise RuntimeError('second transaction did not start')
            cr.commit()
        results['A'] = 'committed'
    except Exception as exc:
        results['A'] = type(exc).__name__
        ready.set()
def second():
    try:
        with reg.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            cr.execute('SELECT COUNT(*) FROM erp_budget_move')
            if not ready.wait(10):
                raise RuntimeError('first transaction did not start')
            release.set()
            e['erp.procurement.request'].browse(request_ids[1]).action_approve()
            cr.commit()
        results['B'] = 'committed'
    except Exception as exc:
        results['B'] = type(exc).__name__
t1 = threading.Thread(target=first)
t2 = threading.Thread(target=second)
t2.start(); t1.start(); t1.join(20); t2.join(20)
with reg.cursor() as cr:
    cr.execute('SELECT control_id, sum(amount) FROM erp_budget_move WHERE control_id IN %s GROUP BY control_id ORDER BY control_id', (control_ids,))
    totals = cr.fetchall()
    cr.execute('SELECT state FROM erp_procurement_request WHERE id IN %s ORDER BY id', (tuple(request_ids),))
    states = [row[0] for row in cr.fetchall()]
print('PR_CONCURRENCY_RESULT', results, totals, states)
assert results.get('A') == 'committed' and results.get('B') != 'committed' and len(totals) == 2 and all(amount == 80 for _, amount in totals) and states == ['approved', 'to_approve']
