import sys, os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'_stubs'))
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from final_c import build, RAW
from apps.ml.features import feature_frame, FEATURE_COLUMNS
from apps.ml.training import within_model_r2
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor, GradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.metrics import r2_score
import curve9
raw=pd.read_csv(RAW); raw['Listing_Year']=np.where(np.arange(len(raw))<974,2022,2026)
df,_,_=build(raw); df['vehicle_age']=df['Listing_Year']-df['year']; df=df.reset_index(drop=True)
X=feature_frame(df); y=np.log(df.resale_price)
idx=np.arange(len(df)); tr,te=train_test_split(idx,test_size=0.2,random_state=42)
mono=[-1 if c in('vehicle_age','mileage') else 0 for c in FEATURE_COLUMNS]
def lin_design(Xf, keys, key_levels):
    D=Xf.copy(); D['age2']=D.vehicle_age**2; D['km']=D.mileage/1e4
    for t in range(1,6): D[f'age_t{t}']=D.vehicle_age*(D.brand_code==t)
    K=pd.get_dummies(pd.Categorical(keys,categories=key_levels),prefix='k',dtype=float); K.index=D.index
    return pd.concat([D.drop(columns=['mileage']),K],axis=1)
cands={
 'GB (run 9 setup)':GridSearchCV(GradientBoostingRegressor(random_state=42),{"n_estimators":[100,200],"learning_rate":[0.05,0.1],"max_depth":[2,3,4]},cv=3,scoring='r2'),
 'RF monotonic':GridSearchCV(RandomForestRegressor(random_state=42,monotonic_cst=mono),{"n_estimators":[100,200,300],"max_depth":[None,8,16]},cv=3,scoring='r2'),
 'HistGB monotonic':GridSearchCV(HistGradientBoostingRegressor(random_state=42,monotonic_cst=mono),{"max_iter":[100,200],"learning_rate":[0.05,0.1],"max_depth":[2,3,4]},cv=3,scoring='r2'),
}
fitted={}
for n,c in cands.items():
    c.fit(X.iloc[tr],y.iloc[tr]); p=c.best_estimator_.predict(X.iloc[te]); fitted[n]=c.best_estimator_
    print(f"{n:18s} R2 {r2_score(y.iloc[te],p):.4f}  within {within_model_r2(df.model_key.iloc[te].values,y.iloc[te].values,p):.4f}  {c.best_params_}")
levels=sorted(df.model_key.unique())
Ltr=lin_design(X.iloc[tr],df.model_key.iloc[tr],levels); Lte=lin_design(X.iloc[te],df.model_key.iloc[te],levels)
lin=RidgeCV(alphas=np.logspace(-3,2,30)).fit(Ltr,y.iloc[tr]); p=lin.predict(Lte)
print(f"{'Log-linear + model':18s} R2 {r2_score(y.iloc[te],p):.4f}  within {within_model_r2(df.model_key.iloc[te].values,y.iloc[te].values,p):.4f}")
def ycurve(fn,t,e,b,km=20000):
    rows=pd.DataFrame([dict(vehicle_age=yy,mileage=km*yy,brand_code=t,engine_litres=e,recond=0,body_type=b) for yy in range(6)])
    return fn(feature_frame(rows))
linfn=lambda F: lin.predict(lin_design(F,['__none__']*len(F),levels))
print('\nPure-ML retention vs age 0 at years 1..5 (20,000 km/yr):')
for n,a in curve9.CARS.items():
    line=f"{n:12s}"
    for name,fn in [('GB',fitted['GB (run 9 setup)'].predict),('RFm',fitted['RF monotonic'].predict),('HGBm',fitted['HistGB monotonic'].predict),('Lin',linfn)]:
        f=ycurve(fn,*a); r=np.minimum.accumulate(np.minimum(np.exp(f-f[0]),1))[1:]
        line+=f" | {name} "+'/'.join(f"{v*100:.0f}" for v in r)
    print(line)
