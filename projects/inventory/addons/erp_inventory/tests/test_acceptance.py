from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from .fixture import InventoryFixture


@tagged('post_install', '-at_install')
class TestWorkAcceptance(InventoryFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user.write({'group_ids': [(4, cls.env.ref('erp_inventory.group_acceptance_manager').id)]})

    def make_acceptance(self, po, qty):
        return self.test_env['erp.inventory.acceptance'].create({
            'company_id': self.company.id,
            'organization_id': self.unit.id,
            'purchase_order_id': po.id,
            'line_ids': [(0, 0, {'purchase_line_id': po.order_line.id, 'quantity': qty})],
        })

    def test_service_partial_multiple_and_guard(self):
        request, po = self.scenario()
        self.assertFalse(po.picking_ids)
        before = self.total()
        a = self.make_acceptance(po, 4)
        b = self.make_acceptance(po, 3)
        c = self.make_acceptance(po, 3)
        self.assertNotEqual(a.name, b.name)
        a.action_accept()
        b.action_accept()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.make_acceptance(po, 4).action_accept()
        c.action_accept()
        self.assertEqual(sum((a | b | c).mapped('line_ids.quantity')), 10)
        self.assertEqual(self.total(), before)
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_cancel()
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            a.line_ids.write({'quantity': 1})
        with self.assertRaises(AccessError), self.cr.savepoint():
            a.write({'state': 'draft'})

    def test_draft_cancel_and_permissions(self):
        request, po = self.scenario()
        a = self.make_acceptance(po, 4)
        ordinary = self.env['res.users'].create({'name': 'Acceptance clerk', 'login': 'wa_clerk', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_inventory.group_acceptance_user').id, self.env.ref('erp_procurement.group_procurement_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': ordinary.id, 'unit_id': self.unit.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            a.with_user(ordinary).action_accept()
        a.action_cancel()
        self.assertEqual(a.state, 'cancel')
        self.make_acceptance(po, 10).action_accept()

    def test_isolation_and_unconfirmed_order(self):
        request, po = self.prepare_po()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.make_acceptance(po, 1)
        po.button_confirm()
        a = self.make_acceptance(po, 1)
        other = self.env['erp.organization.unit'].create({'name': 'Other unit', 'code': 'WAOTHER', 'company_id': self.company.id})
        outsider = self.env['res.users'].create({'name': 'Other unit user', 'login': 'wa_outsider', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_inventory.group_acceptance_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': outsider.id, 'unit_id': other.id})
        self.assertFalse(self.env['erp.inventory.acceptance'].with_user(outsider).with_context(allowed_company_ids=[self.company.id]).search([('id', '=', a.id)]))

    def test_linked_bill_matches_acceptance_and_finance(self):
        request, po = self.scenario()
        acceptance = self.make_acceptance(po, 4)
        acceptance.action_accept()
        bill = self.make_bill(po, 3, 10)
        bill.erp_acceptance_id = acceptance
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()
        bill.invoice_line_ids.filtered('purchase_line_id').quantity = 4
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 40))
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.erp_acceptance_id = False

    def test_goods_receipt_and_native_backorder(self):
        self.product.type = 'consu'
        self.product.is_storable = True
        self.user.write({'group_ids': [(4, self.env.ref('stock.group_stock_user').id)]})
        request, po = self.scenario()
        self.assertEqual(len(po.picking_ids), 1)
        picking = po.picking_ids
        acceptance = self.make_acceptance(po, 4)
        acceptance.action_accept()
        picking.erp_acceptance_id = acceptance
        move = picking.move_ids
        move.quantity = 3
        move.picked = True
        with self.assertRaises(ValidationError), self.cr.savepoint():
            picking.with_context(skip_backorder=True).button_validate()
        move.quantity = 4
        move.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(po.order_line.qty_received, 4)
        self.assertEqual(sum(picking.backorder_ids.move_ids.mapped('product_uom_qty')), 6)
        with self.assertRaises(UserError), self.cr.savepoint():
            move.quantity = 2
        with self.assertRaises(UserError), self.cr.savepoint():
            move.move_line_ids.quantity = 2
        with self.assertRaises(UserError), self.cr.savepoint():
            move.move_line_ids.unlink()
        second = self.make_acceptance(po, 6)
        second.action_accept()
        returned = picking._create_return()
        self.assertFalse(returned.erp_acceptance_id)
        returned.move_ids.product_uom_qty = 1
        returned.move_ids.quantity = 1
        returned.move_ids.picked = True
        returned.button_validate()
        self.assertEqual(returned.state, 'done')
        self.assertEqual(acceptance.line_ids.quantity, 4)

    def test_duplicate_acceptance_in_bill_batch(self):
        request, po = self.scenario()
        acceptance = self.make_acceptance(po, 4)
        acceptance.action_accept()
        first = self.make_bill(po, 4, 10)
        second = self.make_bill(po, 4, 10)
        (first | second).write({'erp_acceptance_id': acceptance.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            (first | second).action_post()
        self.assertEqual((first.state, second.state), ('draft', 'draft'))

    def test_wrong_product_or_unit_on_linked_bill(self):
        request, po = self.scenario()
        acceptance = self.make_acceptance(po, 4)
        acceptance.action_accept()
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        line = bill.invoice_line_ids.filtered('purchase_line_id')
        wrong_product = self.env['product.product'].create({'name': 'Wrong service', 'type': 'service'})
        line.product_id = wrong_product
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()

    def test_unpicked_move_lines_do_not_count_as_received(self):
        self.product.type = 'consu'
        self.product.is_storable = True
        self.user.write({'group_ids': [(4, self.env.ref('stock.group_stock_user').id)]})
        request, po = self.scenario()
        picking = po.picking_ids
        acceptance = self.make_acceptance(po, 4)
        acceptance.action_accept()
        picking.erp_acceptance_id = acceptance
        move = picking.move_ids
        move.quantity = 3
        move.picked = True
        move.move_line_ids[:1].copy({'quantity': 1, 'picked': False})
        self.assertEqual(move.quantity, 4)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            picking._action_done()
        self.assertNotEqual(picking.state, 'done')

    def test_active_company_isolation(self):
        request, po = self.scenario()
        acceptance = self.make_acceptance(po, 4)
        other_company = self.env['res.company'].create({'name': 'Acceptance other company'})
        other_unit = self.env['erp.organization.unit'].create({'name': 'Acceptance other unit', 'code': 'WAB', 'company_id': other_company.id})
        self.user.write({'company_ids': [(4, other_company.id)]})
        self.env['erp.organization.assignment'].create({'user_id': self.user.id, 'unit_id': other_unit.id})
        other_env = self.env(user=self.user, context={'allowed_company_ids': [other_company.id]})
        self.assertFalse(other_env['erp.inventory.acceptance'].search([('id', '=', acceptance.id)]))
        with self.assertRaises((AccessError, ValidationError, UserError)), self.cr.savepoint():
            other_env['erp.inventory.acceptance'].create({'company_id': other_company.id, 'organization_id': other_unit.id, 'purchase_order_id': po.id})
