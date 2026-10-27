"""Independent scalar extraction from the frozen website-compatible round contract.
All features are retrospective; no rich trajectories or external ratings used.
"""
from .contracts import validate_round

def players(r):
 validate_round(r)
 return {p['steam']:p for p in r['players']}
def hp(r,s):
 ps=players(r);p=ps[s];own=p['side'];pr=r['facts'][s];u=pr['utility']
 og=sum(v['startGear'] for v in ps.values() if v['side']==own)/10000;eg=sum(v['startGear'] for v in ps.values() if v['side']!=own)/10000
 death=next((v['tick'] for v in r['killSlots'] if v['victim']==s),r['end'])
 return [float(own=='ct'),p['startGear']/10000,og,eg,og-eg,max(0,(r['end']-r['freeze'])/r['rate'])/120,max(0,(min(death,r['end'])-r['freeze'])/r['rate'])/120,pr['kills']/5,float(pr['deaths']),u['flashAssists']/5]
def hp_dose(r,s):
 ps=players(r);d=r['facts'][s]['damage'];n=sum(v.get('actor')==s and v.get('victim') in ps and ps[v['victim']]['side']!=ps[s]['side'] and r['freeze']<=v['tick']<=r['end'] for v in r['killSlots'])
 return (max(d,n)-n)/100

def context(r,e,actor):
 ps=players(r);own=ps[actor]['side'];x=e['before'];a,b=(0,1) if own=='ct' else (1,0);ga,gb=(5,6) if own=='ct' else (6,5);la,lb=(7,8) if own=='ct' else (8,7)
 return ps,own,x,a,b,ga,gb,la,lb

def life(r,e,k):
 ps,own,x,a,b,ga,gb,la,lb=context(r,e,k['actor'])
 ek=[v for v in e['events'] if v['kind']=='kill' and v.get('actor') in ps and v['victim'] in ps and ps[v['actor']]['side']!=ps[v['victim']]['side']]
 ownK=sum(ps[v['actor']]['side']==own for v in ek);enemyK=len(ek)-ownK
 return [float(own=='ct'),x[a]/5,x[b]/5,(x[a]-x[b])/5,1/max(1,x[a]),1/max(1,x[b]),x[2],x[3]/120,x[4]/40,x[ga],x[gb],x[la],x[lb],ps[k['actor']]['startGear']/10000,ps[k['victim']]['startGear']/10000,ownK/5,enemyK/5,(x[a]-enemyK)/5,(x[b]-ownK)/5]
def objective(r,e,actor):
 ps,own,x,a,b,ga,gb,la,lb=context(r,e,actor)
 return [float(own=='ct'),x[a]/5,x[b]/5,(x[a]-x[b])/5,x[2],x[3]/120,x[4]/40,x[ga],x[gb],x[la],x[lb],ps[actor]['startGear']/10000]
def doses(pr):
 u=pr['utility'];return [u['enemyBlindSeconds'],u['enemyBlindVictims'],u['flashAssists']],u['teamBlindSeconds']
