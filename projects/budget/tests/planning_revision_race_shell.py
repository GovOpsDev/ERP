# Run only on a disposable, upgraded clone of legacy_planning_seed_shell.py.
import threading
from odoo import api

company = env['res.company'].search([('name', '=', 'Legacy planning seed')], limit=1)
manager = env['res.users'].search([('login', '=', 'legacy_planning_manager')], limit=1)
reviewer = env['res.users'].search([('login', '=', 'legacy_planning_reviewer')], limit=1)
e = api.Environment(env.cr, manager.id, {'allowed_company_ids': company.ids})
release = e['erp.budget.kpi.release'].search([('company_id', '=', company.id), ('name', '=', 'Legacy planning released')], limit=1)
assert release.state == 'done' and release.line_ids.amount == 100 and not release.planning_snapshot
assert not release.line_ids.planning_ids and len(release.review_ids) == 1
revision = e['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
assert revision.planning_snapshot and len(revision.line_ids.planning_ids) == 1
revision.action_submit()
uid, company_id, revision_id, previous_id, control_id, cap_id, registry = reviewer.id, company.id, revision.id, release.id, release.line_ids.control_id.id, release.plan_line_id.id, env.registry
old_moves = env['erp.budget.move'].search([('origin_key', '=', 'legacy-planning:commitment')]).ids
env.cr.commit()
ready, proceed = threading.Event(), threading.Event()
results = {}

def approve(index):
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            if index == 1:
                cr.execute('SELECT COUNT(*) FROM erp_budget_kpi_review')
                assert ready.wait(30)
                proceed.set()
            e['erp.budget.kpi.release'].browse(revision_id).action_approve()
            if index == 0:
                ready.set()
                assert proceed.wait(30)
            cr.commit()
        results[index] = 'committed'
    except Exception as exc:
        results[index] = type(exc).__name__
        ready.set()

first, second = (threading.Thread(target=approve, args=(index,)) for index in (0, 1))
second.start()
first.start()
first.join(40)
second.join(40)
assert not first.is_alive() and not second.is_alive()
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    previous = e['erp.budget.kpi.release'].browse(previous_id)
    revision = e['erp.budget.kpi.release'].browse(revision_id)
    cap = e['erp.budget.plan.line'].browse(cap_id)
    print('PLANNING_APPROVAL_RACE', results, previous.state, revision.state, cap._consumed(), cap._ceiling())
    assert results == {0: 'committed', 1: 'SerializationFailure'}
    assert previous.state == 'superseded' and revision.state == 'done'
    assert cap._consumed() == 30 and cap._ceiling() == 100
    assert previous.line_ids.amount == revision.line_ids.amount == 100
    assert e['erp.budget.move'].browse(old_moves).exists().ids == old_moves
