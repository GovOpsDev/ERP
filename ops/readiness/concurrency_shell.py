"""PERFORMANCE FIX: eight-worker cross-domain races with explicit user retries.

No hidden unlimited retry. Native HTTP retry handles each attempt; exhausted
transactions remain unchanged and are explicitly resubmitted once after the burst.
"""
import json,threading,time,os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from odoo import api
from odoo.http.retrying import retrying
assert env.cr.dbname=='erp_readiness_perf'
f=json.loads(Path('/var/lib/odoo/readiness-fixture.json').read_text());ctx={'allowed_company_ids':[f['company']]}
def actor(role):return env(user=f['users'][role]['id'],context=ctx)
results={}
def race(name,role,model,ids,method,args=None):
 env.cr.commit();barrier=threading.Barrier(len(ids));uid=f['users'][role]['id']
 def worker(rid):
  attempts=0;started=time.monotonic()
  try:
   with env.registry.cursor() as cr:
    e=api.Environment(cr,uid,ctx)
    def invoke():
     nonlocal attempts
     attempts+=1
     if attempts==1:
      cr.execute('SELECT 1');barrier.wait(30)
     return getattr(e[model].browse(rid),method)(*(args or []))
    retrying(invoke,e,close_on_commit=False)
   return {'id':rid,'status':'committed','attempts':attempts,'seconds':time.monotonic()-started}
  except Exception as exc:return {'id':rid,'status':type(exc).__name__,'attempts':attempts,'seconds':time.monotonic()-started,'message':str(exc)}
 with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(worker,ids))
 env.cr.rollback();env.invalidate_all()
 for row in rows:
  if row['status']=='SerializationFailure':
   with env.registry.cursor() as cr:
    e=api.Environment(cr,uid,ctx)
    retrying(lambda:getattr(e[model].browse(row['id']),method)(*(args or [])),e,close_on_commit=False)
   row['explicit_user_retry']='committed'
  elif name=='same_asset_duplicate' and row['status']=='UserError' and 'already linked' in row.get('message',''):
   row['expected_rejection']=True
  else:assert row['status']=='committed',row
 env.cr.rollback();env.invalidate_all()
 results[name]=rows;Path('/var/lib/odoo/readiness-domain-concurrency.json').write_text(json.dumps(results,indent=2));print('DOMAIN_RACE',name,json.dumps(rows),flush=True)
if os.environ.get('CONCURRENCY_RESUME')=='1':
 results=json.loads(Path('/var/lib/odoo/readiness-domain-concurrency.json').read_text())
 acquisitions=actor('asset')['erp.asset.asset'].browse([r['id'] for r in results['asset_create']])
else:
 # Verify explicit resubmission of the earlier PR bursts including exhausted calls.
 waiting=actor('approver')['erp.procurement.request'].search([('company_id','=',f['company']),('state','=','to_approve')])
 for request in waiting:
  request.action_approve()
  env.cr.commit()
 assert not actor('approver')['erp.procurement.request'].search_count([('company_id','=',f['company']),('state','=','to_approve')])
 results['earlier_pr_user_retries']={'count':len(waiting),'result':'all approved'}
 linked=env['purchase.order.line'].search([]).erp_request_line_id.request_id | env['purchase.requisition.line'].search([]).erp_request_line_id.request_id
 requests=actor('procurement')['erp.procurement.request'].search([('company_id','=',f['company']),('state','=','approved'),('id','not in',linked.ids)],limit=8)
 assert len(requests)==8
 pos=actor('procurement')['purchase.order']
 for request in requests:
  req=actor('procurement')['purchase.requisition'].browse(request.action_create_requisition()['res_id']);req.vendor_id=f['vendor'];req.action_confirm()
  pos|=actor('procurement')['purchase.order'].browse(req.action_create_rfq()['res_id'])
 race('po_confirm','procurement','purchase.order',pos.ids,'button_confirm')
 was=actor('inventory')['erp.inventory.acceptance']
 for po in pos:
  was|=actor('inventory')['erp.inventory.acceptance'].create({'company_id':f['company'],'organization_id':po.erp_request_organization_id.id,'purchase_order_id':po.id,'line_ids':[(0,0,{'purchase_line_id':po.order_line.id,'quantity':1})]})
 race('work_acceptance','inventory','erp.inventory.acceptance',was.ids,'action_accept')
 bills=actor('finance')['account.move']
 for wa in was:
  po=wa.purchase_order_id;source=po.order_line
  bills|=actor('finance')['account.move'].create({'move_type':'in_invoice','company_id':f['company'],'partner_id':f['vendor'],'journal_id':f['journal'],'invoice_date':'2026-10-01','date':'2026-10-01','erp_acceptance_id':wa.id,'invoice_line_ids':[(0,0,{'name':'Concurrency bill','product_id':f['product'],'account_id':f['account'],'quantity':1,'price_unit':100,'tax_ids':[(5,0,0)],'purchase_line_id':source.id,'analytic_distribution':source.analytic_distribution})]})
 race('bill_post','finance','account.move',bills.ids,'action_post')
 acquisitions=actor('asset')['erp.asset.asset'].search([('bill_id','in',bills.ids)])
 assert len(acquisitions)==8
 race('asset_create','asset','erp.asset.asset',acquisitions.ids,'action_create_depreciation_asset')
race('same_asset_duplicate','asset','erp.asset.asset',[acquisitions[0].id]*8,'action_create_depreciation_asset')
assert len(acquisitions.engine_asset_id)==8
acquisitions.engine_asset_id.validate()
lines=acquisitions.engine_asset_id.mapped('depreciation_line_ids').filtered(lambda line:line.type=='depreciate')
first=lines.browse([asset.depreciation_line_ids.filtered(lambda line:line.type=='depreciate')[0].id for asset in acquisitions.engine_asset_id])
race('depreciation','asset','account.asset.line',first.ids,'create_move')
assert len(first.move_id)==8
wh=env['stock.warehouse'].browse(f['warehouse'])
location=env['stock.location'].create({'name':'PERF internal destination','usage':'internal','company_id':f['company'],'location_id':wh.view_location_id.id})
route=env['stock.route'].create({'name':'PERF internal route','company_id':f['company']})
env['stock.rule'].create({'name':'PERF internal route','company_id':f['company'],'route_id':route.id,'action':'pull','location_dest_from_rule':True,'location_src_id':wh.lot_stock_id.id,'location_dest_id':location.id,'picking_type_id':wh.int_type_id.id,'procure_method':'make_to_stock'})
stock=actor('inventory')['erp.inventory.request']
for _ in range(8):
 request=actor('inventory')['erp.inventory.request'].create({'company_id':f['company'],'organization_id':f['unit'],'warehouse_id':wh.id,'location_id':location.id,'line_ids':[(0,0,{'product_id':f['product'],'quantity':1,'route_id':route.id,'fund_id':f['fund'],'analytic_id':f['analytics'][0]})]})
 request.action_submit();stock|=request
race('stock_request','inventory','erp.inventory.request',stock.ids,'action_approve')
assert len(stock.line_ids.move_ids)==8
caps=actor('budget')['erp.budget.plan.line'].search([('period_id','=',f['period']),('company_id','=',f['company'])],order='id',limit=2)
assert len(caps)==2
before=[cap._ceiling() for cap in caps]
race('budget_transfer','budget','erp.budget.plan.line',[caps[0].id]*8,'action_transfer',[caps[1].id,1,'Readiness parallel transfer'])
assert [cap._ceiling() for cap in caps]==[before[0]-8,before[1]+8]
env.cr.execute("SELECT source_key,control_id FROM erp_budget_move WHERE reversal_of_id IS NULL AND id NOT IN (SELECT reversal_of_id FROM erp_budget_move WHERE reversal_of_id IS NOT NULL) GROUP BY source_key,control_id,move_type HAVING count(*)>1")
assert not env.cr.fetchall()
env.cr.execute('SELECT source_line_id FROM erp_asset_asset GROUP BY source_line_id,item_index,generation HAVING count(*)>1');assert not env.cr.fetchall()
for control in env['erp.budget.control'].search([('company_id','=',f['company'])]):assert control.available_amount>=0
for cap in env['erp.budget.plan.line'].search([('company_id','=',f['company'])]):assert cap._consumed()<=cap._ceiling()
env.cr.commit()
Path('/var/lib/odoo/readiness-domain-concurrency.json').write_text(json.dumps(results,indent=2))
print('DOMAIN_CONCURRENCY_INVARIANTS_PASS',json.dumps({'scenarios':list(results),'workers':8}),flush=True)
