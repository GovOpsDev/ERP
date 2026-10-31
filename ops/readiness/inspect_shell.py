"""DATA MIGRATION FIX: report file integrity, scope inconsistencies and runtime state.

Read-only diagnostics; never backfill mappings, reviewer history or attachments.
"""
import hashlib
import json
from pathlib import Path
from odoo import tools

assert env.cr.dbname.startswith(('erp_readiness','erp_restored','erp_rollback'))
attachments=[]
fixture_path = Path('/var/lib/odoo/readiness-fixture.json')
expected = {item['id']: item for item in json.loads(fixture_path.read_text())['attachments']} if fixture_path.exists() and env.cr.dbname in ('erp_readiness','erp_restored_acceptance') else {}
for record in env['ir.attachment'].search([('type','=','binary')]):
    row={'id':record.id,'model':record.res_model,'record_id':record.res_id,'field':record.res_field,'file_size':record.file_size}
    if record.store_fname:
        path=Path(record._full_path(record.store_fname))
        row['exists']=path.is_file()
        if path.is_file():
            data=path.read_bytes()
            row.update(size_matches=len(data)==record.file_size,checksum_matches=hashlib.sha1(data).hexdigest()==record.checksum,sha256=hashlib.sha256(data).hexdigest())
    else:
        row['stored_in_database']=bool(record.db_datas)
    if record.id in expected:
        wanted = expected[record.id]
        data = bytes(record.raw) if record.raw else b''
        row['fixture_matches'] = len(data) == wanted['bytes'] and hashlib.sha256(data).hexdigest() == wanted['sha256']
    attachments.append(row)
scope=[]
for model,field in [('erp.organization.unit','parent_id'),('hr.employee','organization_unit_id'),('erp.procurement.request','organization_id'),('erp.inventory.acceptance','organization_id'),('erp.asset.asset','organization_id'),('erp.contract.contract','organization_id'),('erp.budget.control','organization_id')]:
    for record in env[model].with_context(active_test=False).search([]):
        other=record[field]
        if other and record.company_id!=other.company_id:
            scope.append({'model':model,'id':record.id,'field':field,'reason':'company mismatch'})
models=['res.company','erp.organization.unit','res.users','hr.employee','erp.organization.assignment','erp.employee.organization.assignment','erp.user.role.assignment','erp.budget.period','erp.budget.plan','erp.budget.allocation','erp.budget.control','erp.budget.move','erp.procurement.request','purchase.requisition','purchase.order','account.move','account.move.line','erp.contract.contract','erp.contract.agreement','erp.inventory.acceptance','erp.inventory.request','stock.move','erp.asset.asset','account.asset','account.asset.line']
installed=env['ir.module.module'].search([('state','=','installed')])
cron=[]
for job in env['ir.cron'].with_context(active_test=False).search([]):
    cron.append({'id':job.id,'name':job.name,'active':job.active,'user_id':job.user_id.id,'model':job.model_id.model,'code':job.code,'nextcall':str(job.nextcall),'failure_count':job.failure_count})
result={'database':env.cr.dbname,'counts':{m:env[m].with_context(active_test=False).search_count([]) for m in models if m in env},'attachments':attachments,'attachment_failures':[r for r in attachments if r.get('exists') is False or r.get('size_matches') is False or r.get('checksum_matches') is False], 'invalid_company_scope':scope,'installed_modules':installed.mapped('name'),'enterprise_modules':installed.filtered(lambda m:m.license in ['OEEL-1','OPL-1']).mapped('name'),'cron':cron,'db_uuid':env['ir.config_parameter'].get_str('database.uuid'),'addons_path':tools.config['addons_path']}
print('READINESS_INSPECTION '+json.dumps(result,default=str))
assert all(row.get('fixture_matches', True) for row in attachments), 'Representative attachment content is missing or incorrect'
assert not result['invalid_company_scope'], 'Invalid company references require explicit reconciliation'
assert not result['enterprise_modules'], 'Enterprise modules are outside this deployment'
assert not result['attachment_failures'], 'Missing or corrupt attachment files require reconciliation'
