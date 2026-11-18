#!/usr/bin/env python3
"""Package only the new multi-round outputs; never rewrite old v4 evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def main():
    p=argparse.ArgumentParser(); p.add_argument('--run-dir', type=Path, required=True)
    args=p.parse_args()
    out=args.run_dir.resolve()
    if not out.is_dir() or not (out/'MULTIROUND_ANALYSIS.json').is_file():
        p.error('missing analyzed multi-round results')
    entries=[]
    for x in sorted(out.rglob('*')):
        if x.is_file() and x.name!='SHA256SUMS':
            entries.append((x.relative_to(out).as_posix(),hashlib.sha256(x.read_bytes()).hexdigest()))
    (out/'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name,digest in entries))
    archive=out.with_suffix('.zip')
    if archive.exists():
        p.error('refusing to overwrite existing archive')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for x in sorted(out.rglob('*')):
            if x.is_file():
                z.write(x, arcname=f'{out.name}/{x.relative_to(out)}')
    print(json.dumps({'archive':str(archive),'files':len(entries)+1,'bytes':archive.stat().st_size}))

if __name__ == '__main__': main()
