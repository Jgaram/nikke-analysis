"""같은 니케·같은 약점의 앞뒤 시즌 쌍으로 기여도 반감 속도 재기 (자기/다른 속성), 시즌이 쌓이며 얼마나 안정적인가.

저장소 루트에서 실행: python docs/time-review/<이 파일>. docs/time-review.md 참고."""
import pandas as pd, numpy as np
t=pd.read_csv('data/processed/metrics_unit_season.csv')
t['end']=pd.to_datetime(t.end_at,utc=True)
t['own']=t.element_match.astype(str).str.lower().eq('true')
t['tr']=t.treasure.astype(str).str.lower().eq('true')
t=t[t.weak_element.isin(['Fire','Water','Wind','Iron','Electric'])]
pairs=[]
for (u,we,tr),g in t.groupby(['unit_id','weak_element','tr']):
    g=g.sort_values('season')
    L=g.lift.to_numpy(); E=g.end.to_numpy(); O=g.own.to_numpy()
    for i in range(len(g)):
        for j in range(i+1,len(g)):
            pairs.append((u,O[i],L[i],L[j],(E[j]-E[i])/np.timedelta64(1,'D')))
p=pd.DataFrame(pairs,columns=['u','own','a','b','gap'])
p=p[p.a>=0.3]   # was in use at the earlier season
p['bucket']=pd.cut(p.gap,[0,150,300,450,600,900])
def hl(df):
    # half-life implied by ratio of sums: sum b / sum a = 0.5^(mean gap / h)
    r=df.b.sum()/df.a.sum(); g=df.gap.mean()
    return pd.Series(dict(n=len(df),ratio=r,gap=g,implied_half_life=(g*np.log(.5)/np.log(r)) if 0<r<1 else np.inf))
print(p.groupby(['own','bucket'],observed=True).apply(hl).round(2).to_string())
print(p.groupby('own').apply(hl).round(2))
# own, high level only
print('own, a>=1.0'); print(p[(p.own)&(p.a>=1.0)].groupby('bucket',observed=True).apply(hl).round(2))

# --- 안정성
import pandas as pd, numpy as np
t=pd.read_csv('data/processed/metrics_unit_season.csv')
t['end']=pd.to_datetime(t.end_at,utc=True)
t['own']=t.element_match.astype(str).str.lower().eq('true'); t['tr']=t.treasure.astype(str).str.lower().eq('true')
t=t[t.weak_element.isin(['Fire','Water','Wind','Iron','Electric'])]
pairs=[]
for k,g in t.groupby(['unit_id','weak_element','tr']):
    g=g.sort_values('season'); L=g.lift.to_numpy(); E=g.end.to_numpy(); O=g.own.to_numpy(); S=g.season.to_numpy()
    for i in range(len(g)):
        for j in range(i+1,len(g)):
            pairs.append((O[i],L[i],L[j],(E[j]-E[i])/np.timedelta64(1,'D'),S[j]))
p=pd.DataFrame(pairs,columns=['own','a','b','gap','sj']); p=p[p.a>=0.3]
hl=lambda d: d.gap.mean()*np.log(.5)/np.log(d.b.sum()/d.a.sum())
for upto in (20,25,30,35,41):
    q=p[p.sj<=upto]
    print(f'시즌 {upto}까지: 자기 {hl(q[q.own]):.0f}일 ({q.own.sum()}쌍) · 다른 {hl(q[~q.own]):.0f}일 ({(~q.own).sum()}쌍)')
