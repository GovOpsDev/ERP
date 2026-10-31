from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class Agreement(models.Model):
    _name = 'erp.contract.agreement'
    _description = 'Purchase Agreement'
    _check_company_auto = True
    _order = 'id desc'

    code = fields.Char(required=True, default='New', readonly=True, copy=False, index=True)
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='restrict', index=True)
    organization_id = fields.Many2one('erp.organization.unit', required=True, check_company=True, ondelete='restrict', index=True)
    partner_id = fields.Many2one('res.partner', required=True, ondelete='restrict')
    purchase_order_id = fields.Many2one('purchase.order', required=True, check_company=True, ondelete='restrict', index=True)
    currency_id = fields.Many2one(related='purchase_order_id.currency_id')
    amount_untaxed = fields.Monetary(related='purchase_order_id.amount_untaxed', string='PO Untaxed Amount')
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    signature_date = fields.Date()
    termination_date = fields.Date(readonly=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('active', 'Active'), ('inactive', 'Inactive')], default='draft', required=True, copy=False)
    version = fields.Integer(default=1, readonly=True, copy=False)
    revision_ids = fields.One2many('erp.contract.agreement.revision', 'agreement_id', readonly=True)
    is_expired = fields.Boolean(compute='_compute_is_expired')
    _code_company_unique = models.Constraint('unique(company_id, code)', 'Agreement reference must be unique in a company.')

    @api.depends('end_date')
    @api.depends_context('tz')
    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for agreement in self:
            agreement.is_expired = bool(agreement.end_date and agreement.end_date < today)

    def _validate_source(self, require_draft=False):
        for agreement in self:
            agreement.purchase_order_id.check_access('read')
            po = agreement.purchase_order_id
            if po.company_id != agreement.company_id or agreement.organization_id.company_id != agreement.company_id:
                raise ValidationError(_('Agreement, organization and purchase order companies must match.'))
            if not agreement.organization_id.active or po.erp_request_organization_id != agreement.organization_id:
                raise ValidationError(_('The agreement must match the active request organization of the purchase order.'))
            if po.partner_id != agreement.partner_id:
                raise ValidationError(_('The agreement partner must match the purchase order vendor.'))
            if require_draft and po.state not in ('draft', 'sent'):
                raise ValidationError(_('An agreement must be linked to a draft or sent RFQ.'))
            if agreement.start_date > agreement.end_date:
                raise ValidationError(_('The start date must be on or before the end date.'))

    @api.model_create_multi
    def create(self, vals_list):
        po_ids = sorted({v.get('purchase_order_id') for v in vals_list if v.get('purchase_order_id')})
        if po_ids:
            self.env['purchase.order'].browse(po_ids)._lock_request_scope()
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' or vals.get('version', 1) != 1 or vals.get('revision_ids') or vals.get('termination_date'):
                raise AccessError(_('Agreements must begin in draft without history.'))
            if not self.env.su and vals.get('company_id', self.env.company.id) not in self.env.companies.ids:
                raise AccessError(_('The agreement company must be active.'))
            unit = self.env['erp.organization.unit'].browse(vals.get('organization_id')).exists()
            if not unit:
                raise ValidationError(_('An organization is required.'))
            unit.check_access('read')
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].with_company(vals.get('company_id', self.env.company.id)).next_by_code('erp.contract.agreement') or 'New'
        with self.env.cr.savepoint():
            records = super().create(vals_list)
            records._validate_source(require_draft=True)
            return records

    def _editable_lifecycle_fields(self):
        return set()

    def write(self, vals):
        self.check_access('write')
        if {'state', 'version', 'revision_ids', 'termination_date', 'company_id', 'organization_id', 'partner_id', 'purchase_order_id', 'code'} & vals.keys():
            raise AccessError(_('Use agreement actions; identity and history cannot be edited.'))
        if vals.keys() - self._editable_lifecycle_fields() and any(record.state != 'draft' for record in self):
            raise UserError(_('Only draft agreements can be edited.'))
        with self.env.cr.savepoint():
            result = super().write(vals)
            self._validate_source()
            return result

    def unlink(self):
        self.check_access('unlink')
        if any(record.state != 'draft' or record.revision_ids for record in self):
            raise UserError(_('Only draft agreements without history can be deleted.'))
        return super().unlink()

    def _manager_check(self):
        self.check_access('write')
        if not self.env.user.has_group('erp_contract.group_contract_manager'):
            raise AccessError(_('Agreement management capability is required.'))

    def action_activate(self):
        self._manager_check()
        self.mapped('purchase_order_id')._lock_request_scope()
        self._validate_source()
        today = fields.Date.context_today(self)
        if any(record.state != 'draft' or not record.signature_date or not record.start_date <= today <= record.end_date or record.purchase_order_id.state == 'cancel' for record in self):
            raise UserError(_('A signed, current draft agreement and a non-cancelled purchase order are required.'))
        return super(Agreement, self).write({'state': 'active'})

    def action_terminate(self):
        self._manager_check()
        self.mapped('purchase_order_id')._lock_request_scope()
        if any(record.state != 'active' for record in self):
            raise UserError(_('Only active agreements may be terminated.'))
        return super(Agreement, self).write({'state': 'inactive', 'termination_date': fields.Date.context_today(self)})

    def _snapshot_values(self):
        self.ensure_one()
        return {'agreement_id': self.id, 'version': self.version, 'name': self.name, 'start_date': self.start_date, 'end_date': self.end_date, 'signature_date': self.signature_date, 'amount_untaxed': self.amount_untaxed, 'currency_id': self.currency_id.id}

    def action_new_version(self):
        self.ensure_one()
        self._manager_check()
        self.purchase_order_id._lock_request_scope()
        if self.state != 'active':
            raise UserError(_('Only active agreements can start a new version.'))
        with self.env.cr.savepoint():
            self.env.cr.execute('SELECT id FROM erp_contract_agreement WHERE id = %s FOR UPDATE', [self.id])
            self.invalidate_recordset()
            if self.state != 'active':
                raise UserError(_('The agreement has changed.'))
            self.env['erp.contract.agreement.revision'].sudo().create(self._snapshot_values())
            return super(Agreement, self).write({'state': 'draft', 'version': self.version + 1, 'signature_date': False})


class AgreementRevision(models.Model):
    _name = 'erp.contract.agreement.revision'
    _description = 'Agreement Version Snapshot'
    _order = 'version desc, id desc'

    agreement_id = fields.Many2one('erp.contract.agreement', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='agreement_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='agreement_id.organization_id', store=True, index=True)
    version = fields.Integer(required=True)
    name = fields.Char(required=True)
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    signature_date = fields.Date()
    currency_id = fields.Many2one('res.currency', required=True)
    amount_untaxed = fields.Monetary()
    _version_unique = models.Constraint('unique(agreement_id, version)', 'Agreement version already exists.')

    def write(self, vals):
        raise AccessError(_('Agreement version snapshots are immutable.'))

    def unlink(self):
        raise AccessError(_('Agreement version snapshots are immutable.'))
