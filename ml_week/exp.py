import sys, numpy as np, pandas as pd, warnings; warnings.filterwarnings('ignore')
sys.path.insert(0,'.')
from feats import load
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.model_selection import GridSearchCV, train_test_split, GroupShuffleSplit
from sklearn.metrics import r2_score, mean_absolute_error
RF={"n_estimators":[100,200,300],"max_depth":[None,8,16]}
GB={"n_estimators":[100,200],"learning_rate":[0.05,0.1],"max_depth":[2,3,4]}
def run(df, feats, target, split='random', clip=True, label=''):
    df=df.copy()
    X=pd.get_dummies(df[feats],columns=[c for c in feats if not pd.api.types.is_numeric_dtype(df[c])],dtype=float)
    y=target(df)
    if split=='random':
        Xtr,Xte,ytr,yte=train_test_split(X,y,test_size=0.2,random_state=42)
    else:
        g=GroupShuffleSplit(n_splits=1,test_size=0.2,random_state=42); tr,te=next(g.split(X,y,groups=df['Model']))
        Xtr,Xte,ytr,yte=X.iloc[tr],X.iloc[te],y.iloc[tr],y.iloc[te]
    out={}
    for name,est,grid in [('RF',RandomForestRegressor(random_state=42),RF),('GB',GradientBoostingRegressor(random_state=42),GB)]:
        s=GridSearchCV(est,grid,cv=3,scoring='r2').fit(Xtr,ytr); p=s.best_estimator_.predict(Xte)
        out[name]=(round(r2_score(yte,p),4), round(mean_absolute_error(yte,p),4))
    print(f"{label:58s} n={len(df):4d}  RF {out['RF']}  GB {out['GB']}", flush=True)
    return out
ratio=lambda d:(d.resale_price/d.msrp_proxy).clip(upper=1.0)
BASE=['vehicle_age','mileage','brand_code','msrp_proxy']
if __name__=='__main__':
    r,_=load()
    run(r,BASE,ratio,label='0 baseline (reproduce)')
    run(r,BASE+['engine_l'],ratio,label='+ engine litres')
    run(r,BASE+['body'],ratio,label='+ body type')
    run(r,BASE+['manual'],ratio,label='+ manual gearbox')
    run(r,BASE+['recond'],ratio,label='+ recond (dual year)')
    run(r,BASE+['state'],ratio,label='+ state')
    run(r,BASE+['model_min_age'],ratio,label='+ age of model newest listing (proxy anchor)')
    run(r,BASE+['model_n'],ratio,label='+ listings per model')
    run(r,BASE+['engine_l','body','manual','recond','state'],ratio,label='+ all listing features (no anchor)')
    run(r,BASE+['engine_l','body','manual','recond','state','model_min_age'],ratio,label='+ all listing features + anchor age')
    run(r,BASE,lambda d:d.resale_price/d.msrp_proxy,label='baseline, ratio NOT clipped')
    r2,_=load(recover_model=True,drop_dup=True)
    run(r2,BASE,ratio,label='clean: recover 81 null-Model rows + drop dup')
    r3,_=load(age_from='reg')
    run(r3,BASE,ratio,label='clean: age from registration year')
    run(r,BASE,ratio,split='group',label='baseline, test split by MODEL (unseen models)')
