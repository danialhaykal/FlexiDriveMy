import sys, os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'_stubs'))
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd, joblib
from final_c import build, RAW
from apps.ml.training import train_and_evaluate
from apps.ml.features import feature_frame
import curve9
raw=pd.read_csv(RAW); raw['Listing_Year']=np.where(np.arange(len(raw))<974,2022,2026)
df,_,_=build(raw); df['vehicle_age']=df['Listing_Year']-df['year']
cols=['vehicle_age','mileage','resale_price','brand_code','engine_litres','body_type','recond','model_key']
res=train_and_evaluate(df[cols]); gb=res['gradient_boosting']['estimator']; rf=res['random_forest']['estimator']
m9=joblib.load(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','backend','ml_models','model_9_gradient_boosting_20d55323.joblib'))
R12=0.77; FB={12:.77,24:.61,36:.50,48:.42,60:.35}
def yearly(model,t,e,b,km=20000):
    rows=pd.DataFrame([dict(vehicle_age=y,mileage=km*y,brand_code=t,engine_litres=e,recond=0,body_type=b) for y in range(6)])
    return model.predict(feature_frame(rows))
for label,model in [('run9 model (as built)',m9),('age-fixed GB',gb),('age-fixed RF',rf)]:
    print('==',label,'| hybrid: month12 = policy 77%, then ML change from year 1, yearly anchors, running min')
    for n,a in curve9.CARS.items():
        f=yearly(model,*a)
        rel=np.exp(f[1:]-f[1]); val=np.minimum.accumulate(np.minimum(R12*rel,R12))
        pure=np.minimum.accumulate(np.minimum(np.exp(f-f[0]),1))[1:]
        print(f"  {n:12s} hybrid 12/24/36/48/60: "+' '.join(f"{v:.0%}" for v in val)+"   | pure-ML yearly: "+' '.join(f"{v:.0%}" for v in pure))
print('fallback BMW standard:', FB)
