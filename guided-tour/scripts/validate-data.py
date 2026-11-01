#!/usr/bin/env python3
"""Validate published replay images, normalized hotspots and references."""
import hashlib
import json
from pathlib import Path
import sys
directory=sys.argv[1] if len(sys.argv)>1 else 'generated'
if directory not in ('generated','generated-fresh'):sys.exit('Invalid generated directory')
root=Path(__file__).resolve().parents[1]/directory
try:
    steps=json.loads((root/'steps.json').read_text())
    docs=json.loads((root/'documents.json').read_text())
    refs={d['key'] for d in docs}
    assert len({s['id'] for s in steps})==len(steps)
    for s in steps:
        assert s['document_ref'] in refs
        p=(root/s['screenshot']).resolve()
        assert p.is_relative_to(root.resolve())
        assert hashlib.sha256(p.read_bytes()).hexdigest()==s['screenshot_sha256']
        t=s['target']
        assert all(0<=t[k]<=1 for k in ['x','y','width','height'])
        assert t['width']>0 and t['height']>0 and t['x']+t['width']<=1.000001 and t['y']+t['height']<=1.000001
    print(f'PASS: {len(steps)} generated steps and screenshot hashes')
except (AssertionError,KeyError,OSError,ValueError) as e:
    sys.exit(f'INVALID: {e}')
