import datetime

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestSecurityBaseline(HttpCase):
    def test_anonymous_signup_denied(self):
        response = self.url_open('/web/signup')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.env['res.users']._get_signup_invitation_scope(), 'b2b')

    def test_native_cooldown_enforces_configured_boundary(self):
        users = self.env['res.users']
        now = datetime.datetime.now()
        self.assertFalse(users._on_login_cooldown(4, now))
        self.assertTrue(users._on_login_cooldown(5, now - datetime.timedelta(seconds=299)))
        self.assertFalse(users._on_login_cooldown(5, now - datetime.timedelta(seconds=301)))
