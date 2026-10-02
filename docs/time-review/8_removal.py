"""6절 비교 표: 시즌을 빼고 다시 계산했을 때 칸 값·속성 티어·종합 티어가 얼마나 바뀌나, 빠진 최근 시즌을 얼마나 맞히나.

기준 시점 = 시즌 20–41 종료 (step 으로 건너뛸 수 있다). 빼는 방법: 시즌 하나씩 전부(그 칸의 가장 최근 시즌 / 그 앞 시즌),
연속 4시즌(어디든) 12번, 무작위 30% 12번, 1년 넘은 시즌 전부. 바뀐 칸만 센다(그 칸 시즌이 빠졌고 하나 이상 남음,
어느 시즌이든 0.3 이상 찍은 칸). 종합은 그런 칸이 있는 니케 중 종합 C(0.07) 이상.

    PYTHONPATH=docs/time-review python docs/time-review/8_removal.py [main|field] [step]

main 은 몇 분, field(체급을 시즌마다 다시 풂)는 십여 분. docs/time-review.md 6절 참고."""
import importlib, sys
import numpy as np, pandas as pd
h = importlib.import_module('7_harness')

which = sys.argv[1] if len(sys.argv) > 1 else 'main'
step = int(sys.argv[2]) if len(sys.argv) > 2 else 1
if which == 'main':
    FIELD = False
    EST = {
        '지금 180/300 (기준 자리 움직임)': h.averaged(180, 300, 300, moving=True),
        '지금 180/300': h.averaged(180, 300, 300),
        '가장 최근 시즌 하나': h.latest,
        '가) 90 / 520·290': h.averaged(90, 520, 290),
        '믿음 365 / 520·290': h.averaged(365, 520, 290),
        '똑같이 / 520·290': h.averaged(0, 520, 290),
        '환산 없이 믿음 90': h.averaged(90, 1e9, 1e9),
        '직선': h.line(),
    }
else:
    FIELD = True
    EST = {'가) 90 / 520·290': h.averaged(90, 520, 290), '체급만': h.field_pure,
           '체급 × 기대 대비': h.field_oe(0.3), '직선': h.line()}

rng = np.random.default_rng(0)
lift = h.T0.set_index(['unit_id', 'weak_element', 'season']).lift
recs = []
for sT in range(20, 42, step):
    base = h.Ctx(sT, field=FIELD)
    B = {n: e(base.rows, base) for n, e in EST.items()}
    BO = {n: h.overall(base, v) for n, v in B.items()}
    g = base.rows.groupby(['unit_id', 'weak_element'])
    info = pd.DataFrame({'mx': g.lift.max(), 'own': g.own.first(), 'last': g.season.max(), 'seasons': g.season.apply(set)})
    info.index.names = ['u', 'e']
    rel = info[info.mx >= 0.3]
    seasons = list(range(1, sT + 1))
    schemes = [('하나', [s]) for s in seasons]
    for _ in range(12):
        a = int(rng.integers(1, sT - 2)); schemes.append(('연속 4', list(range(a, a + 4))))
        schemes.append(('무작위 30%', [int(x) for x in rng.choice(seasons, size=max(1, int(.3 * sT)), replace=False)]))
    schemes.append(('1년 넘은 것 전부', [s for s in seasons if base.Tday - h.CAL.loc[s, 'at'] > 365]))
    for kind, R in schemes:
        Rs = set(R)
        ctx = h.Ctx(sT, R, field=FIELD)
        aff = rel[rel.seasons.map(lambda s: bool(s & Rs) and bool(s - Rs))]
        if kind == '하나':
            lat = aff.index[aff['last'].isin(Rs)]
            sub = {'하나: 그 칸의 최근 시즌': lat, '하나: 그 앞 시즌': aff.index.difference(lat)}
        else:
            sub = {kind: aff.index}
        units = set(aff.index.get_level_values(0))
        for n, e in EST.items():
            v = e(ctx.rows, ctx); vo = h.overall(ctx, v)
            for k2, idx in sub.items():
                if len(idx) == 0:
                    continue
                d = (v.reindex(idx) - B[n].reindex(idx)).to_numpy()
                fl = h.tier_idx(v.reindex(idx).values, h.CUTS) != h.tier_idx(B[n].reindex(idx).values, h.CUTS)
                o = rel.own.reindex(idx).to_numpy(bool)
                r = dict(sT=sT, kind=k2, est=n, own_n=o.sum(), own_abs=np.abs(d[o]).mean(), own_bias=d[o].mean(),
                         own_flip=fl[o].mean(), oth_n=(~o).sum(), oth_abs=np.abs(d[~o]).mean())
                if k2.endswith('최근 시즌'):
                    y = np.array([lift.get((u, e_, R[0]), np.nan) for u, e_ in idx])
                    err = v.reindex(idx).to_numpy() - y
                    r.update(own_err=np.nanmean(np.abs(err[o])), oth_err=np.nanmean(np.abs(err[~o])))
                recs.append(r)
            ou = [u for u in BO[n].index[BO[n] >= 0.07] if u in units]
            if ou:
                do = vo.reindex(ou) - BO[n].reindex(ou)
                ofl = h.tier_idx(vo.reindex(ou).values, h.OCUTS) != h.tier_idx(BO[n].reindex(ou).values, h.OCUTS)
                recs.append(dict(sT=sT, kind=kind, est=n, ovr_n=len(ou), ovr_abs=np.abs(do).mean(), ovr_bias=do.mean(),
                                 ovr_flip=ofl.mean()))
    print(sT, end=' ', flush=True, file=sys.stderr)

R = pd.DataFrame(recs)
def wavg(g, col, n):
    m = g[col].notna() & (g[n] > 0)
    return np.average(g.loc[m, col], weights=g.loc[m, n]) if m.any() else np.nan
rows = []
for (est, kind), g in R.groupby(['est', 'kind']):
    r = dict(est=est, kind=kind)
    if g.get('own_n', pd.Series(dtype=float)).fillna(0).sum():
        rows.append(r)
        r.update({'속성 칸 |차|': wavg(g, 'own_abs', 'own_n'), '속성 칸 평균차': wavg(g, 'own_bias', 'own_n'),
                  '속성 티어 바뀜%': 100 * wavg(g, 'own_flip', 'own_n'), '다른 칸 |차|': wavg(g, 'oth_abs', 'oth_n')})
        if 'own_err' in g and g.own_err.notna().any():
            r.update({'빠진 시즌 오차(속성)': wavg(g, 'own_err', 'own_n'), '빠진 시즌 오차(다른)': wavg(g, 'oth_err', 'oth_n')})
for (est, kind), g in R.groupby(['est', 'kind']):
    if g.get('ovr_n', pd.Series(dtype=float)).fillna(0).sum():
        rows.append({'est': est, 'kind': kind + ' (종합)', '종합 |차|': wavg(g, 'ovr_abs', 'ovr_n'),
                     '종합 평균차': wavg(g, 'ovr_bias', 'ovr_n'), '종합 티어 바뀜%': 100 * wavg(g, 'ovr_flip', 'ovr_n')})
T = pd.DataFrame(rows)
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
for kind in dict.fromkeys(T.kind):
    t = T[T.kind == kind].set_index('est').reindex(list(EST)).drop(columns='kind').dropna(axis=1, how='all')
    print(f'\n== {kind}'); print(t.round(3).to_string())
