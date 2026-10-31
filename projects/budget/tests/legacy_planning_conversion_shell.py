# Run only on the disposable upgraded 09abc35 partial-release seed.
from odoo import api
from odoo.exceptions import UserError

company = env['res.company'].search([('name', '=', 'Legacy planning seed')], limit=1)
manager = env['res.users'].search([('login', '=', 'legacy_planning_manager')], limit=1)
reviewer = env['res.users'].search([('login', '=', 'legacy_planning_reviewer')], limit=1)
e = api.Environment(env.cr, manager.id, {'allowed_company_ids': company.ids})
release = e['erp.budget.kpi.release'].search([('company_id', '=', company.id), ('name', '=', 'Legacy planning released')], limit=1)
assert release.state == 'done' and release.line_ids.amount == 70 and not release.planning_snapshot
assert len(release.review_ids) == 1 and not release.line_ids.planning_ids
moves = e['erp.budget.move'].search([('origin_key', '=', 'legacy-planning:commitment')]).ids
revision = e['erp.budget.kpi.release'].browse(release.action_prepare_revision()['res_id'])
assert revision.line_ids.amount == 70 and revision.planning_snapshot
try:
    with env.cr.savepoint():
        revision.action_submit()
except UserError:
    pass
else:
    raise AssertionError('Incomplete canonical planning must be rejected')
assert not revision.review_ids
revision.write({'released_amount': 100})
revision.line_ids.write({'amount': 100})
revision.action_submit()
revision.with_user(reviewer).action_approve()
assert release.state == 'superseded' and release.line_ids.amount == 70
assert revision.state == 'done' and revision.line_ids.amount == 100
assert revision.line_ids.control_id.amount == 100
assert release.plan_line_id._ceiling() == 100 and release.plan_line_id._consumed() == 30
assert e['erp.budget.move'].browse(moves).exists().ids == moves
assert len(release.review_ids) == len(revision.review_ids) == 1
assert len(revision.line_ids.planning_ids) == 1
env.cr.commit()
print('LEGACY_PARTIAL_CANONICAL_SUCCESSOR', release.id, revision.id, release.line_ids.amount, revision.line_ids.amount, release.plan_line_id._ceiling(), release.plan_line_id._consumed())
