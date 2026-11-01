import json

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged('-at_install', 'post_install')
class TestDashboardCurrency(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.usd = cls.env['res.company'].create({
            'name': 'Dashboard USD', 'currency_id': cls.env.ref('base.USD').id,
        })
        cls.thb = cls.env['res.company'].create({
            'name': 'Dashboard THB', 'currency_id': cls.env.ref('base.THB').id,
        })
        cls.other = cls.env['res.company'].create({'name': 'Dashboard denied'})
        cls.user = new_test_user(cls.env, login='dashboard_currency_test',
            groups='base.group_user', company_id=cls.usd.id,
            company_ids=[(6, 0, (cls.usd | cls.thb).ids)])
        cls.snapshot = {'sheets': [{'id': 'sheet1', 'name': 'Data',
            'cells': {'A1': '1000', 'B1': '=FORMAT.LARGE.NUMBER(A1)'}}]}
        cls.dashboard = cls.env['spreadsheet.dashboard'].create({
            'name': 'Currency regression', 'spreadsheet_data': json.dumps(cls.snapshot),
            'dashboard_group_id': cls.env['spreadsheet.dashboard.group'].create({'name': 'Currency test'}).id,
        })

    def load_dashboard(self, cookie=None):
        self.authenticate(self.user.login, self.user.login)
        if cookie is not None:
            self.opener.cookies.set('cids', cookie)
        return self.url_open(f'/spreadsheet/dashboard/data/{self.dashboard.id}')

    def test_selected_company_overrides_user_default(self):
        original = self.dashboard.spreadsheet_data
        response = self.load_dashboard(str(self.thb.id))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['default_currency']['code'], 'THB')
        self.assertEqual(data['default_currency']['symbol'], '฿')
        self.assertEqual(data['snapshot']['sheets'], self.snapshot['sheets'])
        self.assertEqual(self.dashboard.spreadsheet_data, original)
        self.assertEqual(self.user.company_id, self.usd)

    def test_current_company_is_first_selected(self):
        response = self.load_dashboard(f'{self.usd.id}-{self.thb.id}')
        self.assertEqual(response.json()['default_currency']['code'], 'USD')
        response = self.load_dashboard(f'{self.thb.id}-{self.usd.id}')
        self.assertEqual(response.json()['default_currency']['code'], 'THB')

    def test_no_cookie_keeps_default(self):
        self.assertEqual(self.load_dashboard().json()['default_currency']['code'], 'USD')

    def test_unauthorized_company_rejected(self):
        self.assertEqual(self.load_dashboard(f'{self.thb.id}-{self.other.id}').status_code, 403)

    def test_malformed_cookie_rejected(self):
        self.assertEqual(self.load_dashboard('invalid').status_code, 404)
