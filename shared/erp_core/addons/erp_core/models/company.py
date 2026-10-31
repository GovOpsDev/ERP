"""Thai currency defaults; existing and explicitly selected currencies are preserved."""
from odoo import api, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model
    def _default_currency_id(self):
        # Standard company.create and the parent onchange still inherit a branch's
        # currency from its parent. Also honor the parent in contextual defaults.
        if parent_id := self.env.context.get('default_parent_id'):
            parent = self.browse(parent_id).exists()
            if parent:
                return parent.currency_id
        return self.env.ref('base.THB', raise_if_not_found=False) or super()._default_currency_id()
