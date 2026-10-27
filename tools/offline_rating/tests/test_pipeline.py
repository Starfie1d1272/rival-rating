import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from test_offline import sample, PACKAGE
from tools.offline_rating.heads import loads
from tools.offline_rating.pipeline import score_round, aggregate, compare_after_scoring, replay_rich
from tools.offline_rating.pipeline_cli import main

class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.p=loads(PACKAGE.read_text());self.r=sample();self.r.update(rid='fixture-round',group='synthetic',mapName='de_inferno')
  for f in self.r['facts'].values(): f['utility'].update(heDamage=0,fireDamage=0)
 def test_round_to_accounts_and_reference_join(self):
  ledger=score_round(self.p,'website_common_full',self.r,[]); rows=aggregate([ledger],{(self.r['map'],str(i)):('season',str(i)) for i in range(10)})
  self.assertEqual(len(rows),20);self.assertEqual(ledger['centerClosure'],0.)
  self.assertTrue(all(row['rating']==1 for row in rows))
  diffs=compare_after_scoring(rows,[]);self.assertTrue(all(d['reference'] is None and d['unexplained_external_residual']=='unknown' for d in diffs))
 def test_goal_ledger_and_invalid_reference(self):
  goal={'kind':'planted','actor':'5','index':0,'tick':50,'round':1};event={'tick':50,'before':[5,5,0,0,0,.5,.5,.5,.5],'events':[goal],'terminalAfter':None}
  ledger=score_round(self.p,'website_common_full',self.r,[event]);self.assertEqual(len(ledger['goalEvents']),1);self.assertGreater(ledger['goalEvents'][0]['executionValue'],0)
  self.assertAlmostEqual(sum(sum(c.values()) for c in ledger['components'].values()),0.)
  wider={**event,'before':event['before']+[0.]*31}; self.assertEqual(score_round(self.p,'website_common_full',self.r,[wider])['components'],ledger['components'])
  r=copy.deepcopy(self.r);r['RatingPro']=1
  with self.assertRaises(ValueError):score_round(self.p,'website_common_full',r,[])
 def test_rich_hash_and_cli_tamper(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'input.json';out=root/'out.json';source.write_text(json.dumps({'schema':'rr-offline-round-batch-v1','rounds':[{'round':self.r,'events':[]}]}))
   identity=root/'identity.json';identity.write_text(json.dumps([{'map':self.r['map'],'steam':str(i),'season':'s','userId':str(i)} for i in range(10)]))
   h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
   args=['--mode','website_common_full','--input',str(source),'--input-sha256',h(source),'--parameters',str(PACKAGE),'--parameters-sha256',h(PACKAGE),'--output',str(out),'--identity-map',str(identity),'--identity-sha256',h(identity)]
   self.assertEqual(main(args),0);self.assertEqual(json.loads(out.read_text())['schema'],'rr-offline-report-v1')
   source.write_text(source.read_text()+' ');out.unlink();self.assertEqual(main(args),2)
   with self.assertRaises(ValueError):replay_rich(source,'0'*64)
 def test_unknown_oof_and_duplicate_rounds(self):
  with self.assertRaises(ValueError):score_round(self.p,'professional_common_oof',self.r,[])

class DifferenceTests(unittest.TestCase):
 def test_arithmetic_reference_and_missing(self):
  from tools.offline_rating.differences import registry
  case=PipelineTests();case.setUp()
  for f in case.r['facts'].values():f.update(kast=True,assists=0)
  ledger=score_round(case.p,'website_common_full',case.r,[])
  identities={(case.r['map'],str(i)):('s',str(i)) for i in range(10)}
  rows=aggregate([ledger],identities);batch={'rounds':[{'round':case.r,'events':[]}]}
  records=registry('website',{'aggregates':rows},batch,[],[],identities)
  self.assertEqual(len(records),20);self.assertAlmostEqual(records[0]['H2_public_formula']['value'],.791448)
  self.assertEqual(records[0]['unexplained_external_residual']['H2_community_linear_v1']['status'],'algebraically_specified_difference')
