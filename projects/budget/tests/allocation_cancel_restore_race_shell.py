# Disposable DB only: creates and commits synthetic source-allocation history.
import threading
from odoo import api

company = env['res.company'].create({'name': 'Allocation cancellation race'})
unit = env['erp.organization.unit'].create({'name': 'Cancellation race OU', 'code': 'CRACE', 'company_id': company.id})
user = env['res.users'].create({'name': 'Cancellation race manager', 'login': 'allocation_cancellation_race', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, env.ref('erp_budget.group_budget_manager').ids)]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
group = env['erp.budget.fund.group'].create({'name': 'Cancellation race funds', 'company_id': company.id})
fund = env['erp.budget.fund'].create({'name': 'Cancellation race fund', 'company_id': company.id, 'group_id': group.id})
period = env['erp.budget.period'].create({'name': 'Cancellation race period', 'company_id': company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
root = env['account.analytic.plan'].create({'name': 'Cancellation race root'})
analytic = env['account.analytic.account'].create({'name': 'Cancellation race analytic', 'company_id': company.id, 'plan_id': root.id})
e = api.Environment(env.cr, user.id, {'allowed_company_ids': company.ids})
allocation = e['erp.budget.allocation'].create({'name': 'Cancellation race allocation', 'company_id': company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': unit.id, 'analytic_id': analytic.id, 'fund_id': fund.id, 'allocated_amount': 100})]})
allocation.action_done()
allocation.plan_id.action_confirm()
allocation.line_ids.control_id.action_open()
control = e['erp.budget.control'].create({'name': 'Cancellation race child', 'company_id': company.id, 'period_id': period.id, 'organization_id': unit.id, 'analytic_id': analytic.id, 'level': 'analytic', 'amount': 100})
control.action_open()
controls = control | allocation.line_ids.control_id
revision = e['erp.budget.allocation.revision'].browse(allocation.action_cancel()['res_id'])
uid, company_id, allocation_id, control_ids, registry = user.id, company.id, allocation.id, controls.ids, env.registry
env.cr.commit()

def race(revision_id, label, expected_state, expected_cap):
    ready, proceed = threading.Event(), threading.Event()
    results = {}
    def worker(index):
        try:
            with registry.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                if index == 1:
                    cr.execute('SELECT COUNT(*) FROM erp_budget_move')
                    assert ready.wait(30)
                    proceed.set()
                    e['erp.budget.control.service']._commit(e['erp.budget.control'].browse(control_ids), 60, '2027-06-01', label + ':commitment')
                else:
                    e['erp.budget.allocation.revision'].browse(revision_id).action_activate()
                    ready.set()
                    assert proceed.wait(30)
                cr.commit()
            results[index] = 'committed'
        except Exception as exc:
            results[index] = type(exc).__name__
            ready.set()
    first, second = (threading.Thread(target=worker, args=(index,)) for index in (0, 1))
    second.start()
    first.start()
    first.join(40)
    second.join(40)
    assert not first.is_alive() and not second.is_alive()
    with registry.cursor() as cr:
        e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
        allocation = e['erp.budget.allocation'].browse(allocation_id)
        cap = allocation.plan_id.line_ids
        print(label, results, allocation.state, cap._ceiling(), cap._consumed())
        assert results == {0: 'committed', 1: 'SerializationFailure'}
        assert allocation.state == expected_state and cap._ceiling() == expected_cap and cap._consumed() == 0

race(revision.id, 'ALLOCATION_CANCEL_COMMIT_RACE', 'cancel', 0)
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    restore_id = e['erp.budget.allocation'].browse(allocation_id).action_draft()['res_id']
    cr.commit()
race(restore_id, 'ALLOCATION_RESTORE_COMMIT_RACE', 'done', 100)
