# Disposable clone only; commits a synthetic allocation and runs competing completion callbacks.
import threading
from odoo import api

company = env['res.company'].search([('name', '=', 'Shared cap concurrency')], limit=1)
user = env['res.users'].search([('login', '=', 'shared_cap_race')], limit=1)
unit = env['erp.organization.unit'].search([('company_id', '=', company.id)], limit=1)
analytic = env['account.analytic.account'].search([('name', '=', 'Shared cap analytic'), ('company_id', '=', company.id)], limit=1)
fund = env['erp.budget.fund'].search([('company_id', '=', company.id)], limit=1)
assert company and user and unit and analytic and fund
registry = env.registry
e = api.Environment(env.cr, user.id, {'allowed_company_ids': [company.id]})
period = e['erp.budget.period'].create({'name': 'Initial allocation race', 'company_id': company.id, 'date_from': '2030-01-01', 'date_to': '2030-12-31'})
doc = e['erp.budget.allocation'].create({'name': 'Initial allocation race', 'company_id': company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': unit.id, 'analytic_id': analytic.id, 'fund_id': fund.id, 'allocated_amount': 80})]})
uid, company_id, period_id, allocation_id = user.id, company.id, period.id, doc.id
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
            e['erp.budget.allocation'].browse(allocation_id).action_done()
            if index == 0:
                ready.set()
                assert proceed.wait(30)
            cr.commit()
        result[index] = 'committed'
    except Exception as exc:
        result[index] = type(exc).__name__
        ready.set()

a = threading.Thread(target=worker, args=(0,))
b = threading.Thread(target=worker, args=(1,))
b.start(); a.start(); a.join(40); b.join(40)
assert not a.is_alive() and not b.is_alive()
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    allocation = e['erp.budget.allocation'].browse(allocation_id)
    plans = e['erp.budget.plan'].search([('period_id', '=', period_id)])
    controls = e['erp.budget.control'].search([('period_id', '=', period_id)])
    print('INITIAL_ALLOCATION_RACE', result, allocation.state, len(plans), len(controls), allocation.line_ids.released_amount)
    assert result == {0: 'committed', 1: 'SerializationFailure'}
    assert allocation.state == 'done' and len(plans) == len(controls) == 1 and allocation.line_ids.released_amount == 80
