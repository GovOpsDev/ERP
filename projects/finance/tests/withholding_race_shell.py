# Run with Odoo shell on an isolated, upgraded test database only.
# Creates and commits synthetic business history; never run on production.
import threading
import time
from odoo import api
from odoo.exceptions import UserError

company = env['res.company'].create({'name': 'Withholding concurrency', 'erp_budget_amount_mode': 'net'})
unit = env['erp.organization.unit'].create({'name': 'Expense race OU', 'code': 'DRA', 'company_id': company.id})
user = env['res.users'].create({'name': 'Expense race accountant', 'login': 'withholding_race', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref('erp_procurement.group_procurement_manager').id, env.ref('erp_budget.group_budget_manager').id, env.ref('account.group_account_invoice').id, env.ref('hr_expense.group_hr_expense_manager').id])]})
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

company.country_id = env.ref('base.th')
advance_account = env['account.account'].create({'name': 'Advance', 'code': 'WHADV', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, company.ids)]})
settlement = env['account.journal'].create({'name': 'Settlement', 'code': 'WHST', 'type': 'general', 'company_id': company.id})
bank_account = env['account.account'].create({'name': 'Bank', 'code': 'WHBANK', 'account_type': 'asset_cash', 'company_ids': [(6, 0, company.ids)]})
bank = env['account.journal'].create({'name': 'Bank', 'code': 'WHB', 'type': 'bank', 'company_id': company.id, 'default_account_id': bank_account.id})
company.write({'erp_employee_advance_account_id': advance_account.id, 'erp_employee_advance_journal_id': settlement.id})
base = env['account.account'].create({'name': 'WHT base', 'code': 'WHBASE', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, company.ids)]})
liability = env['account.account'].create({'name': 'WHT payable', 'code': 'WHPAY', 'account_type': 'liability_current', 'company_ids': [(6, 0, company.ids)]})
company.withholding_tax_base_account_id = base
tax_group = env['account.tax.group'].create({'name': 'WHT', 'company_id': company.id})
tax = env['account.tax'].create({'name': 'WHT 3%', 'amount': -3, 'type_tax_use': 'purchase', 'is_withholding_tax': True, 'company_id': company.id, 'tax_group_id': tax_group.id, 'invoice_repartition_line_ids': [(0, 0, {'repartition_type': 'base'}), (0, 0, {'repartition_type': 'tax', 'account_id': liability.id})], 'refund_repartition_line_ids': [(0, 0, {'repartition_type': 'base'}), (0, 0, {'repartition_type': 'tax', 'account_id': liability.id})]})
key = {'erp_budget_period_id': period.id, 'erp_budget_organization_id': unit.id, 'erp_budget_fund_id': fund.id, 'erp_budget_analytic_id': analytic.id, 'analytic_distribution': {str(analytic.id): 100}, 'company_id': company.id, 'employee_id': employee.id, 'product_id': product.id, 'date': '2026-06-01', 'quantity': 1, 'total_amount_currency': 80, 'currency_id': company.currency_id.id}
advance = e['hr.expense'].create(dict(key, name='Race advance', account_id=advance_account.id, erp_is_advance=True, tax_ids=[(5, 0, 0)]))
advance.action_submit()
advance.action_approve()
advance.account_move_id.action_post()
clearing = e['hr.expense'].create(dict(key, name='Race withholding clearing', date='2026-06-02', account_id=account.id, erp_advance_ids=[(6, 0, advance.ids)], tax_ids=[(6, 0, tax.ids)], vendor_id=vendor.id))
clearing.action_submit()
clearing.action_approve()
assert clearing.approval_state == 'approved' and clearing.account_move_id, 'Fixture must reach a real approved accounting document'
uid, company_id = user.id, company.id
control_id = controls.filtered(lambda item: item.level == 'analytic').id
bill_id, clearing_id, advance_id, registry = clearing.account_move_id.id, clearing.id, advance.id, env.registry
env.cr.commit()


def race(model, first_id, second_id):
    ready, snapshot, release = threading.Event(), threading.Event(), threading.Event()
    results = {}

    def first():
        try:
            with registry.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                e[model].browse(first_id).action_post()
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
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                cr.execute('SELECT amount FROM erp_budget_control WHERE id = %s', [control_id])
                cr.fetchone()
                snapshot.set()
                e[model].browse(second_id).action_post()
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
    print('WITHHOLDING_RACE', model, results)
    assert results == {'A': 'committed', 'B': 'SerializationFailure'}
    with registry.cursor() as cr:
        e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
        try:
            with cr.savepoint():
                e[model].browse(second_id).action_post()
        except UserError:
            pass
        else:
            raise AssertionError('Fresh duplicate/excess retry must fail')
        assert len(e['hr.expense'].browse(clearing_id).erp_withholding_payment_ids) == 1
        consumed = sum(e['erp.budget.move'].search([('control_id', '=', control_id)]).mapped('amount'))
        assert consumed == 80, consumed


race('account.move', bill_id, bill_id)
env.cr.rollback()
env.invalidate_all()
returns = e['erp.finance.advance.return'].create([{'name': 'WHT remaining cash '+str(index), 'advance_id': advance_id, 'journal_id': bank.id, 'date': '2026-06-03', 'amount': 2.4, 'currency_id': company.currency_id.id} for index in range(2)])
return_ids = returns.ids
env.cr.commit()
race('erp.finance.advance.return', *return_ids)
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    assert e['hr.expense'].browse(advance_id).erp_advance_remaining == 0
print('WITHHOLDING_CONCURRENCY_PASSED')
