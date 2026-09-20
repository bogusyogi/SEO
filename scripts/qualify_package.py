#!/usr/bin/env python3
"""Exercise a committed Git archive in a clean, SDK-free Python environment."""
from __future__ import annotations
import ast
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def validate(root):
    assert not (root / 'scripts/cms_sellright.py').exists(), 'direct backend adapter must not ship'
    versions = []
    for filename in ('.claude-plugin/plugin.json', '.codex-plugin/plugin.json'):
        manifest = json.loads((root / filename).read_text(encoding='utf-8'))
        assert manifest['name'] == 'seo' and not manifest.get('dependencies')
        versions.append(manifest['version'])
        for field in ('skills', 'mcpServers'):
            value = manifest[field]
            path = (root / value).resolve()
            assert value.startswith('./') and path.is_relative_to(root.resolve()) and path.exists(), field
    assert len(set(versions)) == 1
    for filename in ('seo.py', 'SKILL.md', 'AGENTS.md', 'docs/THIRD_PARTY_NOTICES.md', 'LICENSE',
                     'extensions/banana/scripts/generate.py', 'pdf/google-seo-reference.md',
                     'scripts/report_delivery.py', 'scripts/serp_collect.py',
                     'scripts/seo_workflow.py', 'scripts/portfolio.py', 'scripts/github_publication.py',
                     'scripts/media_assets.py', 'scripts/public_verify.py', 'scripts/outcome_jobs.py', 'scripts/agent_host.py'):
        assert (root / filename).is_file(), filename
    for path in (root / 'scripts').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = [x.name for x in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
            assert not any(name.lower().startswith('legion') for name in names), path.name


def validate_discovery(inventory, site):
    """Discovery returns canonical paths, including through platform temp aliases."""
    expected = [str(Path(site).resolve())]
    assert inventory.get('status') == 'ok', inventory
    assert inventory.get('roots') == expected, (inventory.get('roots'), expected)


def main():
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        archive = temp / 'source.zip'
        subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=zip', 'HEAD', '-o', str(archive)], check=True)
        installed = temp / 'installed'; installed.mkdir()
        with zipfile.ZipFile(archive) as source:
            source.extractall(installed)
        validate(installed)
        environment = temp / 'python'
        venv.EnvBuilder(with_pip=False).create(environment)
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        site = temp / 'site'; site.mkdir()
        home = temp / 'home'; home.mkdir()
        env = {key: value for key, value in os.environ.items() if key in {'PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT', 'LD_LIBRARY_PATH'}}
        env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home), LOCALAPPDATA=str(home),
                   SEO_RUNTIME_DIR=str(temp / 'unused-runtime'), SEO_CONFIG_DIR=str(home / 'config'), PYTHONUTF8='1')
        def run(*args, code=0):
            result = subprocess.run([str(python), str(installed / 'seo.py'), *args], cwd=site,
                                    env=env, capture_output=True, encoding='utf-8', timeout=30)
            assert result.returncode == code, result.stderr or result.stdout
            return result.stdout
        run('project', '--root', str(site), 'setup', '--domain', 'example.com', '--market', 'US', '--language', 'en')
        doctor = json.loads(run('doctor', '--root', str(site)))
        assert doctor['runtime_verified'] is False
        result = json.loads(run('run', '--root', str(site), 'tick', code=2))
        assert result['status'] == 'not_configured'
        run('closure', '--json')
        for command in ('deliver', 'serp', 'content', 'portfolio', 'workflow', 'publication', 'media'):
            run(command, '--help')
        run('cms', '--help', code=2)  # Old installations must not expose a backend write route.
        inventory = json.loads(run('portfolio', 'discover', '--root', str(site)))
        validate_discovery(inventory, site)
        workflow = json.loads(run('workflow', '--root', str(site), 'tick'))
        assert workflow['status'] == 'disabled'
        assert (site / '.seo/site.yaml').exists() and not (site / '.legion').exists()
        assert not (installed / '.seo').exists()
    print(json.dumps({'status': 'pass', 'archive': 'HEAD', 'legion_required': False,
                      'sdks_installed': False, 'network_or_credentials_used': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
