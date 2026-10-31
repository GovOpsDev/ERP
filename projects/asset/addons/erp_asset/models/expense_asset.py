from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from .asset import _engine_creating, _transfer_organization


class ExpenseAsset(models.Model):
    _inherit = 'hr.expense'

    erp_asset_profile_id = fields.Many2one('erp.asset.profile', check_company=True, ondelete='restrict')
    erp_asset_organization_id = fields.Many2one('erp.organization.unit', check_company=True, ondelete='restrict')

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & (
            Domain('erp_asset_organization_id', '=', False) |
            (Domain('erp_asset_organization_id.active', '=', True) & Domain('erp_asset_organization_id.assignment_ids.user_id', '=', self.env.uid)))

    @api.onchange('erp_asset_profile_id')
    def _onchange_asset_profile(self):
        if self.erp_asset_profile_id:
            self.account_id = self.erp_asset_profile_id.account_id

    @api.constrains('erp_asset_profile_id', 'account_id', 'company_id', 'erp_asset_organization_id', 'erp_budget_organization_id')
    def _check_asset_acquisition_scope(self):
        for expense in self:
            profile = expense.erp_asset_profile_id
            if profile and (profile.company_id != expense.company_id or profile.account_id != expense.account_id or not profile.active):
                raise ValidationError(_('The expense asset profile must match its company and account.'))
            if profile or self.env['erp.asset.profile'].sudo().search_count([('company_id', '=', expense.company_id.id), ('account_id', '=', expense.account_id.id), ('active', '=', True)]):
                if expense.erp_is_advance:
                    raise ValidationError(_('An employee advance is not an asset acquisition; capitalize its clearing expense.'))
                unit = expense.erp_asset_organization_id or expense.erp_budget_organization_id
                if not unit or not unit.active or unit.company_id != expense.company_id:
                    raise ValidationError(_('Asset expenses require an active organization in their company.'))
                if expense.erp_budget_organization_id and unit != expense.erp_budget_organization_id:
                    raise ValidationError(_('Asset and budget organizations must match.'))
                unit.check_access('read')
                if not self.env.su and not unit.assignment_ids.filtered(lambda a: a.user_id == self.env.user):
                    raise AccessError(_('The user must be assigned to the asset organization.'))

    def write(self, vals):
        if {'erp_asset_profile_id', 'erp_asset_organization_id'} & vals.keys() and any(e.approval_state == 'approved' or e.account_move_id for e in self):
            raise UserError(_('Reset the expense before changing its asset scope.'))
        return super().write(vals)


class AssetFund(models.Model):
    _inherit = 'account.asset'

    erp_asset_fund_id = fields.Many2one('erp.budget.fund', check_company=True, ondelete='restrict', readonly=True)

    def _set_transfer_fund_provenance(self, sources):
        if not _transfer_organization.get():
            raise AccessError(_('Transfer fund provenance requires the transfer workflow.'))
        funds = sources.erp_asset_fund_id
        # Source fund onchange also leaves an ambiguous multi-fund analytic
        # empty. Preserve all source identities in the immutable transfer history.
        fund = funds if len(funds) == 1 and all(a.erp_asset_fund_id for a in sources) else False
        super(AssetFund, self.sudo()).write({'erp_asset_fund_id': fund.id if fund else False})

    @api.model_create_multi
    def create(self, vals_list):
        if 'default_erp_asset_fund_id' in self.env.context or not _engine_creating.get() and any(vals.get('erp_asset_fund_id') for vals in vals_list):
            raise AccessError(_('Asset fund provenance comes from the acquisition.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_asset_fund_id' in vals or 'analytic_distribution' in vals and any(a.erp_acquisition_id for a in self):
            raise AccessError(_('Acquired asset fund and analytic provenance cannot be rewritten.'))
        return super().write(vals)


class AssetFundMoveLine(models.Model):
    _inherit = 'account.move.line'

    # Reporting provenance only. Depreciation does not consume acquisition
    # budget again through Finance's direct-budget dimension fields.
    erp_asset_fund_id = fields.Many2one('erp.budget.fund', compute='_compute_asset_fund', store=True, check_company=True, ondelete='restrict')

    @api.depends('asset_id.erp_asset_fund_id', 'asset_id.company_id.asset_move_line_analytic', 'account_id')
    def _compute_asset_fund(self):
        for line in self:
            asset = line.asset_id
            line.erp_asset_fund_id = asset.erp_asset_fund_id if asset and (asset.company_id.asset_move_line_analytic or line.account_id == asset.profile_id.account_expense_depreciation_id) else False

    @api.model_create_multi
    def create(self, vals_list):
        if 'default_erp_asset_fund_id' in self.env.context or any('erp_asset_fund_id' in vals for vals in vals_list):
            raise AccessError(_('Asset journal fund provenance is derived from the asset.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_asset_fund_id' in vals:
            raise AccessError(_('Asset journal fund provenance cannot be rewritten.'))
        return super().write(vals)
