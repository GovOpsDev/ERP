"""Explicit synthetic operator setup on the fresh historical rollback copy only."""
import hashlib,json
from odoo.tools.binary import BinaryBytes
from pathlib import Path
assert env.cr.dbname=='erp_rollback_predeploy'
user=env.ref('base.user_admin')
user.write({'login':'readiness_rollback_admin','password':Path('/run/secrets/uat_password').read_text().strip(),'company_ids':[(6,0,env['res.company'].search([]).ids)]})
refs=['erp_organization.group_organization_manager','erp_user_role.group_role_manager','erp_budget.group_budget_manager','erp_procurement.group_procurement_manager','account.group_account_manager','erp_contract.group_contract_manager','erp_inventory.group_acceptance_manager','erp_asset.group_asset_manager']
for ref in refs:
 group=env.ref(ref,raise_if_not_found=False)
 if group:user.write({'group_ids':[(4,group.id)]})
for unit in env['erp.organization.unit'].search([]):
 if not env['erp.organization.assignment'].search_count([('user_id','=',user.id),('unit_id','=',unit.id)]):env['erp.organization.assignment'].create({'user_id':user.id,'unit_id':unit.id})
user.company_id=env['erp.organization.unit'].search([],limit=1).company_id
models=['erp.organization.unit','erp.budget.control','erp.procurement.request','account.move','erp.contract.contract','erp.inventory.acceptance','erp.asset.asset']
records=[]
for model in models:
 rec=env[model].search([],limit=1);assert rec,model
 action=env['ir.actions.act_window'].search([('res_model','=',model)],order='id',limit=1)
 records.append({'model':model,'id':rec.id,'action':action.id})
attachments=[]
# Generated web bundles can be replaced by Odoo during startup. Use stable,
# explicitly synthetic domain attachments for authenticated HTTP acceptance.
for r in records:
    payload=('Synthetic rollback evidence: '+r['model']+'\n').encode()
    a=env['ir.attachment'].create({'name':'Rollback '+r['model'], 'res_model':r['model'],'res_id':r['id'],'raw':BinaryBytes(payload)})
    data=bytes(a.raw);assert data==payload
    attachments.append({'id':a.id,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
f={'login':user.login,'records':records,'attachments':attachments,'companies':user.company_ids.ids}
env.cr.commit();Path('/var/lib/odoo/rollback-smoke-fixture.json').write_text(json.dumps(f,indent=2));print('ROLLBACK_OPERATOR_READY',len(records),len(attachments))
