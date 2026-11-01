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
    require(any(s['mode'] == 'permissions' for s in steps), 'Permission evidence missing')
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
    require(budget['allocated'] == budget['committed'] + budget['actual'] + budget['remaining'], 'Budget does not reconcile')
    require(final['inventory']['total'] == sum(q['quantity'] for q in final['inventory']['locations']), 'Inventory does not reconcile')
    require(final['assets']['count'] > 0 and final['acceptance']['quantity'] >= final['assets']['count'], 'Asset quantities invalid')
    require(data['assertions.json']['result'] == 'PASS' and not data['assertions.json']['browser_errors'], 'Assertions failed')
    if require_review:
        review = read(run / 'publish-review.json')
        require(review.get('approved') is True and review.get('manifest_sha256') == sha(run/'manifest.json'), 'Review must match this manifest')
        require(review.get('synthetic_only') is True and review.get('no_credentials_visible') is True, 'Privacy review incomplete')
    return manifest, data


def build(run):
    manifest, data = validate(run)
    # Validate everything before changing the last known publishable replay.
    destination = ROOT / 'guided-tour/generated'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.build-') as temp:
        target = Path(temp); (target/'screenshots').mkdir()
        for step in data['steps.json']:
            shutil.copyfile(safe_file(run, step['screenshot']), target/step['screenshot'])
        for name, value in data.items():
            (target/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        public_manifest = {k:manifest[k] for k in ('schema_version','run_id','scenario','status','source','created_at','viewport')}
        public_manifest.update({'raw_manifest_sha256':sha(run/'manifest.json'),'privacy_review':'synthetic screenshots and metadata reviewed; raw video is excluded'})
        (target/'manifest.json').write_text(json.dumps(public_manifest, ensure_ascii=False, indent=2)+'\n')
        lines = ['# Generated video storyboard', '', f'Run: `{manifest["run_id"]}`. Generated from steps.json; do not edit manually.', '', '| Step ID | Screenshot | Action | Narration | Duration |', '| --- | --- | --- | --- | ---: |']
        elapsed=0; subtitles=[]
        for s in data['steps.json']:
            escape=lambda text:str(text).replace('|','\\|').replace('\n',' ')
            lines.append(f'| {s["id"]} | [Screenshot]({s["screenshot"]}) | {escape(s["operation"])} | {escape(s["narration"])} | {s["duration_hint"]} s |')
            subtitles.append({'id':s['id'],'start_hint_seconds':elapsed,'end_hint_seconds':elapsed+s['duration_hint'],'text':s['narration']});elapsed+=s['duration_hint']
        (target/'video-storyboard.md').write_text('\n'.join(lines)+'\n')
        (target/'subtitle-hints.json').write_text(json.dumps(subtitles,ensure_ascii=False,indent=2)+'\n')
        # Only this generator-owned subtree is replaced; source and vendor stay intact.
        backup=destination.with_name('.generated-previous')
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
