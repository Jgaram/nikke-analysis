"""재검토(6절)의 공용 틀: 시점 T 의 칸 값을, 일부 시즌을 뺀 데이터로 다시 계산한다. 8·9 가 가져다 쓴다.

칸 = (니케, 보스 약점, 애장품 쪽). 기준 자리(anchor)는 달력으로 정한다 — T 까지 그 약점의 가장 최근 시즌 종료.
시즌을 빼도 기준 자리는 그대로라서, 빼는 것은 "그 시즌의 기록을 모른다"는 뜻이다.

저장소 루트에서 `PYTHONPATH=docs/time-review` 로 8·9 를 실행한다. docs/time-review.md 6절 참고."""
import os, pickle
import numpy as np, pandas as pd
from nikke_analysis import power
from nikke_analysis.analyze.tiers import load_tier_config

CFG = load_tier_config()
EL = ['Fire', 'Water', 'Wind', 'Iron', 'Electric']
CUTS = np.array([CFG.cut(l) for l in CFG.tier_order])
OCUTS = np.array([CFG.overall_cut(l) for l in CFG.tier_order])
def tier_idx(v, cuts):  # 0 = SS ... 6 = F
    return np.searchsorted(-cuts, -np.asarray(v), side='left')

# ---------------------------------------------------------------- data
def _table():
    t = pd.read_csv('data/processed/metrics_unit_season.csv')
    t['unit_id'] = t.unit_id.astype(str)
    t['end'] = pd.to_datetime(t.end_at, utc=True)
    t['own'] = t.element_match.astype(str).str.lower().eq('true')
    t['tr'] = t.treasure.astype(str).str.lower().eq('true')
    t['cell'] = power.cell_key(t.unit_id, t.tr, t.own)
    t = t[t.weak_element.isin(EL)].copy()
    t['at'] = (t.end - pd.Timestamp('2022-11-04', tz='UTC')).dt.total_seconds() / 86400
    return t
T0 = _table()
CAL = T0.groupby('season').agg(at=('at', 'first'), weak=('weak_element', 'first'))

_FIT = 'data/interim/time-review/fit.pkl'
def deck_fit():
    """체급 회귀의 시즌별 합 (5절 재구성안을 시험할 때만)."""
    if not os.path.exists(_FIT):
        entries, history, _, _ = power.load()
        history = history.assign(season=pd.to_numeric(history['season']).astype(int))
        res = power.fit(power.cells(entries, history))
        os.makedirs(os.path.dirname(_FIT), exist_ok=True)
        pickle.dump(dict(cells=res.cells, seasons=res.seasons, n=len(res.cells)), open(_FIT, 'wb'))
    return pickle.load(open(_FIT, 'rb'))
def solve(F, seasons):
    A = sum(F['seasons'][s][0] for s in seasons); b = sum(F['seasons'][s][1] for s in seasons)
    pen = power.RIDGE * np.eye(len(b)); pen[F['n'], F['n']] = 1e-9
    return pd.Series(np.linalg.solve(A + pen, b)[:-1], index=F['cells'])

def pava(x, y):  # isotonic regression of y on x
    o = np.argsort(x, kind='stable'); x = x[o]; y = y[o]
    bv, bw = [], []
    for v in y:
        bv.append(v); bw.append(1)
        while len(bv) > 1 and bv[-2] > bv[-1]:
            w = bw[-2] + bw[-1]; bv[-2] = (bv[-2] * bw[-2] + bv[-1] * bw[-1]) / w; bw[-2] = w; bv.pop(); bw.pop()
    f = pd.Series(np.repeat(bv, bw)).groupby(x).mean()
    return f.index.to_numpy(), f.to_numpy()

class Ctx:
    """시점 = 시즌 sT 종료, 빼는 시즌 R. field=True 면 체급(R 을 빼고 다시 푼 것)과 기대 기여도 곡선도."""
    def __init__(self, sT, R=(), field=False, k=25):
        self.sT, self.R = sT, frozenset(R)
        rows = T0[T0.season <= sT]
        trT = T0[T0.season == sT].set_index('unit_id').tr
        rows = rows[rows.tr.values == rows.unit_id.map(trT).fillna(False).values]
        self.Tday = CAL.loc[sT, 'at']
        cal = CAL.loc[:sT]
        self.anchor = cal.groupby('weak').at.max()
        self.anchor_season = cal.reset_index().groupby('weak').season.max()
        self.all = rows
        d = rows[~rows.season.isin(self.R)].copy()
        d['anchor'] = d.weak_element.map(self.anchor)
        if field:
            th = solve(deck_fit(), [s for s in range(1, sT + 1) if s not in self.R])
            a = T0[T0.season <= sT].assign(th=lambda x: x.cell.map(th))
            c = (a.dropna(subset=['th']).sort_values('th', ascending=False).groupby('season').head(k)
                 .groupby('season').th.mean())
            d['th'] = d.cell.map(th); d['r'] = d.th - d.season.map(c)
            m = {o: pava(d.r[(d.own == o) & d.r.notna()].to_numpy(), d.lift[(d.own == o) & d.r.notna()].to_numpy())
                 for o in (True, False)}
            ev = lambda own, r: np.where(own, np.interp(np.nan_to_num(r, nan=-9), *m[True]),
                                         np.interp(np.nan_to_num(r, nan=-9), *m[False]))
            d['E'] = ev(d.own.values, d.r.values)
            cA = d.weak_element.map(self.anchor_season).map(c)
            d['EA'] = ev(d.own.values, (d.th - cA).values)
        self.rows = d

def overall(ctx, v):
    """다섯 칸 평균. 못 겪은 다른 속성 칸 = 겪은 다른 속성 칸 평균(없으면 0), 못 겪은 자기 속성 칸 = 0."""
    own = ctx.all.groupby(['unit_id', 'weak_element']).own.first().unstack().reindex(columns=EL).fillna(False).astype(bool)
    V = v.unstack().reindex(index=own.index, columns=EL)
    other = V.where(~own).mean(axis=1).fillna(0)
    return pd.DataFrame({e: V[e].where(V[e].notna(), np.where(own[e], 0.0, other)) for e in EL}).mean(axis=1)

# ---------------------------------------------------------------- 칸 값을 내는 방법들
def _grp(d, num, den):
    s = pd.DataFrame({'n': num, 'd': den, 'u': d.unit_id.values, 'e': d.weak_element.values}).groupby(['u', 'e']).sum()
    return s.n / s.d
def _H(g, h):
    return 0.5 ** (g / h) if h else np.ones_like(g)

def averaged(belief, own_hl, other_hl, moving=False):
    """지금 방식의 틀: 옛 시즌을 반감기 own_hl/other_hl 로 기준 자리 값으로 옮기고, belief 반감기로 최근을 크게 친 평균.
    belief 0 = 똑같이. moving = 기준 자리가 데이터에 남은 그 약점의 가장 최근 시즌 (지금 코드)."""
    def f(d, ctx):
        anchor = d.groupby('weak_element')['at'].transform('max').to_numpy() if moving else d.anchor.to_numpy()
        w = _H((ctx.Tday - d['at']).to_numpy(), belief)
        val = d.lift.to_numpy() * 0.5 ** ((anchor - d['at'].to_numpy()) / np.where(d.own, own_hl, other_hl))
        return _grp(d, w * val, w)
    return f

def latest(d, ctx):
    s = d.loc[d.groupby(['unit_id', 'weak_element'])['at'].idxmax()].set_index(['unit_id', 'weak_element']).lift
    s.index.names = ['u', 'e']; return s

def line(slope=(-0.4, -0.5), k=1.0):
    """칸마다 시즌들에 직선을 긋고 기준 자리에서 읽는다(0 아래는 0). 기울기는 칸 자신의 기울기에 그 쪽(자기/다른 속성)
    평균 기울기(1년당 기여도)를 k 만큼 섞는다: (Σ(x−x̄)(y−ȳ) + k·평균) / (Σ(x−x̄)² + k), x 는 년.
    k = (시즌 하나의 흔들림 / 기울기의 니케 간 퍼짐)² 으로 잰 값이 자기 1.25 · 다른 1.0 이라 1."""
    def f(d, ctx):
        x = ((d['at'] - d.anchor) / 365.25).to_numpy(); y = d.lift.to_numpy()
        g = pd.DataFrame({'x': x, 'y': y, 'xx': x * x, 'xy': x * y, 'one': 1.0, 'own': d.own.values,
                          'u': d.unit_id.values, 'e': d.weak_element.values}).groupby(['u', 'e'])
        s = g.agg(n=('one', 'sum'), sx=('x', 'sum'), sy=('y', 'sum'), sxx=('xx', 'sum'), sxy=('xy', 'sum'), own=('own', 'first'))
        xb, yb = s.sx / s.n, s.sy / s.n
        Sxx, Sxy = s.sxx - s.n * xb * xb, s.sxy - s.n * xb * yb
        b = (Sxy + k * np.where(s.own, slope[0], slope[1])) / (Sxx + k)
        return (yb - b * xb).clip(lower=0)
    return f

def field_oe(k=0.3):
    """5절 재구성안: 지금 판에서 체급으로 기대하는 기여도 × (그 니케가 기대만큼 한 비율)."""
    def f(d, ctx):
        s = pd.DataFrame({'L': d.lift.values, 'E': d.E.values, 'EA': d.EA.values, 'u': d.unit_id.values,
                          'e': d.weak_element.values}).groupby(['u', 'e']).agg(L=('L', 'sum'), E=('E', 'sum'), EA=('EA', 'first'))
        return s.EA * (s.L + k) / (s.E + k)
    return f
def field_pure(d, ctx):
    return pd.DataFrame({'EA': d.EA.values, 'u': d.unit_id.values, 'e': d.weak_element.values}).groupby(['u', 'e']).EA.first()
