# Only run on a disposable test DB: this probe commits synthetic fixtures.
import threading
from odoo import api

company = env['res.company'].create({'name': 'Dimension activation race'})
unit = env['erp.organization.unit'].create({'name': 'Dimension race OU', 'code': 'DRACE', 'company_id': company.id})
user = env['res.users'].create({'name': 'Dimension race manager', 'login': 'dimension_activation_race', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, env.ref('erp_budget.group_budget_manager').ids)]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
group = env['erp.budget.fund.group'].create({'name': 'Race funds', 'company_id': company.id})
funds = env['erp.budget.fund'].create([{'name': name, 'company_id': company.id, 'group_id': group.id} for name in ('Initial', 'First', 'Second')])
period = env['erp.budget.period'].create({'name': 'Dimension race period', 'company_id': company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
plan = env['account.analytic.plan'].create({'name': 'Dimension race analytics'})
analytic = env['account.analytic.account'].create({'name': 'Dimension race analytic', 'plan_id': plan.id, 'company_id': company.id})
e = api.Environment(env.cr, user.id, {'allowed_company_ids': company.ids})
allocation = e['erp.budget.allocation'].create({'name': 'Dimension race allocation', 'company_id': company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': unit.id, 'analytic_id': analytic.id, 'fund_id': funds[0].id, 'allocated_amount': 100})]})
allocation.action_done()
allocation.plan_id.action_confirm()
allocation.line_ids.control_id.action_open()
revisions = e['erp.budget.allocation.revision']
for index, amount in ((1, 25), (2, 50)):
    revision = e['erp.budget.allocation.revision'].browse(allocation.action_prepare_allocation_revision()['res_id'])
    revision.write({'reason': 'Concurrent dimension activation'})
    revision.action_add_dimension(unit.id, analytic.id, funds[index].id, amount)
    revisions |= revision
uid, company_id, allocation_id, revision_ids, registry = user.id, company.id, allocation.id, revisions.ids, env.registry
env.cr.commit()
ready, proceed = threading.Event(), threading.Event()
results = {}

def activate(index):
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            if index == 1:
                cr.execute('SELECT COUNT(*) FROM erp_budget_control')
                assert ready.wait(30)
                proceed.set()
            e['erp.budget.allocation.revision'].browse(revision_ids[index]).action_activate()
            if index == 0:
                ready.set()
                assert proceed.wait(30)
            cr.commit()
        results[index] = 'committed'
    except Exception as exc:
        results[index] = type(exc).__name__
        ready.set()

first, second = (threading.Thread(target=activate, args=(index,)) for index in (0, 1))
second.start()
first.start()
first.join(40)
second.join(40)
assert not first.is_alive() and not second.is_alive()
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    allocation = e['erp.budget.allocation'].browse(allocation_id)
    effective = e['erp.budget.allocation.revision'].search([('allocation_id', '=', allocation_id), ('state', '=', 'effective')])
    controls = allocation.line_ids.mapped('control_id')
    print('ALLOCATION_DIMENSION_RACE', results, len(effective), len(controls), sum(controls.mapped('amount')), allocation.plan_id.line_ids._ceiling())
    assert results == {0: 'committed', 1: 'SerializationFailure'}
    assert len(effective) == 1 and len(controls) == 2
    assert sum(controls.mapped('amount')) == allocation.plan_id.line_ids._ceiling() == 125
