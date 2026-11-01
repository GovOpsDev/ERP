#!/usr/bin/env python3
"""Build static replay from one validated, privacy-reviewed Playwright run."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'playwright-demo/output'
REQUIRED = ('steps.json', 'relationships.json', 'documents.json', 'personas.json', 'final-state.json', 'narration.json', 'assertions.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_file(run, relative):
    require(isinstance(relative, str) and not Path(relative).is_absolute(), 'Absolute asset path')
    p = (run / relative).resolve()
    require(p.is_relative_to(run.resolve()) and p.is_file(), f'Missing or unsafe file: {relative}')
    return p


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_dashboard_bi(steps, final, assertions):
    fields = ('allocated_amount', 'committed_amount', 'actual_amount', 'other_amount', 'available_amount')
    require(len(steps) >= 10, 'Insufficient dashboard steps')
    for step in steps:
        require(all(k in step for k in ('dashboard_filters', 'kpis', 'chart_state', 'expected_change')), 'Missing dashboard state')
        kpis = step['kpis']
        require(all(isinstance(kpis.get(k), (int, float)) and math.isfinite(kpis[k]) for k in fields), 'Invalid dashboard metric')
        require(abs(kpis[fields[0]] - sum(kpis[k] for k in fields[1:])) < 0.01, 'Dashboard step does not reconcile')
        chart = step['chart_state']
        if chart.get('measure'):
            measure = chart['measure']
            require(measure in fields and isinstance(chart.get('projects'), list), 'Invalid chart measure')
            values = [point.get('value') for point in chart['projects']]
            require(all(isinstance(v, (int, float)) and math.isfinite(v) for v in values), 'Invalid chart value')
            require(abs(sum(values) - kpis[measure]) < 0.01, 'Chart and KPI differ')
    require(steps[0]['kpis'] == final['reset'] == steps[-1]['kpis'], 'Reset differs from baseline')
    projects = [s for s in steps if s['dashboard_filters'].get('project')]
    require(len({s['dashboard_filters']['project'] for s in projects}) >= 2, 'Project comparison missing')
    require(len({s['kpis']['allocated_amount'] for s in projects}) >= 2, 'Filter did not change the totals')
    require(assertions.get('security_company') == 403 and assertions.get('baseline_unchanged'), 'Security or unchanged baseline failed')


def validate(run, require_review=True):
    manifest = read(run / 'manifest.json')
    require(manifest.get('status') == 'PASS' and manifest.get('schema_version') == 1, 'Run did not pass')
    require(manifest.get('source') == 'Playwright against real Odoo', 'Unsupported evidence source')
    if manifest.get('recording'):
        require(manifest.get('video'), 'Recording missing')
        for video in manifest['video']:
            require(sha(safe_file(run, video)) == manifest['video_hashes'][video], 'Video hash mismatch')
    data = {}
    for name in REQUIRED:
        path = safe_file(run, name)
        require(sha(path) == manifest['files'][name]['sha256'], f'Hash mismatch: {name}')
        data[name] = read(path)
    steps = data['steps.json']; docs = data['documents.json']; personas = data['personas.json']
    doc_ids = {d['key'] for d in docs}; persona_ids = {p['id'] for p in personas}
    require(len(doc_ids) == len(docs), 'Duplicate document IDs')
    require(len(persona_ids) == len(personas), 'Duplicate persona IDs')
    require(len({s['id'] for s in steps}) == len(steps), 'Duplicate step IDs')
    require([s['order'] for s in steps] == list(range(1, len(steps)+1)), 'Invalid step order')
    fresh = manifest.get('tour_type') == 'fresh-creation'
    dashboard_bi = manifest.get('tour_type') == 'dashboard-bi'
    if fresh:
        require(data['assertions.json'].get('ui_creation') is True, 'Fresh UI creation evidence missing')
        require(all(s['mode'] == 'main' for s in steps), 'Fresh workflow must not mix denial evidence')
    main = [s for s in steps if s['mode'] == 'main']
    require(main and main[-1]['screen'] == 'final-result', 'Final real result screenshot missing')
    require(all(s['mode'] in ('main', 'permissions') for s in steps), 'Invalid tour mode')
    by_doc = {d['key']: d for d in docs}
    for step in steps:
        require(re.fullmatch(r'[A-Za-z0-9_-]+', step['id']) is not None, 'Unsafe step ID')
        require(step['persona'] in persona_ids and step['document_ref'] in doc_ids, f'Unresolved step {step["id"]}')
        require(step.get('narration') and step.get('tooltip') and step.get('duration_hint', 0) > 0, 'Narration missing')
        require(all(r in doc_ids for r in step['relationships']), 'Unresolved related document')
        require(step['viewport'] == manifest['viewport'], 'Inconsistent viewport')
        if manifest.get('recording'):
            require(step.get('video', {}).get('file') in manifest['video'], 'Step video link missing')
        target = step['target']
        require(all(isinstance(target.get(k), (int, float)) and math.isfinite(target[k]) and 0 <= target[k] <= 1 for k in ('x', 'y', 'width', 'height')), 'Invalid normalized hotspot')
        require(target['width'] > 0 and target['height'] > 0 and target['x'] + target['width'] <= 1.000001 and target['y'] + target['height'] <= 1.000001, 'Hotspot outside screenshot')
        image = safe_file(run, step['screenshot'])
        require(sha(image) == step['screenshot_sha256'], f'Screenshot changed: {image.name}')
        header = image.read_bytes()[:24]
        require(header[:8] == b'\x89PNG\r\n\x1a\n', 'Screenshot must be PNG')
        width, height = struct.unpack('>II', header[16:24])
        require((width, height) == (manifest['viewport']['width'], manifest['viewport']['height']), 'Wrong screenshot size')
        if step['mode'] == 'permissions':
            require(step['operation'] == 'attempt_read_denied' and step['state_after'] == 'access_denied', 'Not actual denial evidence')
    relations = data['relationships.json']
    require(len({r['id'] for r in relations}) == len(relations), 'Duplicate relationship IDs')
    def identity(value):
        return value[0] if isinstance(value, list) else value
    for rel in relations:
        require(rel['from'] in doc_ids and rel['to'] in doc_ids and rel.get('evidence'), 'Invalid relationship')
        a, b = by_doc[rel['from']], by_doc[rel['to']]
        require(identity(a['company']) == identity(b['company']), 'Cross-company relationship')
        if a.get('organization') and b.get('organization'):
            require(identity(a['organization']) == identity(b['organization']), 'Cross-OU relationship')
    narration = [{k:s[k] for k in ('id','narration','duration_hint')} for s in steps]
    require(data['narration.json'] == narration, 'Narration diverged from steps')
    final = data['final-state.json']; budget = final['budget']
    require(abs(budget['allocated'] - budget['committed'] - budget['actual'] - budget.get('other', 0) - budget['remaining']) < 0.01, 'Budget does not reconcile')
    if dashboard_bi:
        validate_dashboard_bi(steps, final, data['assertions.json'])
    else:
        require(final['inventory']['total'] == sum(q['quantity'] for q in final['inventory']['locations']), 'Inventory does not reconcile')
        require(final['assets']['count'] > 0 and final['acceptance']['quantity'] >= final['assets']['count'], 'Asset quantities invalid')
    if fresh:
        required_steps = {'PROJECT', 'TASK', 'BUDGET-BEFORE', 'PR-DRAFT', 'PR-APPROVED', 'REQ-CONFIRM', 'PO-CONFIRMED', 'AGREEMENT-ACTIVE', 'WA-ACCEPTED', 'STOCK-DONE', 'BILL-POSTED', 'ASSET', 'PROJECT-RESULT', 'FINAL'}
        require(required_steps.issubset({s['id'] for s in steps}), 'Fresh lifecycle evidence incomplete')
        quantity = final['procurement']['ordered_quantity']
        require(quantity == final['acceptance']['quantity'] == final['inventory']['received_qty'] == final['inventory']['run_delta'] == final['bill']['billed_quantity'] == final['assets']['count'], 'Fresh quantities do not reconcile')
        require(final['assets']['value'] == final['bill']['amount'] == budget['actual'], 'Fresh asset and financial values diverge')
        require(final['inventory']['total'] - final['inventory']['before_total'] == quantity, 'Fresh stock delta invalid')
    require(data['assertions.json']['result'] == 'PASS' and not data['assertions.json']['browser_errors'], 'Assertions failed')
    if require_review:
        review = read(run / 'publish-review.json')
        require(review.get('approved') is True and review.get('manifest_sha256') == sha(run/'manifest.json'), 'Review must match this manifest')
        require(review.get('synthetic_only') is True and review.get('no_credentials_visible') is True, 'Privacy review incomplete')
    return manifest, data


def public_tour_data(data):
    """Keep security-test evidence in the private run, never in public tours."""
    result = dict(data)
    result['steps.json'] = [step for step in data['steps.json'] if step['mode'] == 'main']
    retained = {step['persona'] for step in result['steps.json']}
    result['personas.json'] = [p for p in data['personas.json'] if p['id'] in retained]
    excluded = {s['document_ref'] for s in data['steps.json'] if s['mode'] != 'main'}
    used = {s['document_ref'] for s in result['steps.json']}
    used.update(r for s in result['steps.json'] for r in s['relationships'])
    used.update(r[k] for r in data['relationships.json'] for k in ('from', 'to'))
    result['documents.json'] = [d for d in data['documents.json'] if d['key'] not in excluded or d['key'] in used]
    result['narration.json'] = [{k: s[k] for k in ('id', 'narration', 'duration_hint')} for s in result['steps.json']]
    result['assertions.json'] = {k: v for k, v in data['assertions.json'].items() if k != 'security_cases'}
    return result


def build(run):
    manifest, private_data = validate(run)
    data = public_tour_data(private_data)
    # Validate everything before changing the last known publishable replay.
    destination = ROOT / ('guided-tour/generated-bi' if manifest.get('tour_type') == 'dashboard-bi' else 'guided-tour/generated-fresh' if manifest.get('tour_type') == 'fresh-creation' else 'guided-tour/generated')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.build-') as temp:
        target = Path(temp); (target/'screenshots').mkdir()
        for step in data['steps.json']:
            shutil.copyfile(safe_file(run, step['screenshot']), target/step['screenshot'])
        for name, value in data.items():
            (target/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        public_manifest = {k:manifest[k] for k in ('schema_version','run_id','scenario','status','source','created_at','viewport')}
        public_manifest.update({'tour_type':manifest.get('tour_type','recorded-evidence'),'raw_manifest_sha256':sha(run/'manifest.json'),'privacy_review':'synthetic screenshots and metadata reviewed; raw video is excluded'})
        if 'duration_seconds' in manifest: public_manifest['duration_seconds']=manifest['duration_seconds']
        (target/'manifest.json').write_text(json.dumps(public_manifest, ensure_ascii=False, indent=2)+'\n')
        lines = ['# Fresh Creation Tour — Generated video storyboard' if manifest.get('tour_type') == 'fresh-creation' else '# Generated video storyboard', '', f'Run: `{manifest["run_id"]}`. Generated from steps.json; do not edit manually.', '', '| Step ID | Screenshot | Action | Narration | Duration |', '| --- | --- | --- | --- | ---: |']
        elapsed=0; subtitles=[]
        for s in data['steps.json']:
            escape=lambda text:str(text).replace('|','\\|').replace('\n',' ')
            lines.append(f'| {s["id"]} | [Screenshot]({s["screenshot"]}) | {escape(s["operation"])} | {escape(s["narration"])} | {s["duration_hint"]} s |')
            subtitles.append({'id':s['id'],'start_hint_seconds':elapsed,'end_hint_seconds':elapsed+s['duration_hint'],'text':s['narration']});elapsed+=s['duration_hint']
        (target/'video-storyboard.md').write_text('\n'.join(lines)+'\n')
        (target/'subtitle-hints.json').write_text(json.dumps(subtitles,ensure_ascii=False,indent=2)+'\n')
        # Only this generator-owned subtree is replaced; source and vendor stay intact.
        backup=destination.with_name('.'+destination.name+'-previous')
        require(not backup.exists(), 'Previous interrupted build needs review')
        if destination.exists(): destination.rename(backup)
        try: Path(temp).rename(destination)
        except Exception:
            if backup.exists(): backup.rename(destination)
            raise
        if backup.exists(): shutil.rmtree(backup)
    print(f'BUILD PASS: {manifest["run_id"]}, {len(data["steps.json"])} steps')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id', nargs='?')
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--before-review',action='store_true',help='Validate evidence without publishing; review remains required for build')
    args=parser.parse_args()
    try:
        run_id=args.run_id or read(OUTPUT/'latest.json')['run_id']
        require(re.fullmatch(r'[A-Za-z0-9_-]+',run_id) is not None,'Unsafe run ID')
        run=OUTPUT/run_id
        if args.validate_only:
            manifest,data=validate(run,not args.before_review)
            print(f'VALID: {run_id}, {len(data["steps.json"])} steps')
        else:
            require(not args.before_review,'Review cannot be bypassed for publication')
            build(run)
    except (ValueError,KeyError,TypeError,OSError) as error:
        parser.exit(1,f'BUILD FAILED: {error}\n')
