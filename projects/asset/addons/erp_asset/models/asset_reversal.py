"""Retain acquisition and credit history instead of upstream draft-asset deletion."""
from contextvars import ContextVar

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .asset import Asset, _engine_creating

_valuation_creating = ContextVar('erp_asset_valuation_creating', default=False)
_accounting_transition = ContextVar('erp_asset_accounting_transition', default=False)


class AssetValuation(models.Model):
    _name = 'erp.asset.valuation'
    _description = 'Asset Acquisition Valuation History'
    _order = 'id'
    _check_company_auto = True

    acquisition_id = fields.Many2one('erp.asset.asset', required=True, readonly=True, ondelete='restrict')
    company_id = fields.Many2one(related='acquisition_id.company_id', store=True)
    organization_id = fields.Many2one(related='acquisition_id.organization_id', store=True)
    currency_id = fields.Many2one(related='acquisition_id.currency_id')
    move_id = fields.Many2one('account.move', required=True, readonly=True, check_company=True, ondelete='restrict')
    refund_line_id = fields.Many2one('account.move.line', readonly=True, check_company=True, ondelete='restrict')
    reversal_of_id = fields.Many2one('erp.asset.valuation', readonly=True, ondelete='restrict')
    kind = fields.Selection([('credit', 'Credit Adjustment'), ('reset', 'Acquisition Reset'), ('restore', 'Credit Reset')], required=True, readonly=True)
    amount = fields.Monetary(required=True, readonly=True)
    before_value = fields.Monetary(required=True, readonly=True)
    after_value = fields.Monetary(required=True, readonly=True)
    _reversal_unique = models.Constraint('unique(reversal_of_id)', 'A valuation event can only be reversed once.')

    @api.model_create_multi
    def create(self, vals_list):
        if not _valuation_creating.get():
            raise AccessError(_('Valuation history is created by accounting transitions.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Asset valuation history is immutable.'))

    def unlink(self):
        raise AccessError(_('Asset valuation history cannot be deleted.'))


class AcquisitionReversal(models.Model):
    _inherit = 'erp.asset.asset'

    def _lock_valuation(self):
        if not self:
            return
        self.check_access('read')
        ids = tuple(sorted(self.ids))
        self.env.cr.execute('SELECT id FROM erp_asset_asset WHERE id IN %s ORDER BY id FOR UPDATE', [ids])
        self.env.cr.execute('UPDATE erp_asset_asset SET lock_version = COALESCE(lock_version, 0) + 1 WHERE id IN %s', [ids])
        self.invalidate_recordset()
        engines = self.engine_asset_id
        if engines:
            self.env.cr.execute('SELECT id FROM account_asset WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(engines.ids))])
            self.env.cr.execute('UPDATE account_asset SET erp_transfer_lock_version = COALESCE(erp_transfer_lock_version, 0) + 1 WHERE id IN %s', [tuple(sorted(engines.ids))])
            engines.invalidate_recordset()
        if any(a.state != 'draft' for a in engines) or engines.depreciation_line_ids.filtered(lambda l: l.type != 'create' and (l.move_id or l.init_entry)):
            raise UserError(_('Reset or credit requires draft assets without posted depreciation or disposal.'))
        if self.env['erp.asset.transfer.history'].sudo().search_count(['|', ('source_ids', 'in', engines.ids), ('destination_ids', 'in', engines.ids)]):
            raise UserError(_('An acquisition participating in an asset transfer cannot be reset or credited.'))

    def _record_valuation(self, amount, move, kind, refund_line=None, reversal=None):
        self.ensure_one()
        before = self.current_value
        after = self.currency_id.round(before + amount)
        if after < 0:
            raise ValidationError(_('An asset credit cannot exceed its remaining acquisition value.'))
        token = _valuation_creating.set(True)
        try:
            self.env['erp.asset.valuation'].sudo().create({
                'acquisition_id': self.id, 'move_id': move.id, 'refund_line_id': refund_line.id if refund_line else False,
                'kind': kind, 'amount': amount, 'before_value': before, 'after_value': after,
                'reversal_of_id': reversal.id if reversal else False})
        finally:
            _valuation_creating.reset(token)
        engine = self.engine_asset_id.sudo()
        if engine:
            token = _engine_creating.set(True)
            try:
                # Only the unposted depreciation plan changes. Posted GL and
                # original acquisition snapshots remain intact.
                engine.depreciation_line_ids.filtered(lambda l: l.type != 'create').unlink()
                engine.write({'purchase_value': after})
                engine.salvage_value = min(after, engine._get_salvage_value_profile())
                engine.depreciation_line_ids.filtered(lambda l: l.type == 'create').with_context(allow_asset_line_update=True).write({'amount': engine.depreciation_base})
                if kind == 'reset':
                    engine.state = 'removed'
            finally:
                _engine_creating.reset(token)
        if kind == 'reset':
            super(Asset, self.sudo()).write({'state': 'cancel'})


class AssetCreditMove(models.Model):
    _inherit = 'account.move'

    def _asset_credit_sources(self):
        result = []
        for move in self.filtered(lambda m: m.move_type == 'in_refund' or m.move_type == 'entry' and m.reversed_entry_id):
            if not move.reversed_entry_id and self.env['erp.asset.profile'].sudo().search_count([('company_id', '=', move.company_id.id), ('account_id', 'in', move.invoice_line_ids.account_id.ids), ('active', '=', True)]):
                raise ValidationError(_('An asset credit must identify its original acquisition bill.'))
            acquisitions = self.env['erp.asset.asset'].sudo().search([('bill_id', '=', move.reversed_entry_id.id), ('state', '=', 'draft')]) if move.reversed_entry_id else self.env['erp.asset.asset']
            for line in move.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
                candidates = acquisitions.filtered(lambda a: a.source_line_id.account_id == line.account_id and a.product_id == line.product_id and a.purchase_line_id == line.purchase_line_id)
                if line.erp_asset_refund_source_id:
                    candidates = candidates.filtered(lambda a: a.source_line_id == line.erp_asset_refund_source_id)
                    if not candidates:
                        raise ValidationError(_('The asset credit source must belong to the original bill and match this line.'))
                if not candidates:
                    continue
                if len(candidates.source_line_id) != 1:
                    raise ValidationError(_('Select the original asset bill line for this credit.'))
                candidates = candidates.with_env(self.env)
                candidates.check_access('read')
                result.append((line, candidates))
        return result

    def _post(self, soft=True):
        with self.env.cr.savepoint():
            credit_sources = self._asset_credit_sources()
            acquisitions = self.env['erp.asset.asset'].union(*(assets for line, assets in credit_sources))
            acquisitions.source_line_id.account_id._erp_lock_asset_accounts()
            acquisitions._lock_valuation()
            token = _accounting_transition.set(True)
            try:
                posted = super()._post(soft=soft)
            finally:
                _accounting_transition.reset(token)
            for line, assets in credit_sources:
                if line.move_id not in posted or line.move_id.state != 'posted':
                    continue
                amount = -line.balance
                total = sum(assets.mapped('current_value'))
                currency = line.company_id.currency_id
                if amount <= 0 or currency.compare_amounts(amount, total) > 0:
                    raise ValidationError(_('Credit must be positive and cannot exceed the uncredited asset value.'))
                allocated = 0
                cumulative = 0
                for asset in assets:
                    cumulative += asset.current_value
                    part = currency.round(amount * cumulative / total) - allocated
                    part = currency.round(part)
                    allocated += part
                    asset._record_valuation(-part, line.move_id, 'credit', refund_line=line)
            return posted

    def _asset_reset_values(self):
        acquisitions = self.env['erp.asset.asset'].sudo().search([('bill_id', 'in', self.ids), ('state', '=', 'draft')]).with_env(self.env)
        events = self.env['erp.asset.valuation'].sudo().search([('move_id', 'in', self.ids), ('kind', '=', 'credit')])
        reversed_events = self.env['erp.asset.valuation'].sudo().search([('reversal_of_id', 'in', events.ids)]).reversal_of_id
        events -= reversed_events
        affected = acquisitions | events.acquisition_id.with_env(self.env)
        affected.source_line_id.account_id._erp_lock_asset_accounts()
        affected._lock_valuation()
        active_credits = self.env['erp.asset.valuation'].sudo().search([('acquisition_id', 'in', acquisitions.ids), ('kind', '=', 'credit')])
        restored = self.env['erp.asset.valuation'].sudo().search([('reversal_of_id', 'in', active_credits.ids)]).reversal_of_id
        if active_credits - restored:
            raise UserError(_('Reset the asset credit notes before resetting the acquisition bill.'))
        for event in events:
            event.acquisition_id.with_env(self.env)._record_valuation(-event.amount, event.move_id, 'restore', refund_line=event.refund_line_id, reversal=event)
        for asset in acquisitions:
            asset._record_valuation(-asset.current_value, asset.bill_id, 'reset')

    def button_draft(self):
        self.check_access('write')
        with self.env.cr.savepoint():
            self._asset_reset_values()
            token = _accounting_transition.set(True)
            try:
                return super().button_draft()
            finally:
                _accounting_transition.reset(token)

    def button_cancel(self):
        self.check_access('write')
        with self.env.cr.savepoint():
            self._asset_reset_values()
            token = _accounting_transition.set(True)
            try:
                return super().button_cancel()
            finally:
                _accounting_transition.reset(token)

    def write(self, vals):
        if 'state' in vals and not _accounting_transition.get() and (
            self.env['erp.asset.asset'].sudo().search_count([('bill_id', 'in', self.ids)]) or
            self.env['erp.asset.valuation'].sudo().search_count([('move_id', 'in', self.ids)])):
            raise UserError(_('Use accounting post, reset or cancel to reconcile asset valuations.'))
        return super().write(vals)


class AssetCreditLine(models.Model):
    _inherit = 'account.move.line'

    erp_asset_refund_source_id = fields.Many2one('account.move.line', check_company=True, ondelete='restrict', copy=False,
                                               string='Original Asset Bill Line')

    def write(self, vals):
        if 'erp_asset_refund_source_id' in vals and any(line.move_id.state == 'posted' for line in self):
            raise UserError(_('Reset the credit before changing its asset source.'))
        return super().write(vals)


class ValuationEngine(models.Model):
    _inherit = 'account.asset'

    def validate(self):
        acquisitions = self.erp_acquisition_id
        acquisitions._lock_valuation()
        if any(a.state != 'draft' or a.current_value <= 0 for a in acquisitions):
            raise UserError(_('Cancelled or fully credited acquisitions cannot be activated.'))
        return super().validate()

    def write(self, vals):
        if vals.get('state') in ('draft', 'open') and not _engine_creating.get() and any(
            a.erp_acquisition_id and (a.erp_acquisition_id.state != 'draft' or a.erp_acquisition_id.current_value <= 0) for a in self):
            raise UserError(_('A cancelled or fully credited acquisition cannot be reopened.'))
        return super().write(vals)
