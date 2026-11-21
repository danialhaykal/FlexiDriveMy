import sys; import os; sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'_stubs'))
import warnings; warnings.filterwarnings('ignore')
import joblib, math, numpy as np
from decimal import Decimal, ROUND_HALF_UP
from apps.ml.features import car_feature_frame
m=joblib.load(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','backend','ml_models','model_10_log_linear_642b0bf2.joblib'))
CARS={5:('BMW 320i',265800,dict(brand_code=2,engine_litres=2.0,body_type='sedan')),7:('Lexus ES',356888,dict(brand_code=1,engine_litres=2.5,body_type='sedan')),
6:('C200',292888,dict(brand_code=2,engine_litres=1.5,body_type='sedan')),12:('911',1430000,dict(brand_code=1,engine_litres=3.0,body_type='coupe')),
8:('Macan',469000,dict(brand_code=1,engine_litres=2.0,body_type='suv')),17:('Alphard',548000,dict(brand_code=1,engine_litres=2.4,body_type='mpv')),
14:('XC60',328888,dict(brand_code=2,engine_litres=2.0,body_type='suv')),13:('XC90',434888,dict(brand_code=2,engine_litres=2.0,body_type='suv'))}
def curve(car,msrp,km):
    y=np.asarray(m.predict(car_feature_frame(car,km,range(6))),float)
    vals=[]; ceil=float(msrp)
    for mo in range(61):
        yr=min(mo//12,5); w=(mo-12*yr)/12; nx=min(yr+1,5); f=y[yr]+w*(y[nx]-y[yr])
        v=msrp*math.exp(f-y[0]); ceil=min(v,ceil); vals.append(Decimal(str(ceil)).quantize(Decimal('0.01'),ROUND_HALF_UP))
    return vals
if __name__=='__main__':
    for vid,(n,msrp,car) in CARS.items():
        c=curve(car,msrp,15000)
        print(f"{vid:2d} {n:9s} standard: m12 {c[12]} m24 {c[24]} m36 {c[36]} m48 {c[48]} m60 {c[60]}")
    c=curve(CARS[5][2],265800,15000); print('BMW 48mo HP TCO net expected = 331699.64 -', c[60], '=', Decimal('331699.64')-c[60])
