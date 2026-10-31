from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from .fixture import InventoryFixture

@tagged('post_install', '-at_install')
class TestStockRequest(InventoryFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user.write({'group_ids': [(4, cls.env.ref('erp_inventory.group_stock_request_manager').id)]})
        cls.product.write({'type': 'consu', 'is_storable': True})
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.destination = cls.env['stock.location'].create({'name': 'Requested storage', 'usage': 'internal', 'location_id': cls.warehouse.view_location_id.id, 'company_id': cls.company.id})
        cls.route = cls.env['stock.route'].create({'name': 'Request internal transfer', 'company_id': cls.company.id})
        cls.rule = cls.env['stock.rule'].create({'name': 'Requested internal supply', 'route_id': cls.route.id, 'action': 'pull', 'location_dest_from_rule': True, 'location_src_id': cls.warehouse.lot_stock_id.id, 'location_dest_id': cls.destination.id, 'picking_type_id': cls.warehouse.int_type_id.id, 'procure_method': 'make_to_stock', 'company_id': cls.company.id})
        cls.env['stock.quant']._update_available_quantity(cls.product, cls.warehouse.lot_stock_id, 10)

    def request(self, qty=4):
        return self.test_env['erp.inventory.request'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'warehouse_id': self.warehouse.id, 'location_id': self.destination.id, 'line_ids': [(0, 0, {'product_id': self.product.id, 'quantity': qty, 'route_id': self.route.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id})]})

    def test_native_fulfillment_partial_return_and_no_budget_authority(self):
        request = self.request()
        request.action_submit()
        request.action_approve()
        request.action_approve()
        moves = request.line_ids.move_ids
        self.assertEqual(len(moves), 1)
        self.assertEqual((moves.erp_fund_id, moves.erp_analytic_id), (self.fund, self.analytic))
        moves.quantity = 4
        moves.picked = True
        moves.picking_id.button_validate()
        request.action_check_done()
        self.assertEqual((request.state, request.line_ids.delivered_qty, self.total()), ('done', 4, 0))
        returned = moves.picking_id._create_return()
        returned.move_ids.quantity = 1
        returned.move_ids.product_uom_qty = 1
        returned.move_ids.picked = True
        returned.button_validate()
        self.assertEqual(request.line_ids.delivered_qty, 3)
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_reset()
        with self.assertRaises(AccessError), self.cr.savepoint():
            moves.erp_stock_request_line_id = False

    def test_stock_tier_cancel_reset_preserves_decisions(self):
        self.env['erp.procurement.tier'].create({'name': 'Stock review', 'kind': 'stock_request', 'company_id': self.company.id, 'reviewer_id': self.user.id})
        request = self.request()
        request.action_submit()
        with self.assertRaises(UserError), self.cr.savepoint():
            request.line_ids.quantity = 9
        request.action_reject()
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_approve()
        request.action_reset()
        request.action_submit()
        request.action_approve()
        self.assertEqual(len(request.review_ids), 2)
        request.action_cancel()
        self.assertTrue(all(m.state == 'cancel' for m in request.line_ids.move_ids))
        request.action_reset()
        request.action_submit()
        request.action_approve()
        self.assertEqual(len(request.line_ids.move_ids), 2)

    def test_wrong_unit_company_and_virtual_destination(self):
        request = self.request()
        unit = self.env['erp.organization.unit'].create({'name': 'Other stock OU', 'code': 'SROTHER', 'company_id': self.company.id})
        user = self.env['res.users'].create({'name': 'Other stock requester', 'login': 'sr_other', 'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)], 'group_ids': [(6, 0, [self.env.ref('erp_inventory.group_stock_request_manager').id])]})
        self.env['erp.organization.assignment'].create({'user_id': user.id, 'unit_id': unit.id})
        self.assertFalse(self.test_env['erp.inventory.request'].with_user(user).search([('id', '=', request.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            request.with_user(user).action_submit()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            request.location_id = self.env.ref('stock.stock_location_customers')
        self.company.erp_stock_request_virtual_location = True
        request.location_id = self.env.ref('stock.stock_location_customers')
        foreign = self.env['res.company'].create({'name': 'Foreign stock company'})
        foreign_unit = self.env['erp.organization.unit'].create({'name': 'Foreign stock OU', 'code': 'SFOREIGN', 'company_id': foreign.id})
        with self.assertRaises((AccessError, UserError, ValidationError)), self.cr.savepoint():
            request.organization_id = foreign_unit

    def test_card_checksum_request_and_census_preserves_missing(self):
        card = self.test_env['erp.inventory.card'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'warehouse_id': self.warehouse.id, 'location_id': self.destination.id, 'product_id': self.product.id, 'quantity': 2, 'route_id': self.route.id, 'fund_id': self.fund.id, 'analytic_id': self.analytic.id})
        another = card.copy({'name': 'New'})
        self.assertEqual(self.test_env['erp.inventory.card'].search_barcode(card.barcode), card)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.test_env['erp.inventory.card'].search_barcode(card.barcode[:-1] + '?')
        action = self.test_env['erp.inventory.card'].action_scan_request(card.barcode)
        request = self.test_env['erp.inventory.request'].browse(action['res_id'])
        self.assertEqual((request.card_id, request.state, request.line_ids.quantity), (card, 'open', 2))
        census = self.test_env['erp.inventory.card.census'].create({'name': 'Card count', 'company_id': self.company.id, 'organization_id': self.unit.id, 'warehouse_ids': [(6, 0, self.warehouse.ids)]})
        census.action_start()
        census.action_scan(card.barcode)
        census.action_scan(card.barcode)
        self.assertEqual(census.missing_ids, another)
        census.action_finish()
        census.action_close()
        self.assertEqual(census.history[-1]['missing'], another.ids)
        with self.assertRaises(UserError), self.cr.savepoint():
            census.action_reset()
        with self.assertRaises(UserError), self.cr.savepoint():
            census.scanned_ids = another
        self.assertEqual(self.env['stock.quant']._get_available_quantity(self.product, self.destination), 0)

    def test_buy_rule_rfq_origin_and_scope(self):
        buy = self.env['stock.route'].create({'name': 'Request buy route', 'company_id': self.company.id})
        self.env['stock.rule'].create({'name': 'Request buy', 'route_id': buy.id, 'action': 'buy', 'location_dest_id': self.warehouse.lot_stock_id.id, 'picking_type_id': self.warehouse.in_type_id.id, 'company_id': self.company.id})
        self.env['product.supplierinfo'].create({'partner_id': self.vendor.id, 'product_tmpl_id': self.product.product_tmpl_id.id, 'price': 7, 'company_id': self.company.id})
        request = self.request(2)
        request.location_id = self.warehouse.lot_stock_id
        request.line_ids.route_id = buy
        request.action_submit()
        request.action_approve()
        line = request.line_ids.purchase_line_ids
        self.assertEqual((len(line), line.product_qty, line.order_id.erp_stock_request_line_id), (1, 2, request.line_ids))
        self.assertEqual(line.erp_budget_fund_id, self.fund)
        self.assertEqual(self.total(), 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            request.action_reset()
        line.order_id.button_cancel()
        request.action_cancel()
        request.action_reset()

    def test_same_reviewer_completes_each_stock_tier(self):
        self.env['erp.procurement.tier'].create([{'name': 'Stock one', 'kind': 'stock_request', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'sequence': 10}, {'name': 'Stock two', 'kind': 'stock_request', 'company_id': self.company.id, 'reviewer_id': self.user.id, 'sequence': 20}])
        request = self.request()
        request.action_submit()
        request.action_approve()
        self.assertEqual(request.state, 'submitted')
        request.action_approve()
        request.action_approve()
        self.assertEqual((request.state, len(request.line_ids.move_ids)), ('open', 1))
