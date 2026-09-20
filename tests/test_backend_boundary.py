"""A site backend provider is not an SEO publishing API, including for old state."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import remote_actions as actions
import portfolio
import seo_workflow
from seo_project import setup_project, save_site
from seo_state import atomic_json
from site_policy import authorize, load


class BackendBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = setup_project(self.root, domain='example.com', market='US', language='en')
        self.site['policy'] = {'mode': 'approved', 'approval_ref': 'operator-fixture',
            'allowed_actions': ['draft', 'publish', 'metadata', 'deliver', 'deploy', 'merge', 'cms_read'],
            'write_prefixes': ['content']}
        # Old configuration must not restore the removed capability or block reads.
        self.site['cms'] = {'provider': 'sellright', 'api_origin': 'https://api.example.com',
            'store_slug': 'example', 'store_id': 'old-store', 'token_env': 'SEO_CMS_TOKEN',
            'allow_non_atomic_updates': True, 'unexpected_secret': 'PRIVATE_SENTINEL'}
        save_site(self.site, self.root)

    def legacy(self, state='approved', kind='cms'):
        row = {'schema_version': 1, 'id': 'old-action', 'site': 'example.com', 'kind': kind,
            'config_digest': actions.digest(load(self.root)), 'payload': {'operation': 'create'},
            'evidence': 'historical-fixture', 'state': state, 'approval': None,
            'created_at': '2026-09-17T00:00:00+00:00'}
        row['request_sha256'] = actions.fingerprint(row)
        if state != 'proposed':
            row['approval'] = {'digest': row['request_sha256'], 'reference': 'old-approval'}
        if state in {'succeeded', 'partial'}:
            row['receipt'] = {'kind': 'sellright_blog_readback', 'status': 'accepted'}
        path = actions.path_for(self.root, row['id'])
        atomic_json(path, row)
        return row, path, path.read_bytes()

    def test_direct_adapter_is_not_shipped(self):
        self.assertFalse((ROOT / 'scripts/cms_sellright.py').exists())

    def test_cms_cli_is_not_advertised(self):
        result = subprocess.run([sys.executable, str(ROOT/'seo.py'), '--help'],
            capture_output=True, encoding='utf-8', cwd=self.root, timeout=10,
            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('cms_sellright', result.stdout)
        self.assertNotIn('  cms ', result.stdout)
        self.assertIn('publication', result.stdout)

    def test_old_cms_command_is_rejected_even_with_credentials(self):
        with patch.dict(os.environ, {'SEO_CMS_TOKEN': 'PRIVATE_SENTINEL'}):
            result = subprocess.run([sys.executable, str(ROOT/'seo.py'), 'cms', '--help'],
                capture_output=True, encoding='utf-8', cwd=self.root, timeout=10,
                env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 2)
        self.assertIn('Unknown SEO command', result.stderr)
        self.assertNotIn('PRIVATE_SENTINEL', result.stdout + result.stderr)

    def test_remote_kind_allowlist_has_no_delivery_fallback(self):
        for kind in ('cms', 'sellright', 'unknown', '', None):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                actions.action_for(kind, {})

    def test_supported_remote_actions_keep_their_own_authority(self):
        self.assertEqual(actions.action_for('delivery', {}), 'deliver')
        self.assertEqual(actions.action_for('repository', {'operation': 'merge'}), 'merge')
        self.assertEqual(actions.action_for('repository', {'operation': 'submit'}), 'deploy')

    def test_new_backend_proposal_is_rejected_without_an_artifact(self):
        with self.assertRaises(ValueError):
            actions.propose(self.root, 'new-action', 'cms', {'operation': 'create'}, 'review')
        self.assertFalse(actions.path_for(self.root, 'new-action').exists())

    def test_old_backend_proposal_cannot_be_approved(self):
        row, path, original = self.legacy('proposed')
        with self.assertRaises(ValueError):
            actions.approve(self.root, row['id'], row['request_sha256'], 'new-approval')
        self.assertEqual(path.read_bytes(), original)

    def test_old_backend_actions_never_execute_or_return_success(self):
        for state in ('approved', 'running', 'uncertain', 'succeeded', 'partial'):
            row, path, original = self.legacy(state)
            operation, preflight = Mock(), Mock()
            with self.subTest(state=state), self.assertRaises(ValueError):
                actions.execute(self.root, row['id'], 'cms', operation, preflight=preflight)
            operation.assert_not_called(); preflight.assert_not_called()
            self.assertEqual(path.read_bytes(), original)

    def test_unknown_saved_kind_cannot_execute_as_delivery(self):
        row, path, original = self.legacy(kind='unknown')
        operation = Mock(return_value={'status': 'accepted', 'kind': 'fixture'})
        with self.assertRaises(ValueError):
            actions.execute(self.root, row['id'], 'unknown', operation)
        operation.assert_not_called(); self.assertEqual(path.read_bytes(), original)

    def test_legacy_receipts_remain_readable_and_unchanged(self):
        row, path, original = self.legacy('succeeded')
        self.assertEqual(actions.read(self.root, row['id']), row)
        self.assertEqual(path.read_bytes(), original)

    def test_backend_read_capability_cannot_be_revived_by_old_policy(self):
        with self.assertRaises(PermissionError):
            authorize(load(self.root), 'cms_read')

    def test_old_backend_config_does_not_block_site_discovery(self):
        result = portfolio.discover([self.root])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['roots'], [str(self.root.resolve())])
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_old_backend_config_does_not_export_secrets_or_claim_readiness(self):
        result = portfolio.readiness(self.root)
        self.assertIsNone(result['deployment_provider'])
        self.assertNotIn('cms', result)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_agent_request_explicitly_forbids_direct_backend_writes(self):
        task = seo_workflow.enqueue(self.root, target='https://example.com/page', kind='metadata',
            issue='missing title', evidence={'source': 'fixture'})
        row = {'id': task['id'], 'target': 'https://example.com/page', 'hypothesis': 'missing title',
            'workflow': {'kind': 'metadata', 'evidence': {'source': 'fixture'}}}
        request = seo_workflow.host_request(self.root, row)
        self.assertIn('Do not call SellRight APIs', request['instructions'])
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(request))
        self.assertNotIn('SEO_CMS_TOKEN', json.dumps(request))

    def test_runtime_contains_no_backend_endpoint_or_adapter_import(self):
        for path in [ROOT/'seo.py', *(ROOT/'scripts').glob('*.py')]:
            text = path.read_text(encoding='utf-8')
            with self.subTest(path=path.name):
                self.assertNotIn('/v1/admin/blog', text)
                for node in ast.walk(ast.parse(text)):
                    if isinstance(node, ast.Import):
                        self.assertNotIn('cms_sellright', [x.name for x in node.names])
                    elif isinstance(node, ast.ImportFrom):
                        self.assertNotEqual(node.module, 'cms_sellright')


if __name__ == '__main__':
    unittest.main()
