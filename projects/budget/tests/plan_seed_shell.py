# Synthetic fixture: only run on a disposable cloned test database.
company = env['res.company'].search([('name', '=', 'Shared cap concurrency')], limit=1)
assert company
user = env['res.users'].search([('login', '=', 'shared_cap_race')], limit=1)
e = env(user=user, context={'allowed_company_ids': [company.id]})
old_line = e['erp.budget.plan.line'].search([('company_id', '=', company.id)], limit=1)
assert old_line._consumed() == 80
old_line.action_increase(50, 'seed increase')
unit = old_line.organization_id
period = e['erp.budget.period'].create({'name': 'Next year seed period', 'company_id': company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31'})
analytic_plan = old_line.analytic_id.plan_id
second_analytic = env['account.analytic.account'].create({'name': 'Transfer seed analytic', 'plan_id': analytic_plan.id, 'company_id': company.id})
plan = e['erp.budget.plan'].create({'name': 'Seed transfer plan', 'company_id': company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': unit.id, 'analytic_id': old_line.analytic_id.id, 'initial_amount': 100}), (0, 0, {'organization_id': unit.id, 'analytic_id': second_analytic.id, 'initial_amount': 20})]})
plan.action_confirm()
a = plan.line_ids.filtered(lambda row: row.analytic_id == old_line.analytic_id)
b = plan.line_ids - a
a.action_transfer(b.id, 20, 'seed transfer')
assert (a._ceiling(), b._ceiling(), old_line._ceiling(), old_line._consumed()) == (80, 40, 150, 80)
env.cr.commit()
print('PLAN_SEEDED', old_line.id, old_line._consumed(), old_line._ceiling(), a._ceiling(), b._ceiling())
