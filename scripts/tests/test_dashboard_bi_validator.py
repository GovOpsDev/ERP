import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('guided_builder', Path(__file__).parents[1] / 'build-guided-tour.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DashboardValidatorTest(unittest.TestCase):
    def setUp(self):
        def metrics(allocated):
            return dict(allocated_amount=allocated, committed_amount=20, actual_amount=10, other_amount=0, available_amount=allocated-30)
        def step(project, allocated):
            return dict(dashboard_filters={'project': project} if project else {}, kpis=metrics(allocated), chart_state={'measure':'allocated_amount','projects':[{'value':allocated}]}, expected_change='change')
        self.steps = [step(None, 100)] + [step('A', 60)] * 4 + [step('B', 40)] * 4 + [step(None, 100)]
        self.final = {'reset': metrics(100)}
        self.assertions = {'security_company': 403, 'baseline_unchanged': True}

    def test_valid(self):
        builder.validate_dashboard_bi(self.steps, self.final, self.assertions)

    def test_rejects_bad_reconciliation(self):
        self.steps[2]['kpis']['available_amount'] += 1
        with self.assertRaises(ValueError): builder.validate_dashboard_bi(self.steps, self.final, self.assertions)

    def test_rejects_nonfinite(self):
        self.steps[2]['kpis']['actual_amount'] = float('nan')
        with self.assertRaises(ValueError): builder.validate_dashboard_bi(self.steps, self.final, self.assertions)

    def test_rejects_inconsistent_chart(self):
        self.steps[2]['chart_state']['projects'][0]['value'] += 1
        with self.assertRaises(ValueError): builder.validate_dashboard_bi(self.steps, self.final, self.assertions)

    def test_rejects_failed_reset(self):
        self.final['reset']['allocated_amount'] += 1
        with self.assertRaises(ValueError): builder.validate_dashboard_bi(self.steps, self.final, self.assertions)

    def test_rejects_unchanged_filter_or_security(self):
        unchanged = copy.deepcopy(self.steps)
        for s in unchanged:
            if s['dashboard_filters'].get('project') == 'B':
                s['kpis'] = copy.deepcopy(unchanged[1]['kpis'])
                s['chart_state'] = copy.deepcopy(unchanged[1]['chart_state'])
        with self.assertRaises(ValueError): builder.validate_dashboard_bi(unchanged, self.final, self.assertions)
        self.assertions['security_company'] = 200
        with self.assertRaises(ValueError): builder.validate_dashboard_bi(self.steps, self.final, self.assertions)


if __name__ == '__main__': unittest.main()
