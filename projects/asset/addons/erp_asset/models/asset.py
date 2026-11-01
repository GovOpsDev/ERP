from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain


_asset_creating = ContextVar('erp_asset_creating', default=False)
_engine_creating = ContextVar('erp_asset_engine_creating', default=False)
_transfer_organization = ContextVar('erp_asset_transfer_organization', default=False)


class AssetAccountingScope(models.Model):
    _inherit = 'account.move'

    @api.model
    def _erp_source_document_domain(self):
        valid_unit = Domain('active', '=', True) & Domain(
            'assignment_ids', 'any!', Domain('user_id', '=', self.env.uid))
        allowed_asset = Domain('erp_acquisition_id', 'any!', Domain(
            'organization_id', 'any!', valid_unit)) | Domain(
                'erp_transfer_organization_id', 'any!', valid_unit)
        return super()._erp_source_document_domain() & Domain(
            'line_ids', 'not any!', Domain('asset_id', 'any!', ~allowed_asset))


class ScopedAssetRecompute(models.Model):
    _inherit = 'account.asset'

    def _compute_entries(self, date_end, check_triggers=False):
        if not check_triggers:
            return super()._compute_entries(date_end, check_triggers=False)
        self.check_access('write')
        # The upstream helper searches and completes all companies' triggers
        # with sudo. Process only complete company scopes visible to this caller.
        triggers = self.env['account.asset.recompute.trigger'].search([
            ('state', '=', 'open'), ('company_id', 'in', self.company_id.ids)])
        complete = triggers.browse()
        for company in triggers.company_id:
            assets = self.filtered(lambda asset: asset.company_id == company)
            all_ids = self.sudo().search([
                ('company_id', '=', company.id), ('state', '=', 'open')]).ids
            if set(all_ids).issubset(assets.ids):
                assets.compute_depreciation_board()
                complete |= triggers.filtered(lambda trigger: trigger.company_id == company)
        result = super()._compute_entries(date_end, check_triggers=False)
        if complete and not result[1]:
            complete.write({'state': 'done', 'date_completed': fields.Datetime.now()})
        return result


class AssetAccountLock(models.Model):
    _inherit = 'account.account'

    erp_asset_lock_version = fields.Integer(default=0, readonly=True)

    def _erp_lock_asset_accounts(self):
        if self:
            self.check_access('read')
            ids = tuple(sorted(self.ids))
            self.env.cr.execute('SELECT id FROM account_account WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
            self.env.cr.execute('UPDATE account_account SET erp_asset_lock_version = COALESCE(erp_asset_lock_version, 0) + 1 WHERE id IN %s', [ids])
            self.invalidate_recordset(['erp_asset_lock_version'])

    @api.model_create_multi
    def create(self, vals_list):
        if any('erp_asset_lock_version' in vals for vals in vals_list):
            raise AccessError(_('Asset account lock version is internal.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_asset_lock_version' in vals:
            raise AccessError(_('Asset account lock version is internal.'))
        if 'asset_profile_id' in vals:
            self._erp_lock_asset_accounts()
        return super().write(vals)


class AssetProfile(models.Model):
    _name = 'erp.asset.profile'
    _description = 'Asset Acquisition Profile'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict', index=True)
    account_id = fields.Many2one('account.account', required=True, ondelete='restrict')
    active = fields.Boolean(default=True)
    item_mode = fields.Selection([('aggregate', 'One asset per bill line'), ('item', 'One asset per item')], default='aggregate', required=True)
    oca_profile_id = fields.Many2one('account.asset.profile', check_company=True, ondelete='restrict', string='Depreciation Profile')
    lock_version = fields.Integer(default=0, readonly=True)
    _company_account_unique = models.Constraint('unique(company_id, account_id)', 'Only one asset profile per account and company is supported.')

    @api.constrains('company_id', 'account_id', 'oca_profile_id')
    def _check_account_company(self):
        for profile in self:
            if profile.company_id not in profile.account_id.company_ids:
                raise ValidationError(_('The asset account must belong to the profile company.'))
            if profile.oca_profile_id and (profile.oca_profile_id.company_id != profile.company_id or profile.oca_profile_id.account_asset_id != profile.account_id):
                raise ValidationError(_('The depreciation profile must use the same company and asset account.'))

    def _lock_profiles(self):
        if self:
            ids = tuple(sorted(self.ids))
            self.env.cr.execute('SELECT id FROM erp_asset_profile WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
            self.env.cr.execute('UPDATE erp_asset_profile SET lock_version = COALESCE(lock_version, 0) + 1 WHERE id IN %s', [ids])
            self.invalidate_recordset()

    @api.model_create_multi
    def create(self, vals_list):
        if any('lock_version' in vals for vals in vals_list):
            raise AccessError(_('Profile lock version is internal.'))
        self.env['account.account'].browse([vals['account_id'] for vals in vals_list if vals.get('account_id')])._erp_lock_asset_accounts()
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        if 'lock_version' in vals:
            raise AccessError(_('Profile lock version is internal.'))
        accounts = self.mapped('account_id') | self.env['account.account'].browse(vals.get('account_id')).exists()
        accounts._erp_lock_asset_accounts()
        self._lock_profiles()
        if {'company_id', 'account_id', 'item_mode'} & vals.keys() and self.env['erp.asset.asset'].sudo().search_count([('profile_id', 'in', self.ids)]):
            raise UserError(_('The account and company of a used asset profile cannot be changed.'))
        if 'oca_profile_id' in vals and self.env['erp.asset.asset'].sudo().search_count([('profile_id', 'in', self.ids), ('engine_asset_id', '!=', False)]):
            raise UserError(_('The depreciation profile of linked assets cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self.mapped('account_id')._erp_lock_asset_accounts()
        self._lock_profiles()
        return super().unlink()


class Asset(models.Model):
    _name = 'erp.asset.asset'
    _description = 'Asset Acquisition'
    _check_company_auto = True
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True)
    number = fields.Char(required=True, readonly=True, copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, readonly=True, check_company=True, ondelete='restrict', index=True)
    profile_id = fields.Many2one('erp.asset.profile', required=True, readonly=True, check_company=True, ondelete='restrict')
    source_line_id = fields.Many2one('account.move.line', required=True, readonly=True, ondelete='restrict', index=True)
    bill_id = fields.Many2one(related='source_line_id.move_id', store=True, readonly=True)
    purchase_line_id = fields.Many2one(related='source_line_id.purchase_line_id', store=True, readonly=True)
    acceptance_id = fields.Many2one('erp.inventory.acceptance', readonly=True, check_company=True, ondelete='restrict')
    expense_id = fields.Many2one('hr.expense', readonly=True, check_company=True, ondelete='restrict')
    fund_id = fields.Many2one('erp.budget.fund', readonly=True, check_company=True, ondelete='restrict')
    analytic_distribution = fields.Json(readonly=True)
    product_id = fields.Many2one('product.product', readonly=True, ondelete='restrict')
    partner_id = fields.Many2one('res.partner', readonly=True, ondelete='restrict')
    quantity = fields.Float(readonly=True, digits='Product Unit')
    item_index = fields.Integer(default=0, readonly=True, copy=False)
    uom_id = fields.Many2one('uom.uom', readonly=True, ondelete='restrict')
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    purchase_value = fields.Monetary(required=True, readonly=True)
    date_start = fields.Date(required=True, readonly=True)
    state = fields.Selection([('draft', 'Active Acquisition'), ('cancel', 'Cancelled Acquisition')], required=True, default='draft', readonly=True)
    generation = fields.Integer(default=1, readonly=True)
    current_value = fields.Monetary(compute='_compute_current_value')
    valuation_ids = fields.One2many('erp.asset.valuation', 'acquisition_id', readonly=True)
    lock_version = fields.Integer(default=0, readonly=True)
    engine_asset_id = fields.Many2one('account.asset', readonly=True, copy=False, check_company=True, ondelete='restrict')
    _engine_unique = models.Constraint('unique(engine_asset_id)', 'A depreciation asset can only have one acquisition.')
    _source_unique = models.Constraint('unique(source_line_id, item_index, generation)', 'This bill line item already has an acquisition in this generation.')
    _number_company_unique = models.Constraint('unique(company_id, number)', 'Asset number must be unique in a company.')

    @api.model_create_multi
    def create(self, vals_list):
        if not _asset_creating.get():
            raise AccessError(_('Assets are created only by posting eligible bills.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Asset acquisition records are immutable.'))

    def unlink(self):
        raise AccessError(_('Asset acquisition records cannot be deleted.'))

    @api.depends('purchase_value', 'valuation_ids.amount')
    def _compute_current_value(self):
        for asset in self:
            asset.current_value = asset.purchase_value + sum(asset.valuation_ids.mapped('amount'))


    def action_create_depreciation_asset(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('erp_asset.group_asset_manager'):
            raise AccessError(_('Asset manager capability is required.'))
        self.env.cr.execute('SELECT id FROM erp_asset_asset WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()
        if self.state != 'draft' or self.current_value <= 0:
            raise UserError(_('Only an active acquisition with remaining value can create a depreciation asset.'))
        if self.engine_asset_id:
            raise UserError(_('This acquisition is already linked to a depreciation asset.'))
        self.profile_id._lock_profiles()
        profile = self.profile_id.oca_profile_id
        if profile:
            profile._erp_lock_profiles()
        if not profile or profile.open_asset or profile.asset_product_item != (self.profile_id.item_mode == 'item') or profile.company_id != self.company_id or profile.account_asset_id != self.source_line_id.account_id:
            raise ValidationError(_('A matching depreciation profile and item mode that keep assets in draft are required.'))
        # Legacy acquisitions retain their original null snapshot fields; only
        # the newly requested engine link reads the preserved source line.
        distribution = self.analytic_distribution or self.source_line_id.analytic_distribution
        fund = self.fund_id or self.source_line_id.expense_id.erp_budget_fund_id or self.source_line_id._erp_purchase_budget_source().erp_budget_fund_id
        token = _engine_creating.set(True)
        try:
            asset = self.env['account.asset'].sudo().with_company(self.company_id).with_context(create_asset_from_move_line=True, move_id=self.bill_id.id).create({'name': self.name, 'code': self.number, 'profile_id': profile.id, 'purchase_value': self.current_value, 'partner_id': self.partner_id.id, 'date_start': self.date_start, 'erp_acquisition_id': self.id, 'analytic_distribution': distribution, 'erp_asset_fund_id': fund.id})
            super(Asset, self.sudo()).write({'engine_asset_id': asset.id})
        finally:
            _engine_creating.reset(token)
        return True


class OcaAssetProfile(models.Model):
    _inherit = 'account.asset.profile'

    erp_lock_version = fields.Integer(default=0, readonly=True, copy=False)

    def _erp_lock_profiles(self):
        if self:
            ids = tuple(sorted(self.ids))
            self.env.cr.execute('SELECT id FROM account_asset_profile WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
            self.env.cr.execute('UPDATE account_asset_profile SET erp_lock_version = COALESCE(erp_lock_version, 0) + 1 WHERE id IN %s', [ids])
            self.invalidate_recordset()

    @api.model_create_multi
    def create(self, vals_list):
        if any('erp_lock_version' in vals for vals in vals_list):
            raise AccessError(_('Profile lock version is internal.'))
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        if 'erp_lock_version' in vals:
            raise AccessError(_('Profile lock version is internal.'))
        self._erp_lock_profiles()
        protected = {'company_id', 'account_asset_id', 'account_depreciation_id', 'account_expense_depreciation_id', 'journal_id', 'method', 'method_number', 'method_period', 'method_time', 'method_progress_factor', 'salvage_type', 'salvage_value', 'prorata', 'days_calc', 'use_leap_years', 'open_asset', 'asset_product_item'}
        if protected.intersection(vals) and self.env['account.asset'].sudo().search_count([('profile_id', 'in', self.ids), '|', ('erp_acquisition_id', '!=', False), ('erp_transfer_organization_id', '!=', False)]):
            raise UserError(_('A depreciation profile linked to an acquisition cannot be changed.'))
        return super().write(vals)


class OcaAsset(models.Model):
    _inherit = 'account.asset'

    erp_acquisition_id = fields.Many2one('erp.asset.asset', readonly=True, copy=False, ondelete='restrict', index=True)
    erp_transfer_organization_id = fields.Many2one('erp.organization.unit', readonly=True, copy=False, ondelete='restrict', check_company=True, index=True)
    erp_transfer_lock_version = fields.Integer(default=0, readonly=True, copy=False)
    _erp_acquisition_unique = models.Constraint('unique(erp_acquisition_id)', 'This acquisition already has a depreciation asset.')

    @api.model_create_multi
    def create(self, vals_list):
        if any('default_' + field in self.env.context for field in ('erp_transfer_organization_id', 'erp_transfer_lock_version', 'erp_acquisition_id')):
            raise AccessError(_('Asset scope defaults are internal.'))
        if any('erp_transfer_organization_id' in vals or 'erp_transfer_lock_version' in vals for vals in vals_list):
            raise AccessError(_('Transfer scope is internal.'))
        if _transfer_organization.get():
            vals_list = [dict(vals, erp_transfer_organization_id=_transfer_organization.get()) for vals in vals_list]
        if not _engine_creating.get() and any(vals.get('erp_acquisition_id') for vals in vals_list):
            raise AccessError(_('Use the acquisition action to create a depreciation asset.'))
        return super().create(vals_list)

    def write(self, vals):
        protected = {'erp_acquisition_id', 'erp_transfer_organization_id', 'erp_transfer_lock_version', 'profile_id', 'company_id', 'purchase_value', 'date_start', 'code', 'partner_id'}
        if not _engine_creating.get() and (bool({'erp_acquisition_id', 'erp_transfer_organization_id', 'erp_transfer_lock_version'} & vals.keys()) or (protected.intersection(vals) and any(asset.erp_acquisition_id or asset.erp_transfer_organization_id for asset in self))):
            raise AccessError(_('Linked asset acquisition provenance cannot be edited.'))
        return super().write(vals)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _erp_asset_source_lines(self):
        return self.line_ids.filtered(lambda line: not line.tax_line_id and line.display_type not in ('tax', 'payment_term', 'rounding') and (
            line.move_id.move_type == 'in_invoice' or line.expense_id and line.account_id == line.expense_id.account_id and line.balance > 0))

    def _post(self, soft=True):
        # Serialize profile creation, reassignment and posting even when no profile exists yet.
        invoice_lines = self._erp_asset_source_lines()
        invoice_lines.mapped('account_id')._erp_lock_asset_accounts()
        # OCA's action_post and this addon's _post must not create competing assets.
        invoice_lines = self._erp_asset_source_lines()
        for line in invoice_lines.filtered('asset_profile_id'):
            if self.env['erp.asset.profile'].sudo().search_count([('company_id', '=', line.company_id.id), ('account_id', '=', line.account_id.id), ('active', '=', True)]):
                raise ValidationError(_('Remove the automatic OCA profile from this bill; link the acquisition to a depreciation profile instead.'))
        # The savepoint keeps accounting, budget reconciliation and asset creation atomic.
        with self.env.cr.savepoint():
            posted = super()._post(soft=soft)
            invoices = posted.filtered(lambda m: m.state == 'posted')
            invoice_lines = invoices._erp_asset_source_lines()
            profiles = self.env['erp.asset.profile'].sudo().search([('company_id', 'in', invoices.company_id.ids), ('account_id', 'in', invoice_lines.account_id.ids), ('active', '=', True)])
            profiles._lock_profiles()
            for move in invoices:
                lines = move._erp_asset_source_lines()
                for line in lines:
                    profile = profiles.filtered(lambda p: p.company_id == move.company_id and p.account_id == line.account_id and p.active)
                    if not profile:
                        continue
                    acceptance = move.erp_acceptance_id
                    expense = line.expense_id
                    organization = acceptance.organization_id
                    quantity = line.quantity
                    if expense:
                        expense._check_asset_acquisition_scope()
                        organization = expense.erp_asset_organization_id or expense.erp_budget_organization_id
                        quantity = expense.quantity
                    elif not acceptance or acceptance.state != 'accept' or not line.purchase_line_id or line.purchase_line_id.order_id != acceptance.purchase_order_id:
                        raise ValidationError(_('An asset-profile bill requires a linked accepted purchase order.'))
                    acceptance.check_access('read')
                    if quantity <= 0 or line.balance <= 0:
                        raise ValidationError(_('Asset acquisition requires positive quantity and accounting value.'))
                    previous = self.env['erp.asset.asset'].sudo().search([('source_line_id', '=', line.id)])
                    if previous.filtered(lambda a: a.state == 'draft'):
                        continue
                    generation = max(previous.mapped('generation'), default=0) + 1
                    count = 1
                    if profile.item_mode == 'item':
                        count = int(quantity)
                        if count < 1 or quantity != count:
                            raise ValidationError(_('Per-item assets require a whole-number bill quantity.'))
                    currency = move.company_id.currency_id
                    unit_value = currency.round(line.balance / count)
                    if unit_value <= 0:
                        raise ValidationError(_('Each asset must have a positive acquisition value.'))
                    values = []
                    allocated = 0.0
                    for i in range(count):
                        number = self.env['ir.sequence'].sudo().with_company(move.company_id).next_by_code('erp.asset.asset')
                        if not number:
                            raise UserError(_('Asset numbering is not configured.'))
                        value = currency.round(line.balance - allocated) if i == count - 1 else unit_value
                        if value <= 0:
                            raise ValidationError(_('Each asset must have a positive acquisition value.'))
                        allocated = currency.round(allocated + value)
                        # Odoo 20 native PO autocomplete may leave the optional line description empty.
                        name = line.name or line.product_id.display_name or line.account_id.display_name
                        values.append({'name': name, 'number': number, 'company_id': move.company_id.id, 'organization_id': organization.id, 'profile_id': profile.id, 'source_line_id': line.id, 'acceptance_id': acceptance.id, 'expense_id': expense.id, 'fund_id': (expense.erp_budget_fund_id if expense else line._erp_purchase_budget_source().erp_budget_fund_id).id, 'analytic_distribution': line.analytic_distribution, 'product_id': line.product_id.id, 'partner_id': move.partner_id.id, 'quantity': 1 if profile.item_mode == 'item' else quantity, 'item_index': i + 1 if profile.item_mode == 'item' else 0, 'uom_id': line.product_uom_id.id, 'currency_id': currency.id, 'purchase_value': value, 'date_start': move.date if expense else fields.Datetime.to_datetime(acceptance.acceptance_date).date()})
                    token = _asset_creating.set(True)
                    try:
                        self.env['erp.asset.asset'].sudo().create([dict(value, generation=generation) for value in values])
                    finally:
                        _asset_creating.reset(token)
            return posted

class OcaAssetLine(models.Model):
    _inherit = 'account.asset.line'

    def create_move(self):
        linked = self.filtered(lambda line: line.asset_id.erp_acquisition_id)
        if linked:
            linked.check_access('write')
            self.env.cr.execute('SELECT id FROM account_asset_line WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(linked.ids))])
            linked.invalidate_recordset(['move_id', 'type'])
            if any(line.move_id for line in linked):
                raise UserError(_('A depreciation entry has already been posted for this line.'))
        return super().create_move()
