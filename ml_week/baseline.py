import pandas as pd, sys
sys.path.insert(0,'.')
from build_mod import build_dataset
from training_mod import train_and_evaluate
import os
HERE=os.path.dirname(os.path.abspath(__file__))
RAW=os.environ.get('RESALE_CSV', os.path.join(HERE,'..','backend','apps','ml','data','raw','resale_car.csv'))
DER=os.path.join(HERE,'..','backend','apps','ml','data','real_historical_pricing.csv')
raw=pd.read_csv(RAW); df,stats=build_dataset(raw)
print({k:v for k,v in stats.items() if k!='brand_tiers'}); print(stats['brand_tiers'])
shipped=pd.read_csv(DER)
print('identical to shipped CSV:', df.reset_index(drop=True).equals(shipped) or (df.values==shipped.values).all())
res=train_and_evaluate(shipped)
for k,v in res.items(): print(k, round(v['r2'],4), round(v['mae'],4), v['best_params'])
