"""Reference for ML batch 2: per-row listing year + log-linear candidate + yearly-anchor curves + curve check.
Uses the batch-1 features.py/training.py (via _stubs) for RF/GB exactly as the app does."""
import sys, os; HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE); sys.path.insert(0,os.path.join(HERE,'_stubs'))
import warnings; warnings.filterwarnings('ignore')
import numpy as np, pandas as pd
from final_c import build, RAW
from apps.ml.features import feature_frame, FEATURE_COLUMNS
from apps.ml.training import train_and_evaluate, within_model_r2
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error

KAGGLE_LISTING_YEAR, HAND_LISTING_YEAR = 2022, 2026
ALPHAS = np.logspace(-3, 2, 30)

class LogLinearDepreciationModel:
    """log(price) = intercept + per-model level + age, age^2, age x tier, km/10,000, engine, recond, tier, body."""
    def __init__(self): self.key_levels=[]; self.ridge=None
    def design(self, X, keys=None):
        D = X[FEATURE_COLUMNS].astype(float).copy()
        D['age_sq'] = D['vehicle_age']**2
        D['km_10k'] = D['mileage']/10000.0
        for t in range(1,6): D[f'age_x_tier{t}'] = D['vehicle_age']*(D['brand_code']==t)
        D = D.drop(columns=['mileage'])
        K = pd.DataFrame(0.0, index=D.index, columns=[f'key={k}' for k in self.key_levels])
        if keys is not None:
            for i,k in zip(D.index, keys):
                c=f'key={k}'
                if c in K.columns: K.at[i,c]=1.0
        return pd.concat([D,K],axis=1)
    def fit(self, X, y, keys):
        self.key_levels = sorted(set(keys))
        self.ridge = RidgeCV(alphas=ALPHAS).fit(self.design(X,keys), y); return self
    def predict(self, X, keys=None):
        return self.ridge.predict(self.design(X,keys))

def build_v3(raw):
    raw=raw.copy()
    n=len(raw); hand = raw['Monthly_Installment'].isna()
    assert hand.sum()==30 and hand.iloc[974:].all() and not hand.iloc[:974].any()
    raw['Listing_Year']=np.where(hand, HAND_LISTING_YEAR, KAGGLE_LISTING_YEAR)
    df,tiers,_=build(raw); df['vehicle_age']=df['Listing_Year']-df['year']
    return df.reset_index(drop=True), tiers

def train_log_linear(df, random_state=42):
    X=feature_frame(df); y=np.log(df.resale_price.astype(float)); keys=df.model_key.values
    Xtr,Xte,ytr,yte,ktr,kte=train_test_split(X,y,keys,test_size=0.2,random_state=random_state)
    m=LogLinearDepreciationModel().fit(Xtr,ytr,list(ktr)); p=m.predict(Xte,list(kte))
    return m, dict(r2=r2_score(yte,p), mae=mean_absolute_error(yte,p), within=within_model_r2(kte,yte.values,p), alpha=float(m.ridge.alpha_))

CATALOG={'BMW 320i':(2,2.0,'sedan',265800),'Lexus ES 250':(1,2.5,'sedan',356888),'Mercedes C200':(2,1.5,'sedan',292888),
 'Porsche 911':(1,3.0,'coupe',1430000),'Porsche Macan':(1,2.0,'suv',469000),'Toyota Alphard':(1,2.4,'mpv',548000),
 'Volvo XC60':(2,2.0,'suv',328888),'Volvo XC90':(2,2.0,'suv',434888)}
def yearly_logs(model,tier,litres,body,km):
    rows=pd.DataFrame([dict(vehicle_age=y,mileage=km*y,brand_code=tier,engine_litres=litres,recond=0,body_type=body) for y in range(6)])
    return np.asarray(model.predict(feature_frame(rows)),dtype=float)
def monthly_ratio(logs):
    out=[]
    for m in range(61):
        y0=m//12; w=(m-12*y0)/12
        f = logs[y0] if y0==5 else logs[y0]+(logs[y0+1]-logs[y0])*w
        out.append(np.exp(f-logs[0]))
    r=np.minimum.accumulate(np.minimum(np.array(out),1.0)); return r
def curve_problems(model,km=15000,tol=0.01,max12=0.95,lo60=0.20,hi60=0.75):
    probs=[]
    for name,(t,l,b,_) in CATALOG.items():
        logs=yearly_logs(model,t,l,b,km)
        for y in range(5):
            if logs[y+1]>logs[y]+tol: probs.append(f"{name}: value rises from year {y} to {y+1}")
        r12=np.exp(logs[1]-logs[0]); r60=np.exp(min(logs[5],logs[0])-logs[0])
        if r12>max12: probs.append(f"{name}: keeps {r12:.0%} after 12 months (limit {max12:.0%})")
        if not lo60<=r60<=hi60: probs.append(f"{name}: keeps {r60:.0%} after 60 months (allowed {lo60:.0%}-{hi60:.0%})")
    return probs
if __name__=='__main__':
    df,tiers=build_v3(pd.read_csv(RAW))
    print('rows',len(df),'ages',df.vehicle_age.value_counts().sort_index().to_dict())
    cols=['vehicle_age','mileage','resale_price','brand_code','engine_litres','body_type','recond','model_key']
    res=train_and_evaluate(df[cols])
    for k,v in res.items(): print(f"{k:18s} R2 {v['r2']:.4f} MAE {v['mae']:.4f} within {v['within_model_r2']:.4f} {v['best_params']}")
    ll,met=train_log_linear(df[cols]); print(f"{'log_linear':18s} R2 {met['r2']:.4f} MAE {met['mae']:.4f} within {met['within']:.4f} alpha {met['alpha']:.6g}")
    for name,model in [('gradient_boosting',res['gradient_boosting']['estimator']),('random_forest',res['random_forest']['estimator']),('log_linear',ll)]:
        p=curve_problems(model); print(f"curve check {name}: {'PASS' if not p else 'FAIL'}"+('' if not p else ' - '+'; '.join(p[:4])+(f' (+{len(p)-4} more)' if len(p)>4 else '')))
    print('\nlog_linear curves at 15,000 km/yr (standard band), months 12/24/36/48/60:')
    for name,(t,l,b,msrp) in CATALOG.items():
        r=monthly_ratio(yearly_logs(ll,t,l,b,15000))
        print(f"  {name:15s} "+' '.join(f"{r[m]*100:.2f}%" for m in (12,24,36,48,60))+f"  | RM at 60: {msrp*r[60]:,.2f}")
    print('coef age, age_sq, km_10k:', {c:round(v,5) for c,v in zip(ll.design(feature_frame(df.head(1)),None).columns, ll.ridge.coef_) if c in ('vehicle_age','age_sq','km_10k') or c.startswith('age_x')})
