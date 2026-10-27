"""Post-hoc differences: arithmetic reconciliation and explicit reference uncertainty."""
import json
import math
from pathlib import Path
from .pipeline import COMPONENTS, SCALE, aggregate, canonical_hash

H2_FORMULA='.0073*KAST_percent+.3591*KPR-.5329*DPR+.2372*(2.13*KPR+.42*APR-.41)+.0032*ADR+.1587'

def h2_terms(facts):
    if not facts: raise ValueError('no facts for H2')
    n=len(facts)
    k=sum(f['kills'] for f in facts)/n;d=sum(f['deaths'] for f in facts)/n;a=sum(f['assists'] for f in facts)/n
    return {'KAST':.0073*100*sum(bool(f['kast']) for f in facts)/n,'KPR':.3591*k,'DPR':-.5329*d,'Impact':.2372*(2.13*k+.42*a-.41),'ADR':.0032*sum(f['damage'] for f in facts)/n,'intercept':.1587}

def registry(domain, report, batch, references, baseline, identities=None):
    if domain not in ('website','professional'): raise ValueError('unknown domain')
    expected_mode={'website':'website_common_full','professional':'professional_common_oof'}[domain]
    if report.get('mode',expected_mode)!=expected_mode: raise ValueError('report mode mismatch')
    items=batch['rounds']; ledgers=report['ledgers']; source={}
    for item in items:
        r=item['round']; rid=r['rid']
        if rid in source: raise ValueError('duplicate batch round')
        source[rid]=item
    if not source or not isinstance(ledgers,list): raise ValueError('empty or invalid ledger')
    seen=set()
    for ledger in ledgers:
        rid=ledger['rid']
        if rid in seen or rid not in source: raise ValueError('ledger round identity mismatch')
        seen.add(rid); item=source[rid]; r=item['round']
        if ledger.get('mode')!=expected_mode or ledger.get('map')!=r['map'] or ledger.get('round')!=r['round'] or ledger.get('series')!=r['group']:
            raise ValueError('ledger metadata mismatch')
        if ledger.get('sourceRoundSHA256')!=canonical_hash(r) or ledger.get('sourceEventsSHA256')!=canonical_hash(item['events']):
            raise ValueError('ledger source payload hash mismatch')
        if set(ledger['components'])!=set(r['facts']): raise ValueError('ledger player coverage mismatch')
    if seen!=set(source): raise ValueError('batch and ledger coverage mismatch')
    reconstructed=aggregate(ledgers,identities)
    supplied=report['aggregates']
    def indexed(rows):
        result={}
        for row in rows:
            key=(row['scope'],tuple(row['key']))
            if key in result:raise ValueError('duplicate aggregate identity')
            result[key]=row
        return result
    actual=indexed(supplied);expected=indexed(reconstructed)
    if set(actual)!=set(expected): raise ValueError('aggregate key coverage mismatch')
    for key,row in expected.items():
        if actual[key]!=row: raise ValueError('aggregate or ledger evidence mismatch')
    ref_index={}; base_index={};facts={}
    for v in references:
        key=(v['scope'],tuple(v['key']))
        if key in ref_index:raise ValueError('duplicate reference')
        ref_index[key]=v
    for v in baseline:
        key=(v['scope'],tuple(v['key']))
        if key in base_index:raise ValueError('duplicate baseline')
        base_index[key]=v
    for item in batch['rounds']:
        r=item['round']
        for player,f in r['facts'].items():
            identity=tuple(identities[(r['map'],player)]) if domain=='website' else (player,)
            for key in (('map',(r['map'],player)),('player',identity)):facts.setdefault(key,[]).append(f)
    records=[]
    for row in report['aggregates']:
        key=(row['scope'],tuple(row['key'])); prs=facts.get(key,[])
        if len(prs)!=row['rounds'] or len(row['evidence'])!=row['rounds']:raise ValueError('round evidence coverage mismatch')
        terms=h2_terms(prs);h2=sum(terms.values()); ref=ref_index.get(key,{});old=base_index.get(key)
        values=dict(ref.get('values',{}));values['H2_community_linear_v1']=h2
        bridges={};delta={};residual={};trend={}
        for name,value in values.items():
            if value is None:delta[name]=None;bridges[name]=None;residual[name]={'value':None,'status':'missing_reference'};trend[name]='no_reference';continue
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('invalid reference')
            d=row['rating']-value;delta[name]=d
            total=1-value+sum(row['components'].values())
            if abs(d-total)>1e-10:raise ValueError('arithmetic bridge mismatch')
            bridges[name]={'baseOffset':1-value,'scoreComponents':row['components'],'sum':total,'meaning':'arithmetic only'}
            residual[name]={'value':d,'status':'algebraically_specified_difference' if name=='H2_community_linear_v1' else 'unknown_private_reference_mechanism'}
            if old is None:trend[name]='no_baseline'
            else:
                previous=abs(old['rating']-value); current=abs(d);trend[name]='improved' if current<previous else 'worsened' if current>previous else 'unchanged'
        change=None if old is None else {'ratingChange':row['rating']-old['rating'],'componentChanges':{k:row['components'][k]-old['components'][k] for k in COMPONENTS},'meaning':'internal path comparison only'}
        records.append({'domain':domain,'grain':'player-map' if row['scope']=='map' else 'player','key':row['key'],'rounds':row['rounds'],'rating':row['rating'],'references':values,'observed_delta':delta,'internal_arithmetic_decomposition':bridges,'H2_public_formula':{'formula':H2_FORMULA,'terms':terms,'value':h2,'official':False},'known_implementation_change':change,'reference_provenance':ref.get('provenance',{}),'reference_limitations':ref.get('limitations',[]),'unexplained_external_residual':residual,'comparisonTrend':trend,'allRoundEvidence':row['evidence']})
    return records
