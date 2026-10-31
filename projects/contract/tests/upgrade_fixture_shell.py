# Run only on an isolated clone of the documented Finance upgrade fixture.
# This creates and commits synthetic data and assumes the earlier fixture IDs; never run on production.
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
user.write({'group_ids': [(4, env.ref('erp_contract.group_contract_manager').id)]})
old_request = env['erp.procurement.request'].browse(1)
company = old_request.company_id
unit = old_request.organization_id
source = old_request.line_ids
product, vendor = source.product_id, env['purchase.order'].browse(1).partner_id
e = env(user=user, context={'allowed_company_ids': [company.id]})
request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2026-06-01'})
e['erp.procurement.request.line'].create({'request_id': request.id, 'name': 'Contract upgrade request', 'product_id': product.id, 'product_qty': 1, 'estimated_cost': 30, 'period_id': source.period_id.id, 'fund_id': source.fund_id.id, 'analytic_id': source.analytic_id.id, 'account_id': source.account_id.id})
request.action_submit()
request.action_approve()
po = e['purchase.order'].create({'company_id': company.id, 'partner_id': vendor.id, 'date_order': '2026-06-01 12:00:00', 'order_line': [(0, 0, {'name': 'Contract upgrade PO', 'product_id': product.id, 'product_qty': 1, 'price_unit': 20, 'date_planned': '2026-06-05 12:00:00', 'tax_ids': [(5, 0, 0)], 'erp_request_line_id': request.line_ids.id, 'erp_budget_fund_id': source.fund_id.id, 'erp_budget_analytic_id': source.analytic_id.id, 'erp_budget_account_id': source.account_id.id, 'analytic_distribution': {str(source.analytic_id.id): 100}})]})
po.erp_agreement_required = True
agreement = e['erp.contract.agreement'].create({'name': 'Upgrade agreement', 'company_id': company.id, 'organization_id': unit.id, 'partner_id': vendor.id, 'purchase_order_id': po.id, 'start_date': '2026-01-01', 'end_date': '2026-12-31', 'signature_date': '2026-06-01'})
agreement.action_activate()
po.button_confirm()
journal = env['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'purchase')], limit=1)
contract = e['erp.contract.contract'].create({'name': 'Upgrade service contract', 'company_id': company.id, 'organization_id': unit.id, 'partner_id': vendor.id, 'journal_id': journal.id})
line = e['erp.contract.line'].create({'contract_id': contract.id, 'name': 'Service', 'product_id': product.id, 'uom_id': product.uom_id.id, 'quantity': 1, 'price_unit': 10, 'date_start': '2026-01-01', 'date_end': '2026-12-31', 'period_id': source.period_id.id, 'fund_id': source.fund_id.id, 'analytic_id': source.analytic_id.id, 'account_id': source.account_id.id})
contract.action_commit_budget()
bill = e['account.move'].with_company(company).create({'move_type': 'in_invoice', 'company_id': company.id, 'partner_id': vendor.id, 'journal_id': journal.id, 'date': '2026-06-10', 'invoice_date': '2026-06-10', 'invoice_line_ids': [(0, 0, {'name': 'Contract upgrade bill', 'product_id': product.id, 'product_uom_id': line.uom_id.id, 'account_id': source.account_id.id, 'quantity': 0.5, 'price_unit': 10, 'tax_ids': [(5, 0, 0)], 'erp_contract_line_id': line.id, 'analytic_distribution': {str(source.analytic_id.id): 100}})]})
bill.action_post()
env.cr.commit()
print('CONTRACT_UPGRADE_SEEDED', agreement.id, contract.id, line.id, bill.id, bill.state)
