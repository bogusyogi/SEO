#!/usr/bin/env python3
"""Resolve an explicitly installed SEO interpreter without auto-installing anything."""
import os
import sys
from pathlib import Path
candidate = os.environ.get('SEO_PYTHON')
if not candidate:
    default = Path.home()/'.local/share/seo/runtime'/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    candidate = str(default) if default.is_file() else sys.executable
script = Path(__file__).resolve().with_name('seo_mcp.py')
os.execv(candidate, [candidate, str(script)])
