# Copyright 2021-2023 Ecosoft Co., Ltd.
# Copyright 2026 GovOpsDev
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class AssetSubState(models.Model):
    _name = 'account.asset.sub.state'
    _description = 'Asset Substatus'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    note = fields.Text()
    company_id = fields.Many2one('res.company', ondelete='restrict')
    active = fields.Boolean(default=True)
    draft = fields.Boolean()
    open = fields.Boolean()
    close = fields.Boolean()
    removed = fields.Boolean()

    @api.constrains('company_id', 'draft', 'open', 'close', 'removed')
    def _check_linked_assets(self):
        self.env['account.asset'].sudo().search([('asset_sub_state_id', 'in', self.ids)])._check_substate()


class AssetParent(models.Model):
    _name = 'account.asset.parent'
    _description = 'Parent Asset'
    _check_company_auto = True
    _rec_names_search = ['code', 'name']

    name = fields.Char(required=True)
    code = fields.Char(required=True, default='/', copy=False)
    note = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, ondelete='restrict')
    active = fields.Boolean(default=True)
    asset_ids = fields.One2many('account.asset', 'parent_id')

    @api.constrains('company_id')
    def _check_linked_companies(self):
        for parent in self:
            if parent.company_id and self.env['account.asset'].sudo().search_count([('parent_id', '=', parent.id), ('company_id', '!=', parent.company_id.id)]):
                raise ValidationError(_('A parent asset cannot move away from its linked assets company.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', '/') == '/':
                vals['code'] = self.env['ir.sequence'].next_by_code('account.asset.parent') or '/'
        return super().create(vals_list)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '[%s] %s' % (record.code, record.name)

    def action_view_assets(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.display_name,
                'res_model': 'account.asset', 'view_mode': 'list,form',
                'domain': [('parent_id', '=', self.id)]}


class Company(models.Model):
    _inherit = 'res.company'

    asset_move_line_analytic = fields.Boolean(string='Asset analytics on all journal items')


class ThaiAsset(models.Model):
    _inherit = 'account.asset'

    image = fields.Binary(attachment=True)
    parent_id = fields.Many2one('account.asset.parent', check_company=True, ondelete='restrict')
    asset_sub_state_id = fields.Many2one('account.asset.sub.state', check_company=True, ondelete='restrict')
    remove_reason = fields.Char(readonly=True, copy=False)
    depreciation_rate = fields.Float(compute='_compute_thai_rate', store=True)
    low_value = fields.Boolean(compute='_compute_low_value', store=True)
    erp_legacy_auc = fields.Boolean(readonly=True, copy=False, help='Preserved pre-migration zero-year asset semantics; not evidence of an upstream low-value classification.')

    @api.depends('method', 'method_number')
    def _compute_thai_rate(self):
        for asset in self:
            asset.depreciation_rate = 100 / asset.method_number if asset.method in ('linear', 'linear-limit') and asset.method_number else 0

    @api.depends('profile_id.account_asset_id.account_type', 'method_number', 'erp_legacy_auc')
    def _compute_low_value(self):
        for asset in self:
            asset.low_value = not asset.erp_legacy_auc and asset.profile_id.account_asset_id.account_type == 'expense' and asset.method_number == 0

    @api.model_create_multi
    def create(self, vals_list):
        if 'default_erp_legacy_auc' in self.env.context or any('erp_legacy_auc' in vals for vals in vals_list):
            raise AccessError(_('Legacy asset classification is reserved for migration.'))
        return super().create(vals_list)

    @api.depends('low_value')
    def _compute_depreciation(self):
        super()._compute_depreciation()
        for asset in self.filtered('low_value'):
            asset.value_residual = 0

    @api.constrains('asset_sub_state_id', 'state', 'company_id')
    def _check_substate(self):
        for asset in self:
            substate = asset.asset_sub_state_id
            if substate and (not substate[asset.state] or substate.company_id and substate.company_id != asset.company_id):
                raise ValidationError(_('The asset substatus must match its company and lifecycle state.'))

    def write(self, vals):
        if 'erp_legacy_auc' in vals:
            raise AccessError(_('Legacy asset classification is immutable.'))
        if 'state' in vals and 'asset_sub_state_id' not in vals:
            # A source substatus belongs to a lifecycle state; never retain an
            # incompatible label when the native engine advances that state.
            vals = dict(vals, asset_sub_state_id=False)
        return super().write(vals)

    def validate(self):
        result = super().validate()
        for asset in self:
            if asset.low_value:
                asset.state = 'open'
            elif asset.method_number > 0 and asset.company_id.currency_id.compare_amounts(asset.value_residual, asset.salvage_value) == 0:
                asset.state = 'close'
            substate = self.env['account.asset.sub.state'].search([
                (asset.state, '=', True), '|', ('company_id', '=', False), ('company_id', '=', asset.company_id.id)], limit=1)
            if substate:
                asset.asset_sub_state_id = substate
        return result

    def compute_depreciation_board(self):
        return super(ThaiAsset, self.filtered(lambda a: not a.low_value)).compute_depreciation_board()

    def _compute_depreciation_amount_per_fiscal_year(self, table, line_dates, start, stop):
        result = super()._compute_depreciation_amount_per_fiscal_year(table, line_dates, start, stop)
        if self.days_calc:
            day_amount = (self.purchase_value - self.salvage_value) / ((stop - start).days + 1)
            for entry in result:
                entry['day_amount'] = day_amount
        return result

    def action_remove_multi_assets(self):
        self.check_access('write')
        if not self or any(a.state not in ('open', 'close') for a in self):
            raise UserError(_('Only running or fully depreciated assets can be removed.'))
        if len(self.company_id) != 1 or len(set(self.mapped('low_value'))) != 1:
            raise UserError(_('Remove assets of one company and one low-value category at a time.'))
        return {'type': 'ir.actions.act_window', 'name': _('Remove Assets'),
                'res_model': 'account.asset.remove', 'view_mode': 'form', 'target': 'new',
                'view_id': self.env.ref('erp_asset.low_value_remove_form').id if self[0].low_value else False,
                'context': dict(self.env.context, active_ids=self.ids, active_id=self[0].id, erp_batch_remove=True)}

    def remove(self):
        self.ensure_one()
        if self.low_value:
            return self.action_remove_multi_assets()
        return super().remove()


class ThaiAssetLine(models.Model):
    _inherit = 'account.asset.line'

    def _setup_move_line_data(self, depreciation_date, account, ml_type, move):
        vals = super()._setup_move_line_data(depreciation_date, account, ml_type, move)
        if self.asset_id.company_id.asset_move_line_analytic:
            vals['analytic_distribution'] = self.asset_id.analytic_distribution
        return vals

    def create_move(self):
        result = super().create_move()
        for asset in self.asset_id:
            if asset.method_number > 0 and asset.company_id.currency_id.compare_amounts(asset.value_residual, asset.salvage_value) == 0:
                asset.state = 'close'
        return result


class ThaiAssetRemove(models.TransientModel):
    _inherit = 'account.asset.remove'

    remove_reason = fields.Char()

    def remove(self):
        self.ensure_one()
        if self.env.context.get('erp_batch_remove'):
            return self.remove_multi_assets()
        asset = self.env['account.asset'].browse(self.env.context.get('active_id')).exists()
        asset.ensure_one()
        asset.check_access('write')
        if asset.company_id != self.company_id or asset.state not in ('open', 'close'):
            raise ValidationError(_('Removal requires an active asset of the wizard company.'))
        if self.date_remove < asset.date_start:
            raise ValidationError(_('Removal cannot precede acquisition.'))
        if asset.low_value:
            asset.write({'state': 'removed', 'date_remove': self.date_remove, 'remove_reason': self.remove_reason})
            return {'type': 'ir.actions.act_window_close'}
        result = super().remove()
        asset.remove_reason = self.remove_reason
        return result

    def remove_multi_assets(self):
        self.ensure_one()
        assets = self.env['account.asset'].browse(self.env.context.get('active_ids', [])).exists()
        assets.action_remove_multi_assets()  # Server-side scope and category validation.
        with self.env.cr.savepoint():
            for asset in assets:
                early = bool(asset.value_residual and (asset.method not in ('linear-limit', 'degr-limit') or asset.value_residual != asset.salvage_value))
                self.with_context(active_id=asset.id, active_ids=asset.ids, erp_batch_remove=False, early_removal=early).remove()
        return {'type': 'ir.actions.act_window_close'}

    def _get_removal_data(self, asset, residual_value):
        commands = super()._get_removal_data(asset, residual_value)
        if asset.company_id.asset_move_line_analytic:
            commands = [(op, key, dict(vals, analytic_distribution=asset.analytic_distribution)) for op, key, vals in commands]
        return commands
