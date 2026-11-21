import re, numpy as np, pandas as pd
from build_mod import parse_price, parse_mileage, extract_brand, compute_brand_tiers, compute_msrp_proxy, MIN_LISTINGS_FOR_MODEL_PROXY
import os
RAW=os.environ.get('RESALE_CSV', os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','backend','apps','ml','data','raw','resale_car.csv'))
BODY_RE=re.compile(r'\b(Sedan|Hatchback|SUV|MPV|Pickup Truck|Coupe|Convertible|Wagon|Van)\b',re.I)
BRANDS2=['Land Rover','Mercedes-Benz','Alfa Romeo','Mini','MINI']
def brand_from_desc(desc):
    m=re.match(r'^\d{4}(?:/\d{4})?\s+(.*)$',str(desc)); rest=m.group(1) if m else str(desc)
    w=rest.split()
    if len(w)>1 and w[0]=='Land' and w[1]=='Rover': return 'Land Rover',' '.join(w[:3])
    return w[0], ' '.join(w[:2])
def load(recover_model=False, drop_dup=False, age_from='first'):
    r=pd.read_csv(RAW)
    r['row_id']=np.arange(len(r)); r['handcollected']=r['row_id']>=974
    if drop_dup: r=r.drop_duplicates(subset=[c for c in r.columns if c not in('row_id','handcollected')])
    r['resale_price']=r['List_Price'].apply(parse_price); r=r[r.resale_price.notna()]
    if recover_model:
        miss=r.Model.isna()
        rec=r.loc[miss,'Description'].apply(brand_from_desc)
        r.loc[miss,'Model']=rec.str[1]
    r=r[r.Model.notna()].copy()
    yrs=r.Description.str.extract(r'^(\d{4})(?:/(\d{4}))?')
    r['year_mfg']=yrs[0].astype(float); r['year_reg']=yrs[1].astype(float).fillna(r['year_mfg'])
    r['recond']=yrs[1].notna().astype(int)
    r['year']=r['year_mfg'] if age_from=='first' else r['year_reg']
    ref=int(r['year'].max()); r['vehicle_age']=ref-r['year']
    r['brand']=r.Model.apply(extract_brand)
    r['mileage']=r.Milleage.apply(parse_mileage)
    med=r.groupby('brand')['resale_price'].median(); tiers=compute_brand_tiers(med)
    r['brand_code']=r.brand.map(tiers)
    r['msrp_proxy']=compute_msrp_proxy(r.Model,r.brand,r.resale_price,med)
    r['model_n']=r.Model.map(r.Model.value_counts())
    r['engine_l']=r.Description.str.extract(r'\s(\d\.\d)\s')[0].astype(float)
    r['engine_l']=r['engine_l'].fillna(r.groupby('Model')['engine_l'].transform('median')).fillna(r['engine_l'].median())
    b=r.Description.str.extract(BODY_RE)[0].str.lower().fillna('other'); r['body']=b
    r['manual']=(r.Gear_Type=='Manual').astype(int)
    r['state']=r.Location.str.split(',').str[0].str.strip()
    # age of the newest listing of the same model (how 'new' the proxy anchor is)
    r['model_min_age']=r.groupby('Model')['vehicle_age'].transform('min')
    r=r[(r.resale_price>0)&r.mileage.notna()&(r.mileage>=0)&(r.vehicle_age>=0)&r.msrp_proxy.notna()&(r.msrp_proxy>0)]
    return r.reset_index(drop=True), tiers
