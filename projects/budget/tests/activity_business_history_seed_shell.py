# Requires the complete ERP test stack; disposable DB only, commits synthetic data.
from types import SimpleNamespace
from odoo import api
from odoo.addons.erp_budget.tests.common_activity import source_activity_allocation

assert not env['res.company'].search_count([('name', '=', 'Activity business upgrade history')])
company = env['res.company'].create({'name': 'Activity business upgrade history'})
unit = env['erp.organization.unit'].create({'name': 'Activity history OU', 'code': 'AHIST', 'company_id': company.id})
user = env['res.users'].create({'name': 'Activity history manager', 'login': 'activity_history_manager', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref(xml).id for xml in ('erp_procurement.group_procurement_manager', 'erp_contract.group_contract_manager', 'erp_budget.group_budget_manager', 'account.group_account_invoice')])]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
env['erp.procurement.tier'].create({'name': 'Activity history procurement review', 'company_id': company.id, 'reviewer_id': user.id, 'minimum_amount': 0, 'sequence': 10})
group = env['erp.budget.fund.group'].create({'name': 'Activity history funds', 'company_id': company.id})
fund = env['erp.budget.fund'].create({'name': 'Activity history fund', 'company_id': company.id, 'group_id': group.id})
root = env['account.analytic.plan'].create({'name': 'Activity history root'})
analytic = env['account.analytic.account'].create({'name': 'Activity history analytic', 'company_id': company.id, 'plan_id': root.id})
accounts = env['account.account'].create([{'name': name, 'code': code, 'account_type': kind, 'reconcile': kind == 'liability_payable', 'company_ids': [(6, 0, company.ids)]} for name, code, kind in (('Activity history GL expense', 'AHGL', 'expense'), ('Activity history budget expense', 'AHBUD', 'expense'), ('Activity history payable', 'AHPAY', 'liability_payable'))])
gl_account, budget_account, payable = accounts
product = env['product.product'].create({'name': 'Activity history service', 'type': 'service', 'purchase_ok': True})
product.with_company(company).product_tmpl_id.property_account_expense_id = gl_account
vendor = env['res.partner'].create({'name': 'Activity history supplier', 'supplier_rank': 1})
vendor.with_company(company).property_account_payable_id = payable
journal = env['account.journal'].create({'name': 'Activity history purchases', 'code': 'AHIST', 'type': 'purchase', 'company_id': company.id})
data = source_activity_allocation(SimpleNamespace(env=env), user, company, unit, analytic, fund, budget_account, 'Activity history')
e = data.env
warehouse = env['stock.warehouse'].with_company(company).search([('company_id', '=', company.id)], limit=1)
if not warehouse:
    warehouse = env['stock.warehouse'].with_company(company).create({'name': 'Activity history warehouse', 'code': 'AHIST', 'company_id': company.id})
request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2027-06-01'})
line = e['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Activity history PR line', 'product_id': product.id, 'product_qty': 1, 'estimated_cost': 40, 'period_id': data.period.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'activity_id': data.activities[0].id})
request.action_submit()
request.action_approve()
po = e['purchase.order'].create({'picking_type_id': warehouse.in_type_id.id, 'company_id': company.id, 'partner_id': vendor.id, 'date_order': '2027-06-01 12:00:00', 'order_line': [(0, 0, {'name': 'Activity history PO line', 'product_id': product.id, 'product_qty': 4, 'price_unit': 10, 'date_planned': '2027-06-05 12:00:00', 'tax_ids': [(5, 0, 0)], 'erp_request_line_id': line.id, 'erp_budget_fund_id': fund.id, 'erp_budget_analytic_id': analytic.id, 'erp_budget_account_id': budget_account.id, 'analytic_distribution': {str(analytic.id): 100}})]})
po.button_confirm()
contract = e['erp.contract.contract'].create({'name': 'Activity history contract', 'company_id': company.id, 'organization_id': unit.id, 'partner_id': vendor.id, 'journal_id': journal.id})
contract_line = e['erp.contract.line'].create({'contract_id': contract.id, 'name': 'Activity history contract line', 'product_id': product.id, 'uom_id': product.uom_id.id, 'quantity': 6, 'price_unit': 10, 'date_start': '2027-01-01', 'date_end': '2027-12-31', 'period_id': data.period.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'activity_id': data.activities[1].id})
contract.action_commit_budget()
for source, quantity in (({'purchase_line_id': po.order_line.id}, 4), ({'erp_contract_line_id': contract_line.id}, 3)):
    invoice_values = {'name': 'Activity history bill line', 'product_id': product.id, 'product_uom_id': product.uom_id.id, 'account_id': gl_account.id, 'quantity': quantity, 'price_unit': 10, 'tax_ids': [(5, 0, 0)], 'analytic_distribution': {str(analytic.id): 100}, **source}
    bill = e['account.move'].create({'move_type': 'in_invoice', 'company_id': company.id, 'partner_id': vendor.id, 'journal_id': journal.id, 'date': '2027-06-01', 'invoice_date': '2027-06-01', 'invoice_line_ids': [(0, 0, invoice_values)]})
    bill.action_post()
    assert bill.invoice_line_ids.account_id == gl_account
    assert bill.invoice_line_ids.erp_budget_activity_id
assert data.allocation.plan_id.line_ids._consumed() == 100
revision = e['erp.budget.allocation.revision'].browse(data.allocation.action_prepare_allocation_revision()['res_id'])
revision.write({'reason': 'Activity history coordinated increase'})
revision.line_ids.write({'amount': 120})
release = e['erp.budget.kpi.release'].search([('plan_line_id', '=', data.allocation.plan_id.line_ids.id), ('state', '=', 'done')], limit=1)
planning = e['erp.budget.kpi.release'].browse(release.action_prepare_revision(revision.id)['res_id'])
planning.write({'released_amount': 120})
planning.line_ids[0].write({'amount': 50})
planning.line_ids[1].write({'amount': 70})
planning.action_submit()
planning.with_user(data.reviewer).action_approve()
revision.action_activate()
assert data.allocation.plan_id.line_ids._ceiling() == data.fund_control.amount == 120
assert data.allocation.plan_id.line_ids._consumed() == 100
assert len(e['account.move'].search([('company_id', '=', company.id), ('state', '=', 'posted')])) == 2
env.cr.commit()
print('ACTIVITY_BUSINESS_HISTORY', request.id, po.id, contract.id, revision.id, 120, 100)
