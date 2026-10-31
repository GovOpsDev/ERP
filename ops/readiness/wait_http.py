#!/usr/bin/env python3
"""Bounded HTTP startup readiness; rendered UI acceptance remains separate."""
import argparse,time,urllib.request
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:18069/web/login');p.add_argument('--seconds',type=int,default=60);a=p.parse_args()
end=time.monotonic()+a.seconds
while time.monotonic()<end:
    try:
        with urllib.request.urlopen(a.url,timeout=5) as r:
            if r.status==200 and r.read():print('HTTP_STARTUP_READY');break
    except Exception:pass
    time.sleep(0.5)
else:raise SystemExit('HTTP startup deadline exceeded')
