# Disposable full-stack test DB only: commits synthetic PR/activity history.
import threading
from odoo import api
from odoo.exceptions import UserError

company = env['res.company'].create({'name': 'Activity key concurrency'})
unit = env['erp.organization.unit'].create({'name': 'Activity key race OU', 'code': 'ARACE', 'company_id': company.id})
user = env['res.users'].create({'name': 'Activity key race manager', 'login': 'activity_key_race_manager', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref('erp_procurement.group_procurement_manager').id, env.ref('erp_budget.group_budget_manager').id])]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
env['erp.procurement.tier'].create({'name': 'Activity race review', 'company_id': company.id, 'reviewer_id': user.id, 'sequence': 10, 'minimum_amount': 0})
group = env['erp.budget.fund.group'].create({'name': 'Activity race group', 'company_id': company.id})
fund = env['erp.budget.fund'].create({'name': 'Activity race fund', 'company_id': company.id, 'group_id': group.id})
period = env['erp.budget.period'].create({'name': 'Activity race year', 'company_id': company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
root = env['account.analytic.plan'].create({'name': 'Activity race analytic root'})
analytic = env['account.analytic.account'].create({'name': 'Activity race analytic', 'company_id': company.id, 'plan_id': root.id})
accounts = env['account.account'].create([{'name': name, 'code': code, 'account_type': 'expense', 'company_ids': [(6, 0, company.ids)]} for name, code in (('Original budget expense', 'ARACE1'), ('Replacement expense', 'ARACE2'))])
e = api.Environment(env.cr, user.id, {'allowed_company_ids': company.ids})
activities = e['erp.budget.activity'].create([{'name': name, 'company_id': company.id, 'account_id': accounts[0].id} for name in ('Race Activity A', 'Race Activity B')])
base = {'company_id': company.id, 'period_id': period.id, 'organization_id': unit.id, 'analytic_id': analytic.id, 'amount': 100}
controls = e['erp.budget.control'].create([dict(base, name='Activity race analytic control', level='analytic'), dict(base, name='Activity race fund control', level='fund', fund_id=fund.id)])
controls.action_open()
requests = e['erp.procurement.request']
for selection in ([activities[0]], list(activities), list(reversed(activities))):
    request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2027-06-01'})
    for activity in selection:
        e['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Activity race line', 'product_qty': 1, 'estimated_cost': 40 / len(selection), 'period_id': period.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'account_id': accounts[0].id, 'activity_id': activity.id})
    requests |= request
uid, company_id, request_ids, activity_id, replacement_id, control_id, registry = user.id, company.id, requests.ids, activities[0].id, accounts[1].id, controls.filtered(lambda row: row.level == 'analytic').id, env.registry
env.cr.commit()

def run_race(label, first_request_id, second_request_id=None, total=40):
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
                    if second_request_id:
                        request = e['erp.procurement.request'].browse(second_request_id)
                        request.action_submit()
                        request.action_approve()
                    else:
                        e['erp.budget.activity'].browse(activity_id).write({'account_id': replacement_id})
                else:
                    request = e['erp.procurement.request'].browse(first_request_id)
                    request.action_submit()
                    request.action_approve()
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
        amount = sum(e['erp.budget.move'].search([('control_id', '=', control_id)]).mapped('amount'))
        print(label, results, amount)
        assert results == {0: 'committed', 1: 'SerializationFailure'}
        assert amount == total
        if second_request_id:
            assert e['erp.procurement.request'].browse(second_request_id).state == 'draft'

run_race('ACTIVITY_BINDING_APPROVAL_RACE', request_ids[0])
run_race('ACTIVITY_REVERSED_LINE_ORDER_RACE', request_ids[1], request_ids[2], total=80)
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    activity = e['erp.budget.activity'].browse(activity_id)
    assert activity.account_id.id == accounts[0].id
    try:
        with cr.savepoint():
            activity.write({'account_id': replacement_id})
    except UserError:
        pass
    else:
        raise AssertionError('Used activity account must remain immutable on retry')
print('ACTIVITY_KEY_HISTORY_PRESERVED')
