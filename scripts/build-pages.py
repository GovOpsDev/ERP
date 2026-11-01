#!/usr/bin/env python3
"""Build a static-only, allowlisted Pages artifact; never copy repository wholesale."""
import hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'_site'
SOURCE='https://github.com/GovOpsDev/ERP/blob/main/'

def build():
    if OUT.exists(): shutil.rmtree(OUT)  # generator-owned ignored output only
    OUT.mkdir()
    allowed={'index.html','README.md'}
    prefixes=('guided-tour/css/','guided-tour/js/','guided-tour/assets/vendor/','guided-tour/assets/brand/','guided-tour/assets/budget/','guided-tour/generated/','guided-tour/generated-fresh/','guided-tour/generated-bi/')
    files=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT).decode().split('\0')
    for rel in sorted(set(files)):
        if not rel or not (rel.startswith(prefixes) or rel in {'guided-tour/'+x for x in allowed}):continue
        p=ROOT/rel
        if not p.exists() and not p.is_symlink():continue  # tracked files deleted in the working tree
        if p.is_symlink() or p.suffix not in {'.html','.md','.css','.mjs','.js','.json','.png'}: raise ValueError('Disallowed Pages file: '+rel)
        dest=OUT/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    # Help remains readable on Pages; links to non-site source docs go to the repository.
    helpfile=OUT/'guided-tour/README.md'
    text=helpfile.read_text().replace('../playwright-demo/README.md',SOURCE+'playwright-demo/README.md').replace('../docs/fresh-creation-demo.md',SOURCE+'docs/fresh-creation-demo.md').replace('../docs/dashboard-bi-demo.md',SOURCE+'docs/dashboard-bi-demo.md')
    helpfile.write_text(text)
    shutil.copyfile(ROOT/'site/index.html',OUT/'index.html')
    for name in ['LICENSE','NOTICE.md']: shutil.copyfile(ROOT/name,OUT/name)
    notice=OUT/'NOTICE.md'
    notice.write_text(notice.read_text().replace('(docs/', '('+SOURCE+'docs/'))
    (OUT/'.nojekyll').touch()
    manifest={p.relative_to(OUT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.rglob('*')) if p.is_file()}
    (OUT/'site-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Pages artifact: _site/, {len(manifest)+1} public files')
if __name__=='__main__':build()
