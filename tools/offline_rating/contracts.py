"""Versioned retrospective inputs for the common pricing policy."""
import math

CONTRACT_ID = 'rr-offline-round-v1'
POLICY_ID = 'rr-common-pricing-v1'

def number(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be finite numeric')
    if minimum is not None and value < minimum:
        raise ValueError(name + ' below minimum')
    return value

def validate_round(r):
    if not isinstance(r, dict): raise ValueError('round must be an object')
    for key in ('map', 'round', 'players', 'facts', 'killSlots', 'freeze', 'end', 'rate'):
        if key not in r: raise ValueError('missing round field: ' + key)
    if not isinstance(r['map'], str) or not r['map']: raise ValueError('invalid map')
    number(r['round'], 'round', 1)
    rate = number(r['rate'], 'rate', 0)
    if rate == 0: raise ValueError('rate must be positive')
    freeze = number(r['freeze'], 'freeze', 0); end = number(r['end'], 'end', freeze)
    if not isinstance(r['players'], list) or len(r['players']) != 10: raise ValueError('exactly ten players required')
    ids = []
    for p in r['players']:
        if not isinstance(p.get('steam'), str) or not p['steam']: raise ValueError('invalid player ID')
        if p.get('side') not in ('ct', 't'): raise ValueError('invalid side')
        number(p['startGear'], 'startGear', 0); ids.append(p['steam'])
    if len(set(ids)) != 10 or any(sum(p['side']==s for p in r['players']) != 5 for s in ('ct','t')):
        raise ValueError('duplicate IDs or sides not five each')
    if not isinstance(r['facts'], dict) or set(r['facts']) != set(ids): raise ValueError('facts must cover exactly ten players')
    for fact in r['facts'].values():
        for key in ('kills','deaths','damage'): number(fact[key], key, 0)
        u = fact['utility']
        for key in ('flashAssists','enemyBlindSeconds','enemyBlindVictims','teamBlindSeconds'): number(u[key], key, 0)
    if not isinstance(r['killSlots'], list): raise ValueError('killSlots must be a list')
    for k in r['killSlots']:
        number(k['tick'], 'kill tick', 0)
        if k.get('victim') not in ids: raise ValueError('unknown kill victim')
        if k.get('actor') is not None and k['actor'] not in ids: raise ValueError('unknown kill actor')
    return r

def validate_event(r, e, goal, selected):
    validate_round(r)
    tick=number(e['tick'], 'event tick', 0)
    if not r['freeze'] <= tick <= r['end']: raise ValueError('event outside live round')
    if not isinstance(e['before'], (list,tuple)) or len(e['before']) != 9: raise ValueError('before must have nine dimensions')
    for v in e['before']: number(v, 'before')
    events=e['events']
    if not isinstance(events,list) or not events: raise ValueError('events must be a nonempty list')
    players={p['steam']:p for p in r['players']}; keys=set(); killed=set()
    for item in events:
        if not isinstance(item,dict) or not isinstance(item.get('kind'),str): raise ValueError('invalid event')
        index=item.get('index')
        if isinstance(index,bool) or not isinstance(index,int) or index<0: raise ValueError('event source index required')
        key=(item['kind'],index)
        if key in keys: raise ValueError('duplicate source event')
        keys.add(key)
        if item.get('tick')!=tick or item.get('round')!=r['round']: raise ValueError('event outside atomic group')
        if item['kind']=='kill':
            if item.get('victim') not in players or (item.get('actor') is not None and item['actor'] not in players): raise ValueError('unknown kill identity')
            if item['victim'] in killed: raise ValueError('duplicate same-tick victim')
            killed.add(item['victim'])
        if item['kind'] in ('planted','defused'):
            actor=item.get('actor')
            if actor not in players: raise ValueError('unknown goal actor')
            side='t' if item['kind']=='planted' else 'ct'
            if players[actor]['side']!=side: raise ValueError('illegal goal actor side')
    if goal.get('kind') not in ('planted','defused') or sum(item==goal for item in events)!=1: raise ValueError('goal must identify exactly one source event')
    selected_keys=[]
    for item in selected:
        key=(item.get('kind'),item.get('index'))
        if item.get('kind')!='kill' or sum(event==item for event in events)!=1: raise ValueError('selected kill must identify one event in current tick')
        selected_keys.append(key)
    if len(set(selected_keys))!=len(selected_keys): raise ValueError('duplicate selected kill')
    return r
