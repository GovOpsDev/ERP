"""OPERATIONS FIX: synthetic UAT fixture; execute with Odoo shell on erp_readiness.

No guessed historic mappings: existing restored history is left untouched.
Business documents use ordinary role environments. Only setup uses shell admin.
"""
import base64
from odoo.tools.binary import BinaryBytes
import hashlib
import json
from pathlib import Path
import time
from odoo import fields

assert env.cr.dbname == 'erp_readiness', 'Synthetic fixture is limited to the UAT DB'
assert not env['res.company'].search([('name','=','Readiness UAT')]), 'Fixture already exists'
started=time.monotonic()
password=Path('/run/secrets/uat_password').read_text().strip()
company=env['res.company'].create({'name':'Readiness UAT','email':'uat@example.invalid','iap_enrich_auto_done':True})
foreign=env['res.company'].create({'name':'Readiness Foreign','email':'foreign@example.invalid','iap_enrich_auto_done':True})
units=env['erp.organization.unit'].create([{'name':f'UAT Unit {i:02d}','code':f'UAT{i:02d}','company_id':company.id} for i in range(20)])
foreign_unit=env['erp.organization.unit'].create({'name':'Foreign unit','code':'FOREIGN','company_id':foreign.id})
for child in units[1:]:
    child.parent_id=units[0]
roles={
 'requester':['erp_procurement.group_procurement_user'],
 'approver':['erp_procurement.group_procurement_manager'],
 'budget':['erp_budget.group_budget_manager'],
 'procurement':['erp_procurement.group_procurement_manager'],
 'finance':['account.group_account_manager','erp_procurement.group_procurement_user'],
 'contract':['erp_contract.group_contract_manager','account.group_account_invoice'],
 'inventory':['erp_inventory.group_acceptance_manager','erp_inventory.group_stock_request_manager'],
 'asset':['erp_asset.group_asset_manager','account.group_account_invoice'],
 'unauthorized':['base.group_user'],
}
roles['manager']=sorted(set(sum(roles.values(),[])+['erp_organization.group_organization_manager','hr.group_hr_manager']))
users={}
for role,groups in roles.items():
    users[role]=env['res.users'].create({'name':'UAT '+role,'login':'uat_'+role,'password':password,'tz':'Asia/Bangkok','company_id':company.id,'company_ids':[(6,0,company.ids)],'group_ids':[(6,0,[env.ref(x).id for x in groups])]})
    if role!='unauthorized':
        env['erp.organization.assignment'].create([{'user_id':users[role].id,'unit_id':u.id} for u in (units if role=='manager' else units[:1])])
outsider=env['res.users'].create({'name':'UAT foreign manager','login':'uat_foreign','password':password,'company_id':foreign.id,'company_ids':[(6,0,foreign.ids)],'group_ids':[(6,0,[env.ref(x).id for x in roles['manager']])]})
env['erp.organization.assignment'].create({'user_id':outsider.id,'unit_id':foreign_unit.id})
other=env['res.users'].create({'name':'UAT other OU','login':'uat_other_ou','password':password,'company_id':company.id,'company_ids':[(6,0,company.ids)],'group_ids':[(6,0,[env.ref(x).id for x in roles['manager']])]})
env['erp.organization.assignment'].create({'user_id':other.id,'unit_id':units[1].id})
users.update(foreign=outsider,other_ou=other)
env['hr.employee'].create([{'name':f'UAT Employee {i:03d}','company_id':company.id,'organization_unit_id':units[i%20].id} for i in range(200)])
warehouse=env['stock.warehouse'].search([('company_id','=',company.id)],limit=1)
if not warehouse:
    warehouse=env['stock.warehouse'].create({'name':'UAT warehouse','code':'UAT','company_id':company.id})
group=env['erp.budget.fund.group'].create({'name':'UAT funds','company_id':company.id})
fund=env['erp.budget.fund'].create({'name':'UAT fund','group_id':group.id,'company_id':company.id})
period=env['erp.budget.period'].create({'name':'UAT 2026','company_id':company.id,'date_from':'2026-01-01','date_to':'2026-12-31'})
aplan=env['account.analytic.plan'].create({'name':'UAT analytics'})
analytics=env['account.analytic.account'].create([{'name':f'UAT project {i:02d}','company_id':company.id,'plan_id':aplan.id} for i in range(20)])
account=env['account.account'].create({'name':'UAT equipment','code':'UAT100','account_type':'asset_fixed','company_ids':[(6,0,company.ids)]})
payable=env['account.account'].create({'name':'UAT payable','code':'UAT200','account_type':'liability_payable','reconcile':True,'company_ids':[(6,0,company.ids)]})
depreciation=env['account.account'].create({'name':'UAT accumulated depreciation','code':'UAT110','account_type':'asset_fixed','company_ids':[(6,0,company.ids)]})
expense=env['account.account'].create({'name':'UAT depreciation expense','code':'UAT500','account_type':'expense','company_ids':[(6,0,company.ids)]})
product=env['product.product'].create({'name':'UAT equipment','type':'consu','is_storable':True,'purchase_ok':True,'supplier_taxes_id':[(5,0,0)],'taxes_id':[(5,0,0)]})
product.with_company(company).property_account_expense_id=account
vendor=env['res.partner'].create({'name':'UAT vendor','supplier_rank':1})
vendor.with_company(company).property_account_payable_id=payable
journal=env['account.journal'].create({'name':'UAT purchases','code':'UATP','type':'purchase','company_id':company.id})
general=env['account.journal'].create({'name':'UAT assets','code':'UATA','type':'general','company_id':company.id})
engine_profile=env['account.asset.profile'].create({'name':'UAT depreciation','company_id':company.id,'account_asset_id':account.id,'account_depreciation_id':depreciation.id,'account_expense_depreciation_id':expense.id,'journal_id':general.id,'method_time':'year','method_number':3,'method_period':'year','open_asset':False})
# Explicit acquisition handoff: disable OCA's automatic account-level creation.
account.asset_profile_id=False
profile=env['erp.asset.profile'].create({'name':'UAT acquisition','company_id':company.id,'account_id':account.id,'oca_profile_id':engine_profile.id})
controls=env['erp.budget.control']
for unit,analytic in zip(units,analytics):
    values={'company_id':company.id,'period_id':period.id,'organization_id':unit.id,'analytic_id':analytic.id,'amount':1000000}
    controls |= env['erp.budget.control'].create([dict(values,name=unit.name+' analytic',level='analytic'),dict(values,name=unit.name+' fund',level='fund',fund_id=fund.id)])
controls.action_open()
env['erp.procurement.tier'].create({'name':'UAT PR review','company_id':company.id,'reviewer_id':users['approver'].id})
def actor(role):
    return env(user=users[role],context={'allowed_company_ids':[company.id],'tz':'Asia/Bangkok'})
records={}
requests=[]
for i in range(200):
    e=actor('requester')
    request=e['erp.procurement.request'].create({'company_id':company.id,'organization_id':units[0].id,'date_start':'2026-10-01','line_ids':[(0,0,{'name':f'UAT request line {i}','product_id':product.id,'product_qty':1,'estimated_cost':100,'period_id':period.id,'fund_id':fund.id,'analytic_id':analytics[0].id,'account_id':account.id})]})
    requests.append(request.id)
    if i>=100:
        continue
    request.action_submit()
    request.with_user(users['approver']).action_approve()
    if i>=40:
        continue
    e=actor('procurement')
    requisition=e['purchase.requisition'].browse(request.with_user(users['procurement']).action_create_requisition()['res_id'])
    requisition.vendor_id=vendor
    requisition.action_confirm()
    po=e['purchase.order'].browse(requisition.action_create_rfq()['res_id'])
    po.button_confirm()
    acceptance=actor('inventory')['erp.inventory.acceptance'].create({'company_id':company.id,'organization_id':units[0].id,'purchase_order_id':po.id,'line_ids':[(0,0,{'purchase_line_id':po.order_line.id,'quantity':1})]})
    acceptance.action_accept()
    picking=po.with_user(users['inventory']).picking_ids
    picking.erp_acceptance_id=acceptance
    picking.move_ids.quantity=1
    picking.move_ids.picked=True
    picking.button_validate()
    bill=actor('finance')['account.move'].create({'move_type':'in_invoice','company_id':company.id,'partner_id':vendor.id,'journal_id':journal.id,'invoice_date':'2026-10-01','date':'2026-10-01','erp_acceptance_id':acceptance.id,'invoice_line_ids':[(0,0,{'name':'UAT equipment bill','product_id':product.id,'account_id':account.id,'quantity':1,'price_unit':100,'tax_ids':[(5,0,0)],'purchase_line_id':po.order_line.id,'analytic_distribution':{str(analytics[0].id):100}})]})
    bill.action_post()
    acquisition=actor('asset')['erp.asset.asset'].search([('bill_id','=',bill.id)])
    assert len(acquisition)==1
    if i<10:
        acquisition.action_create_depreciation_asset()
        acquisition.engine_asset_id.validate()
    if i==0:
        records.update(request=request.id,requisition=requisition.id,po=po.id,acceptance=acceptance.id,bill=bill.id,asset=acquisition.id,picking=picking.id,engine_asset=acquisition.engine_asset_id.id)
contract=actor('contract')['erp.contract.contract'].create({'name':'UAT service contract','company_id':company.id,'organization_id':units[0].id,'partner_id':vendor.id,'journal_id':journal.id,'line_ids':[(0,0,{'name':'UAT contract service','product_id':product.id,'uom_id':product.uom_id.id,'quantity':2,'price_unit':100,'date_start':'2026-01-01','date_end':'2026-12-31','period_id':period.id,'fund_id':fund.id,'analytic_id':analytics[0].id,'account_id':account.id})]})
contract.action_commit_budget()
records['contract']=contract.id
attachments=[]
for key,model in [('contract','erp.contract.contract'),('acceptance','erp.inventory.acceptance'),('bill','account.move'),('asset','erp.asset.asset'),('request','erp.procurement.request')]:
    payload=('Synthetic readiness attachment: '+key+'\n').encode()
    attachment=env['ir.attachment'].create({'name':'UAT '+key+'.txt','res_model':model,'res_id':records[key],'raw':BinaryBytes(payload),'mimetype':'text/plain'})
    attachments.append({'id':attachment.id,'model':model,'record':records[key],'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'store_fname':attachment.store_fname})
summary={'dataset':'synthetic; not production data','company':company.id,'foreign_company':foreign.id,'unit':units[0].id,'other_unit':units[1].id,'users':{k:{'id':u.id,'login':u.login} for k,u in users.items()},'records':records,'requests':requests,'fund':fund.id,'period':period.id,'analytics':analytics.ids,'controls':controls.ids,'account':account.id,'product':product.id,'vendor':vendor.id,'journal':journal.id,'warehouse':warehouse.id,'attachments':attachments,'seconds':round(time.monotonic()-started,3)}
Path('/var/lib/odoo/readiness-fixture.json').write_text(json.dumps(summary,indent=2)+'\n')
env.cr.commit()
print('READINESS_FIXTURE_CREATED',json.dumps({'records':records,'seconds':summary['seconds'],'users':len(users),'requests':len(requests),'attachments':len(attachments)}))
