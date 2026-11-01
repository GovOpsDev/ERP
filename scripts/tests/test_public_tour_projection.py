import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('guided_builder', Path(__file__).parents[1] / 'build-guided-tour.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PublicTourProjectionTest(unittest.TestCase):
    def test_permission_evidence_remains_private_after_every_build(self):
        original = {
            'steps.json': [
                {'id': 'MAIN', 'mode': 'main', 'persona': 'demo', 'document_ref': 'a', 'relationships': [], 'narration': 'main', 'duration_hint': 1},
                {'id': 'PRIVATE', 'mode': 'permissions', 'persona': 'restricted', 'document_ref': 'b', 'relationships': [], 'narration': 'private', 'duration_hint': 1},
            ],
            'personas.json': [{'id': 'demo'}, {'id': 'restricted'}],
            'documents.json': [{'key': 'a'}, {'key': 'b'}],
            'relationships.json': [],
            'narration.json': [],
            'assertions.json': {'result': 'PASS', 'security_cases': ['PRIVATE']},
        }
        saved = copy.deepcopy(original)
        public = builder.public_tour_data(original)
        self.assertEqual([s['id'] for s in public['steps.json']], ['MAIN'])
        self.assertEqual([p['id'] for p in public['personas.json']], ['demo'])
        self.assertEqual([d['key'] for d in public['documents.json']], ['a'])
        self.assertNotIn('security_cases', public['assertions.json'])
        self.assertEqual([n['id'] for n in public['narration.json']], ['MAIN'])
        self.assertEqual(original, saved)


if __name__ == '__main__': unittest.main()
