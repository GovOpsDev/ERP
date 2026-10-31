"""Legal agreement content and versioned review evidence from OCA agreement_legal."""
from contextvars import ContextVar
from datetime import timedelta
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_legal_internal = ContextVar('erp_agreement_legal_internal', default=False)
_REVIEW_FIELDS = {'reviewed_date', 'reviewed_user_id', 'approved_date', 'approved_user_id', 'review_scheduled_version', 'review_scheduled_date'}


class AgreementStage(models.Model):
    _name = 'erp.contract.agreement.stage'
    _description = 'Agreement Legal Stage'
    _order = 'sequence, id'
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean()
    readonly = fields.Boolean()
    active = fields.Boolean(default=True)


class AgreementType(models.Model):
    _name = 'erp.contract.agreement.type'
    _description = 'Agreement Legal Type'
    name = fields.Char(required=True)
    review_days = fields.Integer()
    review_user_id = fields.Many2one('res.users', ondelete='restrict')
    active = fields.Boolean(default=True)

    @api.constrains('review_days')
    def _check_days(self):
        if any(record.review_days < 0 for record in self):
            raise ValidationError(_('Review notice days cannot be negative.'))


class AgreementSubtype(models.Model):
    _name = 'erp.contract.agreement.subtype'
    _description = 'Agreement Legal Subtype'
    name = fields.Char(required=True)
    type_id = fields.Many2one('erp.contract.agreement.type', required=True, ondelete='restrict')
    active = fields.Boolean(default=True)


class LegalAgreement(models.Model):
    _name = 'erp.contract.agreement'
    _inherit = ['erp.contract.agreement', 'mail.thread', 'mail.activity.mixin']

    stage_id = fields.Many2one('erp.contract.agreement.stage', ondelete='restrict', tracking=True)
    type_id = fields.Many2one('erp.contract.agreement.type', ondelete='restrict')
    subtype_id = fields.Many2one('erp.contract.agreement.subtype', ondelete='restrict')
    description = fields.Html()
    parties = fields.Html()
    special_terms = fields.Html()
    partner_contact_id = fields.Many2one('res.partner', ondelete='restrict')
    company_contact_id = fields.Many2one('res.users', ondelete='restrict')
    assigned_user_id = fields.Many2one('res.users', ondelete='restrict')
    notification_address_id = fields.Many2one('res.partner', ondelete='restrict')
    company_signed_user_id = fields.Many2one('res.users', ondelete='restrict')
    partner_signed_user_id = fields.Many2one('res.partner', ondelete='restrict')
    company_signed_date = fields.Date()
    partner_signed_date = fields.Date()
    signed_contract = fields.Binary(attachment=True, copy=False)
    signed_contract_filename = fields.Char(copy=False)
    legal_item_ids = fields.One2many('erp.contract.agreement.item', 'agreement_id', copy=True)
    reviewed_date = fields.Date(readonly=True, copy=False)
    reviewed_user_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_date = fields.Date(readonly=True, copy=False)
    approved_user_id = fields.Many2one('res.users', readonly=True, copy=False)
    to_review_date = fields.Date(compute='_compute_review_date', store=True, readonly=False)
    review_scheduled_version = fields.Integer(readonly=True, copy=False)
    review_scheduled_date = fields.Date(readonly=True, copy=False)

    @api.depends('end_date', 'type_id.review_days')
    def _compute_review_date(self):
        for agreement in self:
            agreement.to_review_date = agreement.end_date - timedelta(days=agreement.type_id.review_days) if agreement.end_date else False

    def _editable_lifecycle_fields(self):
        return super()._editable_lifecycle_fields() | {'stage_id', 'message_follower_ids', 'activity_ids'} | (_REVIEW_FIELDS if _legal_internal.get() else set())

    @api.constrains('type_id', 'subtype_id', 'assigned_user_id', 'company_contact_id', 'company_signed_user_id')
    def _check_legal_identity(self):
        for agreement in self:
            if agreement.subtype_id and agreement.subtype_id.type_id != agreement.type_id:
                raise ValidationError(_('Agreement subtype must belong to its selected legal type.'))
            users = agreement.assigned_user_id | agreement.company_contact_id | agreement.company_signed_user_id
            if any(agreement.company_id not in user.company_ids for user in users):
                raise ValidationError(_('Agreement internal contacts must belong to its company.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not _legal_internal.get() and (any(_REVIEW_FIELDS & vals.keys() for vals in vals_list) or any('default_' + name in self.env.context for name in _REVIEW_FIELDS)):
            raise AccessError(_('Review evidence is recorded by agreement actions.'))
        return super().create(vals_list)

    def write(self, vals):
        if _REVIEW_FIELDS & vals.keys() and not _legal_internal.get():
            raise AccessError(_('Review actor/date and scheduling evidence cannot be forged.'))
        if vals.keys() - self._editable_lifecycle_fields() and any(record.stage_id.readonly for record in self):
            raise UserError(_('Move the agreement out of its read-only legal stage before editing.'))
        if 'stage_id' in vals:
            self._manager_check()
        return super().write(vals)

    def _snapshot_values(self):
        values = super()._snapshot_values()
        names = ['description', 'parties', 'special_terms', 'company_signed_date', 'partner_signed_date', 'to_review_date', 'reviewed_date', 'approved_date']
        payload = {name: str(self[name]) if self[name] and self._fields[name].type == 'date' else self[name] for name in names}
        for name in ['stage_id', 'type_id', 'subtype_id', 'partner_contact_id', 'company_contact_id', 'assigned_user_id', 'notification_address_id', 'company_signed_user_id', 'partner_signed_user_id', 'reviewed_user_id', 'approved_user_id']:
            record = self[name]
            payload[name] = {'id': record.id, 'name': record.display_name} if record else False
        payload['items'] = [{'id': item.id, 'kind': item.kind, 'name': item.name, 'title': item.title, 'sequence': item.sequence, 'section_id': item.section_id.id, 'content': item.content, 'active': item.active} for item in self.with_context(active_test=False).legal_item_ids]
        values.update({'legal_snapshot': payload, 'signed_contract': self.signed_contract, 'signed_contract_filename': self.signed_contract_filename})
        return values

    def action_new_version(self):
        result = super().action_new_version()
        token = _legal_internal.set(True)
        try:
            self.write({'reviewed_date': False, 'reviewed_user_id': False, 'approved_date': False, 'approved_user_id': False, 'review_scheduled_version': 0, 'review_scheduled_date': False})
        finally:
            _legal_internal.reset(token)
        return result

    def _mark_legal_review(self, approve):
        self._manager_check()
        if any(record.state == 'inactive' for record in self):
            raise UserError(_('Inactive agreements cannot record a new review.'))
        prefix = 'approved' if approve else 'reviewed'
        token = _legal_internal.set(True)
        try:
            return self.write({prefix + '_date': fields.Date.context_today(self), prefix + '_user_id': self.env.uid})
        finally:
            _legal_internal.reset(token)

    def action_mark_reviewed(self):
        self._mark_legal_review(False)
        return self._legal_review_notification(_('Review recorded.'))

    def action_mark_approved(self):
        self._mark_legal_review(True)
        return self._legal_review_notification(_('Legal approval recorded.'))

    def _legal_review_notification(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.model
    def _cron_agreement_reviews(self):
        today = fields.Date.context_today(self)
        agreements = self.search([('state', '!=', 'inactive'), ('to_review_date', '<=', today), ('type_id.review_user_id', '!=', False)])
        for agreement in agreements:
            self.env.cr.execute('SELECT id FROM erp_contract_agreement WHERE id=%s FOR UPDATE', [agreement.id])
            agreement.invalidate_recordset()
            if agreement.review_scheduled_version == agreement.version and agreement.review_scheduled_date == agreement.to_review_date:
                continue
            reviewer = agreement.type_id.review_user_id
            if not reviewer.active or agreement.company_id not in reviewer.company_ids:
                continue
            scoped = agreement.with_user(reviewer).with_context(allowed_company_ids=agreement.company_id.ids)
            if not scoped.has_access('read'):
                continue
            agreement.activity_schedule('mail.mail_activity_data_todo', user_id=reviewer.id, date_deadline=agreement.to_review_date, summary=_('Review agreement before expiry'))
            token = _legal_internal.set(True)
            try:
                agreement.write({'review_scheduled_version': agreement.version, 'review_scheduled_date': agreement.to_review_date})
            finally:
                _legal_internal.reset(token)


class LegalItem(models.Model):
    _name = 'erp.contract.agreement.item'
    _description = 'Agreement Legal Content'
    _check_company_auto = True
    _order = 'sequence, id'
    agreement_id = fields.Many2one('erp.contract.agreement', required=True, check_company=True, ondelete='cascade')
    company_id = fields.Many2one(related='agreement_id.company_id', store=True)
    organization_id = fields.Many2one(related='agreement_id.organization_id', store=True)
    kind = fields.Selection([('recital', 'Recital'), ('section', 'Section'), ('clause', 'Clause'), ('appendix', 'Appendix')], required=True)
    name = fields.Char(required=True)
    title = fields.Char()
    sequence = fields.Integer(default=10)
    section_id = fields.Many2one('erp.contract.agreement.item', check_company=True, ondelete='restrict')
    content = fields.Html()
    dynamic_content = fields.Html(compute='_compute_dynamic_content')
    active = fields.Boolean(default=True)

    @api.depends('content', 'agreement_id.name', 'agreement_id.partner_id', 'agreement_id.version')
    def _compute_dynamic_content(self):
        for item in self:
            item.dynamic_content = self.env['mail.template']._render_template(item.content or '', self._name, item.ids)[item.id] if item.id else item.content

    @api.constrains('section_id', 'kind', 'agreement_id')
    def _check_section(self):
        for item in self:
            if item.section_id and (item.kind != 'clause' or item.section_id.kind != 'section' or item.section_id.agreement_id != item.agreement_id):
                raise ValidationError(_('A clause section must belong to the same agreement.'))

    def _check_editable(self):
        self.agreement_id.check_access('write')
        if any(a.state != 'draft' or a.stage_id.readonly for a in self.agreement_id):
            raise UserError(_('Legal content can only change in an editable draft version.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            agreement = self.env['erp.contract.agreement'].browse(vals.get('agreement_id', self.env.context.get('default_agreement_id')))
            agreement.check_access('write')
            if not agreement or agreement.state != 'draft' or agreement.stage_id.readonly:
                raise UserError(_('Legal content requires an editable draft agreement.'))
        return super().create(vals_list)

    def write(self, vals):
        self._check_editable()
        if 'agreement_id' in vals:
            raise AccessError(_('Legal content cannot change its agreement.'))
        if vals.get('kind') and vals['kind'] != 'section' and self.sudo().search_count([('section_id', 'in', self.ids)]):
            raise ValidationError(_('A section referenced by clauses must remain a section.'))
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()


class LegalRevision(models.Model):
    _inherit = 'erp.contract.agreement.revision'
    legal_snapshot = fields.Json(readonly=True)
    signed_contract = fields.Binary(attachment=True, readonly=True)
    signed_contract_filename = fields.Char(readonly=True)
