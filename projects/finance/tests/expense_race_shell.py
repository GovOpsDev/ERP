# Run with Odoo shell on an isolated, upgraded test database only.
# Creates and commits synthetic business history; never run on production.
import threading
import time
from odoo import api
from odoo.exceptions import UserError

company = env['res.company'].create({'name': 'Expense concurrency', 'erp_budget_amount_mode': 'net'})
unit = env['erp.organization.unit'].create({'name': 'Expense race OU', 'code': 'DRA', 'company_id': company.id})
user = env['res.users'].create({'name': 'Expense race accountant', 'login': 'expense_race', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref('erp_procurement.group_procurement_manager').id, env.ref('erp_budget.group_budget_manager').id, env.ref('account.group_account_invoice').id, env.ref('hr_expense.group_hr_expense_manager').id])]})
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
key = {'erp_budget_period_id': period.id, 'erp_budget_organization_id': unit.id, 'erp_budget_fund_id': fund.id, 'erp_budget_analytic_id': analytic.id, 'analytic_distribution': {str(analytic.id): 100}}
bills = e['hr.expense'].with_company(company).create([dict(key, name='Race expense '+str(index), company_id=company.id, employee_id=employee.id, product_id=product.id, account_id=account.id, date='2026-06-%02d' % (index + 1), quantity=1, total_amount_currency=80, tax_ids=[(5, 0, 0)]) for index in range(3)])
for expense in bills:
    expense.action_submit()
request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2026-06-01', 'line_ids': [(0, 0, {'name': 'Concurrent request', 'product_id': product.id, 'product_qty': 1, 'estimated_cost': 60, 'period_id': period.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'account_id': account.id})]})
uid, company_id, control_id = user.id, company.id, controls.filtered(lambda row: row.level == 'analytic').id
bill_ids, request_id, registry = bills.ids, request.id, env.registry
env.cr.commit()


def race(label, first_id, second_id=None):
    posted = threading.Event()
    snapshot = threading.Event()
    release = threading.Event()
    results = {}

    def first():
        try:
            with registry.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                e['hr.expense'].browse(first_id).action_approve()
                posted.set()
                assert release.wait(20), 'second cursor did not establish its snapshot'
                cr.commit()
            results['A'] = 'committed'
        except Exception as exc:
            results['A'] = type(exc).__name__
            posted.set()

    def second():
        assert posted.wait(20)
        try:
            with registry.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                cr.execute('SELECT amount FROM erp_budget_control WHERE id = %s', [control_id])
                cr.fetchone()
                snapshot.set()
                if second_id:
                    e['hr.expense'].browse(second_id).action_approve()
                else:
                    source = e['erp.procurement.request'].browse(request_id)
                    source.action_submit()
                    source.action_approve()
                cr.commit()
            results['B'] = 'committed'
        except Exception as exc:
            results['B'] = type(exc).__name__
            snapshot.set()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    assert snapshot.wait(20)
    time.sleep(0.3)
    release.set()
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    with registry.cursor() as cr:
        e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
        cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [control_id])
        consumed = cr.fetchone()[0]
        loser = e['hr.expense'].browse(second_id) if second_id else e['erp.procurement.request'].browse(request_id)
        print(label, results, 'consumed', consumed, 'loser', loser.state)
        assert results == {'A': 'committed', 'B': 'SerializationFailure'}
        assert consumed == 80 and loser.state == ('submitted' if second_id else 'draft')
        try:
            with cr.savepoint():
                if second_id:
                    loser.action_approve()
                else:
                    loser.action_submit()
        except UserError:
            pass
        else:
            raise AssertionError('fresh retry must respect the remaining capacity')
        e['hr.expense'].browse(first_id).action_reset()
        cr.commit()


race('EXPENSE_VS_EXPENSE', bill_ids[0], bill_ids[1])
race('EXPENSE_VS_PR', bill_ids[2])
print('EXPENSE_RACES_PASSED')
