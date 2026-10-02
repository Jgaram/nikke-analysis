"""체급(전 시즌으로 푼 값)과 시즌별 판의 세기를 data/interim/time-review/ 에 저장. `nikke build raids` 가 먼저 필요.

저장소 루트에서 실행: python docs/time-review/<이 파일>. docs/time-review.md 참고."""
import os; os.makedirs('data/interim/time-review/',exist_ok=True)
import pandas as pd, numpy as np
from nikke_analysis import power
entries, history, roster, config = power.load()
history = history.assign(season=pd.to_numeric(history["season"]).astype(int))
res = power.fit(power.cells(entries, history))
w = power.weights(res)
F = power.field_strength(w, history)
F.to_csv('data/interim/time-review/field.csv')
w[['cell','unit_id','own','treasure','log','status']].to_csv('data/interim/time-review/cells.csv',index=False)
print(F.round(3).to_string())
