# Only a disposable clone: commits synthetic release and revision records.
from odoo import api, fields
company = env['res.company'].search([('name', '=', 'Shared cap concurrency')], limit=1)
submitter = env['res.users'].search([('login', '=', 'shared_cap_race')], limit=1)
assert company and submitter
unit = env['erp.organization.unit'].search([('company_id', '=', company.id)], limit=1)
analytic = env['account.analytic.account'].search([('name', '=', 'Shared cap analytic'), ('company_id', '=', company.id)], limit=1)
fund = env['erp.budget.fund'].search([('company_id', '=', company.id)], limit=1)
reviewer = env['res.users'].create({'name': 'Seed release reviewer', 'login': 'seed_release_reviewer', 'company_id': company.id, 'company_ids': [(6, 0, [company.id])], 'group_ids': [(6, 0, [env.ref('erp_budget.group_budget_manager').id])]})
env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': unit.id})
env['erp.budget.kpi.tier'].create({'company_id': company.id, 'organization_id': unit.id, 'sequence': 10, 'reviewer_id': reviewer.id})
e = api.Environment(env.cr, submitter.id, {'allowed_company_ids': [company.id]})
period = e['erp.budget.period'].create({'name': 'Seed formal period', 'company_id': company.id, 'date_from': '2028-01-01', 'date_to': '2028-12-31'})
plan = e['erp.budget.plan'].create({'name': 'Seed formal plan', 'company_id': company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': unit.id, 'analytic_id': analytic.id, 'initial_amount': 100, 'allocation_mode': 'allocated', 'release_required': True})]})
plan.action_confirm()
cap = plan.line_ids
kpis = env['erp.budget.kpi'].create([{'name': 'Seed release A', 'company_id': company.id}, {'name': 'Seed release B', 'company_id': company.id}])
base = {'company_id': company.id, 'period_id': period.id, 'organization_id': unit.id, 'analytic_id': analytic.id}
controls = e['erp.budget.control'].create([dict(base, name='Seed KPI A', level='analytic', kpi_id=kpis[0].id, amount=40), dict(base, name='Seed KPI B', level='analytic', kpi_id=kpis[1].id, amount=30), dict(base, name='Seed fund', level='fund', fund_id=fund.id, amount=100)])
controls[2].action_open()
release = e['erp.budget.kpi.release'].create({'name': 'Seed 70 release', 'plan_line_id': cap.id, 'released_amount': 70, 'line_ids': [(0, 0, {'control_id': controls[0].id}), (0, 0, {'control_id': controls[1].id})]})
release.action_submit()
release.with_user(reviewer).with_context(allowed_company_ids=[company.id]).action_approve()
e['erp.budget.control.service']._commit(controls[0] | controls[2], 40, fields.Date.from_string('2028-06-01'), 'seed:formal:commit')
version = e['erp.budget.plan.version'].browse(plan.action_prepare_revision()['res_id'])
version.write({'reason': 'Seed revision'})
version.line_ids.write({'amount': 110})
version.action_activate()
assert release.state == 'done' and cap._consumed() == 40 and cap._ceiling() == 110
assert len(release.review_ids) == 1 and release.review_ids.state == 'approved'
env.cr.commit()
print('RELEASE_REVISION_SEEDED', cap.id, cap._ceiling(), cap._consumed(), release.id, version.id)
