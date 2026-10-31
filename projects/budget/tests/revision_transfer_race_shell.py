# Run only against a disposable seeded test database; commits synthetic revisions/transfers.
import threading
from odoo import api
reg = env.registry
company = env['res.company'].search([('name', '=', 'Shared cap concurrency')], limit=1)
user = env['res.users'].search([('login', '=', 'shared_cap_race')], limit=1)
assert company and user
e = api.Environment(env.cr, user.id, {'allowed_company_ids': [company.id]})
plan = e['erp.budget.plan'].search([('name', '=', 'Plan'), ('company_id', '=', company.id)], limit=1)
assert plan and plan.line_ids._consumed() == 80
first = e['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
second = e['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
first.write({'reason': 'Version race A'})
second.write({'reason': 'Version race B'})
first.line_ids.write({'amount': 160})
second.line_ids.write({'amount': 170})
uid, company_id, first_id, second_id, plan_id = user.id, company.id, first.id, second.id, plan.id
env.cr.commit()

def run_race(first_action, second_action):
    ready, release = threading.Event(), threading.Event()
    result = {}
    def first_worker():
        try:
            with reg.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                first_action(e)
                ready.set()
                assert release.wait(30)
                cr.commit()
            result['A'] = 'committed'
        except Exception as exc:
            result['A'] = type(exc).__name__
            ready.set()
    def second_worker():
        try:
            with reg.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                cr.execute('SELECT COUNT(*) FROM erp_budget_move')
                assert ready.wait(30)
                release.set()
                second_action(e)
                cr.commit()
            result['B'] = 'committed'
        except Exception as exc:
            result['B'] = type(exc).__name__
    a, b = threading.Thread(target=first_worker), threading.Thread(target=second_worker)
    b.start(); a.start(); a.join(40); b.join(40)
    assert not a.is_alive() and not b.is_alive()
    return result

versions = run_race(lambda e: e['erp.budget.plan.version'].browse(first_id).action_activate(), lambda e: e['erp.budget.plan.version'].browse(second_id).action_activate())
with reg.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    p = e['erp.budget.plan'].browse(plan_id)
    effective = e['erp.budget.plan.version'].search([('plan_id', '=', plan_id), ('state', '=', 'effective')])
    print('VERSION_RACE', versions, len(effective), p.line_ids._ceiling())
    assert versions.get('A') == 'committed' and versions.get('B') == 'SerializationFailure' and len(effective) == 1 and p.line_ids._ceiling() == 160
    transfer_plan = e['erp.budget.plan'].search([('name', '=', 'Seed transfer plan'), ('company_id', '=', company_id)], limit=1)
    source = transfer_plan.line_ids.filtered(lambda line: line._ceiling() == 80)
    destination = transfer_plan.line_ids.filtered(lambda line: line._ceiling() == 40)
    assert len(source) == len(destination) == 1
    source_id, destination_id = source.id, destination.id

transfers = run_race(lambda e: e['erp.budget.plan.line'].browse(source_id).action_transfer(destination_id, 60, 'race A'), lambda e: e['erp.budget.plan.line'].browse(source_id).action_transfer(destination_id, 60, 'race B'))
with reg.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    source = e['erp.budget.plan.line'].browse(source_id)
    destination = e['erp.budget.plan.line'].browse(destination_id)
    print('TRANSFER_RACE', transfers, source._ceiling(), destination._ceiling())
    assert transfers.get('A') == 'committed' and transfers.get('B') == 'SerializationFailure' and source._ceiling() == 20 and destination._ceiling() == 100
