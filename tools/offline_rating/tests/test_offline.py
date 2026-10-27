import copy
import json
from pathlib import Path
import tempfile
import unittest
from tools.offline_rating.contracts import validate_round
from tools.offline_rating.evidence import check_derived_hurt_bookkeeping
from tools.offline_rating.heads import infer, loads
from tools.offline_rating.integrity import fold_evidence, verify_files
from tools.offline_rating.objective_context import make_context, allocate_objective

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'tools/offline_rating'
PACKAGE=BASE/'parameters/common-heads-v1.json'

def sample():
    players=[{'steam':str(i),'side':'ct' if i<5 else 't','startGear':1000} for i in range(10)]
    fact={'kills':0,'deaths':0,'damage':0,'utility':{'flashAssists':0,'enemyBlindSeconds':0,'enemyBlindVictims':0,'teamBlindSeconds':0}}
    return {'map':'de_inferno','round':1,'players':players,'facts':{p['steam']:copy.deepcopy(fact) for p in players},'killSlots':[],'freeze':10,'end':100,'rate':64}

class OfflineTests(unittest.TestCase):
    def test_golden_all_heads_known_and_unknown_maps(self):
        p=loads(PACKAGE.read_text()); fixture=json.loads((BASE/'tests/fixtures/synthetic-head-cases.json').read_text()); seen=set()
        for c in fixture['cases']:
            self.assertAlmostEqual(infer(p,c['kind'],c['fold'],c['x'],c['map'],c['dose']),c['expected'],delta=fixture['absoluteTolerance'])
            seen.add((c['kind'],c['fold'],c['map']=='__unknown_map__'))
        self.assertEqual(len(seen),72)
    def test_duplicate_json_and_invalid_vector(self):
        with self.assertRaises(ValueError): loads('{"schema":1,"schema":2}')
        p=loads(PACKAGE.read_text())
        with self.assertRaises(ValueError): infer(p,'HP','full',[float('nan')]*10,'x')
        with self.assertRaises(ValueError): infer(p,'HP','full',[1]*9,'x')
    def test_contract_rejects_missing_duplicate_invalid_rate(self):
        for mutation in ('missing','duplicate','rate','nonfinite'):
            r=sample()
            if mutation=='missing': del r['facts']['0']['utility']['flashAssists']
            if mutation=='duplicate': r['players'][1]['steam']='0'
            if mutation=='rate': r['rate']=0
            if mutation=='nonfinite': r['players'][0]['startGear']=float('nan')
            with self.assertRaises((ValueError,KeyError)): validate_round(r)
    def test_objective_single_context_and_same_tick_unknown(self):
        r=sample(); kill={'kind':'kill','actor':'5','victim':'1','index':0}; goal={'kind':'planted','actor':'0','index':0}
        e={'tick':50,'before':[5,5,0,0,0,0.5,0.5,0.5,0.5],'events':[kill,goal]}
        c=make_context(r,e,goal,'synthetic'); self.assertEqual(c.orderEvidence['crossTypeOrder'],'unknown')
        self.assertEqual(allocate_objective(0.5,c,r)['N'],5)
        hypothetical=make_context(r,e,goal,'synthetic',[kill]);self.assertEqual(allocate_objective(0.5,hypothetical,r)['N'],4)
        with self.assertRaises(ValueError): make_context(r,{**e,'tick':101},goal,'synthetic')
        with self.assertRaises(ValueError): make_context(r,e,goal,'synthetic',[{'kind':'kill','victim':'2'}])
    def test_derived_hp_does_not_prove_order(self):
        result=check_derived_hurt_bookkeeping([{'roundNumber':1,'victimIndex':1,'healthDamageRaw':4,'victimHealthBefore':100,'healthDamage':4}])
        self.assertTrue(result['bookkeepingConsistent']); self.assertEqual(result['actualSameTickOrder'],'unknown')
    def test_fold_missing_and_overlap(self):
        p=loads(PACKAGE.read_text()); self.assertEqual(fold_evidence(p)['labelOrigin'],'unverified')
        self.assertEqual(fold_evidence({'folds':{}})['routing'],'unverified')
        p['folds']['teacherOuter'][0]['trainingGroups'].append(p['folds']['teacherOuter'][0]['validationGroups'][0])
        with self.assertRaises(ValueError): fold_evidence(p)
    def test_hash_tampering(self):
        manifest=json.loads((BASE/'parameters/integrity-v1.json').read_text());self.assertTrue(verify_files(ROOT,manifest))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_text('wrong')
            with self.assertRaises(ValueError): verify_files(d,{'x':'0'*64})

if __name__=='__main__': unittest.main()
