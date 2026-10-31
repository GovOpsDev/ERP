"""OPERATIONS FIX: additional synthetic browser fixtures and action metadata."""
import json
from pathlib import Path
assert env.cr.dbname=='erp_readiness'
p=Path('/var/lib/odoo/readiness-fixture.json');f=json.loads(p.read_text())
assert 'extra' not in f, 'Additional fixtures already prepared'
company=env['res.company'].browse(f['company']);finance=env['res.users'].browse(f['users']['finance']['id'])
finance.write({'group_ids':[(4,env.ref('hr_expense.group_hr_expense_manager').id),(4,env.ref('erp_budget.group_budget_user').id)]})
wh=env['stock.warehouse'].browse(f['warehouse'])
location=env['stock.location'].create({'name':'UAT internal destination','usage':'internal','company_id':company.id,'location_id':wh.view_location_id.id})
route=env['stock.route'].create({'name':'UAT internal supply','company_id':company.id})
env['stock.rule'].create({'name':'UAT internal supply','company_id':company.id,'route_id':route.id,'action':'pull','location_dest_from_rule':True,'location_src_id':wh.lot_stock_id.id,'location_dest_id':location.id,'picking_type_id':wh.int_type_id.id,'procure_method':'make_to_stock'})
employee=env['hr.employee'].create({'name':'UAT Expense claimant','company_id':company.id,'organization_unit_id':f['unit'],'expense_manager_id':finance.id})
payable=env['account.account'].with_company(company).search([('code','=','UAT200'),('company_ids','in',company.ids)])
employee.work_contact_id.with_company(company).property_account_payable_id=payable
expense_account=env['account.account'].with_company(company).search([('code','=','UAT500'),('company_ids','in',company.ids)])
service=env['product.product'].create({'name':'UAT reimbursable service','type':'service','can_be_expensed':True,'purchase_ok':True,'supplier_taxes_id':[(5,0,0)]})
service.with_company(company).property_account_expense_id=expense_account
journal=env['account.journal'].create({'name':'UAT expenses','code':'UATE','type':'purchase','company_id':company.id,'default_account_id':expense_account.id})
company.expense_journal_id=journal
advance_account=env['account.account'].create({'name':'UAT employee advance','code':'UAT120','account_type':'asset_current','reconcile':True,'company_ids':[(6,0,company.ids)]})
general=env['account.journal'].search([('code','=','UATA'),('company_id','=',company.id)])
company.write({'erp_employee_advance_account_id':advance_account.id,'erp_employee_advance_journal_id':general.id})
env['erp.budget.kpi.tier'].create({'company_id':company.id,'organization_id':f['unit'],'reviewer_id':f['users']['manager']['id'],'sequence':10})
models=['erp.organization.unit','erp.budget.control','erp.budget.plan','erp.budget.allocation','erp.budget.kpi.release','erp.procurement.request','purchase.requisition','purchase.order','erp.inventory.acceptance','account.move','erp.asset.asset','account.asset','erp.contract.contract','erp.contract.agreement','erp.inventory.request','stock.picking','hr.expense']
f['actions']={model:env['ir.actions.act_window'].search([('res_model','=',model)],order='id',limit=1).id for model in models}
f['extra']={'location':location.id,'route':route.id,'employee':employee.id,'expense_account':expense_account.id,'service':service.id,'expense_journal':journal.id,'advance_account':advance_account.id,'currency':company.currency_id.id,'uom':service.uom_id.id}
env['erp.budget.period'].create({'name':'Browser fiscal 2027','company_id':company.id,'date_from':'2027-01-01','date_to':'2027-12-31','release_policy':'formal'})
env.cr.commit();p.write_text(json.dumps(f,indent=2))
print('UAT_EXTRA_FIXTURES_READY',list(f['extra']))
