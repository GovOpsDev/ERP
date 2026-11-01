import json

from odoo import models


class SpreadsheetDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    def _get_serialized_readonly_dashboard(self):
        result = super()._get_serialized_readonly_dashboard()
        if self != self.env.ref('erp_budget_dashboard.dashboard_project_budget', raise_if_not_found=False):
            return result
        self.env['erp.budget.report'].check_access('read')
        data = json.loads(result)
        currency = self.env.company.currency_id
        # Format the actual company currency. Never replace a USD symbol by THB.
        number = '#,##0'
        symbol = '"' + currency.symbol.replace('"', '""') + '"'
        data['snapshot']['formats']['1'] = symbol + number if currency.position == 'before' else number + ' ' + symbol
        for sheet in data['snapshot']['sheets']:
            if sheet['name'] == 'Data':
                sheet['cells']['B1'] = self.env.company.name + ' · ' + currency.name
                # Truncate AFTER aggregation, toward zero (also for reversals).
                # A zero-decimal format alone would round the value instead.
                for row in range(1, 6):
                    cell = f'A{row}'
                    formula = sheet['cells'].get(cell, '')
                    if isinstance(formula, str) and formula.startswith('=PIVOT.VALUE('):
                        sheet['cells'][cell] = f'=TRUNC({formula[1:]},0)'
            for figure in sheet.get('figures', []):
                for chart in figure.get('data', {}).get('chartDefinitions', {}).values():
                    chart['dataSource']['searchParams'].setdefault('context', {})['erp_budget_integer_display'] = True
                if figure.get('data', {}).get('type') == 'scorecard':
                    figure['data']['baseline'] = 'Data!B1'
        return json.dumps(data)
