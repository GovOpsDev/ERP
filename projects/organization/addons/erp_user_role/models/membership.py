from contextvars import ContextVar

from odoo import Command, fields, models


# Only internal Python calls can set this; an RPC context cannot disable tracking.
_engine_write = ContextVar('erp_role_engine_write', default=False)


def _intents(commands, current):
    """Return final explicit link/unlink intentions, including no-op link/set."""
    current = set(current)
    intents = {}
    for cmd in commands or []:
        op = cmd[0]
        ident = cmd[1] if len(cmd) > 1 else 0
        value = cmd[2] if len(cmd) > 2 else None
        if op == 4:
            current.add(ident)
            intents[ident] = True
        elif op in (2, 3):
            current.discard(ident)
            intents[ident] = False
        elif op == 5:
            for ident in current:
                intents[ident] = False
            current.clear()
        elif op == 6:
            desired = set(value)
            for ident in current - desired:
                intents[ident] = False
            for ident in desired:
                intents[ident] = True
            current = desired
    return intents


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _role_lock(self):
        if self.ids:
            self.env.cr.execute('SELECT id FROM res_users WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.invalidate_recordset(['group_ids', 'company_ids', 'active'])

    def _role_reconcile(self):
        users = self.sudo().exists()
        if not users:
            return
        users._role_lock()
        assignments = self.env['erp.user.role.assignment'].sudo().with_context(active_test=False).search([('user_id', 'in', users.ids)])
        states_model = self.env['erp.user.role.group.state'].sudo()
        assignments.invalidate_recordset(['effective'])
        today = fields.Date.today()
        for user in users:
            required = set(assignments.filtered(lambda a: a.user_id == user and a._is_effective(today)).mapped('role_id.group_ids').ids)
            existing = set(user.group_ids.ids)
            states = states_model.search([('user_id', '=', user.id)])
            by_group = {s.group_id.id: s for s in states}
            add, remove = [], []
            for group_id in required:
                state = by_group.get(group_id)
                if not state:
                    state = states_model.create({'user_id': user.id, 'group_id': group_id, 'manual': group_id in existing})
                if group_id not in existing:
                    add.append(Command.link(group_id))
            for state in states:
                if state.group_id.id not in required:
                    if not state.manual and state.group_id.id in existing:
                        remove.append(Command.unlink(state.group_id.id))
                    state.unlink()
            if add or remove:
                token = _engine_write.set(True)
                try:
                    user.write({'group_ids': remove + add})
                finally:
                    _engine_write.reset(token)

    def write(self, vals):
        if _engine_write.get():
            return super().write(vals)
        changes = {}
        if 'group_ids' in vals:
            self.sudo()._role_lock()
            changes = {user.id: _intents(vals['group_ids'], user.sudo().group_ids.ids) for user in self}
        result = super().write(vals)
        if changes:
            state_model = self.env['erp.user.role.group.state'].sudo()
            for user_id, intents in changes.items():
                for state in state_model.search([('user_id', '=', user_id), ('group_id', 'in', list(intents))]):
                    state.manual = intents[state.group_id.id]
        if changes or {'company_ids', 'active'} & vals.keys():
            self.sudo()._role_reconcile()
        return result


class ResGroups(models.Model):
    _inherit = 'res.groups'

    def write(self, vals):
        if _engine_write.get() or 'user_ids' not in vals:
            return super().write(vals)
        changes = {group.id: _intents(vals['user_ids'], group.sudo().user_ids.ids) for group in self}
        user_ids = set().union(*(set(c) for c in changes.values())) if changes else set()
        users = self.env['res.users'].sudo().browse(list(user_ids)).exists()
        users._role_lock()
        result = super().write(vals)
        states = self.env['erp.user.role.group.state'].sudo().search([('group_id', 'in', self.ids), ('user_id', 'in', users.ids)])
        for state in states:
            intent = changes.get(state.group_id.id, {}).get(state.user_id.id)
            if intent is not None:
                state.manual = intent
        users._role_reconcile()
        return result
