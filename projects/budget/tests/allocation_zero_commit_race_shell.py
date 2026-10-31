# Disposable clone of allocation_revision_race_shell.py's DB; commits synthetic records.
import threading
from odoo import api

company = env['res.company'].search([('name', '=', 'Shared cap concurrency')], limit=1)
user = env['res.users'].search([('login', '=', 'shared_cap_race')], limit=1)
e = api.Environment(env.cr, user.id, {'allowed_company_ids': [company.id]})
allocation = e['erp.budget.allocation'].search([('name', '=', 'Initial allocation race'), ('company_id', '=', company.id)], limit=1)
assert company and user and allocation and allocation.plan_id.line_ids._ceiling() == 100
line, fund = allocation.line_ids, allocation.line_ids.control_id
analytic = e['erp.budget.control'].create({'name': 'Zero race analytic', 'company_id': company.id, 'period_id': allocation.period_id.id, 'organization_id': line.organization_id.id, 'analytic_id': line.analytic_id.id, 'level': 'analytic', 'amount': 100})
analytic.action_open()
revision = e['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
revision.write({'reason': 'Remove capacity'})
revision.line_ids.write({'amount': 0})
uid, company_id, revision_id, allocation_id, analytic_id, fund_id, registry = user.id, company.id, revision.id, allocation.id, analytic.id, fund.id, env.registry
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
                e['erp.budget.control.service']._commit(e['erp.budget.control'].browse([analytic_id, fund_id]), 60, '2030-06-01', 'zero-race:commit')
            else:
                e['erp.budget.allocation.revision'].browse(revision_id).action_activate()
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
    print('ALLOCATION_ZERO_COMMIT_RACE', result, allocation.line_ids.control_id.amount, allocation.plan_id.line_ids._ceiling(), allocation.plan_id.line_ids._consumed())
    assert result == {0: 'committed', 1: 'SerializationFailure'}
    assert allocation.line_ids.control_id.amount == 0 and allocation.plan_id.line_ids._ceiling() == 0 and allocation.plan_id.line_ids._consumed() == 0
