# Disposable clone of revision_release_seed_shell.py data only; commits synthetic releases.
import threading
from odoo import api

company = env['res.company'].search([('name', '=', 'Shared cap concurrency')], limit=1)
submitter = env['res.users'].search([('login', '=', 'shared_cap_race')], limit=1)
reviewer = env['res.users'].search([('login', '=', 'seed_release_reviewer')], limit=1)
plan = env['erp.budget.plan'].search([('name', '=', 'Seed formal plan'), ('company_id', '=', company.id)], limit=1)
assert company and submitter and reviewer and plan and plan.line_ids._allocated() == 70
unit, cap = plan.line_ids.organization_id, plan.line_ids
kpis = env['erp.budget.kpi'].create([{'name': 'Race release A', 'company_id': company.id}, {'name': 'Race release B', 'company_id': company.id}])
e = api.Environment(env.cr, submitter.id, {'allowed_company_ids': [company.id]})
base = {'company_id': company.id, 'period_id': plan.period_id.id, 'organization_id': unit.id, 'analytic_id': cap.analytic_id.id, 'amount': 30, 'level': 'analytic'}
controls = e['erp.budget.control'].create([dict(base, name='Race KPI A', kpi_id=kpis[0].id), dict(base, name='Race KPI B', kpi_id=kpis[1].id)])
releases = e['erp.budget.kpi.release'].create([{'name': 'Race release A', 'plan_line_id': cap.id, 'released_amount': 30, 'line_ids': [(0, 0, {'control_id': controls[0].id})]}, {'name': 'Race release B', 'plan_line_id': cap.id, 'released_amount': 30, 'line_ids': [(0, 0, {'control_id': controls[1].id})]}])
for release in releases:
    release.action_submit()
ids, uid, company_id, cap_id, registry = releases.ids, reviewer.id, company.id, cap.id, env.registry
env.cr.commit()
ready, proceed = threading.Event(), threading.Event()
result = {}

def worker(index):
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            if index == 1:
                cr.execute('SELECT COUNT(*) FROM erp_budget_move')
                assert ready.wait(30)
                proceed.set()
            e['erp.budget.kpi.release'].browse(ids[index]).action_approve()
            if index == 0:
                ready.set()
                assert proceed.wait(30)
            cr.commit()
        result[index] = 'committed'
    except Exception as exc:
        result[index] = type(exc).__name__
        ready.set()

b = threading.Thread(target=worker, args=(1,))
a = threading.Thread(target=worker, args=(0,))
b.start(); a.start(); a.join(40); b.join(40)
assert not a.is_alive() and not b.is_alive()
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    rows = e['erp.budget.kpi.release'].browse(ids)
    cap = e['erp.budget.plan.line'].browse(cap_id)
    print('KPI_RELEASE_RACE', result, rows.mapped('state'), cap._allocated(), cap._ceiling())
    assert result == {0: 'committed', 1: 'SerializationFailure'}
    assert rows.mapped('state').count('done') == 1 and cap._allocated() == 100 and cap._ceiling() == 110
