# Run with Odoo shell on an isolated, upgraded test database only.
# Creates and commits synthetic business history; never run on production.
import threading
import time
from odoo import api
from odoo.exceptions import UserError

company = env['res.company'].create({'name': 'Deposit concurrency', 'erp_budget_amount_mode': 'net'})
env['stock.warehouse'].create({'name': 'Deposit race warehouse', 'code': 'DPR', 'company_id': company.id})
unit = env['erp.organization.unit'].create({'name': 'Direct race OU', 'code': 'DRA', 'company_id': company.id})
user = env['res.users'].create({'name': 'Direct race accountant', 'login': 'deposit_race', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, [env.ref('erp_procurement.group_procurement_manager').id, env.ref('erp_budget.group_budget_manager').id, env.ref('account.group_account_invoice').id])]})
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
values = {'company_id': company.id, 'organization_id': unit.id, 'period_id': period.id, 'analytic_id': analytic.id, 'amount': 100}
controls = env['erp.budget.control'].create([dict(values, name='Race analytic cap', level='analytic'), dict(values, name='Race fund cap', level='fund', fund_id=fund.id)])
controls.action_open()
e = env(user=user, context={'allowed_company_ids': company.ids})
request = e['erp.procurement.request'].create({'company_id': company.id, 'organization_id': unit.id, 'date_start': '2026-06-01', 'line_ids': [(0, 0, {'name': 'Deposit request', 'product_id': product.id, 'product_qty': 10, 'estimated_cost': 100, 'period_id': period.id, 'fund_id': fund.id, 'analytic_id': analytic.id, 'account_id': account.id})]})
request.action_submit()
request.action_approve()
po = e['purchase.order'].create({'company_id': company.id, 'partner_id': vendor.id, 'date_order': '2026-06-01', 'order_line': [(0, 0, {'name': 'Deposit source', 'product_id': product.id, 'product_qty': 10, 'price_unit': 10, 'date_planned': '2026-06-10', 'tax_ids': [(5, 0, 0)], 'erp_request_line_id': request.line_ids.id, 'erp_budget_period_id': period.id, 'erp_budget_fund_id': fund.id, 'erp_budget_analytic_id': analytic.id, 'erp_budget_account_id': account.id, 'analytic_distribution': {str(analytic.id): 100}})]})
po.button_confirm()
origin = po.order_line
base_line = {'name': 'Deposit', 'account_id': account.id, 'quantity': 1, 'price_unit': 40, 'tax_ids': [(5, 0, 0)], 'analytic_distribution': {str(analytic.id): 100}}
base_bill = {'move_type': 'in_invoice', 'company_id': company.id, 'journal_id': journal.id, 'partner_id': vendor.id, 'date': '2026-06-01', 'invoice_date': '2026-06-01'}
deposit = e['account.move'].with_company(company).create(dict(base_bill, invoice_line_ids=[(0, 0, base_line)]))
deposit.action_post()
e['bill.to.po.wizard'].with_context(active_ids=[-deposit.invoice_line_ids.id]).create({'purchase_order_id': po.id}).action_add_downpayment()
dpl = deposit.invoice_line_ids.purchase_line_id
bills = e['account.move'].with_company(company).create([dict(base_bill, invoice_line_ids=[(0, 0, dict(base_line, name='Partial delivery', product_id=product.id, product_uom_id=origin.uom_id.id, quantity=5, price_unit=10, purchase_line_id=origin.id)), (0, 0, dict(base_line, name='Deposit deduction', quantity=-0.75, purchase_line_id=dpl.id))]) for _ in range(2)])
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
                e['account.move'].browse(first_id).action_post()
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
                    e['account.move'].browse(second_id).action_post()
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
        loser = e['account.move'].browse(second_id) if second_id else e['erp.procurement.request'].browse(request_id)
        cr.execute("SELECT COALESCE(SUM(amount), 0) FROM erp_budget_move WHERE control_id=%s AND move_type IN ('actual', 'actual_reversal')", [control_id])
        actual = cr.fetchone()[0]
        print(label, results, 'consumed', consumed, 'actual', actual, 'loser', loser.state)
        assert actual == 60
        assert results == {'A': 'committed', 'B': 'SerializationFailure'}
        assert consumed == 100 and loser.state == 'draft'
        try:
            with cr.savepoint():
                if second_id:
                    loser.action_post()
                else:
                    loser.action_submit()
        except UserError:
            pass
        else:
            raise AssertionError('fresh retry must respect the remaining capacity')
        e['account.move'].browse(first_id).button_draft()
        cr.commit()


race('DEPOSIT_DEDUCTION_VS_DEDUCTION', bill_ids[0], bill_ids[1])
print('DEPOSIT_RACE_PASSED')
