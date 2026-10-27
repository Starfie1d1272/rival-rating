"""Explicit common objective contract. No claim about actual same-tick order."""
from dataclasses import dataclass,asdict
import hashlib,json
from .features import objective as objective_features
from .contracts import validate_event, validate_round
@dataclass(frozen=True)
class ObjectiveContext:
 sourceEventKeys: tuple
 atomicTick: int
 statePhase: str
 aliveIds: tuple
 aliveCounts: dict
 actor: str
 actorAlive: bool
 commonFeatureState: tuple
 orderEvidence: dict
 selectedKillKeys: tuple
 anomalies: tuple
 def payload(self):
  return asdict(self)
 def context_hash(self):
  return hashlib.sha256(json.dumps(self.payload(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
 def record(self):return dict(**self.payload(),contextSHA256=self.context_hash())
 @property
 def valid(self):return self.actorAlive and not self.anomalies
 def own_count(self,r):return self.aliveCounts[next(p['side'] for p in r['players'] if p['steam']==self.actor)]
 def features(self,r):
  if not self.valid: raise ValueError('invalid objective context')
  allocate_objective(0, self, r)
  return objective_features(r,{'before':list(self.commonFeatureState)},self.actor)
def event_key(r,e,k,domain):
 return dict(domain=domain,map=r['map'],round=r['round'],tick=e['tick'],kind=k['kind'],sourceTypeIndex=k.get('index'),actor=k.get('actor'),victim=k.get('victim'))
def make_context(r,e,goal,domain,selected_kills=()):
 validate_event(r,e,goal,selected_kills)
 ps={p['steam']:p for p in r['players']};alive=set(ps);anomalies=[]
 for i,k in sorted(enumerate(r['killSlots']),key=lambda v:(v[1]['tick'],v[0])):
  if k['tick']>=e['tick']:continue
  victim=k.get('victim');key=dict(sourceRoundSlot=i,tick=k['tick'],victim=victim,actor=k.get('actor'))
  if victim not in ps:anomalies.append(dict(reason='unknown_prior_kill_victim',source=key));continue
  if victim not in alive:anomalies.append(dict(reason='duplicate_prior_death',source=key))
  alive.discard(victim)
 counts={s:sum(ps[p]['side']==s for p in alive) for s in ['ct','t']}
 state=list(e['before'][:9])
 for i,s in enumerate(['ct','t']):
  if counts[s]!=state[i]:anomalies.append(dict(reason='before_alive_count_mismatch',side=s,replayed=counts[s],sourceBefore=state[i]))
  gear=sum(ps[p]['startGear'] for p in alive if ps[p]['side']==s)/10000
  if abs(gear-state[7+i])>1e-10:anomalies.append(dict(reason='before_alive_gear_mismatch',side=s,replayed=gear,sourceBefore=state[7+i]))
 # Subset is a hypothetical chronology, never a guessed actual order.
 for k in selected_kills:
  victim=k.get('victim')
  if victim not in ps:anomalies.append(dict(reason='unknown_selected_kill_victim',victim=victim));continue
  if victim not in alive:anomalies.append(dict(reason='selected_victim_not_alive',victim=victim));continue
  alive.remove(victim);side=ps[victim]['side'];i=0 if side=='ct' else 1;state[i]-=1;state[7+i]-=ps[victim]['startGear']/10000
 counts={s:sum(ps[p]['side']==s for p in alive) for s in ['ct','t']}
 if goal['kind']=='planted' and state[2]!=0:anomalies.append(dict(reason='plant_pre_state_already_planted'))
 if goal['kind']=='defused' and state[2]!=1:anomalies.append(dict(reason='defuse_pre_state_not_planted'))
 actor=goal.get('actor')
 if actor not in ps:anomalies.append(dict(reason='unknown_goal_actor',actor=actor))
 same=[k for k in e['events'] if k['kind']=='kill']
 return ObjectiveContext(tuple(event_key(r,e,k,domain) for k in e['events']),e['tick'],'atomic_group_start' if not selected_kills else 'hypothetical_selected_kills_before_objective',tuple(sorted(alive)),counts,actor,actor in alive,tuple(state),dict(crossTypeOrder='unknown',globalSequenceAvailable=False,knownBeforeRule='all source kills with kill.tick strictly less than atomic tick, including world/self/friendly',sameTickKillCount=len(same),interpretation='model sensitivity only; no inferred actual ordering'),tuple(event_key(r,e,k,domain) for k in selected_kills),tuple(anomalies))

def allocate_objective(team_goal, context, r):
 """Use one explicit context for execution share; never infer a true ordering."""
 import math
 if isinstance(team_goal,bool) or not isinstance(team_goal,(int,float)) or not math.isfinite(team_goal) or team_goal<0:
  raise ValueError('team goal value must be finite and nonnegative, not bool')
 validate_round(r)
 if not context.valid:
  raise ValueError('invalid objective context: actor dead/unresolved or source mismatch')
 ps={p['steam']:p for p in r['players']};alive=set(context.aliveIds)
 if len(alive)!=len(context.aliveIds) or not alive<=set(ps) or context.actor not in alive:
  raise ValueError('objective alive identities are inconsistent')
 if context.orderEvidence.get('crossTypeOrder')!='unknown':
  raise ValueError('this contract has no independent cross-type order evidence')
 for i,side in enumerate(['ct','t']):
  count=sum(ps[s]['side']==side for s in alive)
  if context.aliveCounts.get(side)!=count or context.commonFeatureState[i]!=count:
   raise ValueError('pricing and allocation state counts differ')
 n=context.own_count(r)
 if n<=0:raise ValueError('no living objective executor')
 execution=team_goal/n
 return dict(teamGoalValue=team_goal,N=n,executionShare=1/n,executionValue=execution,
             teamRemainder=team_goal-execution,contextSHA256=context.context_hash(),
             statePhase=context.statePhase,orderEvidence=context.orderEvidence)


def price_and_allocate(package, kind, fold, map_name, context, r):
 """Use the identical context for feature extraction, price and allocation."""
 from .heads import infer
 if kind not in ('plant', 'defuse'): raise ValueError('invalid objective head')
 features = context.features(r)
 value = infer(package, kind, fold, features, map_name)
 return allocate_objective(value, context, r)
