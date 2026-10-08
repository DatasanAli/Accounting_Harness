"""A deferred external gate must never masquerade as verified completion."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_foundation', ROOT / 'scripts/verify_foundation.py')
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class RoadmapTests(unittest.TestCase):
    def test_deferred_gate_requires_explicit_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Plan').mkdir()
            (root / 'README.md').write_text('')
            (root / 'AGENTS.md').write_text('')
            (root / 'Plan/phase.md').write_text('### Step 01: Initial\n### Step 02: Next\n')
            steps = [dict(id='01', status='deferred'), dict(id='02', status='ready')]
            roadmap = dict(schema_version=2, current_step='01', next_step='02',
                           phases=[dict(id='01', path='Plan/phase.md', steps=steps)])
            path = root / 'Plan/roadmap.json'
            path.write_text(json.dumps(roadmap))
            with patch.object(verification, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'reason'):
                    verification.check_plan()
                steps[0]['deferred_reason'] = 'Live API connection deferred by the user.'
                path.write_text(json.dumps(roadmap))
                verification.check_plan()
                steps[0]['status'] = 'planned'
                path.write_text(json.dumps(roadmap))
                with self.assertRaises(ValueError):
                    verification.check_plan()
