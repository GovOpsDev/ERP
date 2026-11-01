#!/usr/bin/env python3
"""Serve a byte-for-byte copy of the exact Pages artifact under a project prefix."""
import functools,http.server,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
testroot=ROOT/'.pages-test';target=testroot/'repository-name'
if testroot.exists():shutil.rmtree(testroot)
testroot.mkdir();shutil.copytree(ROOT/'_site',target)
handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(testroot))
http.server.ThreadingHTTPServer(('127.0.0.1',18767),handler).serve_forever()
