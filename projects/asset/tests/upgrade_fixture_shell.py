# Only for an isolated Inventory milestone clone; commits synthetic configuration.
po = env['purchase.order'].browse(1)
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
account = po.order_line[:1].erp_budget_account_id
assert env['account.move.line'].search_count([('purchase_line_id', 'in', po.order_line.ids), ('move_id.state', '=', 'posted')])
assert env['erp.inventory.acceptance'].search_count([('purchase_order_id', '=', po.id), ('state', '=', 'accept')])
assert not env['erp.asset.asset'].search_count([])
profile = env['erp.asset.profile'].create({'name': 'Historical asset profile test', 'company_id': po.company_id.id, 'account_id': account.id})
assert not env['erp.asset.asset'].search_count([])
env.cr.commit()
print('HISTORICAL_PROFILE_SEEDED_WITHOUT_BACKFILL', profile.id)
