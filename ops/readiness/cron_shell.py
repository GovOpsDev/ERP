"""OPERATIONS FIX: real scheduler transactions, date boundaries and visible retry.

Only synthetic UAT records. Contract jobs use a scoped service user; role expiry
uses the existing administrator-owned reconciliation job as designed.
"""
from datetime import date,timedelta
import json,time
from pathlib import Path
from unittest.mock import patch
from odoo import fields
assert env.cr.dbname=='erp_readiness'
f=json.loads(Path('/var/lib/odoo/readiness-fixture.json').read_text())
assert not env['ir.cron'].with_context(active_test=False).search([('name','=','Readiness recurring invoices')]), 'Cron fixture already exists'
company=env['res.company'].browse(f['company']);context={'allowed_company_ids':company.ids,'tz':'Asia/Bangkok'}
contract_user=env['res.users'].browse(f['users']['contract']['id']);e=env(user=contract_user,context=context)
today=fields.Date.context_today(e['erp.contract.contract'])
contract=e['erp.contract.contract'].create({'name':'Readiness cron recurrence','company_id':company.id,'organization_id':f['unit'],'partner_id':f['vendor'],'journal_id':f['journal'],'recurrence_enabled':True,'line_ids':[(0,0,{'name':'Readiness recurring service','product_id':f['extra']['service'],'uom_id':f['extra']['uom'],'quantity':1,'price_unit':10,'date_start':today,'date_end':today,'period_id':f['period'],'fund_id':f['fund'],'analytic_id':f['analytics'][0],'account_id':f['extra']['expense_account'],'auto_renew':True,'termination_notice_days':0})]})
line=contract.line_ids
atype=env['erp.contract.agreement.type'].create({'name':'Readiness expiry review','review_days':0,'review_user_id':contract_user.id})
proc=env(user=f['users']['procurement']['id'],context=context)
request=proc['erp.procurement.request'].browse(f['requests'][90])
req=proc['purchase.requisition'].browse(request.action_create_requisition()['res_id'])
req.vendor_id=f['vendor'];req.action_confirm()
po=proc['purchase.order'].browse(req.action_create_rfq()['res_id'])
agreement=e['erp.contract.agreement'].create({'name':'Readiness expiring agreement','purchase_order_id':po.id,'company_id':company.id,'organization_id':f['unit'],'partner_id':f['vendor'],'start_date':today-timedelta(days=1),'end_date':today,'type_id':atype.id})
# Harmless dated capability; no business permission is granted by this group.
group=env['res.groups'].create({'name':'Readiness dated capability'})
role=env['erp.user.role'].create({'name':'Readiness dated role','code':'READINESS_DATE','company_id':company.id,'group_ids':[(4,group.id)]})
assignment=env['erp.user.role.assignment'].create({'user_id':f['users']['requester']['id'],'role_id':role.id,'company_id':company.id,'unit_id':f['unit'],'date_from':'2026-12-31','date_to':'2027-01-01'})

def cron(name,model,code,uid):
 return env['ir.cron'].create({'name':name,'model_id':env['ir.model']._get_id(model),'code':code,'user_id':uid,'interval_number':1,'interval_type':'days','active':False})
jobs=[cron('Readiness recurring invoices','erp.contract.contract','model._cron_recurring_invoices()',contract_user.id),cron('Readiness contract renewals','erp.contract.line','model._cron_renew_contract_lines()',contract_user.id),cron('Readiness agreement reviews','erp.contract.agreement','model._cron_agreement_reviews()',contract_user.id),cron('Readiness scoped depreciation','account.asset.compute','model.create({}).asset_compute()',f['users']['asset']['id'])]
probe=cron('Readiness expected failure probe','erp.contract.contract',"raise UserError('READINESS_EXPECTED_CRON_FAILURE')",contract_user.id)
env.cr.commit()
results=[]
def run(job):
 started=time.monotonic();outcome=job.method_direct_trigger();env.cr.commit();env.invalidate_all()
 result={'name':job.name,'seconds':time.monotonic()-started,'failure_count':job.failure_count,'lastcall':str(job.lastcall),'result':True if outcome is True else outcome.get('tag')}
 results.append(result);print('CRON_RUN',json.dumps(result),flush=True);return outcome
for job in jobs:
 assert run(job) is True
 assert run(job) is True
 assert job.failure_count==0
assert len(line.cycle_ids)==1
assert len(line.successor_ids)==1
activities=env['mail.activity'].search([('res_model','=','erp.contract.agreement'),('res_id','=',agreement.id)])
assert len(activities)==1
assert all(c.company_id==company for c in line.cycle_ids)
role_job=env['ir.cron'].search([('model_id.model','=','erp.user.role.assignment')],limit=1)
for day,expected in [(date(2026,12,30),False),(date(2026,12,31),True),(date(2027,1,1),True),(date(2027,1,2),False)]:
 with patch('odoo.addons.erp_user_role.models.membership.fields.Date.today',return_value=day):
  assert run(role_job) is True
  target=env['res.users'].browse(f['users']['requester']['id'])
  assert (group in target.group_ids)==expected,(day,expected)
# Return date-sensitive role state to actual runtime date.
assert run(role_job) is True
outcome=run(probe);assert isinstance(outcome,dict) and outcome['tag']=='display_exception'
assert probe.failure_count==1 and probe.first_failure_date
print('CRON_FAILURE_VISIBLE',probe.id,probe.failure_count,flush=True)
probe.write({'code':'model.search_count([])' });env.cr.commit()
assert run(probe) is True and probe.failure_count==0 and not probe.first_failure_date
# Dedicated scoped jobs are configured but activation is an explicit deployment step.
probe.active=False
env.cr.commit()
result={'jobs':results,'role_boundary':'PASS','contract_cycles':len(line.cycle_ids),'successors':len(line.successor_ids),'agreement_activities':len(activities),'failure_and_retry':'PASS','scheduled_job_ids':jobs.ids if hasattr(jobs,'ids') else [j.id for j in jobs],'scope':'synthetic UAT, actual scheduler separate transactions'}
Path('/var/lib/odoo/readiness-cron.json').write_text(json.dumps(result,indent=2))
print('CRON_ACCEPTANCE',json.dumps(result),flush=True)
