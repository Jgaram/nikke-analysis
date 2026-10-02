"""체급 관점 일곱 주장 검증: 덱 대미지 R², 출시일 인플레, 체급 순위별 채용률, 기여도 분산 분해, 채용 S자 곡선.

저장소 루트에서 실행: python docs/time-review/<이 파일>. docs/time-review.md 참고."""
import os; os.makedirs('data/interim/time-review/',exist_ok=True)
import pandas as pd, numpy as np
from nikke_analysis import power
from nikke_analysis.analyze import tiers as T
entries, history, roster, config = power.load()
history = history.assign(season=pd.to_numeric(history["season"]).astype(int))
ce = power.cells(entries, history)
res = power.fit(ce); w = power.weights(res)
# claim 4: within-player deck damage explained by 체급
yd = res.decks["yd"].to_numpy(); wt = res.decks["w"].to_numpy(); pr = res.predicted(res.coef)
print("claim4 R2 (log deck dmg vs player mean, weighted):", round(1-np.sum(wt*(yd-pr)**2)/np.sum(wt*yd**2),3))
print("  resid sd (log):", round(np.sqrt(np.average((yd-pr)**2,weights=wt)),3), " yd sd:", round(np.sqrt(np.average(yd**2,weights=wt)),3))
# claim 2: release date vs 체급
rel = pd.to_datetime(roster.drop_duplicates('unit_id').set_index(roster.drop_duplicates('unit_id').unit_id.astype(str))['release_date'],errors='coerce')
ok = w[(w.status=='ok')&(~w.treasure.astype(bool))].copy()
ok['yr'] = (ok.unit_id.astype(str).map(rel)-pd.Timestamp('2022-11-04')).dt.days/365.25
for side in (True,False):
    q=ok[ok.own.astype(bool)==side].dropna(subset=['yr'])
    b=np.polyfit(q.yr,q.log,1); r=np.corrcoef(q.yr,q.log)[0,1]
    print(f"claim2 {'own' if side else 'other'}: x{np.exp(b[0]):.3f}/yr, R2={r*r:.2f}, n={len(q)}, sd of log θ around trend={np.std(q.log-np.polyval(b,q.yr)):.2f}")
# claim 3: per season, usage vs 체급 rank among available units
h = history.copy(); h['unit_id']=h.unit_id.astype(str)
h['cell'] = power.cell_key(h.unit_id, T.played_with_treasure(h), T.flags(h,'element_match'))
h['log'] = h.cell.map(w.set_index('cell')['log'])
h['burst']=h.unit_id.map(roster.drop_duplicates('unit_id').set_index(roster.drop_duplicates('unit_id').unit_id.astype(str)).burst)
h = h.dropna(subset=['log'])
h['rk'] = h.groupby('season')['log'].rank(ascending=False)
h['used'] = h.usage_rate>=0.5
bands=pd.cut(h.rk,[0,5,10,15,20,25,30,40,60,200])
print("\nclaim3 usage by 체급 rank among available (measured cells), seasons 16-41")
q=h[h.season>=16]
print(q.groupby(pd.cut(q.rk,[0,5,10,15,20,25,30,40,60,200]),observed=True).agg(n=('used','size'),used50=('used','mean'),usage=('usage_rate','mean'),lift=('lift','mean')).round(2).to_string())
spearmanr=lambda a,b:(pd.Series(np.asarray(a)).rank().corr(pd.Series(np.asarray(b)).rank()),)
print("spearman(체급, usage) per season median:", round(q.groupby('season').apply(lambda g: spearmanr(g.log,g.usage_rate)[0]).median(),2))
print("of units used by >=50%: share whose 체급 rank >25:", round((q[q.used].rk>25).mean(),2), "; rank>40:", round((q[q.used].rk>40).mean(),2))
# within burst type
q2=q.copy(); q2['rkb']=q2.groupby(['season','burst'])['log'].rank(ascending=False)
print("spearman within burst type median:", round(q2.groupby(['season','burst']).apply(lambda g: spearmanr(g.log,g.usage_rate)[0] if len(g)>3 else np.nan).median(),2))
# claim 5: lift = usage x per-use share
u=q[q.lift>0.03]
per_use=np.log(u.lift/u.presence); 
print("\nclaim5 var(log lift) =", round(np.log(u.lift).var(),3), " var(log presence)=",round(np.log(u.presence).var(),3)," var(log per-use)=",round(per_use.var(),3), " cov2=",round(2*np.cov(np.log(u.presence),per_use)[0,1],3))
print("corr(log θ, log per-use share)=",round(np.corrcoef(u.log,per_use)[0,1],2), " corr(log θ, log presence)=",round(np.corrcoef(u.log,np.log(u.presence))[0,1],2))
h.to_csv('data/interim/time-review/h.csv',index=False)

# --- 채용률 vs (체급 - 그 시즌 25번째 체급): 시기별로 같은 곡선인가
h=pd.read_csv('data/interim/time-review/h.csv')
cut=h.sort_values('log',ascending=False).groupby('season')['log'].apply(lambda s:s.iloc[24] if len(s)>=25 else np.nan)
h['d']=h.log-h.season.map(cut)
q=h[h.season>=16].copy(); q['era']=np.where(q.season<=28,'S16-28','S29-41')
b=pd.cut(q.d,[-2,-.3,-.2,-.1,0,.1,.2,.3,2])
print(q.groupby([b,'era'],observed=True).usage_rate.mean().unstack().round(2).to_string())
for name,g in (('d bins',b),('rank bins',pd.cut(q.rk,[0,5,10,15,20,25,30,40,60,200]))):
    m=q.groupby(g,observed=True).usage_rate.transform('mean'); print(name,'R2',round(1-((q.usage_rate-m)**2).sum()/((q.usage_rate-q.usage_rate.mean())**2).sum(),2))
