#!/usr/bin/env python3
"""Record a completed visual review; this command does not perform that review."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
spec=importlib.util.spec_from_file_location('builder',Path(__file__).with_name('build-guided-tour.py'))
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('run_id');p.add_argument('--confirm-synthetic',action='store_true');p.add_argument('--confirm-no-credentials',action='store_true')
a=p.parse_args()
if not a.confirm_synthetic or not a.confirm_no_credentials:p.error('Review every screenshot and the selected JSON before confirming both flags')
if not re.fullmatch(r'[A-Za-z0-9_-]+',a.run_id):p.error('Unsafe run ID')
run=builder.OUTPUT/a.run_id
try:
    builder.validate(run,require_review=False)
    (run/'publish-review.json').write_text(json.dumps({'approved':True,'synthetic_only':True,'no_credentials_visible':True,'manifest_sha256':builder.sha(run/'manifest.json'),'method':'Explicit confirmation after visual review of screenshots and selected JSON'},indent=2)+'\n')
    print(f'Review recorded: {a.run_id}')
except (ValueError,KeyError,OSError) as error:p.exit(1,str(error)+'\n')
