"""Localize the standard warehouse dashboard response without changing its data."""
import json

from odoo import models

WAREHOUSE_XMLID = 'spreadsheet_dashboard_stock_account.spreadsheet_dashboard_warehouse_metrics'


def localize_snapshot(snapshot, labels):
    """Change display strings only; sheet names, references and numbers stay intact."""
    def figures(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {'text', 'title', 'label'} and isinstance(value, str):
                    node[key] = labels.get(value, value)
                else:
                    figures(value)
        elif isinstance(node, list):
            for value in node:
                figures(value)

    for sheet in snapshot.get('sheets', []):
        figures(sheet.get('figures', []))
        for cell, content in sheet.get('cells', {}).items():
            # Standard JSON has string cells. Also support newer object cell exports.
            value = content.get('content') if isinstance(content, dict) else content
            if not isinstance(value, str):
                continue
            if value.startswith('='):
                # Only quoted UI literals change. Functions, references, numeric
                # expressions, domains and pivot definitions are never rewritten.
                for source in ('No data', ' out of '):
                    value = value.replace(json.dumps(source), json.dumps(labels[source], ensure_ascii=False))
            else:
                value = labels.get(value, value)
            if isinstance(content, dict):
                content['content'] = value
            else:
                sheet['cells'][cell] = value
    return snapshot


class SpreadsheetDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    def _warehouse_th_labels(self):
        return {
            'Warehouse Metrics': self.env._('Warehouse Metrics'),
            'Share reserved stock Qty': self.env._('Share reserved stock Qty'),
            'Share reserved stock Value': self.env._('Share reserved stock Value'),
            'Share of reserved stock qty': self.env._('Share of reserved stock qty'),
            'Share of reserved stock Value': self.env._('Share of reserved stock Value'),
            'Lines with negative stock': self.env._('Lines with negative stock'),
            'Products with negative stock': self.env._('Products with negative stock'),
            'Count of products with negative stock': self.env._('Count of products with negative stock'),
            'Available & Reserved Stock Quantity': self.env._('Available & Reserved Stock Quantity'),
            'Available & Reserved Stock Value': self.env._('Available & Reserved Stock Value'),
            'Top Locations': self.env._('Top Locations'),
            'Top Products': self.env._('Top Products'),
            'Top 50': self.env._('Top 50'),
            'Stock Quantity': self.env._('Stock Quantity'),
            'Stock Value': self.env._('Stock Value'),
            'Available Value': self.env._('Available Value'),
            'Reserved value': self.env._('Reserved value'),
            'Reserved': self.env._('Reserved'),
            'Total': self.env._('Total'),
            'Total inventory value': self.env._('Total inventory value'),
            'Stock location Qty': self.env._('Stock location Qty'),
            'Stock location Value': self.env._('Stock location Value'),
            'Ageing stock qty by product and creation date': self.env._('Ageing stock qty by product and creation date'),
            'Ageing stock value by product and creation date': self.env._('Ageing stock value by product and creation date'),
            'Creation Date': self.env._('Creation Date'),
            'Location': self.env._('Location'),
            'Warehouse': self.env._('Warehouse'),
            'Product': self.env._('Product'),
            'Products': self.env._('Products'),
            'Product Category': self.env._('Product Category'),
            'Chart': self.env._('Chart'),
            'No data': self.env._('No data'),
            ' out of ': self.env._(' out of '),
        }

    def _uses_thai_warehouse_labels(self):
        return (
            self.env.lang == 'th_TH'
            and self == self.env.ref(WAREHOUSE_XMLID, raise_if_not_found=False)
        )

    def _get_serialized_readonly_dashboard(self):
        body = super()._get_serialized_readonly_dashboard()
        if self._uses_thai_warehouse_labels():
            payload = json.loads(body)
            localize_snapshot(payload['snapshot'], self._warehouse_th_labels())
            return json.dumps(payload)
        return body

    def _get_sample_dashboard(self):
        snapshot = super()._get_sample_dashboard()
        if snapshot and self._uses_thai_warehouse_labels():
            localize_snapshot(snapshot, self._warehouse_th_labels())
        return snapshot
