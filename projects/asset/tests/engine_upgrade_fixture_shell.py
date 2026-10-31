# Run only in a disposable clone of the upgraded Asset milestone.
acquisition = env['erp.asset.asset'].search([], limit=1)
assert acquisition and not acquisition.engine_asset_id
company = acquisition.company_id
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
user.write({'group_ids': [(4, env.ref('erp_asset.group_asset_manager').id)]})
journal = env['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'general')], limit=1)
if not journal:
    journal = env['account.journal'].create({'name': 'Engine fixture', 'code': 'EFIX', 'type': 'general', 'company_id': company.id})
account = acquisition.source_line_id.account_id
depreciation = env['account.account'].create({'name': 'Fixture accumulated depreciation', 'code': 'FXDEP', 'account_type': 'asset_fixed', 'company_ids': [(6, 0, [company.id])]})
expense = env['account.account'].create({'name': 'Fixture depreciation expense', 'code': 'FXEXP', 'account_type': 'expense', 'company_ids': [(6, 0, [company.id])]})
profile = env['account.asset.profile'].with_company(company).create({'name': 'Upgrade engine fixture', 'company_id': company.id, 'account_asset_id': account.id, 'account_depreciation_id': depreciation.id, 'account_expense_depreciation_id': expense.id, 'journal_id': journal.id, 'method_time': 'year', 'method_number': 3, 'method_period': 'year', 'open_asset': False})
account.asset_profile_id = False
acquisition.profile_id.oca_profile_id = profile
acquisition.with_user(user).with_context(allowed_company_ids=[company.id]).action_create_depreciation_asset()
asset = acquisition.engine_asset_id
assert asset.erp_acquisition_id == acquisition and asset.purchase_value == acquisition.purchase_value and asset.date_start == acquisition.date_start
assert env['account.asset'].search_count([('erp_acquisition_id', '=', acquisition.id)]) == 1
asset.validate()
line = asset.depreciation_line_ids.filtered(lambda row: row.type == 'depreciate')[:1]
assert line
line.create_move()
assert line.move_id.state == 'posted'
env.cr.commit()
print('EXISTING_ACQUISITION_LINKED', acquisition.id, asset.id, asset.state)
