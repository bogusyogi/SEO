import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from external_audit import normalize
from seo_runtime import init_site

class ExternalAuditTests(unittest.TestCase):
    def test_unknown_export_is_not_pass(self):
        self.assertEqual(normalize({'hello':'world'},'seomator','fixture')['status'],'failed')
    def test_lighthouse_manual_is_unmeasured(self):
        r=normalize({'finalUrl':'https://example.com','audits':{'test':{'score':None,'scoreDisplayMode':'manual','title':'Manual check'}}},'lighthouse','fixture')
        self.assertEqual(r['findings'][0]['status'],'not_testable')
        self.assertFalse(r['coverage']['site_complete'])
    def test_legacy_zero_weight_warning_is_not_measured(self):
        r=normalize({'results':[{'ruleId':'x','status':'warn','weight':0}]},'seomator','fixture')
        self.assertEqual(r['findings'][0]['status'],'not_testable')

class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_discovers_and_calls_same_runtime(self):
        try:
            from mcp import Client
            from seo_mcp import build_server
        except (ImportError,SystemExit):
            self.skipTest('MCP SDK unavailable; integration CI installs it')
        with tempfile.TemporaryDirectory() as td:
            init_site(td,'example.com','IN','en')
            async with Client(build_server(td)) as client:
                tools=await client.list_tools()
                names={t.name for t in tools.tools}
                self.assertIn('seo_status',names)
                self.assertIn('seo_propose',names)
                self.assertNotIn('seo_approve',names)
                result=await client.call_tool('seo_status',{})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content['site'],'example.com')

if __name__=='__main__': unittest.main()
