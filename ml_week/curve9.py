import sys, os; sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'_stubs'))
import warnings; warnings.filterwarnings('ignore')
import joblib, numpy as np, pandas as pd
from apps.ml.features import feature_frame
m9=joblib.load(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','backend','ml_models','model_9_gradient_boosting_20d55323.joblib'))
CARS={'BMW 320i':(2,2.0,'sedan'),'C200':(2,1.5,'sedan'),'Lexus ES250':(1,2.5,'sedan'),'911':(1,3.0,'coupe'),'Macan':(1,2.0,'suv'),'Alphard':(1,2.4,'mpv'),'XC60/XC90':(2,2.0,'suv')}
def curve(model,t,e,b,km=20000):
    rows=pd.DataFrame([dict(vehicle_age=m/12,mileage=km*m/12,brand_code=t,engine_litres=e,recond=0,body_type=b) for m in range(61)])
    f=model.predict(feature_frame(rows)); r=np.exp(f-f[0]); c=np.minimum.accumulate(np.minimum(r,1.0)); return r,c
if __name__=='__main__':
    for n,a in CARS.items():
        r,c=curve(m9,*a)
        first_drop=next((m for m in range(61) if c[m]<0.9999),None)
        print(f"{n:12s} clamped @12/24/36/48/60: "+' '.join(f"{c[m]:.0%}" for m in (12,24,36,48,60))+f" | first month below 100%: {first_drop} | raw max {r.max():.2f} at m{r.argmax()}")
