from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from .fixture import InventoryFixture

@tagged('post_install', '-at_install')
class TestAcceptanceWorkflow(InventoryFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user.write({'group_ids': [(4, cls.env.ref('erp_inventory.group_acceptance_manager').id), (4, cls.env.ref('stock.group_stock_user').id)]})

    def wa(self, po, qty=4):
        return self.test_env['erp.inventory.acceptance'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'purchase_order_id': po.id, 'line_ids': [(0, 0, {'purchase_line_id': po.order_line.id, 'quantity': qty})]})

    def test_dedicated_acceptance_role_reads_source_without_procurement_write(self):
        request, po = self.scenario()
        reviewer = self.env['res.users'].create({
            'name': 'Dedicated acceptance reviewer', 'login': 'wa_dedicated_role',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('erp_inventory.group_acceptance_manager').id])],
        })
        self.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': self.unit.id})
        e = self.env(user=reviewer, context={'allowed_company_ids': self.company.ids})
        wa = e['erp.inventory.acceptance'].create({
            'company_id': self.company.id, 'organization_id': self.unit.id,
            'purchase_order_id': po.id,
            'line_ids': [(0, 0, {'purchase_line_id': po.order_line.id, 'quantity': 1})],
        })
        wa.action_accept()
        self.assertEqual(wa.state, 'accept')
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.with_user(reviewer).write({'description': 'Unauthorized edit'})
        self.env['erp.organization.assignment'].search([('user_id', '=', reviewer.id)]).unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.with_user(reviewer).read(['name'])

    def test_cancel_reset_history_and_consumed_dependencies(self):
        request, po = self.scenario()
        wa = self.wa(po)
        wa.action_accept()
        wa.action_cancel()
        wa.action_reset()
        wa.line_ids.quantity = 3
        wa.action_accept()
        self.assertEqual(wa.workflow_history[0]['lines'][0]['quantity'], 4)
        bill = self.make_bill(po, 3, 10)
        bill.erp_acceptance_id = wa
        with self.assertRaises(UserError), self.cr.savepoint():
            wa.action_cancel()
        bill.action_post()
        with self.assertRaises(UserError), self.cr.savepoint():
            wa.action_reset()
        bill.button_draft()
        bill.button_cancel()
        wa.action_cancel()
        wa.action_reset()
        with self.assertRaises(UserError), self.cr.savepoint():
            wa.unlink()
        self.assertEqual(self.total(), 100)

    def test_ordered_reviews_freeze_quantity_and_retain_restart(self):
        request, po = self.scenario()
        second = self.env['res.users'].create({'name': 'WA reviewer 2', 'login': 'wa_review2', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, [self.env.ref('erp_inventory.group_acceptance_manager').id, self.env.ref('erp_procurement.group_procurement_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': second.id, 'unit_id': self.unit.id})
        self.env['erp.procurement.tier'].create([{'name': 'WA first', 'kind': 'acceptance', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'sequence': 10}, {'name': 'WA second', 'kind': 'acceptance', 'company_id': self.company.id, 'reviewer_id': second.id, 'sequence': 20}])
        wa = self.wa(po)
        member = self.test_env['erp.inventory.committee'].create({'acceptance_id': wa.id, 'name': 'External reviewer', 'approve_role': 'chairman'})
        wa.action_accept()
        self.assertEqual(wa.state, 'draft')
        with self.assertRaises(AccessError), self.cr.savepoint():
            wa.with_user(second).action_approve_review()
        with self.assertRaises(UserError), self.cr.savepoint():
            wa.line_ids.quantity = 5
        with self.assertRaises(UserError), self.cr.savepoint():
            member.name = 'Another person'
        member.write({'status': 'accept', 'note': 'Inspected'})
        wa.action_approve_review()
        wa.action_approve_review()
        wa.with_user(second).action_reject_review()
        wa.action_reset()
        self.assertFalse(member.status)
        self.assertEqual(wa.workflow_history[-1]['committees'][0]['note'], 'Inspected')
        wa.action_accept()
        wa.action_approve_review()
        wa.with_user(second).action_approve_review()
        self.assertEqual((wa.state, len(wa.review_ids)), ('accept', 4))
        with self.assertRaises(AccessError), self.cr.savepoint():
            wa.review_ids.write({'state': 'approved'})

    def test_evaluation_required_case_scores_and_paper_mode(self):
        self.user.write({'group_ids': [(4, self.env.ref('erp_inventory.group_evaluate_acceptance').id)]})
        case = self.env['erp.inventory.evaluation'].create({'name': 'Delivery quality', 'company_id': self.company.id, 'state_required': 'draft', 'score_ids': [(0, 0, {'name': 'Good', 'score': 3})]})
        request, po = self.scenario()
        po.erp_wa_paperless = False
        wa = self.wa(po)
        self.assertFalse(wa.paperless)
        with self.assertRaises(UserError), self.cr.savepoint():
            wa.action_accept()
        wa.evaluation_ids.score_id = case.score_ids
        wa.action_accept()
        with self.assertRaises(UserError), self.cr.savepoint():
            wa.evaluation_ids.note = 'Rewritten after acceptance'
        with self.assertRaises(UserError), self.cr.savepoint():
            case.score_ids.score = 4
        self.assertEqual(wa.workflow_history[-1]['evaluations'][0]['value'], 3)

    def test_configured_receipt_enforcement_and_manager_bypass(self):
        self.product.type = 'consu'
        self.product.is_storable = True
        self.user.write({'group_ids': [(4, self.env.ref('erp_inventory.group_require_acceptance_receipt').id)]})
        request, po = self.scenario()
        picking = po.picking_ids
        picking.move_ids.quantity = 10
        picking.move_ids.picked = True
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.button_validate()
        with self.assertRaises(AccessError), self.cr.savepoint():
            picking.picking_type_id.erp_bypass_wa = True
        picking.picking_type_id.sudo().erp_bypass_wa = True
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertFalse(picking.erp_acceptance_id)

    def test_installment_acceptance_bill_partial_and_final_quantity(self):
        request, po = self.scenario()
        po.create_invoice_plan(2, '2026-06-01')
        plans = po.erp_invoice_plan_ids.sorted('installment')
        # Establish native payable and purchase journal before plan conversion.
        setup_bill = self.make_bill(po, 1, 10)
        setup_bill.button_cancel()
        first = self.test_env['erp.inventory.acceptance'].browse(plans[0].action_create_acceptance()['res_id'])
        self.assertEqual(first.line_ids.quantity, 5)
        self.assertEqual(plans[0].action_create_acceptance()['res_id'], first.id)
        first.line_ids.quantity = 4
        first.action_accept()
        bill = self.test_env['account.move'].browse(first.action_create_invoice()['res_id'])
        bill.action_post()
        self.assertEqual((bill.erp_acceptance_id, bill.amount_untaxed), (first, 40))
        last = self.test_env['erp.inventory.acceptance'].browse(plans[1].action_create_acceptance()['res_id'])
        self.assertEqual(last.line_ids.quantity, 6)
        last.action_accept()
        final = self.test_env['account.move'].browse(last.action_create_invoice()['res_id'])
        final.action_post()
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (100, 0))
        with self.assertRaises(UserError), self.cr.savepoint():
            plans[0].percent = 30

    def test_stock_fund_return_and_negative_policy(self):
        self.product.type = 'consu'
        self.product.is_storable = True
        request, po = self.scenario()
        picking = po.picking_ids
        self.assertEqual(picking.move_ids.erp_fund_id, self.fund)
        picking.move_ids.quantity = 10
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(picking.move_ids.move_line_ids.erp_fund_id, self.fund)
        returned = picking._create_return()
        returned.move_ids.product_uom_qty = 3
        returned.move_ids.quantity = 3
        returned.move_ids.picked = True
        self.assertEqual(returned.move_ids.erp_fund_id, self.fund)
        returned.button_validate()
        self.assertEqual(self.active('actual'), 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.move_ids.erp_fund_id = False
        location = picking.location_dest_id
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['stock.quant']._update_available_quantity(self.product, location, -8)
        self.product.erp_allow_negative_stock = True
        self.env['stock.quant']._update_available_quantity(self.product, location, -8)
        self.assertEqual(self.env['stock.quant']._get_available_quantity(self.product, location, allow_negative=True), -1)

    def test_native_scrap_valuation_retains_fund_without_budget_actual(self):
        self.product.write({'type': 'consu', 'is_storable': True})
        stock_account = self.env['account.account'].create({'name': 'Stock valuation', 'code': 'WASTOCK', 'account_type': 'asset_current', 'company_ids': [(6, 0, self.company.ids)]})
        journal = self.env['account.journal'].create({'name': 'Stock valuation', 'code': 'WAST', 'type': 'general', 'company_id': self.company.id})
        self.company.write({'account_stock_valuation_id': stock_account.id, 'account_stock_journal_id': journal.id, 'inventory_valuation': 'real_time'})
        self.product.with_company(self.company).standard_price = 5
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1)
        destination = self.env['stock.location'].create({'name': 'Damaged stock', 'usage': 'inventory', 'company_id': self.company.id, 'valuation_account_id': self.account.id})
        self.env['stock.quant']._update_available_quantity(self.product, warehouse.lot_stock_id, 3)
        move = self.test_env['stock.move'].create({'product_id': self.product.id, 'product_uom_qty': 2, 'uom_id': self.product.uom_id.id, 'company_id': self.company.id, 'location_id': warehouse.lot_stock_id.id, 'location_dest_id': destination.id, 'reference': 'WA scrap valuation', 'erp_fund_id': self.fund.id, 'erp_analytic_id': self.analytic.id})
        move.quantity = 2
        move.picked = True
        move._action_done()
        self.assertEqual(move.account_move_id.state, 'posted')
        self.assertTrue(move.account_move_id.erp_budget_exempt)
        self.assertEqual(move.account_move_id.line_ids.erp_budget_fund_id, self.fund)
        self.assertEqual(self.active('actual'), 0)

    def test_planned_acceptance_excludes_native_deposit_deduction_quantity(self):
        request, po = self.scenario()
        po.create_invoice_plan(2, '2026-06-01')
        setup_bill = self.make_bill(po, 1, 10)
        setup_bill.button_cancel()
        deposit = self.test_env['erp.procurement.invoice.plan'].create({'purchase_id': po.id, 'installment': 0, 'invoice_type': 'advance', 'deposit_origin_id': po.order_line.id, 'percent': 30, 'plan_date': '2026-06-01'})
        bill = self.test_env['account.move'].browse(deposit.action_create_invoice()['res_id'])
        bill.action_post()
        for plan in po.erp_invoice_plan_ids.filtered(lambda p: p.invoice_type == 'installment').sorted('installment'):
            wa = self.test_env['erp.inventory.acceptance'].browse(plan.action_create_acceptance()['res_id'])
            wa.action_accept()
            invoice = self.test_env['account.move'].browse(wa.action_create_invoice()['res_id'])
            self.assertEqual(invoice.amount_untaxed, 35)
            invoice.action_post()
        self.assertEqual((self.active('actual'), self.active('po_commitment')), (100, 0))

    def test_repeated_reviewer_and_manual_acceptance_date(self):
        self.env['erp.procurement.tier'].create([{'name': 'WA one', 'kind': 'acceptance', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'sequence': 10}, {'name': 'WA two', 'kind': 'acceptance', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'sequence': 20}])
        request, po = self.scenario()
        wa = self.wa(po)
        wa.requested_acceptance_date = '2026-06-10 09:00:00'
        wa.action_accept()
        wa.action_approve_review()
        self.assertEqual(wa.state, 'draft')
        wa.action_approve_review()
        self.assertEqual(str(wa.acceptance_date), '2026-06-10 09:00:00')
        self.assertEqual(wa.workflow_history[-1]['acceptance_date'], '2026-06-10 09:00:00')
