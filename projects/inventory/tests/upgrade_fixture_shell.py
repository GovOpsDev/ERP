# Synthetic fixture, only on an isolated copy of the Contract milestone.
po = env['purchase.order'].browse(1)
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
user.write({'group_ids': [(4, env.ref('erp_inventory.group_acceptance_manager').id)]})
e = env(user=user, context={'allowed_company_ids': [po.company_id.id]})
acceptance = e['erp.inventory.acceptance'].create({'company_id': po.company_id.id, 'organization_id': po.erp_request_organization_id.id, 'purchase_order_id': po.id, 'line_ids': [(0, 0, {'purchase_line_id': po.order_line[:1].id, 'quantity': po.order_line[:1].product_qty * 0.4})]})
acceptance.action_accept()
env.cr.commit()
print('INVENTORY_UPGRADE_SEEDED', acceptance.id, acceptance.name, acceptance.state, acceptance.line_ids.quantity)
