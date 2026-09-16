"""Explicit isolated dependency setup; importing/installing a skill never runs pip."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path


def runtime_dir():
    return Path(os.environ.get('SEO_RUNTIME_DIR', str(Path.home()/'.local/share/seo/runtime'))).expanduser().resolve()


def python_executable():
    root=runtime_dir();candidate=root/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    return str(candidate) if candidate.is_file() else sys.executable


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--install-deps',action='store_true');ap.add_argument('--browser',action='store_true')
    a=ap.parse_args()
    if a.browser and not a.install_deps:
        ap.error('--browser requires explicit --install-deps')
    if a.install_deps:
        root=runtime_dir();venv.EnvBuilder(with_pip=True).create(root)
        subprocess.run([python_executable(),'-m','pip','install','-r',str(Path(__file__).resolve().parent.parent/'requirements.txt')],check=True)
        if a.browser:
            subprocess.run([python_executable(),'-m','playwright','install','chromium'],check=True)
    print(json.dumps({'runtime':str(runtime_dir()),'python':python_executable(),'dependencies_installed_this_run':a.install_deps},indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
