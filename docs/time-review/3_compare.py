"""칸 추정 방식 비교: 다음 시즌 예측(bias, MAE), 1년 넘은 시즌/한 시즌을 지웠을 때의 변화, 관측 최저보다 낮은 비율.
2024-06 이후 각 시즌 시작 시점, 그때까지 0.3 이상 찍은 칸.

저장소 루트에서 실행: python docs/time-review/<이 파일>. docs/time-review.md 참고."""
import pandas as pd, numpy as np
from nikke_analysis.analyze.tiers import assign_tier, TierConfig
c=TierConfig()
t=pd.read_csv('data/processed/metrics_unit_season.csv')
s=pd.read_csv('data/processed/metrics_seasons.csv')
t['end']=pd.to_datetime(t.end_at,utc=True); t['start']=pd.to_datetime(t.start_at,utc=True)
t['own']=t.element_match.astype(str).str.lower().eq('true')
t['tr']=t.treasure.astype(str).str.lower().eq('true')
t=t[t.weak_element.isin(['Fire','Water','Wind','Iron','Electric'])]
H=lambda g,h: np.ones_like(g) if h in (0,None) else 0.5**(g/h)

def est(L,G,own,m):
    """L lifts, G days before the slot's latest season (0 for latest)."""
    kind=m[0]
    if kind=='A':   # recency h, value v (v may be (own,other))
        h,v=m[1],m[2]
        v=v[0] if (isinstance(v,tuple) and own) else (v[1] if isinstance(v,tuple) else v)
        w=H(G,h); return (w*L*H(G,v)).sum()/w.sum()
    if kind=='S':
        h=m[1][0] if own else m[1][1]; w=H(G,h); return (w*L*H(G,h)).sum()/w.sum()
    if kind=='W':   # last n seasons
        n=m[1]; o=np.argsort(G)[:n]; return L[o].mean()
METHODS={
 '현재 180/300':('A',180,300),
 '가) 90/(500,230)':('A',90,(500,230)),
 '90/잰값(520,290)':('A',90,(520,290)),
 '120/(500,230)':('A',120,(500,230)),
 '180/(500,230)':('A',180,(500,230)),
 '믿음 없음/(500,230)':('A',0,(500,230)),
 'h=v 300':('A',300,300),
 'h=v 자기500,다른230':('S',(500,230)),
 '한 반감기 90, 환산 없음':('A',90,0),
 '한 반감기 180, 환산 없음':('A',180,0),
 '최근 1시즌':('W',1),
 '최근 2시즌':('W',2),
}
seasons=sorted(t.season.unique())
starts=t.groupby('season').start.first(); ends=t.groupby('season').end.first()
out=[]
by=t.groupby(['unit_id','weak_element','tr'])
for key,g in by:
    g=g.sort_values('season')
    for _,tg in g.iterrows():
        mom=tg.start
        if mom < pd.Timestamp('2024-06-01',tz='UTC'): continue
        prior=g[g.end<=mom]
        if prior.empty or prior.lift.max()<0.3: continue
        L=prior.lift.to_numpy(); E=prior.end
        G=((E.max()-E).dt.total_seconds()/86400).to_numpy()
        old=((mom-E).dt.total_seconds()/86400).to_numpy()>365
        loo={}
        if len(L)>=2:
            for name,m in METHODS.items():
                e0=est(L,G,tg.own,m); ch=[];fl=[]
                for i in range(len(L)):
                    k=np.arange(len(L))!=i
                    e1=est(L[k],G[k]-G[k].min(),tg.own,m); ch.append(abs(e1-e0)); fl.append(assign_tier(e0,c)!=assign_tier(e1,c))
                loo[name+'|loo']=np.mean(ch); loo[name+'|loof']=np.mean(fl)
        rec=dict(own=tg.own,**loo,target=tg.lift,n=len(L),L=L,G=G)
        for name,m in METHODS.items():
            e=est(L,G,tg.own,m); rec[name]=e
            if (~old).any() and old.any():
                rec[name+'|drop']=e-est(L[~old],G[~old]-G[~old].min(),tg.own,m)
            rec[name+'|lab']=(assign_tier(e,c)!=assign_tier(est(L[~old],G[~old]-G[~old].min(),tg.own,m),c)) if ((~old).any() and old.any()) else np.nan
            rec[name+'|below']=(len(L)>=2) and e<L.min()-1e-9
        out.append(rec)
d=pd.DataFrame(out)
d['hist']=pd.cut(d.n,[0,1,3,100],labels=['1','2-3','4+'])
for side,dd in (('자기 속성 칸',d[d.own]),('다른 속성 칸',d[~d.own])):
    print(f'\n== {side}: 예측 {len(dd)}건')
    rows=[]
    for name in METHODS:
        err=dd[name]-dd.target
        drop=dd[name+'|drop'].dropna()
        r=dict(method=name,bias=err.mean(),MAE=err.abs().mean())
        for h,ddd in dd.groupby('hist',observed=True): r[f'bias n={h}']=(ddd[name]-ddd.target).mean()
        r['1년전삭제 평균차']=drop.mean(); r['1년전삭제 |차|']=drop.abs().mean()
        r['삭제시 티어바뀜%']=100*dd[name+'|lab'].dropna().mean(); r['한시즌삭제 |차|']=dd[name+'|loo'].mean(); r['한시즌삭제 티어바뀜%']=100*dd[name+'|loof'].mean(); r['관측최저보다낮음%']=100*dd.loc[dd.n>=2,name+'|below'].mean()
        rows.append(r)
    print(pd.DataFrame(rows).set_index('method').drop(columns=['bias n=1','bias n=2-3','bias n=4+']).round(3).to_string())
