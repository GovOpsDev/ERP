# Run with Odoo shell on an isolated, upgraded test database only.
# Creates and commits synthetic business history; never run on production.
import threading
import time
from odoo import api
from odoo.exceptions import UserError

company = env['res.company'].create({'name': 'Asset concurrency', 'erp_budget_amount_mode': 'net'})
unit = env['erp.organization.unit'].create({'name': 'Expense race OU', 'code': 'DRA', 'company_id': company.id})
user = env['res.users'].create({'name': 'Expense race accountant', 'login': 'asset_credit_race', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref('erp_procurement.group_procurement_manager').id, env.ref('erp_budget.group_budget_manager').id, env.ref('account.group_account_invoice').id, env.ref('hr_expense.group_hr_expense_manager').id])]})
env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
env['erp.procurement.tier'].create({'name': 'Race review', 'company_id': company.id, 'reviewer_id': user.id, 'minimum_amount': 0})
group = env['erp.budget.fund.group'].create({'name': 'Race fund group', 'company_id': company.id})
fund = env['erp.budget.fund'].create({'name': 'Race fund', 'group_id': group.id, 'company_id': company.id})
period = env['erp.budget.period'].create({'name': 'Race period', 'company_id': company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
plan = env['account.analytic.plan'].create({'name': 'Race analytics'})
analytic = env['account.analytic.account'].create({'name': 'Race analytic', 'plan_id': plan.id, 'company_id': company.id})
account = env['account.account'].create({'name': 'Race expense', 'code': 'DRAEXP', 'account_type': 'expense', 'company_ids': [(6, 0, company.ids)]})
payable = env['account.account'].create({'name': 'Race payable', 'code': 'DRAPAY', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, company.ids)]})
journal = env['account.journal'].create({'name': 'Race purchases', 'code': 'DRA', 'type': 'purchase', 'company_id': company.id})
vendor = env['res.partner'].create({'name': 'Race supplier'})
vendor.with_company(company).property_account_payable_id = payable
product = env['product.product'].create({'name': 'Race service', 'type': 'service'})
product.with_company(company).property_account_expense_id = account
product.can_be_expensed = True
company.expense_journal_id = journal
employee = env['hr.employee'].create({'name': 'Race employee', 'company_id': company.id, 'expense_manager_id': user.id})
employee.work_contact_id.with_company(company).property_account_payable_id = payable
values = {'company_id': company.id, 'organization_id': unit.id, 'period_id': period.id, 'analytic_id': analytic.id, 'amount': 100}
controls = env['erp.budget.control'].create([dict(values, name='Race analytic cap', level='analytic'), dict(values, name='Race fund cap', level='fund', fund_id=fund.id)])
controls.action_open()
e = env(user=user, context={'allowed_company_ids': company.ids})

user.write({'group_ids': [(4, env.ref('erp_asset.group_asset_manager').id), (4, env.ref('erp_inventory.group_acceptance_manager').id)]})
profile = env['erp.asset.profile'].create({'name': 'Race acquisition', 'company_id': company.id, 'account_id': account.id})
request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2026-06-01', 'line_ids': [(0, 0, {'name': 'Race purchase', 'product_id': product.id, 'product_qty': 1, 'estimated_cost': 100, 'period_id': period.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'account_id': account.id})]})
request.action_submit()
request.action_approve()
warehouse = env['stock.warehouse'].create({'name': 'Asset race warehouse', 'code': 'ASR', 'company_id': company.id})
po = e['purchase.order'].create({'company_id': company.id, 'partner_id': vendor.id, 'date_order': '2026-06-01', 'picking_type_id': warehouse.in_type_id.id, 'order_line': [(0, 0, {'name': 'Race asset', 'product_id': product.id, 'product_qty': 1, 'price_unit': 100, 'date_planned': '2026-06-01', 'tax_ids': [(5, 0, 0)], 'erp_request_line_id': request.line_ids.id, 'erp_budget_fund_id': fund.id, 'erp_budget_analytic_id': analytic.id, 'erp_budget_account_id': account.id, 'analytic_distribution': {str(analytic.id): 100}})]})
po.button_confirm()
acceptance = e['erp.inventory.acceptance'].create({'company_id': company.id, 'organization_id': unit.id, 'purchase_order_id': po.id, 'line_ids': [(0, 0, {'purchase_line_id': po.order_line.id, 'quantity': 1})]})
acceptance.action_accept()
def document(amount, original=None):
    return e['account.move'].create({'move_type': 'in_refund' if original else 'in_invoice', 'company_id': company.id, 'partner_id': vendor.id, 'journal_id': journal.id, 'date': '2026-06-01', 'invoice_date': '2026-06-01', 'erp_acceptance_id': False if original else acceptance.id, 'reversed_entry_id': original.id if original else False, 'invoice_line_ids': [(0, 0, {'name': 'Race asset credit', 'product_id': product.id, 'account_id': account.id, 'quantity': 1, 'price_unit': amount, 'purchase_line_id': po.order_line.id, 'tax_ids': [(5, 0, 0)], 'analytic_distribution': {str(analytic.id): 100}})]})
bill = document(100)
bill.action_post()
acquisition = e['erp.asset.asset'].search([('bill_id', '=', bill.id)])
refunds = document(60, bill) | document(60, bill)
uid, company_id, acquisition_id = user.id, company.id, acquisition.id
registry = env.registry
env.cr.commit()


def race(first_model, first_id, first_method, second_model, second_id, second_method):
    ready, snapshot, release = threading.Event(), threading.Event(), threading.Event()
    results = {}
    def first():
        try:
            with registry.cursor() as cr:
                session = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                getattr(session[first_model].browse(first_id), first_method)()
                ready.set()
                assert release.wait(20)
                cr.commit()
            results['A'] = 'committed'
        except Exception as exc:
            results['A'] = type(exc).__name__
            ready.set()
    def second():
        assert ready.wait(20)
        try:
            with registry.cursor() as cr:
                session = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                cr.execute('SELECT purchase_value FROM erp_asset_asset WHERE id = %s', [acquisition_id])
                cr.fetchone()
                snapshot.set()
                getattr(session[second_model].browse(second_id), second_method)()
                cr.commit()
            results['B'] = 'committed'
        except Exception as exc:
            results['B'] = type(exc).__name__
            snapshot.set()
    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    assert snapshot.wait(20)
    time.sleep(.3)
    release.set()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    print('ASSET_RACE', first_method, second_method, results)
    assert results == {'A': 'committed', 'B': 'SerializationFailure'}, results
    with registry.cursor() as cr:
        session = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
        try:
            with cr.savepoint():
                getattr(session[second_model].browse(second_id), second_method)()
        except UserError:
            pass
        else:
            raise AssertionError('Fresh excess/active-asset retry must fail')
        assert session['erp.asset.asset'].browse(acquisition_id).current_value == 40

race('account.move', refunds[0].id, 'action_post', 'account.move', refunds[1].id, 'action_post')
env.cr.rollback()
env.invalidate_all()
depreciation = env['account.account'].create({'name': 'Accumulated', 'code': 'RDEP', 'account_type': 'asset_fixed', 'company_ids': [(6, 0, [company_id])]})
dep_journal = env['account.journal'].create({'name': 'Depreciation', 'code': 'RDEP', 'type': 'general', 'company_id': company_id})
engine_profile = env['account.asset.profile'].with_company(company).create({'name': 'Race engine', 'company_id': company_id, 'account_asset_id': account.id, 'account_depreciation_id': depreciation.id, 'account_expense_depreciation_id': account.id, 'journal_id': dep_journal.id, 'method_time': 'year', 'method_number': 3, 'method_period': 'year', 'open_asset': False})
account.asset_profile_id = False
profile.oca_profile_id = engine_profile
acquisition.action_create_depreciation_asset()
small_credit = document(10, bill)
engine_id = acquisition.engine_asset_id.id
env.cr.commit()
race('account.asset', engine_id, 'validate', 'account.move', small_credit.id, 'action_post')
print('ASSET_CONCURRENCY_PASSED')
