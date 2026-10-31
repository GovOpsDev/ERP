# Run only on a disposable clone of initial_allocation_race_shell.py's seeded DB.
import threading
from odoo import api

company = env['res.company'].search([('name', '=', 'Shared cap concurrency')], limit=1)
user = env['res.users'].search([('login', '=', 'shared_cap_race')], limit=1)
e = api.Environment(env.cr, user.id, {'allowed_company_ids': [company.id]})
allocation = e['erp.budget.allocation'].search([('name', '=', 'Initial allocation race'), ('company_id', '=', company.id)], limit=1)
assert company and user and allocation and allocation.plan_id.state == 'draft'
allocation.plan_id.action_confirm()
allocation.line_ids.control_id.action_open()
first = e['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
second = e['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
first.write({'reason': 'Revision race A'})
second.write({'reason': 'Revision race B'})
first.line_ids.write({'amount': 100})
second.line_ids.write({'amount': 120})
ids, uid, company_id, allocation_id, registry = [first.id, second.id], user.id, company.id, allocation.id, env.registry
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
            e['erp.budget.allocation.revision'].browse(ids[index]).action_activate()
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
    revisions = e['erp.budget.allocation.revision'].search([('allocation_id', '=', allocation_id), ('state', '=', 'effective')])
    print('ALLOCATION_REVISION_RACE', result, len(revisions), allocation.line_ids.control_id.amount, allocation.plan_id.line_ids._ceiling())
    assert result == {0: 'committed', 1: 'SerializationFailure'}
    assert len(revisions) == 1 and allocation.line_ids.control_id.amount == 100 and allocation.plan_id.line_ids._ceiling() == 100
