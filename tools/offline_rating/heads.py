"""Public head inference. Runtime dependencies: Python standard library json/math only.
Input x is the documented ordered retrospective website feature vector.
Unknown maps produce all-zero one-hot before standardization, matching original.
"""
import json
import math
SCHEMA='rr-common-heads-v1'
FIXED_FEATURES={'HP': ['ownIsCT', 'actorStartGear10k', 'ownStartGear10k', 'enemyStartGear10k', 'gearDifference10k', 'duration120', 'exposure120', 'kills5', 'deaths', 'flashAssists5'], 'life': ['ownIsCT', 'ownAlive5', 'enemyAlive5', 'aliveDifference5', 'inverseOwnAlive', 'inverseEnemyAlive', 'planted', 'elapsed120', 'bombElapsed40', 'ownStartGear10k', 'enemyStartGear10k', 'ownAliveStartGear10k', 'enemyAliveStartGear10k', 'actorStartGear10k', 'victimStartGear10k', 'ownKillsThisTick5', 'enemyKillsThisTick5', 'ownAliveAfterKills5', 'enemyAliveAfterKills5'], 'plant': ['ownIsCT', 'ownAlive5', 'enemyAlive5', 'aliveDifference5', 'planted', 'elapsed120', 'bombElapsed40', 'ownStartGear10k', 'enemyStartGear10k', 'ownAliveStartGear10k', 'enemyAliveStartGear10k', 'actorStartGear10k'], 'defuse': ['ownIsCT', 'ownAlive5', 'enemyAlive5', 'aliveDifference5', 'planted', 'elapsed120', 'bombElapsed40', 'ownStartGear10k', 'enemyStartGear10k', 'ownAliveStartGear10k', 'enemyAliveStartGear10k', 'actorStartGear10k'], 'enemyFlash': ['ownIsCT', 'actorStartGear10k', 'ownStartGear10k', 'enemyStartGear10k', 'gearDifference10k', 'duration120', 'exposure120', 'kills5', 'deaths'], 'friendlyFlash': ['ownIsCT', 'actorStartGear10k', 'ownStartGear10k', 'enemyStartGear10k', 'gearDifference10k', 'duration120', 'exposure120', 'kills5', 'deaths']}
def finite_number(x):
 if isinstance(x,bool) or not isinstance(x,(int,float)):return False
 try:return math.isfinite(x)
 except OverflowError:return False
def finite_tree(value):
 if isinstance(value,float) and not math.isfinite(value):raise ValueError('NaN/Inf rejected')
 if isinstance(value,dict):
  for v in value.values():finite_tree(v)
 elif isinstance(value,list):
  for v in value:finite_tree(v)
def vector(v,n,label):
 if not isinstance(v,list) or len(v)!=n:raise ValueError(label+' dimension mismatch')
 if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in v):raise ValueError(label+' must contain finite numbers')
def validate_package(p):
 expected={'schema','description','features','heads','folds','gamma','scale','centerRule','unknownMapRule','provenance'}
 if not isinstance(p,dict) or set(p)!=expected or p.get('schema')!=SCHEMA:raise ValueError('unknown package schema')
 finite_tree(p)
 if not finite_number(p['scale']) or p['scale']<=0:raise ValueError('scale must be finite positive number, not bool')
 if not isinstance(p['gamma'],dict) or set(p['gamma'])!={'full','0','1','2','3','4'}:raise ValueError('gamma keys mismatch')
 if any(not finite_number(v) or not 0<=v<=1 for v in p['gamma'].values()):raise ValueError('gamma must be finite in [0,1], not bool')
 if set(p['features'])!={'HP','life','plant','defuse','enemyFlash','friendlyFlash'}:raise ValueError('unknown feature schema')
 for kind,names in FIXED_FEATURES.items():
  if [v['name'] for v in p['features'][kind]]!=names:raise ValueError('fixed feature schema mismatch')
 if set(p['heads'])!={k+'/'+fold for k in p['features'] for fold in ['full','0','1','2','3','4']}:raise ValueError('head set mismatch')
 fields={'kind','features','vocab','mean','scale','coef','intercept','bound','doseScale','mix','alpha','sourceFile','sourceSHA256','sourceHeadSHA256'}
 for key,h in p['heads'].items():
  if set(h)!=fields or h['kind'] not in ['poisson','bounded-logit','nonnegative-exposure-mixture']:raise ValueError('unknown head schema')
  expected_kind={'HP':'poisson','life':'bounded-logit','plant':'bounded-logit','defuse':'bounded-logit','enemyFlash':'nonnegative-exposure-mixture','friendlyFlash':'poisson'}[key.split('/')[0]]
  if h['kind']!=expected_kind:raise ValueError('head kind incompatible with feature schema')
  if isinstance(h['intercept'],bool) or not isinstance(h['intercept'],(int,float)) or not math.isfinite(h['intercept']):raise ValueError('invalid intercept')
  if not finite_number(h['alpha']) or h['alpha']<0:raise ValueError('alpha must be finite nonnegative number, not bool')
  names=FIXED_FEATURES[key.split('/')[0]]
  if h['features']!=names:raise ValueError('feature order mismatch')
  if len(h['vocab'])!=len(set(h['vocab'])) or not all(isinstance(v,str) for v in h['vocab']):raise ValueError('invalid map vocabulary')
  n=len(names)+len(h['vocab'])
  for k in ['mean','scale','coef']:vector(h[k],n,k)
  if any(x<=0 for x in h['scale']):raise ValueError('invalid scaler scale')
  expected_bound={'life':.5,'plant':1.,'defuse':1.}.get(key.split('/')[0])
  if expected_bound is None:
   if h['bound'] is not None:raise ValueError('non-bounded head bound must be null')
  elif not finite_number(h['bound']) or h['bound']!=expected_bound:raise ValueError('fixed bound mismatch')
  if h['kind']=='nonnegative-exposure-mixture':
   vector(h['doseScale'],3,'doseScale');vector(h['mix'],3,'mix')
   if any(x<=0 for x in h['doseScale']) or any(x<0 for x in h['mix']) or abs(sum(h['mix'])-1)>1e-12:raise ValueError('invalid exposure mixture')
 for key,g in p['folds']['headGroups'].items():
  if set(g['trainingGroups'])&set(g['validationGroups']):raise ValueError('training validation overlap')
 if set(p['folds']['headGroups'])!=set(p['heads']):raise ValueError('fold head set mismatch')
 return p
def unique_object(pairs):
 result={}
 for key,value in pairs:
  if key in result:raise ValueError('duplicate JSON key: '+key)
  result[key]=value
 return result
def loads(text):return validate_package(json.loads(text,object_pairs_hook=unique_object,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON'))))
def sigmoid(x):
 if x>=0:return 1/(1+math.exp(-x))
 e=math.exp(x);return e/(1+e)
def infer(p,kind,fold,x,map_name,dose=1.):
 if p.get('schema')!=SCHEMA:raise ValueError('unknown schema')
 if not isinstance(map_name,str):raise ValueError('map must be a string')
 h=p['heads'][kind+'/'+str(fold)];vector(x,len(h['features']),'input')
 raw=x+[float(map_name==v) for v in h['vocab']]
 z=[(v-m)/s for v,m,s in zip(raw,h['mean'],h['scale'])]
 eta=h['intercept']+sum(v*c for v,c in zip(z,h['coef']))
 if not math.isfinite(eta):raise ValueError('nonfinite linear predictor')
 if h['kind']=='nonnegative-exposure-mixture':
  vector(dose,3,'dose')
  if any(v<0 for v in dose):raise ValueError('negative exposure')
  exposure=sum(v/s*w for v,s,w in zip(dose,h['doseScale'],h['mix']))
 else:
  if isinstance(dose,bool) or not isinstance(dose,(int,float)) or not math.isfinite(dose) or dose<0:raise ValueError('invalid dose')
  exposure=dose
 try:unit=h['bound']*sigmoid(eta) if h['kind']=='bounded-logit' else math.exp(eta)
 except OverflowError as e:raise ValueError('exponential overflow; input outside numeric domain') from e
 if h['kind']!='bounded-logit' and unit==0.:raise ValueError('exponential underflow; input outside numeric domain')
 result=exposure*unit
 if not math.isfinite(result):raise ValueError('nonfinite output')
 return result
