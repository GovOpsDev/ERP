# Run with Odoo shell on an isolated, upgraded test database only.
# Creates and commits synthetic business history; never run on production.
import threading
import time
from odoo import api
from odoo.exceptions import UserError

company = env['res.company'].create({'name': 'Expense concurrency', 'erp_budget_amount_mode': 'net'})
unit = env['erp.organization.unit'].create({'name': 'Expense race OU', 'code': 'DRA', 'company_id': company.id})
user = env['res.users'].create({'name': 'Expense race accountant', 'login': 'advance_race', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref('erp_procurement.group_procurement_manager').id, env.ref('erp_budget.group_budget_manager').id, env.ref('account.group_account_invoice').id, env.ref('hr_expense.group_hr_expense_manager').id])]})
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
advance_account = env['account.account'].create({'name': 'Race employee advance', 'code': 'ADR', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, company.ids)]})
settlement_journal = env['account.journal'].create({'name': 'Race advance settlement', 'code': 'ADS', 'type': 'general', 'company_id': company.id})
bank_account = env['account.account'].create({'name': 'Race advance bank', 'code': 'ADB', 'account_type': 'asset_cash', 'company_ids': [(6, 0, company.ids)]})
bank_journal = env['account.journal'].create({'name': 'Race advance bank', 'code': 'ADB', 'type': 'bank', 'company_id': company.id, 'default_account_id': bank_account.id})
company.write({'erp_employee_advance_account_id': advance_account.id, 'erp_employee_advance_journal_id': settlement_journal.id})
advance = e['hr.expense'].create(dict(key, name='Race advance 80', company_id=company.id, employee_id=employee.id, product_id=product.id, account_id=advance_account.id, date='2026-06-01', quantity=1, total_amount_currency=80, tax_ids=[(5, 0, 0)], erp_is_advance=True))
advance.action_submit()
advance.action_approve()
advance.account_move_id.action_post()
clearing = e['hr.expense'].create(dict(key, name='Race clearing 60', company_id=company.id, employee_id=employee.id, product_id=product.id, account_id=account.id, date='2026-06-02', quantity=1, total_amount_currency=60, tax_ids=[(5, 0, 0)], erp_advance_ids=[(6, 0, advance.ids)]))
clearing.action_submit()
returns = e['erp.finance.advance.return'].create([{'name': 'Race return '+str(index), 'advance_id': advance.id, 'journal_id': bank_journal.id, 'date': '2026-06-03', 'amount': 60, 'currency_id': company.currency_id.id} for index in range(3)])
uid, company_id, control_id = user.id, company.id, controls.filtered(lambda row: row.level == 'analytic').id
clearing_id, return_ids, registry = clearing.id, returns.ids, env.registry
env.cr.commit()


def race(label, clearing_first=False):
    ready, snapshot, release = threading.Event(), threading.Event(), threading.Event()
    results = {}
    first_id = clearing_id if clearing_first else return_ids[0]
    second_id = return_ids[2] if clearing_first else return_ids[1]

    def first():
        try:
            with registry.cursor() as cr:
                tx = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                if clearing_first:
                    tx['hr.expense'].browse(first_id).action_approve()
                else:
                    tx['erp.finance.advance.return'].browse(first_id).action_post()
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
                tx = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                cr.execute('SELECT amount FROM erp_budget_control WHERE id = %s', [control_id])
                cr.fetchone()
                snapshot.set()
                tx['erp.finance.advance.return'].browse(second_id).action_post()
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
    with registry.cursor() as cr:
        tx = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
        loser = tx['erp.finance.advance.return'].browse(second_id)
        cr.execute('SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id = %s', [control_id])
        amount = cr.fetchone()[0]
        print(label, results, 'consumed', amount, 'loser', loser.state)
        assert results == {'A': 'committed', 'B': 'SerializationFailure'}
        assert amount == (80 if clearing_first else 20) and loser.state == 'draft'
        try:
            with cr.savepoint():
                loser.action_post()
        except UserError:
            pass
        else:
            raise AssertionError('fresh retry must reject an over-return after the winning transaction')
        if clearing_first:
            tx['hr.expense'].browse(first_id).action_reset()
        else:
            tx['erp.finance.advance.return'].browse(first_id).action_cancel()
        cr.commit()

race('RETURN_VS_RETURN')
race('CLEARING_APPROVAL_VS_RETURN', clearing_first=True)
print('ADVANCE_RACES_PASSED')
