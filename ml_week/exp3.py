import sys; sys.path.insert(0,'.')
from exp import *
import numpy as np
rr,_=load(recover_model=True,drop_dup=True)
rr['model_key']=rr.Model.where(rr.model_n>=3,'other')
ATTR=['vehicle_age','mileage','brand_code','engine_l','body','manual','recond']
def within(df,feats,label):
    X=pd.get_dummies(df[feats],columns=[c for c in feats if not pd.api.types.is_numeric_dtype(df[c])],dtype=float)
    y=np.log(df.resale_price)
    idx=np.arange(len(df)); tr,te=train_test_split(idx,test_size=0.2,random_state=42)
    s=GridSearchCV(GradientBoostingRegressor(random_state=42),GB,cv=3,scoring='r2').fit(X.iloc[tr],y.iloc[tr])
    p=pd.Series(s.best_estimator_.predict(X.iloc[te]),index=df.index[te]); yt=y.iloc[te]
    t=df.iloc[te].copy(); t['y']=yt; t['p']=p
    t=t[t.Model.map(t.Model.value_counts())>=2]   # models with >=2 test listings
    yd=t.y-t.groupby('Model').y.transform('mean'); pd_=t.p-t.groupby('Model').p.transform('mean')
    print(f"{label:45s} overall R2 {r2_score(yt,p):.4f} | within-model R2 {r2_score(yd,pd_):.4f} on {len(t)} test rows / {t.Model.nunique()} models", flush=True)
within(rr,ATTR,'H2 attributes')
within(rr,ATTR+['model_key'],'H3 attributes + model key')
