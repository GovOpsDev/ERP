"""Prepare isolated synthetic fixtures for repeatable final browser acceptance."""
import json
from pathlib import Path
assert env.cr.dbname == 'erp_readiness'
p=Path('/var/lib/odoo/readiness-fixture.json'); f=json.loads(p.read_text())
company=env['res.company'].browse(f['company'])
year=2027
while env['erp.budget.period'].search_count([('company_id','=',company.id),('date_from','=',f'{year}-01-01')]): year+=1
period=env['erp.budget.period'].create({'name':f'Browser fiscal {year}','company_id':company.id,'date_from':f'{year}-01-01','date_to':f'{year}-12-31','release_policy':'formal'})
f['browser_year']=year
profile=env['account.asset'].browse(f['records']['engine_asset']).profile_id
profile.write({'account_residual_value_id':f['extra']['expense_account']})
manager=env['res.users'].browse(f['users']['manager']['id'])
manager.write({'group_ids':[(4,env.ref('erp_user_role.group_role_manager').id)]})
role=env['erp.user.role'].search([('code','=','READINESS_DATE')],limit=1)
f['security']={'role':role.id,'system_group':env.ref('base.group_system').id,'other_unit':f['units'][1] if 'units' in f else False}
f['actions']['account.asset.transfer']=env.ref('account_asset_transfer.action_account_asset_transfer').id
f['actions']['account.asset.remove']=env.ref('account_asset_management.account_asset_remove_view_form').id
# No business accounting is changed by fixture preparation.
env.cr.commit();p.write_text(json.dumps(f,indent=2));print('BROWSER_FIXTURES_READY',year)
