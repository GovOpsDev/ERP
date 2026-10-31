import threading
from odoo import api, fields
reg = env.registry

company = env['res.company'].create({'name': 'Concurrency isolated test'})
unit = env['erp.organization.unit'].create({'name': 'Concurrency unit', 'code': 'CONC', 'company_id': company.id})
user = env['res.users'].create({'name': 'Concurrency budget manager', 'login': 'budget_concurrency_manager', 'company_id': company.id, 'company_ids': [(6, 0, [company.id])], 'group_ids': [(6, 0, [env.ref('erp_budget.group_budget_manager').id])]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
group = env['erp.budget.fund.group'].create({'name': 'Concurrency group', 'company_id': company.id})
fund = env['erp.budget.fund'].create({'name': 'Concurrency fund', 'company_id': company.id, 'group_id': group.id})
period = env['erp.budget.period'].create({'name': 'Concurrency period', 'company_id': company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
plan = env['account.analytic.plan'].create({'name': 'Concurrency plan'})
analytic = env['account.analytic.account'].create({'name': 'Concurrency analytic', 'plan_id': plan.id, 'company_id': company.id})
vals = {'company_id': company.id, 'period_id': period.id, 'organization_id': unit.id, 'analytic_id': analytic.id, 'amount': 100}
controls = env['erp.budget.control'].with_user(user).with_context(allowed_company_ids=[company.id]).create([dict(vals, name='A', level='analytic'), dict(vals, name='B', level='fund', fund_id=fund.id)])
controls.action_open()
control_ids, company_id, uid, dbname = controls.ids, company.id, user.id, env.cr.dbname
env.cr.commit()
ready = threading.Event()
release = threading.Event()
results = {}

def first():
    try:
        with reg.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e['erp.budget.control.service']._commit(e['erp.budget.control'].browse(control_ids), 80, fields.Date.from_string('2026-06-01'), 'concurrency:A')
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
            e['erp.budget.control.service']._commit(e['erp.budget.control'].browse(control_ids), 80, fields.Date.from_string('2026-06-01'), 'concurrency:B')
            cr.commit()
        results['B'] = 'committed'
    except Exception as exc:
        results['B'] = type(exc).__name__

t1 = threading.Thread(target=first)
t2 = threading.Thread(target=second)
t2.start()
t1.start()
t1.join(20)
t2.join(20)
with reg.cursor() as cr:
    cr.execute('SELECT control_id, sum(amount) FROM erp_budget_move WHERE control_id IN %s GROUP BY control_id ORDER BY control_id', (tuple(control_ids),))
    totals = cr.fetchall()
print('CONCURRENCY_RESULT', results, totals)
assert results.get('A') == 'committed' and results.get('B') != 'committed' and len(totals) == 2 and all(amount == 80 for _, amount in totals)
