"""Option (c) candidate: log resale price from attributes only. Mirrors what the ML batch asks to build."""
import sys, os, re; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, warnings; warnings.filterwarnings('ignore')
from build_mod import parse_price, parse_mileage, extract_brand, compute_brand_tiers
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.model_selection import GridSearchCV, train_test_split
from sklearn.metrics import r2_score, mean_absolute_error
RAW=os.environ.get('RESALE_CSV', os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','backend','apps','ml','data','raw','resale_car.csv'))
BODY_MAP={'sedan':'sedan','hatchback':'hatchback','suv':'suv','crossover':'suv','mpv':'mpv','van':'mpv','pickup truck':'pickup','pickup':'pickup','coupe':'coupe','convertible':'coupe','wagon':'hatchback'}
BODY_RE=re.compile(r'\b(Sedan|Hatchback|SUV|MPV|Pickup Truck|Coupe|Convertible|Wagon|Van|Crossover)\b',re.I)
def normalise_key(model):
    out=[]
    for w in str(model).split():
        if re.fullmatch(r'\d\.\d',w): break
        out.append(w)
    return ' '.join(out)
def build(raw):
    df=raw.copy(); df=df.drop_duplicates()
    df['resale_price']=df.List_Price.apply(parse_price); df=df[df.resale_price.notna()]
    known=set(df.Model.dropna().apply(extract_brand))
    def recover(desc):
        rest=re.sub(r'^\d{4}(?:/\d{4})?\s+','',str(desc)); w=rest.split()
        if len(w)>=3 and w[0]=='Land' and w[1]=='Rover': brand,model=('Land Rover',' '.join(w[:3]))
        elif len(w)>=2: brand,model=(w[0],' '.join(w[:2]))
        else: return None
        return model if brand in known else None
    miss=df.Model.isna(); df.loc[miss,'Model']=df.loc[miss,'Description'].apply(recover)
    df=df[df.Model.notna()].copy()
    df['model_key']=df.Model.apply(normalise_key)
    y=df.Description.str.extract(r'^(\d{4})(?:/(\d{4}))?')
    df['year']=y[0].astype(int); df['recond']=y[1].notna().astype(int)
    df['vehicle_age']=df.year.max()-df.year
    df['brand']=df.Model.apply(extract_brand)
    df['mileage']=df.Milleage.apply(parse_mileage)
    tiers=compute_brand_tiers(df.groupby('brand').resale_price.median()); df['brand_code']=df.brand.map(tiers)
    df['engine_litres']=df.Description.str.extract(r'\s(\d\.\d)\s')[0].astype(float)
    df['body_type']=df.Description.str.extract(BODY_RE)[0].str.lower().map(BODY_MAP)
    n0=len(df); df=df[df.engine_litres.notna()&df.body_type.notna()&df.mileage.notna()&(df.resale_price>0)&(df.vehicle_age>=0)]
    return df.reset_index(drop=True), tiers, n0-len(df)
FEATS=['vehicle_age','mileage','brand_code','engine_litres','body_type','recond']
BODIES=['sedan','hatchback','suv','mpv','pickup','coupe']
def X_of(d):
    X=d[['vehicle_age','mileage','brand_code','engine_litres','recond']].astype(float).copy()
    for b in BODIES: X['body_'+b]=(d.body_type==b).astype(float)
    return X
if __name__=='__main__':
    raw=pd.read_csv(RAW); df,tiers,dropped=build(raw)
    print('rows',len(df),'dropped for missing engine/body',dropped)
    X=X_of(df); y=np.log(df.resale_price)
    idx=np.arange(len(df)); tr,te=train_test_split(idx,test_size=0.2,random_state=42)
    RF={"n_estimators":[100,200,300],"max_depth":[None,8,16]}; GB={"n_estimators":[100,200],"learning_rate":[0.05,0.1],"max_depth":[2,3,4]}
    for name,est,grid in [('RF',RandomForestRegressor(random_state=42),RF),('GB',GradientBoostingRegressor(random_state=42),GB)]:
        s=GridSearchCV(est,grid,cv=3,scoring='r2').fit(X.iloc[tr],y.iloc[tr]); p=s.best_estimator_.predict(X.iloc[te])
        t=df.iloc[te].copy(); t['y']=y.iloc[te].values; t['p']=p
        k=t[t.model_key.map(t.model_key.value_counts())>=2]
        wr2=r2_score(k.y-k.groupby('model_key').y.transform('mean'), k.p-k.groupby('model_key').p.transform('mean'))
        print(f"{name}: R2(log price) {r2_score(t.y,t.p):.4f}  MAE(log) {mean_absolute_error(t.y,t.p):.4f} (~{(np.exp(mean_absolute_error(t.y,t.p))-1)*100:.1f}% of price)  within-model R2 {wr2:.4f} on {len(k)} rows/{k.model_key.nunique()} models  best {s.best_params_}")
