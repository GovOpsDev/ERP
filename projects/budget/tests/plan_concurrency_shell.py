# Use only a disposable test database; creates and commits synthetic records.
import threading
from odoo import api, fields
reg = env.registry
company = env['res.company'].create({'name': 'Shared cap concurrency'})
unit = env['erp.organization.unit'].create({'name': 'Shared cap OU', 'code': 'SCC', 'company_id': company.id})
user = env['res.users'].create({'name': 'Shared cap manager', 'login': 'shared_cap_race', 'company_id': company.id, 'company_ids': [(6, 0, [company.id])], 'group_ids': [(6, 0, [env.ref('erp_budget.group_budget_manager').id])]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
group = env['erp.budget.fund.group'].create({'name': 'Shared cap funds', 'company_id': company.id})
funds = env['erp.budget.fund'].create([{'name': 'Fund A', 'company_id': company.id, 'group_id': group.id}, {'name': 'Fund B', 'company_id': company.id, 'group_id': group.id}])
kpis = env['erp.budget.kpi'].create([{'name': 'KPI A', 'company_id': company.id}, {'name': 'KPI B', 'company_id': company.id}])
period = env['erp.budget.period'].create({'name': 'Shared cap period', 'company_id': company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
analytic_plan = env['account.analytic.plan'].create({'name': 'Shared cap analytic plan'})
analytic = env['account.analytic.account'].create({'name': 'Shared cap analytic', 'plan_id': analytic_plan.id, 'company_id': company.id})
e = api.Environment(env.cr, user.id, {'allowed_company_ids': [company.id]})
vals = {'company_id': company.id, 'period_id': period.id, 'organization_id': unit.id, 'analytic_id': analytic.id, 'amount': 100}
controls = e['erp.budget.control'].create([dict(vals, name='Analytic A', level='analytic', kpi_id=kpis[0].id), dict(vals, name='Fund A', level='fund', fund_id=funds[0].id), dict(vals, name='Analytic B', level='analytic', kpi_id=kpis[1].id), dict(vals, name='Fund B', level='fund', fund_id=funds[1].id)])
controls.action_open()
plan = e['erp.budget.plan'].create({'name': 'Plan', 'company_id': company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': unit.id, 'analytic_id': analytic.id, 'initial_amount': 100})]})
plan.action_confirm()
first_ids, second_ids = controls[:2].ids, controls[2:].ids
uid, company_id, line_id = user.id, company.id, plan.line_ids.id
env.cr.commit()
ready, release = threading.Event(), threading.Event()
results = {}
def first():
    try:
        with reg.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e['erp.budget.control.service']._commit(e['erp.budget.control'].browse(first_ids), 80, fields.Date.from_string('2026-06-01'), 'shared:A')
            ready.set()
            assert release.wait(30)
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
            assert ready.wait(30)
            release.set()
            e['erp.budget.control.service']._commit(e['erp.budget.control'].browse(second_ids), 80, fields.Date.from_string('2026-06-01'), 'shared:B')
            cr.commit()
        results['B'] = 'committed'
    except Exception as exc:
        results['B'] = type(exc).__name__
a, b = threading.Thread(target=first), threading.Thread(target=second)
b.start(); a.start(); a.join(40); b.join(40)
assert not a.is_alive() and not b.is_alive()
with reg.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    cap = e['erp.budget.plan.line'].browse(line_id)
    total = cap._consumed()
    print('SHARED_CAP_RACE', results, total, cap._ceiling(), first_ids, second_ids)
    assert results.get('A') == 'committed' and results.get('B') == 'SerializationFailure' and total == 80 and cap._ceiling() == 100
