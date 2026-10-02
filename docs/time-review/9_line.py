"""6절 직선 모형: 숫자 재기(평균 기울기, 니케 간 퍼짐, 시즌 하나의 흔들림), 이름이 알려진 칸의 지금 값,
"모든 시즌 티어보다 낮은 속성 티어"의 비율, 1년 넘은 시즌을 빼도 평균이 안 움직이는 기울기.

    PYTHONPATH=docs/time-review python docs/time-review/9_line.py

docs/time-review.md 6절 참고."""
import importlib
import numpy as np, pandas as pd
h = importlib.import_module('7_harness')
pd.set_option('display.width', 250)

# 1. 칸마다 직선 (시즌 4개 이상, 어느 시즌이든 0.5 이상): 기울기의 평균, 퍼짐(추정 오차를 뺀 것), 직선 둘레 흔들림
R = []
for (u, e, tr), g in h.T0.groupby(['unit_id', 'weak_element', 'tr']):
    if len(g) < 4 or g.lift.max() < 0.5:
        continue
    x = g['at'].to_numpy() / 365.25; y = g.lift.to_numpy()
    X = np.c_[np.ones_like(x), x - x.mean()]; b = np.linalg.lstsq(X, y, rcond=None)[0]
    s2 = ((y - X @ b) ** 2).sum() / (len(y) - 2)
    R.append(dict(own=g.own.iloc[0], slope=b[1], se2=s2 / ((x - x.mean()) ** 2).sum(), s2=s2))
d = pd.DataFrame(R)
for own, q in d.groupby('own'):
    print(('자기' if own else '다른') + f' 속성 칸 {len(q)}개: 평균 기울기 {q.slope.mean():+.2f}/년 · '
          f'퍼짐 {np.sqrt(max(q.slope.var() - q.se2.mean(), 0)):.2f}/년 · 흔들림 {np.sqrt(q.s2.median()):.2f}')

# 2. 1년 넘은 시즌을 다 빼도 평균이 안 움직이는 평균 기울기 (안 움직여야 옛 시즌이 한쪽으로 끌지 않는다)
out = []
for sT in range(20, 42, 2):
    base = h.Ctx(sT)
    ctx = h.Ctx(sT, [s for s in range(1, sT + 1) if base.Tday - h.CAL.loc[s, 'at'] > 365])
    g = base.rows.groupby(['unit_id', 'weak_element']); mx, own = g.lift.max(), g.own.first()
    mx.index.names = own.index.names = ['u', 'e']
    for b in (0, -.2, -.3, -.4, -.6):
        f = h.line(slope=(b, b)); a, c = f(base.rows, base), f(ctx.rows, ctx)
        idx = c.index.intersection(mx[mx >= .3].index); o = own.reindex(idx).to_numpy(bool)
        dd = (a.reindex(idx) - c.reindex(idx)).to_numpy()
        out.append(dict(b=b, own=dd[o].mean(), oth=dd[~o].mean(), no=o.sum(), nt=(~o).sum()))
o = pd.DataFrame(out)
print('\n1년 넘은 시즌 빼기: 평균차 (뺀 것과 안 뺀 것), 평균 기울기별')
print(o.groupby('b').apply(lambda g: pd.Series({'자기': np.average(g.own, weights=g.no),
                                                 '다른': np.average(g.oth, weights=g.nt)})).round(4).to_string())

# 3. 시즌 20–41 종료 시점마다: 속성 티어가 그 칸의 모든 시즌 티어보다 낮은 비율 (시즌 2개 이상, 어느 시즌이든 B 이상)
E = {'지금': h.averaged(180, 300, 300, moving=True), '가)': h.averaged(90, 520, 290),
     '똑같이 / 520·290': h.averaged(0, 520, 290), '직선': h.line()}
out = []
for sT in range(20, 42):
    ctx = h.Ctx(sT); dd = ctx.rows[ctx.rows.own]
    g = dd.groupby(['unit_id', 'weak_element']).lift
    best, n = g.max(), g.size(); worst = g.apply(lambda s: h.tier_idx(s.values, h.CUTS).max())
    for x in (best, n, worst): x.index.names = ['u', 'e']
    sel = ((n >= 2) & (best >= 0.5)).to_numpy()
    for k, f in E.items():
        t = h.tier_idx(f(dd, ctx).reindex(best.index).values, h.CUTS)
        out.append(dict(est=k, n=sel.sum(), below=((t > worst.to_numpy()) & sel).sum()))
o = pd.DataFrame(out).groupby('est').sum()
print('\n속성 티어 < 그 칸의 모든 시즌 티어'); print((100 * o.below / o.n).round(1).reindex(list(E)).to_string())

# 4. 지금(시즌 41 종료) 이름이 알려진 칸
ctx = h.Ctx(41); dd = ctx.rows[ctx.rows.own]
names = h.T0.drop_duplicates('unit_id').set_index('unit_id').name_ko
V = pd.DataFrame({k: f(dd, ctx) for k, f in E.items()})
s = dd.groupby(['unit_id', 'weak_element']).lift.apply(lambda x: ' '.join(f'{v:.2f}' for v in x)); s.index.names = ['u', 'e']
V.insert(0, '시즌', s); V.insert(0, '니케', [names[u] for u, _ in V.index])
pick = V.니케.str.fullmatch('미하라 : 본딩 체인|크라운|라피 : 레드 후드|홍련 : 흑영|신데렐라|앨리스|모더니아|리타|루주|D : 킬러 와이프')
print('\n시즌 41 종료, 자기 속성 칸'); print(V[pick].round(2).to_string())
