"""앞뒤 시즌 쌍의 기여도 변화를 무엇이 설명하나: 날짜 / 판의 세기 / 니케 체급 - 판. 4_field.py 뒤에.

저장소 루트에서 실행: python docs/time-review/<이 파일>. docs/time-review.md 참고."""
import pandas as pd, numpy as np
S='data/interim/time-review/'
F=pd.read_csv(S+'field.csv',index_col=0).iloc[:,0]; lF=np.log(F)
cells=pd.read_csv(S+'cells.csv'); cells['unit_id']=cells.unit_id.astype(str)
t=pd.read_csv('data/processed/metrics_unit_season.csv'); t['unit_id']=t.unit_id.astype(str)
t['end']=pd.to_datetime(t.end_at,utc=True)
t['own']=t.element_match.astype(str).str.lower().eq('true'); t['tr']=t.treasure.astype(str).str.lower().eq('true')
t=t[t.weak_element.isin(['Fire','Water','Wind','Iron','Electric'])]
key=cells.set_index(['unit_id','own','treasure'])['log']
rows=[]
for (u,we,tr),g in t.groupby(['unit_id','weak_element','tr']):
    g=g.sort_values('season'); L=g.lift.to_numpy(); E=g.end.to_numpy(); S_=g.season.to_numpy(); own=bool(g.own.iloc[0])
    th=key.get((u,own,tr),np.nan)
    for i in range(len(g)-1):
        j=i+1  # consecutive same-weakness seasons
        if L[i]>=0.3:
            rows.append(dict(u=u,own=own,a=L[i],b=L[j],gap=(E[j]-E[i])/np.timedelta64(1,'D')/365,
                dF=lF[S_[j]]-lF[S_[i]],rel=th-lF[S_[i]]))
p=pd.DataFrame(rows).dropna()
p['y']=np.log(np.maximum(p.b,0.02)/p.a)
def ols(X,y):
    X=np.column_stack([np.ones(len(y))]+X); b=np.linalg.lstsq(X,y,rcond=None)[0]; r=y-X@b
    return b, 1-r.var()/y.var()
for side in (True,False):
    q=p[p.own==side]; print('\n== own' if side else '\n== other', len(q))
    for name,X in [('시간(년)',[q.gap]),('판의 세기 변화 ΔlogF',[q.dF]),
                   ('시간 + 시간×(체급−판)',[q.gap,q.gap*q.rel]),('ΔlogF + ΔlogF×(체급−판)',[q.dF,q.dF*q.rel]),
                   ('체급−판 만',[q.rel])]:
        b,r2=ols(X,q.y.to_numpy()); print(f'  {name:28s} R²={r2:.3f} coef={np.round(b,3)}')
    print('  corr(gap,dF)=%.2f'%np.corrcoef(q.gap,q.dF)[0,1])
print()
q=p[p.own]; print('own rel quantiles', q.rel.quantile([.1,.5,.9]).round(3).to_dict())
names=t.drop_duplicates('unit_id').set_index('unit_id').name_ko
for u in ['162']+list(t[t.name_ko.isin(['크라운','모더니아','리타','그레이브','라피 : 레드 후드'])].unit_id.unique()):
    r=p[(p.u==u)&p.own]
    if len(r): print(names[u], 'rel=%.3f'%r.rel.iloc[-1], '1년당 예상 변화 x%.2f'%np.exp(-0.606+3.923*r.rel.iloc[-1]))
