"""Versioned round ledger and aggregation. No external reference ratings are inputs."""
import hashlib
import json
import math
from collections import defaultdict
from .contracts import validate_round, number
from .features import hp, hp_dose, life, doses
from .heads import infer
from .integrity import fold_evidence
from .objective_context import price_and_allocate

MODES = ('website_common_full','professional_common_oof','professional_rich_diagnostic')
COMPONENTS = ('weaponHP','utilityHP','killLife','deathLife','clutchGain','clutchLoss','tradeRecovery','flash','friendlyFlash','plant','defuse','center')
SCALE = 9.759021807012848

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def route(package, mode, group):
    if mode == 'website_common_full': return 'full'
    if mode != 'professional_common_oof': raise ValueError('rich mode requires frozen ledger replay')
    ev=fold_evidence(package)
    if ev['routing'] != 'verified_metadata': raise ValueError('OOF routing unverified')
    matches=[str(f['fold']) for f in package['folds']['teacherOuter'] if group in f['validationGroups']]
    if len(matches)!=1: raise ValueError('series must have exactly one OOF fold')
    return matches[0]

def score_round(package, mode, r, events):
    if mode not in MODES: raise ValueError('unknown mode')
    validate_round(r)
    if any(k in r for k in ('RatingPro','HLTV','H2','reference')): raise ValueError('external reference forbidden in scoring input')
    for k in ('rid','group','mapName'):
        if k not in r: raise ValueError('missing '+k)
    fold=route(package,mode,r['group']); players={p['steam']:p for p in r['players']}
    components={s:dict.fromkeys(COMPONENTS,0.) for s in players}; hp_events=[]; flash_events=[]; life_events=[]; goals=[]
    for s in players:
        fact=r['facts'][s]; utility=fact['utility']; damage=fact['damage']
        he=number(utility['heDamage'],'heDamage',0); fire=number(utility['fireDamage'],'fireDamage',0)
        dose=hp_dose(r,s); price=infer(package,'HP',fold,hp(r,s),r['mapName'],dose)
        fraction=min(damage,he+fire)/damage if damage else 0.
        components[s]['weaponHP']+=price*(1-fraction); components[s]['utilityHP']+=price*fraction
        hp_events.append({'actor':s,'sourceD':damage,'dose':dose,'value':price,'utilityFraction':fraction})
        enemy,friendly=doses(fact); x=hp(r,s)[:-1]
        pos=infer(package,'enemyFlash',fold,x,r['mapName'],enemy); neg=infer(package,'friendlyFlash',fold,x,r['mapName'],friendly)
        components[s]['flash']+=pos; components[s]['friendlyFlash']-=neg
        flash_events.append({'actor':s,'enemyValue':pos,'friendlyCost':neg,'FAAdditionalAward':0.})
    terminal=None
    ordered=sorted(enumerate(events),key=lambda x:(x[1]['tick'],x[0]))
    if len({e['tick'] for _,e in ordered})!=len(ordered): raise ValueError('event ticks must be unique atomic groups')
    for _,e in ordered:
        tick=number(e['tick'],'event tick',0)
        if len(e['before']) < 9: raise ValueError('invalid state dimension')
        for x in e['before']: number(x,'state')
        for k in e['events']:
            if k['kind']=='kill':
                a=k.get('actor'); v=k.get('victim')
                if v not in players or (a is not None and a not in players): raise ValueError('unknown event player')
                if a is None or players[a]['side']==players[v]['side']: continue
                val=0. if terminal is not None and tick>terminal else infer(package,'life',fold,life(r,e,k),r['mapName'])
                ca=0 if players[a]['side']=='ct' else 1; cv=0 if players[v]['side']=='ct' else 1
                components[a]['clutchGain' if e['before'][ca]==1 else 'killLife']+=val
                components[v]['clutchLoss' if e['before'][cv]==1 else 'deathLife']-=val
                life_events.append({'tick':tick,'actor':a,'victim':v,'actorCredit':val,'victimCredit':-val})
            elif k['kind'] in ('planted','defused'):
                from .objective_context import make_context
                common_event={**e,'before':e['before'][:9]}
                c=make_context(r,common_event,k,'website' if mode=='website_common_full' else 'professional')
                if terminal is not None and tick>terminal:
                    from .objective_context import allocate_objective
                    result=allocate_objective(0.,c,r)
                else: result=price_and_allocate(package,'plant' if k['kind']=='planted' else 'defuse',fold,r['mapName'],c,r)
                components[k['actor']]['plant' if k['kind']=='planted' else 'defuse']+=result['executionValue']
                goals.append({'tick':tick,'actor':k['actor'],'kind':k['kind'],'context':c.record(),**result})
        if e.get('terminalAfter') is not None and terminal is None: terminal=tick
    gamma=package['gamma'][fold]; prior=[]; used=set(); recovery=[]
    for tick in sorted({e['tick'] for e in life_events}):
        current=[e for e in life_events if e['tick']==tick]
        for v in current:
            eligible=[d for d in prior if d['actor']==v['victim'] and players[d['victim']]['side']==players[v['actor']]['side'] and d['victim'] not in used and 0<tick-d['tick']<=6*r['rate']]
            total=sum(d['actorCredit'] for d in eligible)
            if not eligible: continue
            amount=gamma*min(v['actorCredit'],total); members=[]
            for d in eligible:
                share=amount*d['actorCredit']/total if total else 0.; used.add(d['victim']); components[d['victim']]['tradeRecovery']+=share
                members.append({'victim':d['victim'],'deathTick':d['tick'],'recovery':share})
            recovery.append({'tick':tick,'trader':v['actor'],'amount':amount,'members':members})
        prior.extend(current)
    paid={(e['tick'],e['actor'],e['victim']) for e in life_events}
    zero_slots=[]
    for slot in r['killSlots']:
        a=slot.get('actor');v=slot['victim'];tick=slot['tick']
        if a not in players or players[a]['side']==players[v]['side'] or (tick,a,v) in paid: continue
        reason='before_freeze' if tick<r['freeze'] else 'after_source_end' if tick>r['end'] else None
        if reason is None: raise ValueError('uncovered active enemy kill')
        zero_slots.append({'tick':tick,'actor':a,'victim':v,'reason':reason,'lifeValue':0.})
    center=-sum(sum(c.values()) for c in components.values())/10
    for c in components.values(): c['center']=center
    closure=sum(sum(c.values()) for c in components.values())
    if abs(closure)>1e-10: raise ValueError('center does not close')
    return {'mode':mode,'rid':r['rid'],'map':r['map'],'series':r['group'],'round':r['round'],'fold':fold,'components':components,'centerPerPerson':center,'centerClosure':closure,'hpEvents':hp_events,'lifeEvents':life_events,'goalEvents':goals,'flashEvents':flash_events,'recoveryGroups':recovery,'zeroKillSlots':zero_slots,'sourceRoundSHA256':canonical_hash(r),'sourceEventsSHA256':canonical_hash(events),'scale':SCALE}

def accounts(c):
    return {'Combat':c['weaponHP']+c['killLife']+c['deathLife'],'Trade':c['tradeRecovery'],'MapControl':0.,'Utility':c['utilityHP']+c['flash']+c['friendlyFlash'],'Clutch':c['clutchGain']+c['clutchLoss'],'Objective':c['plant']+c['defuse']}

def aggregate(ledgers):
    buckets={}
    for ledger in ledgers:
        for player,c in ledger['components'].items():
            for scope,key in [('map',(ledger['map'],player)),('player',(player,))]:
                row=buckets.setdefault((scope,key),{'scope':scope,'key':list(key),'rounds':0,'components':dict.fromkeys(COMPONENTS,0.),'evidence':[]})
                row['rounds']+=1;row['evidence'].append({'rid':ledger['rid'],'ledgerSHA256':canonical_hash(ledger)})
                for name in COMPONENTS: row['components'][name]+=c[name]
    out=[]
    for row in buckets.values():
        c={k:SCALE*v/row['rounds'] for k,v in row['components'].items()};row['components']=c;row['accounts']=accounts(c);row['centerCorrection']=c['center'];row['rating']=1+sum(row['accounts'].values())+c['center'];out.append(row)
    return out

def compare_after_scoring(rows, references):
    """Join post-hoc only; absent references remain unknown."""
    index={tuple(r['key']):r for r in references}
    if len(index)!=len(references): raise ValueError('duplicate reference key')
    out=[]
    for row in rows:
        ref=index.get(tuple(row['key']));value=None if ref is None else number(ref['value'],'reference')
        out.append({'scope':row['scope'],'key':row['key'],'rating':row['rating'],'reference':value,'observed_delta':None if value is None else row['rating']-value,'unexplained_external_residual':'unknown','evidence':row['evidence']})
    return out

def replay_rich(path, expected_hash):
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected_hash: raise ValueError('rich ledger hash mismatch')
    rows=[json.loads(line) for line in data.splitlines() if line.strip()]
    if not rows or any(r.get('pricingMode',r.get('mode'))!='professional_rich_diagnostic' for r in rows): raise ValueError('invalid rich diagnostic ledger')
    return rows
