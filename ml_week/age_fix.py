"""Age-fix check: Kaggle rows (first 974) were listed ~2022, the 30 hand-collected rows in Oct 2026.
The build uses ONE reference year (newest year in the file = 2023 since the top-up), so Kaggle ages are +1
and hand-collected ages are -3. This recomputes age per source and re-runs training + curves."""
import sys, os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'_stubs'))
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from final_c import build, RAW
from apps.ml.training import train_and_evaluate
from apps.ml.features import feature_frame
raw=pd.read_csv(RAW); raw['Listing_Year']=np.where(np.arange(len(raw))<974,2022,2026)
df,t,_=build(raw)   # build keeps Listing_Year column through
df['vehicle_age']=df['Listing_Year']-df['year']
print('ages:',df.vehicle_age.value_counts().sort_index().to_dict())
cols=['vehicle_age','mileage','resale_price','brand_code','engine_litres','body_type','recond','model_key']
res=train_and_evaluate(df[cols])
for k,v in res.items(): print(k, round(v['r2'],4), round(v['mae'],4), round(v['within_model_r2'],4), v['best_params'])
import curve9
for n,a in curve9.CARS.items():
    r,c=curve9.curve(res['gradient_boosting']['estimator'],*a)
    print(f"{n:12s} GB clamped @12/24/36/48/60: "+' '.join(f"{c[m]:.0%}" for m in (12,24,36,48,60))+f" | raw max {r.max():.2f} at m{r.argmax()}")
