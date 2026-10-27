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
  self.p=loads(PACKAGE.read_text());self.r=sample();self.r.update(rid='fixture-round',group='synthetic',mapName='de_inferno',sourceCoverage={'killSlots':'complete','events':'complete'})
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
  records=registry('website',{'mode':'website_common_full','ledgers':[ledger],'aggregates':rows},batch,[],[],identities)
  self.assertEqual(len(records),20);self.assertAlmostEqual(records[0]['H2_public_formula']['value'],.791448)
  self.assertEqual(records[0]['unexplained_external_residual']['H2_community_linear_v1']['status'],'algebraically_specified_difference')
  report={'mode':'website_common_full','ledgers':[ledger],'aggregates':rows}
  wrong=copy.deepcopy(batch);wrong['rounds'][0]['round']['rid']='another'
  changed=copy.deepcopy(batch);changed['rounds'][0]['round']['facts']['0']['damage']=1000
  cases=[(report,wrong),(report,changed),({**report,'aggregates':rows[:-1]},batch),({**report,'aggregates':rows+[copy.deepcopy(rows[0])]},batch)]
  extra=copy.deepcopy(rows[0]);extra['key']=['extra'];cases.append(({**report,'aggregates':rows+[extra]},batch))
  bad=copy.deepcopy(report);bad['aggregates'][0]['evidence'][0]['ledgerSHA256']='0'*64;cases.append((bad,batch))
  for bad_report,bad_batch in cases:
   with self.assertRaises(ValueError):registry('website',bad_report,bad_batch,[],[],identities)

class DifferenceCLITests(unittest.TestCase):
 def test_changed_source_with_valid_file_hash_is_rejected(self):
  from tools.offline_rating.differences_cli import main as run
  case=PipelineTests();case.setUp()
  for f in case.r['facts'].values(): f.update(kast=True,assists=0)
  ledger=score_round(case.p,'website_common_full',case.r,[])
  identities=[{'map':case.r['map'],'steam':str(i),'season':'s','userId':str(i)} for i in range(10)]
  mapping={(v['map'],v['steam']):(v['season'],v['userId']) for v in identities}
  report={'mode':'website_common_full','ledgers':[ledger],'aggregates':aggregate([ledger],mapping)}
  batch={'rounds':[{'round':case.r,'events':[]}]}
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);sources={'report':report,'batch':batch,'references':[],'baseline':[],'identities':identities};args=['--domain','website','--output',str(root/'out')]
   for key,value in sources.items():
    path=root/key;path.write_text(json.dumps(value));args.extend(['--'+key,str(path),'--'+key+'-sha256',hashlib.sha256(path.read_bytes()).hexdigest()])
   self.assertEqual(run(args),0);(root/'out').unlink()
   changed=copy.deepcopy(batch);changed['rounds'][0]['round']['facts']['0']['damage']=1000;path=root/'batch';path.write_text(json.dumps(changed));pos=args.index('--batch-sha256')+1;args[pos]=hashlib.sha256(path.read_bytes()).hexdigest()
   self.assertEqual(run(args),2)
   path.write_text(json.dumps(batch));args[pos]=hashlib.sha256(path.read_bytes()).hexdigest()
   corruptions=[]
   missing=copy.deepcopy(report);missing['aggregates'].pop();corruptions.append(missing)
   extra=copy.deepcopy(report);v=copy.deepcopy(extra['aggregates'][0]);v['key']=['bogus'];extra['aggregates'].append(v);corruptions.append(extra)
   badlink=copy.deepcopy(report);badlink['aggregates'][0]['evidence'][0]['ledgerSHA256']='0'*64;corruptions.append(badlink)
   for value in corruptions:
    target=root/'report';target.write_text(json.dumps(value));args[args.index('--report-sha256')+1]=hashlib.sha256(target.read_bytes()).hexdigest()
    self.assertEqual(run(args),2)
   target=root/'report';target.write_text(json.dumps(report));args[args.index('--report-sha256')+1]=hashlib.sha256(target.read_bytes()).hexdigest()
   wrong=copy.deepcopy(batch);wrong['rounds'][0]['round']['rid']='another';path.write_text(json.dumps(wrong));args[pos]=hashlib.sha256(path.read_bytes()).hexdigest()
   self.assertEqual(run(args),2)

class CoverageTests(unittest.TestCase):
 def test_missing_duplicate_extra_and_outside_kills(self):
  case=PipelineTests();case.setUp();r=case.r;p=case.p
  bad=copy.deepcopy(r);del bad['sourceCoverage']
  with self.assertRaises(ValueError):score_round(p,'website_common_full',bad,[])
  kill={'kind':'kill','actor':'0','victim':'5','index':0,'tick':50,'round':1}
  e={'tick':50,'before':[5,5,0,0,0,.5,.5,.5,.5],'events':[kill],'terminalAfter':None}
  with self.assertRaises(ValueError):score_round(p,'website_common_full',r,[e])
  r['killSlots']=[{'tick':50,'actor':'0','victim':'5'}]
  with self.assertRaises(ValueError):score_round(p,'website_common_full',r,[{**e,'events':[kill,dict(kill)]}])
  with self.assertRaises(ValueError):score_round(p,'website_common_full',r,[{**e,'tick':101}])
  r['killSlots']=[];r['facts']['0']['damage']=100
  with self.assertRaises(ValueError):score_round(p,'website_common_full',r,[])
 def test_duplicate_ledger_rejected(self):
  case=PipelineTests();case.setUp();ledger=score_round(case.p,'website_common_full',case.r,[])
  with self.assertRaises(ValueError):aggregate([ledger,ledger],{})
  with tempfile.TemporaryDirectory() as d:
   rich={**ledger,'mode':'professional_rich_diagnostic'};path=Path(d)/'rich.jsonl';line=json.dumps(rich)+'\n';path.write_text(line+line)
   with self.assertRaises(ValueError):replay_rich(path,hashlib.sha256(path.read_bytes()).hexdigest())

class AdapterTests(unittest.TestCase):
 def test_missing_coverage_and_duplicate_round(self):
  from tools.offline_rating.adapters import adapt
  case=PipelineTests();case.setUp();r=case.r;r['source']='website'
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   def inventory(rounds,coverage):
    datasets={'rounds':rounds,'events':[],'playerRounds':[],'kills':[],'coverage':coverage};out={}
    for key,values in datasets.items():
     path=root/(key+'.json');path.write_text(json.dumps(values));out[key]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return out
   with self.assertRaises(ValueError):adapt(inventory([r],[]),'website')
   with self.assertRaises(ValueError):adapt(inventory([r,r],[{'rid':r['rid'],'events':'complete','killSlots':'complete'}]),'website')
