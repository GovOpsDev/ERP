"""Explicit activation in the restored synthetic deployment, never a production DB."""
from datetime import timedelta
import json
from pathlib import Path
from odoo import fields
assert env.cr.dbname=='erp_restored_acceptance'
fixture=json.loads(Path('/var/lib/odoo/readiness-cron.json').read_text())
jobs=env['ir.cron'].browse(fixture['scheduled_job_ids']).exists()
role=env['ir.cron'].with_context(active_test=False).search([('model_id.model','=','erp.user.role.assignment')],limit=1)
assert len(jobs)==4 and role
jobs|=role
# Keep network/email/native maintenance dormant on the isolated deployment copy.
env['ir.cron'].with_context(active_test=False).search([]).write({'active':False})
threshold=fields.Datetime.now()
jobs.write({'active':True,'nextcall':threshold-timedelta(minutes=1)})
env.cr.commit()
Path('/var/lib/odoo/readiness-deployed-cron.json').write_text(json.dumps({'database':env.cr.dbname,'ids':jobs.ids,'threshold':str(threshold)},indent=2))
print('DEPLOYED_CRON_ACTIVATED',jobs.ids,str(threshold))
