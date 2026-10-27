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
    if not isinstance(e['events'], list) or goal not in e['events']: raise ValueError('goal must be an event in this tick')
    if goal.get('kind') not in ('planted','defused'): raise ValueError('unknown goal')
    if goal.get('actor') not in {p['steam'] for p in r['players']}: raise ValueError('unknown goal actor')
    if len({id(k) for k in selected}) != len(selected) or any(k not in e['events'] or k.get('kind') != 'kill' for k in selected):
        raise ValueError('selected kills must be distinct events in current tick')
    return r
