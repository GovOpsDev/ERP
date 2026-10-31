"""Synthetic AUC configuration only; lifecycle is exercised by ordinary browser roles."""
import json
from pathlib import Path
assert env.cr.dbname=='erp_readiness'
p=Path('/var/lib/odoo/readiness-fixture.json');f=json.loads(p.read_text());assert 'auc' not in f
c=env['res.company'].browse(f['company']);base=env['account.asset'].browse(f['records']['engine_asset']).profile_id
account=env['account.account'].create({'name':'UAT construction in progress','code':'UAT102','account_type':'asset_fixed','company_ids':[(6,0,c.ids)]})
engine=env['account.asset.profile'].create({'name':'UAT AUC','company_id':c.id,'account_asset_id':account.id,'account_depreciation_id':base.account_depreciation_id.id,'account_expense_depreciation_id':base.account_expense_depreciation_id.id,'journal_id':base.journal_id.id,'method_time':'year','method_number':0,'method_period':'year','open_asset':False})
profile=env['erp.asset.profile'].create({'name':'UAT AUC acquisition','company_id':c.id,'account_id':account.id,'oca_profile_id':engine.id})
account.asset_profile_id=False
f['auc']={'account':account.id,'profile':profile.id,'engine_profile':engine.id,'destination_profile':base.id,'journal':base.journal_id.id}
env.cr.commit();p.write_text(json.dumps(f,indent=2));print('AUC_CONFIGURATION_READY')
