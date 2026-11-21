import sys; sys.path.insert(0,".")
from exp import *
import numpy as np
r,_=load(); rr,_=load(recover_model=True,drop_dup=True)
logp=lambda d:np.log(d.resale_price)
ATTR=['vehicle_age','mileage','brand_code','engine_l','body','manual','recond']
run(r,['vehicle_age','mileage','brand_code'],logp,label='H1 log price: age, mileage, tier')
run(r,ATTR,logp,label='H2 log price: + engine, body, gearbox, recond')
run(rr,ATTR,logp,label='H2 on cleaned 998 rows')
run(rr,ATTR,logp,split='group',label='H2 cleaned, split by MODEL (unseen models)')
rr['model_key']=rr.Model.where(rr.model_n>=3,'other')
run(rr,ATTR+['model_key'],logp,label='H3 + model key (models with >=3 listings)')
run(rr,ATTR+['brand'],logp,label='H4 + brand name instead of key')
run(rr,ATTR+['brand'],logp,split='group',label='H4 split by MODEL')
