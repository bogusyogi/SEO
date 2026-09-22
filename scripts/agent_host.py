"""Bounded JSON handoff to an operator-selected existing agent, not an agent framework.

The host proposes data. It cannot grant policy or replace deterministic effect adapters.
The process is trusted operator code; this transport is NOT an OS security sandbox.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

MAX_OUTPUT = 2 * 1024 * 1024
BASE_ENV = ('PATH', 'HOME', 'USERPROFILE', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL')


def invoke(root, config, request):
    argv = config.get('argv')
    if not config.get('approval_ref') or not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x and '\x00' not in x for x in argv):
        raise ValueError('host requires an operator-approved argv list')
    if not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
        raise ValueError('host executable must be an existing absolute file; no shell resolution')
    timeout = config.get('timeout_seconds', 180)
    if type(timeout) is not int or not 1 <= timeout <= 1800:
        raise ValueError('host timeout must be within 1..1800 seconds')
    names = config.get('env_allowlist', [])
    if not isinstance(names, list) or not all(isinstance(x, str) and re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', x) for x in names):
        raise ValueError('host env_allowlist must contain environment names, not values')
    env = {key: os.environ[key] for key in (*BASE_ENV, *names) if key in os.environ}
    env['PYTHONIOENCODING'] = 'utf-8'
    encoded = json.dumps(request, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_OUTPUT:
        raise ValueError('host request exceeds 2 MiB')
    # Disk-backed output avoids unbounded capture_output allocations. Monitor both
    # streams while running and terminate on timeout/size breach. Never log stderr:
    # an agent SDK can include authentication data in errors.
    with tempfile.TemporaryDirectory(prefix='seo-agent-') as directory:
        base = Path(directory)
        (base/'request.json').write_bytes(encoded)
        with (base/'request.json').open('rb') as src, (base/'out').open('wb') as out, (base/'err').open('wb') as err:
            proc = subprocess.Popen(argv, cwd=Path(root).resolve(), env=env, stdin=src,
                                    stdout=out, stderr=err, shell=False)
            deadline = time.monotonic() + timeout
            try:
                while proc.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('agent host exceeded configured deadline')
                    if (base/'out').stat().st_size + (base/'err').stat().st_size > MAX_OUTPUT:
                        raise ValueError('agent output exceeds 2 MiB')
                    time.sleep(0.02)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
        if proc.returncode != 0:
            raise RuntimeError('agent host failed; sensitive stderr was not retained')
        if (base/'out').stat().st_size + (base/'err').stat().st_size > MAX_OUTPUT:
            raise ValueError('agent output exceeds 2 MiB')
        result = json.loads((base/'out').read_text(encoding='utf-8'))
        if not isinstance(result, dict):
            raise ValueError('host response must be a JSON object')
        return result
