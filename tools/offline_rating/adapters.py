"""Read a caller-specified, hash-verified frozen research inventory.

No path discovery or reference ratings: inventory maps roles to files and hashes.
"""
import json
from collections import defaultdict
from pathlib import Path
from .integrity import sha256
from .heads import unique_object

def read(path):
    return json.loads(Path(path).read_text(),object_pairs_hook=unique_object,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
def lines(path):
    with open(path) as f:
        return [json.loads(line,object_pairs_hook=unique_object) for line in f if line.strip()]

def adapt(inventory, domain):
    if domain not in ('website','professional'): raise ValueError('unknown domain')
    required={'rounds','events','playerRounds','kills','coverage'}
    if set(inventory)!=required: raise ValueError('inventory roles must be rounds, events, playerRounds, kills')
    data={}
    for role,entry in inventory.items():
        path=Path(entry['path']); digest=entry['sha256']
        if sha256(path)!=digest: raise ValueError('source hash mismatch: '+role)
        data[role]=lines(path) if entry.get('format')=='jsonl' else read(path)
    keep='website' if domain=='website' else 'cologne'
    selected=[r for r in data['rounds'] if r['source']==keep]
    rounds={r['rid']:r for r in selected}
    if len(rounds)!=len(selected): raise ValueError('duplicate round ID')
    coverage={v['rid']:v for v in data['coverage']}
    if len(coverage)!=len(data['coverage']) or set(coverage)!=set(rounds): raise ValueError('coverage must uniquely list each round')
    if any(set(v)!={'rid','killSlots','events'} or v['killSlots']!='complete' or v['events']!='complete' for v in coverage.values()): raise ValueError('source coverage incomplete')
    if not rounds: raise ValueError('no matching rounds')
    events=defaultdict(list)
    for e in data['events']:
        if e['rid'] in rounds: events[e['rid']].append(e)
    prs={};ks=defaultdict(list)
    if domain=='website':
        for page in data['playerRounds']:
            for v in page['player_rounds']:
                key=(page['match_map_id'],v['roundSeq'],v['steamId64'])
                if key in prs: raise ValueError('duplicate player-round source')
                prs[key]=v
        for page in data['kills']:
            for v in page['source_facts']['kills']:
                ks[(page['match_map_id'],v['roundSeq'])].append({'tick':v['tick'],'actor':v['killerSteamId64'],'victim':v['victimSteamId64']})
    else:
        for v in data['playerRounds']:
            key=(v['file'],v['roundNumber'],v['steamId64'])
            if key in prs: raise ValueError('duplicate player-round source')
            prs[key]=v
        for page in data['kills']:
            if 'rounds' in page:
                for v in page['rounds']:ks[(page['map'],v['round'])].extend(v['kills'])
            else:
                for v in page['kills']:ks[(page['map'],v['round'])].append(v)
    result=[]
    for r in rounds.values():
        r=dict(r); r['sourceCoverage']={'killSlots':'complete','events':'complete'}; r['killSlots']=sorted(ks.get((r['map'],r['round']),[]),key=lambda k:k['tick'])
        r['facts']={p['steam']:prs[(r['map'],r['round'],p['steam'])] for p in r['players']}
        result.append({'round':r,'events':events[r['rid']]})
    return {'schema':'rr-offline-round-batch-v1','rounds':result}
