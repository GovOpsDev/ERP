from . import models
from odoo.exceptions import UserError
from odoo import _


def post_init_hook(env):
    # Never silently backfill accounting data that predates this integration.
    if env['account.move.line'].sudo().search_count([('purchase_line_id.erp_request_line_id', '!=', False), ('move_id.state', '=', 'posted')], limit=1):
        raise UserError(_('Existing posted bills linked to controlled purchase requests require explicit migration before installing Finance integration.'))
