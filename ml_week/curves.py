import sys; sys.path.insert(0,'.')
from feats import load
import numpy as np, pandas as pd, warnings; warnings.filterwarnings('ignore')
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import GridSearchCV
from exp import GB
r,tiers=load(recover_model=True,drop_dup=True)
F=['vehicle_age','mileage','brand_code','engine_l','body','manual','recond']
X=pd.get_dummies(r[F],columns=['body'],dtype=float); y=np.log(r.resale_price)
m=GridSearchCV(GradientBoostingRegressor(random_state=42),GB,cv=3,scoring='r2').fit(X,y).best_estimator_
print('ages in data:', r.vehicle_age.value_counts().sort_index().to_dict())
cars={'BMW 320i (t2,2.0,sedan)':(tiers['BMW'],2.0,'sedan'),'Mercedes C200 (t2,1.5,sedan)':(tiers['Mercedes-Benz'],1.5,'sedan'),
'Lexus ES250 (t1,2.5,sedan)':(tiers['Lexus'],2.5,'sedan'),'Porsche Macan (t1,2.0,suv)':(tiers['Porsche'],2.0,'suv'),
'Toyota Alphard (t1,2.4,mpv)':(tiers['Toyota'],2.4,'mpv'),'Porsche 911 (t1,3.0,coupe)':(tiers['Porsche'],3.0,'coupe'),'Volvo XC90 (t2,2.0,suv)':(tiers['Volvo'],2.0,'suv')}
cols=X.columns
for name,(t,e,b) in cars.items():
    rows=[]
    for yr in [0,1,2,3,4,5]:
        d={c:0.0 for c in cols}; d.update(vehicle_age=yr,mileage=20000*yr,brand_code=t,engine_l=e); d['body_'+b]=1.0; rows.append(d)
    p=m.predict(pd.DataFrame(rows)[cols]); ret=np.exp(p-p[0])
    print(f"{name:32s} retention vs age0 @1..5y: "+' '.join(f"{v:.0%}" for v in ret[1:])+f"   (age0 pred RM{np.exp(p[0]):,.0f})")
