"""PERFORMANCE FIX: isolated synthetic scale and eight-worker transactional probe.

Uses Odoo's native bounded retry, fresh transaction snapshots, and ordinary roles.
Never run on UAT or a production database. All timings are observations, not an SLA.
"""
import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from odoo import api, fields
from odoo.http.retrying import retrying

assert env.cr.dbname == 'erp_readiness_perf'
f = json.loads(Path('/var/lib/odoo/readiness-fixture.json').read_text())
company = env['res.company'].browse(f['company'])
units = env['erp.organization.unit'].search([('company_id', '=', company.id)], order='id')
analytics = env['account.analytic.account'].browse(f['analytics'])
users = {role: env['res.users'].browse(data['id']) for role, data in f['users'].items()}
for role in ['approver', 'requester', 'procurement', 'finance', 'inventory', 'asset', 'budget']:
    assigned = env['erp.organization.assignment'].search([('user_id', '=', users[role].id)]).unit_id
    env['erp.organization.assignment'].create([{'user_id': users[role].id, 'unit_id': u.id} for u in units-assigned])
context = {'allowed_company_ids': [company.id], 'tz': 'Asia/Bangkok'}
def actor(role):
    return env(user=users[role], context=context)
resume = os.environ.get('PERF_RESUME') == '1'
if resume:
    periods = env['erp.budget.period'].browse(f['period']) | env['erp.budget.period'].search([('name', '=', 'PERF 2027')])
    assert len(periods)==2
    plans=env['erp.budget.plan'].search([('company_id','=',company.id)])
else:
    assert not env['erp.budget.period'].search([('name', '=', 'PERF 2027')])
    periods = env['erp.budget.period'].browse(f['period']) | env['erp.budget.period'].create({'name':'PERF 2027', 'company_id':company.id, 'date_from':'2027-01-01', 'date_to':'2027-12-31'})
    for unit, analytic in zip(units, analytics):
        vals = {'company_id':company.id,'period_id':periods[1].id,'organization_id':unit.id,'analytic_id':analytic.id,'amount':1000000}
        controls = env['erp.budget.control'].create([dict(vals,name='PERF analytic',level='analytic'),dict(vals,name='PERF fund',level='fund',fund_id=f['fund'])])
        controls.action_open()
    plans = env['erp.budget.plan']
    for period in periods:
        plan = actor('budget')['erp.budget.plan'].create({'name':'PERF '+period.name,'company_id':company.id,'period_id':period.id,'line_ids':[(0,0,{'organization_id':u.id,'analytic_id':a.id,'initial_amount':1000000}) for u,a in zip(units,analytics)]})
        plan.action_confirm()
        plans |= plan
    existing = env['hr.employee'].search_count([('company_id','=',company.id)])
    env['hr.employee'].with_context(tracking_disable=True).create([{'name':f'PERF Employee {i:04d}','company_id':company.id,'organization_unit_id':units[i%len(units)].id} for i in range(existing,1000)])
measurements = {}
def measure(name, fn):
    before=env.cr.sql_log_count; started=time.monotonic()
    result=fn()
    measurements.setdefault(name,[]).append({'seconds':time.monotonic()-started,'queries':env.cr.sql_log_count-before})
    return result

def make_request(index=0, period_index=0):
    unit, analytic = units[index%len(units)], analytics[index%len(analytics)]
    period=periods[period_index]
    return actor('requester')['erp.procurement.request'].create({'company_id':company.id,'organization_id':unit.id,'date_start':f'{period.date_from.year}-10-01','line_ids':[(0,0,{'name':'PERF request','product_id':f['product'],'product_qty':1,'estimated_cost':100,'period_id':period.id,'fund_id':f['fund'],'analytic_id':analytic.id,'account_id':f['account']})]})

def request_approve(request):
    request.action_submit()
    request.with_user(users['approver']).action_approve()

new_requests=[]
for i in range(40 if resume else 1200):
    request=make_request(i)
    measure('pr_approval',lambda:request_approve(request))
    new_requests.append(request.id)
    if (i+1)%100==0:
        env.cr.commit()
        print('SCALE_PROGRESS',i+1,flush=True)
# Full source workflows at scale, retaining existing fiscal history.
flow=[]
for i, rid in enumerate(new_requests[:20 if resume else 100]):
    request=actor('procurement')['erp.procurement.request'].browse(rid)
    req=actor('procurement')['purchase.requisition'].browse(request.action_create_requisition()['res_id'])
    req.vendor_id=f['vendor'];req.action_confirm()
    po=actor('procurement')['purchase.order'].browse(req.action_create_rfq()['res_id'])
    measure('po_approval',po.button_confirm)
    wa=actor('inventory')['erp.inventory.acceptance'].create({'company_id':company.id,'organization_id':request.organization_id.id,'purchase_order_id':po.id,'line_ids':[(0,0,{'purchase_line_id':po.order_line.id,'quantity':1})]})
    measure('work_acceptance',wa.action_accept)
    picking=po.with_user(users['inventory']).picking_ids
    picking.erp_acceptance_id=wa;picking.move_ids.quantity=1;picking.move_ids.picked=True
    measure('stock_receipt',picking.button_validate)
    bill=actor('finance')['account.move'].create({'move_type':'in_invoice','company_id':company.id,'partner_id':f['vendor'],'journal_id':f['journal'],'invoice_date':'2026-10-01','date':'2026-10-01','erp_acceptance_id':wa.id,'invoice_line_ids':[(0,0,{'name':'PERF equipment bill','product_id':f['product'],'account_id':f['account'],'quantity':1,'price_unit':100,'tax_ids':[(5,0,0)],'purchase_line_id':po.order_line.id,'analytic_distribution':{str(analytics[i%len(units)].id):100}})]})
    measure('bill_post',bill.action_post)
    acquisition=actor('asset')['erp.asset.asset'].search([('bill_id','=',bill.id)])
    assert len(acquisition)==1
    measure('asset_create',acquisition.action_create_depreciation_asset)
    measure('asset_validate',acquisition.engine_asset_id.validate)
    flow.append({'request':rid,'po':po.id,'wa':wa.id,'bill':bill.id,'asset':acquisition.id})
    if (i+1)%20==0:
        env.cr.commit();print('FLOW_PROGRESS',i+1,flush=True)

controls=env['erp.budget.control'].search([('company_id','=',company.id)])
for _ in range(20):
    env.invalidate_all()
    measure('availability_80_controls',lambda:controls.with_user(users['budget']).read(['available_amount']))
    for model in ['erp.procurement.request','purchase.order','account.move','erp.asset.asset','hr.employee']:
        measure('list_'+model,lambda model=model:actor('manager')[model].search_read([],['name'],limit=80))

def race(label, cases):
    barrier=threading.Barrier(len(cases)); results=[]
    env.cr.commit()
    def worker(case):
        rid=case;attempts=0;began=time.monotonic();queries=0
        try:
            with env.registry.cursor() as cr:
                e=api.Environment(cr,users['approver'].id,context)
                def operation():
                    nonlocal attempts,queries
                    attempts+=1
                    if attempts==1:
                        cr.execute('SELECT count(*) FROM erp_budget_move');barrier.wait(30)
                    before=cr.sql_log_count
                    e['erp.procurement.request'].browse(rid).action_approve()
                    queries+=cr.sql_log_count-before
                retrying(operation,e,close_on_commit=False)
            return {'id':rid,'status':'committed','attempts':attempts,'seconds':time.monotonic()-began,'queries':queries}
        except Exception as exc:
            return {'id':rid,'status':type(exc).__name__,'attempts':attempts,'seconds':time.monotonic()-began}
    started=time.monotonic()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(worker,cases))
    env.cr.rollback()
    env.invalidate_all()
    for row in results:
        request=env['erp.procurement.request'].browse(row['id'])
        assert request.state==('approved' if row['status']=='committed' else 'to_approve'), row
    value={'seconds':time.monotonic()-started,'workers':len(cases),'results':results}
    print('CONCURRENCY',label,json.dumps(value),flush=True)
    return value
Path('/var/lib/odoo/readiness-performance-timings.json').write_text(json.dumps(measurements))
races={}
for label,indices in [('same_parent_same_period',[(0,0)]*8),('different_parent_same_period',[(i,0) for i in range(8)]),('different_parent_different_period',[(i,i%2) for i in range(8)])]:
    ids=[]
    for i,p in indices:
        request=make_request(i,p);request.action_submit();ids.append(request.id)
    races[label]=race(label,ids)
# Exact source economic checks: no duplicate active commitments or acquisitions.
env.cr.execute("SELECT source_key, control_id FROM erp_budget_move WHERE reversal_of_id IS NULL AND id NOT IN (SELECT reversal_of_id FROM erp_budget_move WHERE reversal_of_id IS NOT NULL) GROUP BY source_key,control_id,move_type HAVING count(*)>1")
assert not env.cr.fetchall(), 'Duplicate active source ledger'
env.cr.execute('SELECT source_line_id FROM erp_asset_asset GROUP BY source_line_id,item_index,generation HAVING count(*)>1')
assert not env.cr.fetchall(), 'Duplicate acquisition'
for line in plans.line_ids:
    assert line._consumed() <= line._ceiling(), 'Shared parent overspend'
for control in controls:
    assert control.available_amount>=0, 'Control overspend'
queries={}
for name,sql in {'ledger_source':"SELECT * FROM erp_budget_move WHERE source_key='account.move.line:1'",'company_pr':f'SELECT id FROM erp_procurement_request WHERE company_id={company.id} ORDER BY id DESC LIMIT 80'}.items():
    env.cr.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+sql);queries[name]=env.cr.fetchone()[0]
summary={'scope':'synthetic representative workload; intended production SLA is unconfirmed','concurrency':races,'counts':{m:env[m].search_count([]) for m in ['erp.organization.unit','hr.employee','res.users','erp.budget.control','erp.budget.move','erp.procurement.request','purchase.order','account.move','stock.move','erp.asset.asset','account.asset']},'timings':{name:{'samples':len(rows),'median_seconds':statistics.median(r['seconds'] for r in rows),'p95_seconds':sorted(r['seconds'] for r in rows)[min(len(rows)-1,int(len(rows)*.95))],'max_seconds':max(r['seconds'] for r in rows),'median_queries':statistics.median(r['queries'] for r in rows)} for name,rows in measurements.items()},'query_plans':queries,'financial_invariants':'PASS','flow':flow}
env.cr.commit()
Path('/var/lib/odoo/readiness-performance.json').write_text(json.dumps(summary,indent=2,default=str))
print('PERFORMANCE_SUMMARY',json.dumps(summary,default=str),flush=True)
