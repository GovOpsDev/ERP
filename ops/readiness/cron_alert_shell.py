"""Exercise visible cron failure/recovery in the synthetic UAT only."""
import os
assert env.cr.dbname=='erp_readiness'
job=env['ir.cron'].with_context(active_test=False).search([('name','=','Readiness expected failure probe')]);assert len(job)==1
recover=os.environ.get('READINESS_CRON_RECOVER')=='1'
job.write({'active':True,'code':'model.search_count([])' if recover else "raise UserError('READINESS_EXPECTED_CRON_FAILURE')"})
env.cr.commit();result=job.method_direct_trigger();env.cr.commit();env.invalidate_all()
assert job.failure_count==(0 if recover else 1)
if recover:job.active=False;env.cr.commit()
print('CRON_ALERT_PROBE', 'RECOVERED' if recover else 'VISIBLE_FAILURE', job.failure_count)
