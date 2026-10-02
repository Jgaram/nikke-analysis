"""지금 속성 티어 칸이 그 칸의 관측 시즌 값·티어보다 낮은 경우 세기 (미하라·크라운).

저장소 루트에서 실행: python docs/time-review/<이 파일>. docs/time-review.md 참고."""
import pandas as pd, numpy as np
from nikke_analysis.analyze.tiers import assign_tier, TierConfig, tier_rank
c=TierConfig()
t=pd.read_csv('data/processed/metrics_unit_season.csv')
e=pd.read_csv('data/processed/metrics_element_tiers.csv')
e=e[e.element_seasons>0]
t['tr']=t.treasure.astype(str).str.lower().eq('true')
rows=[]
for _,r in e.iterrows():
    g=t[(t.unit_id.astype(str)==str(r.unit_id))&(t.weak_element==r.element)&(t.tr==bool(r.treasure))].sort_values('season')
    if g.empty: continue
    lifts=g.lift.to_numpy()
    rows.append(dict(name=r.name_ko,el=r.element,est=r.element_lift,tier=r.element_tier,n=len(g),
        lo=lifts.min(),hi=lifts.max(),latest=lifts[-1],mean=lifts.mean(),
        seasons=' '.join(f'{x:.2f}' for x in lifts)))
d=pd.DataFrame(rows)
d['below_min']=d.est<d.lo-1e-9
d['tier_latest']=d.latest.map(lambda v:assign_tier(v,c))
d['worse_than_all']=[all(tier_rank(r.tier)>tier_rank(assign_tier(x,c)) for x in map(float,r.seasons.split())) for r in d.itertuples()]
m=d[(d.n>=2)&(d.hi>=0.5)]
print('slots with >=2 seasons & some season >= B:',len(m))
print('estimate below every season value:',m.below_min.sum())
print('element tier worse than every season tier:',m.worse_than_all.sum())
print('est/latest median', (m.est/m.latest).median())
print(m[m.worse_than_all].sort_values('est',ascending=False)[['name','el','est','tier','seasons']].head(25).to_string())

# --- 분해: 평활 평균 x 깎기 계수, 후보 90/(500,230)
import pandas as pd, numpy as np
from nikke_analysis.analyze.tiers import assign_tier, TierConfig
c=TierConfig()
t=pd.read_csv('data/processed/metrics_unit_season.csv'); t['end']=pd.to_datetime(t.end_at,utc=True)
t['tr']=t.treasure.astype(str).str.lower().eq('true')
e=pd.read_csv('data/processed/metrics_element_tiers.csv'); e=e[e.element_seasons>0]
H=lambda g,h: 0.5**(g/h) if h else np.ones_like(g)
def A(L,G,h,v): w=H(G,h); return (w*L*H(G,v)).sum()/w.sum()
rows=[]
for _,r in e.iterrows():
    g=t[(t.unit_id.astype(str)==str(r.unit_id))&(t.weak_element==r.element)&(t.tr==bool(r.treasure))].sort_values('season')
    L=g.lift.to_numpy(); G=((g.end.max()-g.end).dt.total_seconds()/86400).to_numpy()
    sm=A(L,G,112.5,0); defl=H(G,112.5).sum()/H(G,180).sum()
    rows.append(dict(name=r.name_ko,el=r.element,seasons=' '.join(f'{x:.2f}' for x in L),
      now=A(L,G,180,300),smooth=sm,deflate=defl,new=A(L,G,90,500),latest=L[-1]))
d=pd.DataFrame(rows)
for k in ('now','new','latest'): d[k+'_t']=d[k].map(lambda v:assign_tier(v,c))
pd.set_option('display.width',250)
sel=d[d.name.str.contains('미하라|크라운|라피 : 레드|모더니아|리타|루드밀라|헬름|그레이브')]
print(sel[['name','el','seasons','smooth','deflate','now','now_t','new','new_t','latest_t']].round(2).to_string())
print('tier changes now->new:',(d.now_t!=d.new_t).sum(),'of',len(d), ' up:',(d.new>d.now).sum())
print('mean change', (d.new-d.now).mean().round(3))
