from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.addons.erp_inventory.tests.fixture import InventoryFixture


@tagged('post_install', '-at_install')
class TestAssetAcquisition(InventoryFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user.write({'group_ids': [(4, cls.env.ref('erp_inventory.group_acceptance_manager').id), (4, cls.env.ref('erp_asset.group_asset_manager').id)]})
        cls.profile = cls.env['erp.asset.profile'].create({'name': 'Acquisition profile', 'company_id': cls.company.id, 'account_id': cls.account.id})

    def acceptance(self, po, qty):
        record = self.test_env['erp.inventory.acceptance'].create({'company_id': self.company.id, 'organization_id': self.unit.id, 'purchase_order_id': po.id, 'line_ids': [(0, 0, {'purchase_line_id': po.order_line.id, 'quantity': qty})]})
        record.action_accept()
        return record

    def test_finance_role_posts_acquisition_without_asset_management(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 1)
        accountant = self.env['res.users'].create({
            'name': 'Dedicated accountant', 'login': 'asset_dedicated_accountant',
            'company_id': self.company.id, 'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, [self.env.ref('account.group_account_invoice').id,
                                  self.env.ref('erp_procurement.group_procurement_user').id])],
        })
        self.env['erp.organization.assignment'].create({'user_id': accountant.id, 'unit_id': self.unit.id})
        bill = self.make_bill(po, 1, 10).with_user(accountant)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        # Native accounting forms compute this even for ordinary accounting users.
        self.assertEqual(bill.asset_count, 0)
        asset = self.env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        self.assertEqual(len(asset), 1)
        with self.assertRaises(AccessError), self.cr.savepoint():
            asset.with_user(accountant).action_create_depreciation_asset()
        with self.assertRaises(AccessError), self.cr.savepoint():
            acceptance.with_user(accountant).write({'notes': 'Unauthorized change'})

    def test_native_bill_without_description_has_named_acquisition(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 1)
        bill = self.make_bill(po, 1, 10)
        bill.erp_acceptance_id = acceptance
        line = bill.invoice_line_ids.filtered('purchase_line_id')
        line.name = ''
        bill.action_post()
        asset = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        self.assertEqual(len(asset), 1)
        self.assertEqual(asset.name, line.product_id.display_name)
        self.assertTrue(asset.name)
        self.make_oca_profile()
        asset.action_create_depreciation_asset()
        self.assertEqual(asset.engine_asset_id.sudo().name, asset.name)

    def test_partial_bills_create_separate_assets_once(self):
        request, po = self.scenario()
        a = self.acceptance(po, 4)
        first = self.make_bill(po, 4, 10)
        first.erp_acceptance_id = a
        first.action_post()
        asset = self.test_env['erp.asset.asset'].search([('bill_id', '=', first.id)])
        self.assertEqual(len(asset), 1)
        self.assertEqual((asset.quantity, asset.purchase_value, asset.company_id, asset.organization_id), (4, 40, self.company, self.unit))
        self.assertEqual(asset.date_start, a.acceptance_date.date())
        self.assertEqual(asset.source_line_id, first.invoice_line_ids.filtered('purchase_line_id'))
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (60, 40))
        b = self.acceptance(po, 6)
        second = self.make_bill(po, 6, 10)
        second.erp_acceptance_id = b
        second.action_post()
        assets = self.test_env['erp.asset.asset'].search([('bill_id', 'in', (first | second).ids)])
        self.assertEqual(len(assets), 2)
        self.assertEqual(sum(assets.mapped('purchase_value')), 100)
        self.assertNotEqual(assets[0].number, assets[1].number)
        first.button_draft()
        self.assertEqual((asset.state, asset.current_value), ('cancel', 0))
        first.action_post()
        replacement = self.test_env['erp.asset.asset'].search([('bill_id', '=', first.id), ('state', '=', 'draft')])
        self.assertEqual((replacement.generation, replacement.purchase_value), (2, 40))
        with self.assertRaises(AccessError), self.cr.savepoint():
            asset.write({'purchase_value': 1})

    def test_missing_acceptance_rolls_back_post_and_budget(self):
        request, po = self.scenario()
        bill = self.make_bill(po, 4, 10)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual((self.active('po_commitment'), self.active('actual')), (100, 0))
        self.assertFalse(self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)]))

    def test_unprofiled_bill_no_asset(self):
        self.profile.active = False
        request, po = self.scenario()
        bill = self.make_bill(po, 4, 10)
        bill.action_post()
        self.assertFalse(self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)]))
        self.assertEqual(self.active('actual'), 40)

    def test_ou_access_and_forgery(self):
        request, po = self.scenario()
        a = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = a
        bill.action_post()
        asset = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        other = self.env['erp.organization.unit'].create({'name': 'Other asset OU', 'code': 'ASO', 'company_id': self.company.id})
        outsider = self.env['res.users'].create({'name': 'Other asset user', 'login': 'asset_outsider', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_asset.group_asset_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': outsider.id, 'unit_id': other.id})
        self.assertFalse(self.env['erp.asset.asset'].with_user(outsider).with_context(allowed_company_ids=[self.company.id]).search([('id', '=', asset.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['erp.asset.asset'].create({'name': 'Forged'})

    def test_goods_receipt_bill_asset_and_return_boundary(self):
        self.product.type = 'consu'
        self.product.is_storable = True
        self.user.write({'group_ids': [(4, self.env.ref('stock.group_stock_user').id)]})
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        picking = po.picking_ids
        picking.erp_acceptance_id = acceptance
        picking.move_ids.quantity = 4
        picking.move_ids.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, 'done')
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        asset = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        self.assertEqual((len(asset), asset.quantity, asset.purchase_value), (1, 4, 40))
        returned = picking._create_return()
        returned.move_ids.product_uom_qty = 1
        returned.move_ids.quantity = 1
        returned.move_ids.picked = True
        returned.button_validate()
        self.assertEqual((returned.state, asset.purchase_value), ('done', 40))
        credit = self.make_bill(po, 1, 10, kind='in_refund', reversed_entry=bill)
        credit.action_post()
        self.assertEqual((asset.purchase_value, asset.current_value, self.active('actual')), (40, 30, 30))

    def test_asset_backed_refund_adjusts_value_and_reset_restores(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        refund = self.make_bill(po, 1, 10, kind='in_refund', reversed_entry=bill)
        refund.action_post()
        asset = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        self.assertEqual((asset.purchase_value, asset.current_value), (40, 30))
        self.assertEqual(self.active('actual'), 30)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.button_draft()
        refund.button_draft()
        self.assertEqual((asset.purchase_value, asset.current_value), (40, 40))
        self.assertEqual(len(asset.valuation_ids), 2)
        refund.action_post()
        self.assertEqual((asset.current_value, self.active('actual')), (30, 30))
        with self.assertRaises(AccessError), self.cr.savepoint():
            asset.valuation_ids.write({'amount': 0})

    def test_profile_company_and_company_switch(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        asset = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        other = self.env['res.company'].create({'name': 'Asset other company'})
        self.user.write({'company_ids': [(4, other.id)]})
        e = self.env(user=self.user, context={'allowed_company_ids': [other.id]})
        self.assertFalse(e['erp.asset.asset'].search([('id', '=', asset.id)]))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['erp.asset.profile'].create({'name': 'Invalid company account', 'company_id': other.id, 'account_id': self.account.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.profile.write({'account_id': self.env['account.account'].create({'name': 'Other account', 'code': 'AOTHER', 'account_type': 'expense', 'company_ids': [(6, 0, [self.company.id])]}).id})

    def test_reposting_cannot_duplicate(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(self.test_env['erp.asset.asset'].search_count([('bill_id', '=', bill.id)]), 1)

    def make_oca_profile(self):
        journal = self.env['account.journal'].create({'name': 'Asset general', 'code': 'ASGEN', 'type': 'general', 'company_id': self.company.id})
        depreciation = self.env['account.account'].create({'name': 'Accumulated depreciation', 'code': 'ASDEP', 'account_type': 'asset_fixed', 'company_ids': [(6, 0, [self.company.id])]})
        expense = self.env['account.account'].create({'name': 'Depreciation expense', 'code': 'ASEXP', 'account_type': 'expense', 'company_ids': [(6, 0, [self.company.id])]})
        profile = self.env['account.asset.profile'].with_company(self.company).create({'name': 'Three year profile', 'company_id': self.company.id, 'account_asset_id': self.account.id, 'account_depreciation_id': depreciation.id, 'account_expense_depreciation_id': expense.id, 'journal_id': journal.id, 'method_time': 'year', 'method_number': 3, 'method_period': 'year', 'open_asset': False})
        self.account.asset_profile_id = False
        self.profile.oca_profile_id = profile
        return profile

    def test_depreciation_link_from_existing_acquisition(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        profile = self.make_oca_profile()
        acquisition.action_create_depreciation_asset()
        oca = acquisition.engine_asset_id.sudo()
        self.assertEqual((oca.erp_acquisition_id, oca.profile_id, oca.purchase_value, oca.date_start, oca.state), (acquisition.sudo(), profile, 40, acquisition.date_start, 'draft'))
        self.assertEqual(oca.depreciation_line_ids.filtered(lambda line: line.type == 'create').move_id, bill.sudo())
        oca.validate()
        self.assertEqual(oca.state, 'open')
        depreciation = oca.depreciation_line_ids.filtered(lambda line: line.type == 'depreciate')
        self.assertTrue(depreciation)
        first_depreciation = depreciation[:1]
        entry_ids = first_depreciation.create_move()
        entry = self.env['account.move'].browse(entry_ids)
        self.assertEqual((entry.state, entry.company_id, entry.journal_id), ('posted', self.company, profile.journal_id))
        self.assertEqual(round(sum(entry.line_ids.mapped('balance')), 2), 0)
        with self.assertRaises(UserError), self.cr.savepoint():
            first_depreciation.create_move()
        with self.assertRaises(UserError), self.cr.savepoint():
            acquisition.action_create_depreciation_asset()
        self.assertEqual(self.env['account.asset'].sudo().search_count([('erp_acquisition_id', '=', acquisition.id)]), 1)

    def test_automatic_oca_and_erp_duplicate_guard(self):
        profile = self.make_oca_profile()
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.invoice_line_ids.filtered('purchase_line_id').asset_profile_id = profile
        with self.assertRaises(ValidationError), self.cr.savepoint():
            bill.action_post()
        self.assertEqual(bill.state, 'draft')
        self.assertFalse(self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)]))
        self.assertFalse(self.env['account.asset'].sudo().search([('erp_acquisition_id.bill_id', '=', bill.id)]))

    def test_engine_security_and_provenance(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        self.make_oca_profile()
        acquisition.action_create_depreciation_asset()
        engine = acquisition.engine_asset_id
        self.assertTrue(self.test_env['account.asset'].search([('id', '=', engine.id)]))
        other = self.env['erp.organization.unit'].create({'name': 'Other engine OU', 'code': 'ENGO', 'company_id': self.company.id})
        outsider = self.env['res.users'].create({'name': 'Other engine user', 'login': 'engine_outsider', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_asset.group_asset_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': outsider.id, 'unit_id': other.id})
        foreign = self.env['account.asset'].with_user(outsider).with_context(allowed_company_ids=[self.company.id])
        self.assertFalse(foreign.search([('id', '=', engine.id)]))
        reader = self.env['res.users'].create({'name': 'Asset read only', 'login': 'engine_reader', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_asset.group_asset_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reader.id, 'unit_id': self.unit.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            engine.with_user(reader).with_context(allowed_company_ids=[self.company.id]).validate()
        finance = self.env['res.users'].create({'name': 'Finance only', 'login': 'engine_finance', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('account.group_account_invoice').id])]})
        self.env['erp.organization.assignment'].create({'user_id': finance.id, 'unit_id': self.unit.id})
        finance_engine = engine.with_user(finance).with_context(allowed_company_ids=[self.company.id])
        self.assertEqual(finance_engine.read(['name'])[0]['id'], engine.id)
        with self.assertRaises(AccessError), self.cr.savepoint():
            finance_engine.validate()
        self.env['erp.organization.assignment'].search([('user_id', '=', finance.id)]).unlink()
        with self.assertRaises(AccessError), self.cr.savepoint():
            finance_engine.read(['name'])
        with self.assertRaises(AccessError), self.cr.savepoint():
            engine.sudo().write({'purchase_value': 99})
        with self.assertRaises(UserError), self.cr.savepoint():
            engine.sudo().profile_id.write({'method_number': 9})

    def test_profile_copy_resets_internal_lock_without_copying_assets(self):
        self.user.write({'group_ids': [(4, self.env.ref('account.group_account_manager').id)]})
        profile = self.make_oca_profile()
        profile._erp_lock_profiles()
        profile.invalidate_recordset()
        self.assertGreater(profile.erp_lock_version, 0)
        duplicate = profile.with_env(self.test_env).copy({'name': 'Independent profile'})
        self.assertNotEqual(duplicate, profile)
        self.assertEqual(duplicate.erp_lock_version, 0)
        self.assertEqual(duplicate.account_asset_id, profile.account_asset_id)
        self.assertFalse(self.env['account.asset'].search([('profile_id', '=', duplicate.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            duplicate.with_user(self.user).write({'erp_lock_version': 100})

    def test_recompute_trigger_cannot_complete_another_company(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        self.make_oca_profile()
        acquisition.action_create_depreciation_asset()
        engine = acquisition.engine_asset_id
        engine.validate()
        foreign_company = self.env['res.company'].create({'name': 'Foreign recompute'})
        foreign = self.env['account.asset.recompute.trigger'].create({
            'reason': 'Foreign pending schedule', 'company_id': foreign_company.id})
        own = self.env['account.asset.recompute.trigger'].create({
            'reason': 'Own pending schedule', 'company_id': self.company.id})
        engine._compute_entries(engine.date_start, check_triggers=True)
        self.assertEqual((own.state, foreign.state), ('done', 'open'))
        self.assertFalse(self.test_env['account.asset.recompute.trigger'].search([('id', '=', foreign.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            foreign.with_env(self.test_env).write({'state': 'done'})

    def test_depreciation_accounting_requires_asset_organization(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        self.make_oca_profile()
        acquisition.action_create_depreciation_asset()
        engine = acquisition.engine_asset_id
        engine.validate()
        depreciation = engine.depreciation_line_ids.filtered(lambda line: line.type == 'depreciate')[:1]
        depreciation.create_move()
        move = depreciation.move_id
        self.assertTrue(move)
        self.assertTrue(move.read(['name']))
        lines = move.line_ids
        self.env['erp.organization.assignment'].search([('user_id', '=', self.user.id)]).unlink()
        for records in [move, lines]:
            self.assertFalse(self.test_env[records._name].search([('id', 'in', records.ids)]))
            with self.assertRaises(AccessError), self.cr.savepoint():
                records.read(['name'])

    def test_per_item_profile_fails_closed(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        profile = self.make_oca_profile()
        profile.asset_product_item = True
        with self.assertRaises(ValidationError), self.cr.savepoint():
            acquisition.action_create_depreciation_asset()
        self.assertFalse(acquisition.engine_asset_id)

    def test_disposal_preserves_acquisition(self):
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        profile = self.make_oca_profile()
        acquisition.action_create_depreciation_asset()
        engine = acquisition.engine_asset_id.sudo()
        engine.validate()
        wizard = self.env['account.asset.remove'].sudo().with_context(active_id=engine.id, active_ids=engine.ids, early_removal=True).create({'date_remove': fields.Date.add(acquisition.date_start, months=1), 'sale_value': 0.0, 'posting_regime': 'gain_loss_on_sale', 'account_plus_value_id': profile.account_expense_depreciation_id.id, 'account_min_value_id': profile.account_expense_depreciation_id.id})
        wizard.remove()
        self.assertEqual(engine.state, 'removed')
        self.assertEqual(acquisition.engine_asset_id, engine)
        removal = engine.depreciation_line_ids.filtered(lambda line: line.type == 'remove')
        self.assertTrue(removal)
        self.assertEqual(removal.move_id.state, 'draft')
        removal.move_id.action_post()
        self.assertEqual(removal.move_id.state, 'posted')

    def test_per_item_acquisition_and_depreciation_links(self):
        self.profile.item_mode = 'item'
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisitions = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)], order='item_index')
        self.assertEqual(acquisitions.mapped('item_index'), [1, 2, 3, 4])
        self.assertEqual(acquisitions.mapped('quantity'), [1, 1, 1, 1])
        self.assertEqual(sum(acquisitions.mapped('purchase_value')), 40)
        self.assertEqual(len(set(acquisitions.mapped('number'))), 4)
        profile = self.make_oca_profile()
        profile.asset_product_item = True
        for acquisition in acquisitions:
            acquisition.action_create_depreciation_asset()
        self.assertEqual(self.env['account.asset'].sudo().search_count([('erp_acquisition_id', 'in', acquisitions.ids)]), 4)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.profile.item_mode = 'aggregate'

    def test_auc_transfer_split_merge_preserves_scope_and_history(self):
        self.account.account_type = 'asset_fixed'
        self.user.write({'group_ids': [(4, self.env.ref('account.group_account_manager').id)]})
        request, po = self.scenario()
        acceptance = self.acceptance(po, 10)
        bill = self.make_bill(po, 10, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        profile = self.make_oca_profile()
        profile.method_number = 0
        acquisition.action_create_depreciation_asset()
        source = acquisition.engine_asset_id
        source.validate()
        wizard = self.test_env['account.asset.transfer'].with_context(active_ids=source.ids).create({
            'company_id': self.company.id, 'transfer_journal_id': profile.journal_id.id,
            'date_transfer': fields.Date.today(), 'from_asset_ids': [(6, 0, source.ids)],
            'to_asset_ids': [(0, 0, {'asset_name': 'Split 40', 'asset_profile_id': profile.id, 'quantity': 1, 'price_unit': 40}),
                             (0, 0, {'asset_name': 'Split 60', 'asset_profile_id': profile.id, 'quantity': 1, 'price_unit': 60})],
        })
        wizard.date_transfer = fields.Date.subtract(source.date_start, days=1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.transfer()
        wizard.date_transfer = fields.Date.today()
        result = wizard.transfer()
        history = self.test_env['erp.asset.transfer.history'].search([('move_id', '=', result['domain'][0][2])])
        self.assertEqual(len(history), 1)
        children = history.destination_ids
        self.assertEqual(sorted(children.mapped('purchase_value')), [40, 60])
        self.assertEqual(source.state, 'removed')
        self.assertEqual(history.source_ids, source)
        self.assertEqual(history.organization_id, self.unit)
        self.assertEqual(acquisition.purchase_value, 100)
        self.assertEqual(sum(history.move_id.line_ids.mapped('balance')), 0)
        self.assertTrue(all(asset.erp_transfer_organization_id == self.unit for asset in children))
        self.assertTrue(all(asset.erp_asset_fund_id == self.fund for asset in children))
        children.validate()
        wizard2 = self.test_env['account.asset.transfer'].with_context(active_ids=children.ids).create({
            'company_id': self.company.id, 'transfer_journal_id': profile.journal_id.id,
            'date_transfer': fields.Date.today(), 'from_asset_ids': [(6, 0, children.ids)],
            'to_asset_ids': [(0, 0, {'asset_name': 'Merge 100', 'asset_profile_id': profile.id, 'quantity': 1, 'price_unit': 100})],
        })
        wizard2.to_asset_ids.price_unit = 99.99
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard2.transfer()
        wizard2.to_asset_ids.price_unit = 99.999
        result2 = wizard2.transfer()
        history2 = self.test_env['erp.asset.transfer.history'].search([('move_id', '=', result2['domain'][0][2])])
        self.assertEqual(set(history2.source_ids.ids), set(children.ids))
        self.assertEqual(history2.destination_ids.purchase_value, 100)
        self.assertEqual(set(children.mapped('state')), {'removed'})
        with self.assertRaises(UserError), self.cr.savepoint():
            source.write({'state': 'open'})
        with self.assertRaises(UserError), self.cr.savepoint():
            history.move_id.button_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            history.move_id._reverse_moves()
        with self.assertRaises(UserError), self.cr.savepoint():
            history.move_id.line_ids[:1].write({'debit': 1})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.transfer()
        reader = self.env['res.users'].create({'name': 'Transfer reader', 'login': 'transfer_reader', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_asset.group_asset_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': reader.id, 'unit_id': self.unit.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            wizard.with_user(reader).with_context(allowed_company_ids=[self.company.id]).transfer()
        with self.assertRaises(AccessError), self.cr.savepoint():
            history.sudo().write({'value': 1})
        with self.assertRaises(AccessError), self.cr.savepoint():
            history2.destination_ids.sudo().write({'erp_transfer_organization_id': False})
        outsider_ou = self.env['erp.organization.unit'].create({'name': 'Transfer outsider OU', 'code': 'TOUT', 'company_id': self.company.id})
        outsider = self.env['res.users'].create({'name': 'Transfer outsider', 'login': 'transfer_outsider', 'company_id': self.company.id, 'company_ids': [(6, 0, [self.company.id])], 'group_ids': [(6, 0, [self.env.ref('erp_asset.group_asset_user').id])]})
        self.env['erp.organization.assignment'].create({'user_id': outsider.id, 'unit_id': outsider_ou.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.test_env['account.asset'].with_context(default_erp_transfer_organization_id=self.unit.id).create({'name': 'Forged scope', 'profile_id': profile.id, 'purchase_value': 1, 'date_start': fields.Date.today()})
        foreign = self.env['account.asset'].with_user(outsider).with_context(allowed_company_ids=[self.company.id])
        self.assertFalse(foreign.search([('id', 'in', history2.destination_ids.ids)]))

    def thai_engine(self, low_value=False, days=False):
        profile = self.make_oca_profile()
        profile.write({'method_number': 0 if low_value else 3, 'days_calc': days,
                       'method': 'linear-limit', 'salvage_type': 'fixed', 'salvage_value': 1})
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        acquisition.action_create_depreciation_asset()
        return acquisition.engine_asset_id

    def test_thai_low_value_removal_without_accounting(self):
        asset = self.thai_engine(low_value=True)
        self.assertTrue(asset.low_value)
        self.assertEqual(asset.value_residual, 0)
        asset.validate()
        self.assertEqual(asset.state, 'open')
        asset.compute_depreciation_board()
        self.assertFalse(asset.depreciation_line_ids.filtered(lambda l: l.type == 'depreciate'))
        moves = self.env['account.move'].search_count([])
        action = asset.remove()
        wizard = self.test_env['account.asset.remove'].with_context(**action['context']).create({
            'date_remove': asset.date_start, 'remove_reason': 'Obsolete low-value item'})
        wizard.remove()
        self.assertEqual((asset.state, asset.remove_reason), ('removed', 'Obsolete low-value item'))
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            wizard.with_context(erp_batch_remove=False).remove()

    def test_thai_daily_salvage_and_substatus_company(self):
        asset = self.thai_engine(days=True)
        state = self.test_env['account.asset.sub.state'].create({'name': 'In service', 'open': True, 'company_id': self.company.id})
        asset.validate()
        self.assertEqual(asset.asset_sub_state_id, state)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            state.open = False
        self.assertAlmostEqual(asset.depreciation_rate, 100 / 3)
        lines = asset.depreciation_line_ids.filtered(lambda l: l.type == 'depreciate')
        self.assertAlmostEqual(sum(lines.mapped('amount')), 39, places=2)
        lines.create_move()
        self.assertEqual((asset.state, asset.value_residual), ('close', 1))
        self.assertFalse(asset.asset_sub_state_id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            asset.asset_sub_state_id = state
        other = self.env['res.company'].create({'name': 'Foreign substatus company'})
        foreign = self.env['account.asset.sub.state'].create({'name': 'Foreign', 'close': True, 'company_id': other.id})
        with self.assertRaises((ValidationError, AccessError)), self.cr.savepoint():
            asset.asset_sub_state_id = foreign

    def make_expense(self, amount=60):
        self.user.write({'group_ids': [(4, self.env.ref('hr_expense.group_hr_expense_manager').id), (4, self.env.ref('erp_budget.group_budget_user').id)]})
        employee = self.env['hr.employee'].create({'name': 'Budget expense employee', 'company_id': self.company.id, 'expense_manager_id': self.user.id})
        payable = self.env['account.account'].create({'name': 'Expense payable', 'code': 'EXPPAY', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, [self.company.id])]})
        employee.work_contact_id.with_company(self.company).property_account_payable_id = payable
        journal = self.env['account.journal'].create({'name': 'Expenses', 'code': 'EXP', 'type': 'purchase', 'company_id': self.company.id, 'default_account_id': self.account.id})
        self.company.expense_journal_id = journal
        self.product.can_be_expensed = True
        return self.test_env['hr.expense'].create({'name': 'Budget expense', 'company_id': self.company.id, 'employee_id': employee.id, 'product_id': self.product.id, 'account_id': self.account.id, 'date': '2026-06-01', 'quantity': 1, 'total_amount_currency': amount, 'currency_id': self.company.currency_id.id, 'tax_ids': [(5, 0, 0)], 'analytic_distribution': {str(self.analytic.id): 100}, 'erp_budget_period_id': self.period.id, 'erp_budget_organization_id': self.unit.id, 'erp_budget_fund_id': self.fund.id, 'erp_budget_analytic_id': self.analytic.id})


    def test_expense_asset_acquisition_and_fund_analytics(self):
        profile = self.make_oca_profile()
        self.company.asset_move_line_analytic = True
        expense = self.make_expense(60)
        expense.erp_asset_profile_id = self.profile
        expense.action_submit()
        expense.action_approve()
        bill = expense.account_move_id
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('expense_id', '=', expense.id)])
        self.assertEqual(len(acquisition), 1)
        self.assertFalse(acquisition.acceptance_id)
        self.assertEqual((acquisition.purchase_value, acquisition.fund_id, acquisition.organization_id), (60, self.fund, self.unit))
        self.assertEqual(acquisition.analytic_distribution, expense.analytic_distribution)
        acquisition.action_create_depreciation_asset()
        asset = acquisition.engine_asset_id
        self.assertEqual(asset.erp_asset_fund_id, self.fund)
        self.assertEqual(asset.analytic_distribution, expense.analytic_distribution)
        asset.validate()
        line = asset.depreciation_line_ids.filtered(lambda l: l.type == 'depreciate')[:1]
        moves = self.test_env['account.move'].browse(line.create_move())
        self.assertEqual(set(moves.line_ids.mapped('erp_asset_fund_id').ids), {self.fund.id})
        self.assertTrue(all(l.analytic_distribution == expense.analytic_distribution for l in moves.line_ids))
        self.assertEqual(self.active('actual'), 60)
        with self.assertRaises(UserError), self.cr.savepoint():
            expense.erp_asset_organization_id = False
        with self.assertRaises(AccessError), self.cr.savepoint():
            asset.analytic_distribution = {}

    def test_expense_asset_per_item_rounding_and_scope(self):
        self.profile.item_mode = 'item'
        expense = self.make_expense(10)
        expense.quantity = 3
        expense.total_amount_currency = 10
        expense.action_submit()
        expense.action_approve()
        expense.account_move_id.action_post()
        acquisitions = self.test_env['erp.asset.asset'].search([('expense_id', '=', expense.id)])
        self.assertEqual(len(acquisitions), 3)
        self.assertEqual(sorted(acquisitions.mapped('purchase_value')), [3.33, 3.33, 3.33])
        self.assertAlmostEqual(sum(acquisitions.mapped('purchase_value')), sum(acquisitions.source_line_id.mapped('balance')))
        other = self.env['erp.organization.unit'].create({'name': 'Expense asset foreign scope', 'code': 'EAX', 'company_id': self.company.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            expense.copy({'name': 'Other scope', 'erp_asset_organization_id': other.id})

    def test_draft_engine_credit_reset_and_replacement_history(self):
        profile = self.make_oca_profile()
        request, po = self.scenario()
        acceptance = self.acceptance(po, 4)
        bill = self.make_bill(po, 4, 10)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        acquisition.action_create_depreciation_asset()
        engine = acquisition.engine_asset_id
        refund = self.make_bill(po, 1, 10, kind='in_refund', reversed_entry=bill)
        refund.action_post()
        self.assertEqual((engine.purchase_value, acquisition.current_value), (30, 30))
        self.assertEqual(engine.depreciation_line_ids.filtered(lambda l: l.type == 'create').amount, 30)
        refund.button_draft()
        self.assertEqual((engine.purchase_value, acquisition.current_value), (40, 40))
        bill.button_draft()
        self.assertEqual((acquisition.state, acquisition.current_value, engine.state, engine.purchase_value), ('cancel', 0, 'removed', 0))
        with self.assertRaises(UserError), self.cr.savepoint():
            engine.validate()
        bill.action_post()
        replacement = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id), ('state', '=', 'draft')])
        replacement.action_create_depreciation_asset()
        self.assertNotEqual(replacement.engine_asset_id, engine)
        self.assertEqual((replacement.generation, acquisition.purchase_value), (2, 40))
        self.assertEqual(len(acquisition.valuation_ids), 3)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.write({'state': 'draft'})

    def test_active_or_depreciated_asset_cannot_be_credited(self):
        asset = self.thai_engine()
        acquisition = asset.erp_acquisition_id
        bill = acquisition.bill_id
        po = acquisition.purchase_line_id.order_id
        asset.validate()
        refund = self.make_bill(po, 1, 10, kind='in_refund', reversed_entry=bill)
        with self.assertRaises(UserError), self.cr.savepoint():
            refund.action_post()
        self.assertEqual((refund.state, acquisition.current_value), ('draft', 40))
        depreciation = asset.depreciation_line_ids.filtered(lambda l: l.type == 'depreciate')[:1]
        depreciation.create_move()
        asset.set_to_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.button_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            refund.action_post()
        self.assertEqual(bill.state, 'posted')

    def test_asset_full_credit_and_excess_are_atomic(self):
        asset = self.thai_engine()
        acquisition = asset.erp_acquisition_id
        bill = acquisition.bill_id
        po = acquisition.purchase_line_id.order_id
        refund = self.make_bill(po, 4, 10, kind='in_refund', reversed_entry=bill)
        refund.action_post()
        self.assertEqual((acquisition.current_value, asset.purchase_value, asset.salvage_value), (0, 0, 0))
        with self.assertRaises(UserError), self.cr.savepoint():
            asset.validate()
        extra = self.make_bill(po, 1, 10, kind='in_refund', reversed_entry=bill)
        with self.assertRaises((UserError, ValidationError)), self.cr.savepoint():
            extra.action_post()
        self.assertEqual((extra.state, acquisition.current_value), ('draft', 0))
        refund.button_draft()
        self.assertEqual((asset.purchase_value, asset.salvage_value), (40, 1))

    def test_per_item_credit_rounding_is_nonnegative(self):
        self.profile.item_mode = 'item'
        request, po = self.scenario()
        acceptance = self.acceptance(po, 5)
        bill = self.make_bill(po, 5, 0.01)
        bill.erp_acceptance_id = acceptance
        bill.action_post()
        assets = self.test_env['erp.asset.asset'].search([('bill_id', '=', bill.id)])
        refund = self.make_bill(po, 3, 0.01, kind='in_refund', reversed_entry=bill)
        refund.action_post()
        self.assertAlmostEqual(sum(assets.mapped('current_value')), 0.02)
        self.assertTrue(all(0 <= a.current_value <= 0.01 for a in assets))
        self.assertTrue(all(v.amount <= 0 for v in assets.valuation_ids))

    def test_asset_expense_company_payment_and_accounting_scope(self):
        expense = self.make_expense(70)
        bank = self.env['account.account'].create({'name': 'Expense bank', 'code': 'EXPBANK', 'account_type': 'asset_cash', 'company_ids': [(6, 0, [self.company.id])]})
        outstanding = self.env['account.account'].create({'name': 'Expense outstanding', 'code': 'EXPOUT', 'account_type': 'asset_current', 'reconcile': True, 'company_ids': [(6, 0, [self.company.id])]})
        journal = self.env['account.journal'].create({'name': 'Expense bank', 'code': 'EXPB', 'type': 'bank', 'company_id': self.company.id, 'default_account_id': bank.id})
        method = journal.outbound_payment_method_line_ids[:1]
        method.payment_account_id = outstanding
        expense.write({'payment_mode': 'company_account', 'payment_method_line_id': method.id})
        expense.action_submit()
        expense.action_approve()
        bill = expense.account_move_id
        self.assertEqual(self.active('expense_commitment'), 70)
        bill.action_post()
        self.assertEqual((self.active('expense_commitment'), self.active('actual')), (0, 70))
        assets = self.test_env['erp.asset.asset'].search([('expense_id', '=', expense.id)])
        self.assertEqual((len(assets), assets.purchase_value, assets.fund_id), (1, 70, self.fund))
        bad_company = self.env['res.company'].create({'name': 'Expense other company'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            bill.with_context(allowed_company_ids=bad_company.ids).button_draft()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.line_ids.filtered(lambda line: not line.expense_id).write({'balance': -1})

    def test_expense_asset_native_credit_and_reset_history(self):
        self.make_oca_profile()
        expense = self.make_expense(60)
        expense.action_submit()
        expense.action_approve()
        bill = expense.account_move_id
        bill.action_post()
        acquisition = self.test_env['erp.asset.asset'].search([('expense_id', '=', expense.id)])
        acquisition.action_create_depreciation_asset()
        refund = bill._reverse_moves(default_values_list=[{'date': bill.date, 'invoice_date': bill.date}], cancel=False)
        refund.action_post()
        self.assertEqual((acquisition.current_value, acquisition.engine_asset_id.purchase_value, self.active('actual')), (0, 0, 0))
        refund.button_draft()
        self.assertEqual((acquisition.current_value, self.active('actual')), (60, 60))
        bill.button_draft()
        expense.action_reset()
        self.assertEqual((acquisition.state, acquisition.current_value, bill.state), ('cancel', 0, 'cancel'))
        self.assertTrue(acquisition.valuation_ids)
