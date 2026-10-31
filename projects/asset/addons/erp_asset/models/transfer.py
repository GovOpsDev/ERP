from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare

from .asset import _transfer_organization

_history_creating = ContextVar('erp_asset_transfer_history_creating', default=False)


class AssetTransferHistory(models.Model):
    _name = 'erp.asset.transfer.history'
    _description = 'Asset accounting transfer history'
    _check_company_auto = True
    _order = 'id desc'

    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict', index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, readonly=True, check_company=True, ondelete='restrict', index=True)
    date = fields.Date(required=True, readonly=True)
    move_id = fields.Many2one('account.move', required=True, readonly=True, check_company=True, ondelete='restrict')
    source_ids = fields.Many2many('account.asset', 'erp_asset_transfer_history_source_rel', 'history_id', 'asset_id', readonly=True)
    destination_ids = fields.Many2many('account.asset', 'erp_asset_transfer_history_destination_rel', 'history_id', 'asset_id', readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    value = fields.Monetary(required=True, readonly=True)
    user_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    _move_unique = models.Constraint('unique(move_id)', 'This transfer entry already has a history record.')

    @api.model_create_multi
    def create(self, vals_list):
        if not _history_creating.get():
            raise AccessError(_('Transfer history is created only by the transfer action.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Transfer history is immutable.'))

    def unlink(self):
        raise AccessError(_('Transfer history cannot be deleted.'))


class AssetTransfer(models.TransientModel):
    _inherit = 'account.asset.transfer'

    def _check_amount_transfer(self):
        self.ensure_one()
        rounding = self.company_id.currency_id.rounding
        if float_compare(self.from_asset_value, self.to_asset_value, precision_rounding=rounding):
            raise UserError(_('Source and destination values must match at company currency precision.'))
        if any(float_compare(line.asset_value, 0, precision_rounding=rounding) <= 0 for line in self.to_asset_ids):
            raise UserError(_('Each destination value must be positive at company currency precision.'))

    def transfer(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('erp_asset.group_asset_manager'):
            raise AccessError(_('Asset manager capability is required.'))
        sources = self.from_asset_ids
        if not sources:
            raise ValidationError(_('Select source assets.'))
        sources.check_access('write')
        ids = tuple(sorted(sources.ids))
        self.env.cr.execute('SELECT id FROM account_asset WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
        self.env.cr.execute('UPDATE account_asset SET erp_transfer_lock_version = COALESCE(erp_transfer_lock_version, 0) + 1 WHERE id IN %s', [ids])
        sources.invalidate_recordset()
        sources._check_can_transfer()
        if sources.mapped('depreciation_line_ids').filtered(lambda line: line.type == 'depreciate' and line.move_id):
            raise UserError(_('AUC transfer does not support assets with posted depreciation.'))
        companies = sources.mapped('company_id')
        organizations = sources.mapped('erp_acquisition_id.organization_id') | sources.mapped('erp_transfer_organization_id')
        if len(companies) != 1 or companies != self.company_id or len(organizations) != 1:
            raise ValidationError(_('Transfer sources must belong to one company and one organization.'))
        organization = organizations
        if any(not (asset.erp_acquisition_id or asset.erp_transfer_organization_id) for asset in sources):
            raise ValidationError(_('All source assets must have an ERP organization scope.'))
        if not organization.active or organization.company_id != self.company_id or not organization.assignment_ids.filtered(lambda a: a.user_id == self.env.user):
            raise AccessError(_('The asset manager must be assigned to the source organization.'))
        if any(line.asset_profile_id.company_id != self.company_id or line.asset_profile_id.open_asset for line in self.to_asset_ids):
            raise ValidationError(_('Destination profiles must use the same company and create draft assets.'))
        rounding = self.company_id.currency_id.rounding
        if any(float_compare(asset.purchase_value, 0, precision_rounding=rounding) <= 0 for asset in sources):
            raise ValidationError(_('Each source asset must have positive value.'))
        source_dates = sources.mapped('date_start') + sources.mapped('depreciation_line_ids.move_id.date')
        if any(date > self.date_transfer for date in source_dates if date):
            raise ValidationError(_('Transfer date cannot precede a source acquisition or accounting entry.'))
        source_value = sum(sources.mapped('purchase_value'))
        target_value = sum(self.to_asset_ids.mapped('asset_value'))
        if float_compare(source_value, target_value, precision_rounding=self.company_id.currency_id.rounding):
            raise ValidationError(_('Source and destination values must match at company currency precision.'))
        token = _transfer_organization.set(organization.id)
        try:
            with self.env.cr.savepoint():
                result = super().transfer()
                move = self.env['account.move'].browse(result['domain'][0][2]).exists()
                destinations = move.line_ids.filtered(lambda line: line.debit and line.asset_id and line.asset_id not in sources).mapped('asset_id')
                if not move or move.state != 'posted' or not destinations or any(a.erp_transfer_organization_id != organization or a.company_id != self.company_id for a in destinations):
                    raise ValidationError(_('The transfer did not create valid scoped destination assets.'))
                if float_compare(sum(destinations.mapped('purchase_value')), source_value, precision_rounding=self.company_id.currency_id.rounding):
                    raise ValidationError(_('Destination assets must conserve the source value.'))
                destinations._set_transfer_fund_provenance(sources)
                token_history = _history_creating.set(True)
                try:
                    self.env['erp.asset.transfer.history'].sudo().create({'company_id': self.company_id.id, 'organization_id': organization.id, 'date': self.date_transfer, 'move_id': move.id, 'source_ids': [(6, 0, sources.ids)], 'destination_ids': [(6, 0, destinations.ids)], 'value': source_value, 'user_id': self.env.user.id})
                finally:
                    _history_creating.reset(token_history)
                return result
        finally:
            _transfer_organization.reset(token)


class TransferAssetProtection(models.Model):
    _inherit = 'account.asset'

    def write(self, vals):
        if {'state', 'date_remove'} & vals.keys() and self.env['erp.asset.transfer.history'].sudo().search_count([('source_ids', 'in', self.ids)]):
            raise UserError(_('A transferred source asset cannot be reopened or its removal date changed.'))
        return super().write(vals)

    def unlink(self):
        history = self.env['erp.asset.transfer.history'].sudo().search_count(['|', ('source_ids', 'in', self.ids), ('destination_ids', 'in', self.ids)])
        if history:
            raise UserError(_('Assets in a transfer history cannot be deleted.'))
        return super().unlink()


class TransferMoveProtection(models.Model):
    _inherit = 'account.move'

    def _check_erp_transfer_history(self):
        if self.env['erp.asset.transfer.history'].sudo().search_count([('move_id', 'in', self.ids)]):
            raise UserError(_('Asset transfer entries cannot be reset or deleted.'))

    def button_draft(self):
        self._check_erp_transfer_history()
        return super().button_draft()

    def unlink(self):
        self._check_erp_transfer_history()
        return super().unlink()

    def button_cancel(self):
        self._check_erp_transfer_history()
        return super().button_cancel()

    def _reverse_moves(self, *args, **kwargs):
        self._check_erp_transfer_history()
        return super()._reverse_moves(*args, **kwargs)

    def write(self, vals):
        if {'line_ids', 'date', 'journal_id', 'company_id', 'state'} & vals.keys():
            self._check_erp_transfer_history()
        return super().write(vals)


class TransferMoveLineProtection(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        move_ids = [vals.get('move_id') or self.env.context.get('default_move_id') for vals in vals_list]
        self.env['account.move'].browse([move_id for move_id in move_ids if move_id]).exists()._check_erp_transfer_history()
        return super().create(vals_list)

    def write(self, vals):
        if {'move_id', 'account_id', 'debit', 'credit', 'balance', 'asset_id', 'asset_profile_id', 'currency_id', 'amount_currency'} & vals.keys():
            moves = self.mapped('move_id') | self.env['account.move'].browse(vals.get('move_id')).exists()
            moves._check_erp_transfer_history()
        return super().write(vals)

    def unlink(self):
        self.mapped('move_id')._check_erp_transfer_history()
        return super().unlink()
