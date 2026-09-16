import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
from seo_prioritize import prioritize

class PrioritizationTests(unittest.TestCase):
    def test_no_evidence_is_not_pass(self):
        self.assertEqual(prioritize({})['primary_action']['action'],'collect_baseline')
    def test_broken_measurement_precedes_copy(self):
        latest={'gsc':{'job_id':'g','job_state':'failed','updated':time.time(),'result':{'error':'access denied'}},'crawl':{'job_id':'c','job_state':'succeeded','updated':time.time(),'result':{'issues':[{'target':'https://example.com','observed':'duplicate_title','severity':'medium'}]}}}
        self.assertEqual(prioritize(latest)['primary_action']['action'],'restore_measurement')
    def test_opportunity_remains_hypothesis_not_permission(self):
        latest={'gsc':{'job_id':'g','job_state':'succeeded','updated':time.time(),'result':{'data':{'rows':[{'query':'tool','page':'https://example.com','impressions':500,'position':8}]}}}}
        result=prioritize(latest)['primary_action']
        self.assertEqual(result['claim_state'],'hypothesis');self.assertEqual(result['effect'],'none')
    def test_stale_data_not_actionable_opportunity(self):
        latest={'gsc':{'job_id':'g','job_state':'succeeded','updated':0,'result':{'rows':[{'query':'tool','page':'https://example.com','impressions':500,'position':8}]}}}
        self.assertEqual(prioritize(latest)['primary_action']['action'],'refresh_stale_evidence')
if __name__=='__main__':unittest.main()
