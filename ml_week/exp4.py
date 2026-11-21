import sys; sys.path.insert(0,'.')
from feats import load
import numpy as np, pandas as pd, warnings; warnings.filterwarnings('ignore')
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score
r,_=load(recover_model=True,drop_dup=True)
r['lp']=np.log(r.resale_price)
def design(d):
    X=pd.DataFrame({'age':d.vehicle_age,'age2':d.vehicle_age**2,'km':d.mileage/1e4,'recond':d.recond,'manual':d.manual})
    for t in range(1,6): X[f'age_t{t}']=d.vehicle_age*(d.brand_code==t)
    X=pd.concat([X,pd.get_dummies(d.Model,prefix='m',dtype=float),pd.get_dummies(d.body,prefix='b',dtype=float)],axis=1)
    X['eng']=d.engine_l; X['tier']=d.brand_code
    return X
X=design(r); y=r.lp
idx=np.arange(len(r)); tr,te=train_test_split(idx,test_size=0.2,random_state=42)
m=RidgeCV(alphas=np.logspace(-3,2,30)).fit(X.iloc[tr],y.iloc[tr]); p=pd.Series(m.predict(X.iloc[te]),index=r.index[te])
t=r.iloc[te].copy(); t['p']=p
seen=t.Model.isin(r.iloc[tr].Model)
print('overall R2 (log price) %.4f'%r2_score(t.lp,t.p), ' seen-model share', seen.mean().round(2))
k=t[t.Model.map(t.Model.value_counts())>=2]
yd=k.lp-k.groupby('Model').lp.transform('mean'); pdd=k.p-k.groupby('Model').p.transform('mean')
print('within-model R2 %.4f on %d rows'%(r2_score(yd,pdd),len(k)))
print('MAE log %.4f'%np.abs(t.lp-t.p).mean())
print('age coef', m.coef_[:2], 'km', m.coef_[2], 'tier slopes', m.coef_[5:10])
