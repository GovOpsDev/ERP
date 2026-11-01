#!/usr/bin/env python3
"""Audit tracked AND untracked files without printing secret values. No uploads."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ('playwright-demo/output/', 'video/output/', '_site/', '.pages-test/')
SKIP = {'.git', 'node_modules', '__pycache__', '.venv'}
PATTERNS = {
    'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'service-token': r'(?:ghp_|github_pat_|sk_live_)[A-Za-z0-9_]{20,}',
    'credential-url': r'(?i)(?:postgres(?:ql)?|mysql)://[^\s:/]+:[^\s@]+@',
    'literal-credential': r'''(?i)(?:password|passwd|api_key|secret|token)\s*["']?\s*[:=]\s*["'][^"'\n]{3,}["']''',
    'temporary-tunnel': r'https://[^\s/]+\.trycloudflare\.com',
}

def audit(root=ROOT):
    tracked=set(subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0'))
    results=[]; excluded={}; count=0; email_files=[]; private_paths=[]
    for directory, dirs, files in os.walk(root):
        dirs[:]=[d for d in dirs if d not in SKIP]
        for name in files:
            p=Path(directory)/name; rel=p.relative_to(root).as_posix()
            if p.is_symlink():
                results.append({'file':rel,'rule':'symlink'});continue
            if rel.startswith(PRIVATE):
                if rel in tracked: results.append({'file':rel,'rule':'tracked-private-output'})
                excluded[rel.split('/')[0]+'/'+rel.split('/')[1]]=excluded.get(rel.split('/')[0]+'/'+rel.split('/')[1],0)+1
                continue
            count+=1
            if (name.startswith('.env') and name!='.env.example') or p.suffix.lower() in {'.webm','.mp4','.zip','.dump','.sql','.pem','.key','.p12','.pfx'} or any(x in p.parts for x in ('filestore','sessions','.auth')):
                results.append({'file':rel,'rule':'private-file-type'})
            if p.stat().st_size>10*1024*1024: results.append({'file':rel,'rule':'large-file'})
            try: text=p.read_text(encoding='utf-8')
            except UnicodeError: continue
            for rule,pattern in PATTERNS.items():
                for m in re.finditer(pattern,text): results.append({'file':rel,'line':text.count('\n',0,m.start())+1,'rule':rule})
            if re.search(r'"cookies"\s*:\s*\[',text) and re.search(r'"origins"\s*:',text): results.append({'file':rel,'rule':'browser-storage-state'})
            public=rel=='README.md' or rel.startswith(('guided-tour/','site/','video/'))
            if re.search(r'/home/[^/\s]+/',text):
                (results if public else private_paths).append({'file':rel,'rule':'home-path'})
            if rel=='README.md' and re.search(r'https?://(?:localhost|127\.0\.0\.1)',text): results.append({'file':rel,'rule':'public-readme-localhost'})
            if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text): email_files.append(rel)
    review=root/'docs/public-visual-review.json'
    if review.exists():
        reviewed=json.loads(review.read_text())['files']
        covered={entry['file'] for entry in reviewed}
        for rel in tracked:
            if (root/rel).is_file() and rel.endswith(('.png','.jpg')) and rel not in covered:
                results.append({'file':rel,'rule':'visual-review-missing'})
        for entry in reviewed:
            image=root/entry['file']
            if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest()!=entry['sha256']:
                results.append({'file':entry['file'],'rule':'visual-review-hash-changed'})
    return {'status':'FAIL' if results else 'PASS','files_scanned':count,'findings':results,'excluded_private_files':excluded,'reviewed_categories':{'email_files':email_files,'developer_path_files':private_paths},'limits':'Heuristic content/file scan plus separate visual review. Ignored private outputs inventoried, not published; dependencies and Git object storage excluded.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path);args=parser.parse_args();r=audit()
    if args.report: args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(r,indent=2)+'\n')
    print(f"{r['status']}: {r['files_scanned']} source/public files, {len(r['findings'])} blocking findings, private outputs inventoried separately")
    for x in r['findings']: print(json.dumps(x))
    raise SystemExit(r['status']!='PASS')
