"""ML batch 2: the log-linear (hedonic) candidate, trained and compared with
Random Forest and Gradient Boosting on every run.

log(price) = intercept + a level per car model (model_key) + age + age² +
age x brand tier + km/10,000 + engine size + recond + brand tier + body type,
fitted with ridge regression (RidgeCV, alpha chosen on the training split).

Why it is a candidate: young listings are mostly expensive models (Alphard,
Land Cruiser, Range Rover), so a tree cannot tell "young" from "pricey model"
and its curve steps flat for the first year or two. Giving each car model its
own price level separates model mix from age, so one age/mileage effect is
learned across models and the curve is smooth by construction - the standard
econometric (hedonic) model for car depreciation. Its limit: catalog cars get
nearly the same shape, since the model-specific part is a level, not a slope.

At inference no model_key is passed (a catalog car's level is unknown, and
the curve only uses value at month m relative to month 0, so the level would
cancel anyway): every key column is 0. A key not seen in training is 0 too.

Module-level class so joblib can unpickle a saved model (apps/ml/storage.py).
Mirrors ml_week/final_d.py exactly.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV

from .features import FEATURE_COLUMNS

RIDGE_ALPHAS = np.logspace(-3, 2, 30)
BRAND_TIERS = range(1, 6)
KEY_PREFIX = "key="


def age_terms():
    """The design columns that carry the age effect (grouped as "vehicle_age"
    in an explanation)."""
    return ["vehicle_age", "age_sq"] + [f"age_x_tier{t}" for t in BRAND_TIERS]


class LogLinearDepreciationModel:
    def __init__(self):
        self.key_levels = []
        self.ridge = None

    def design(self, X, keys=None):
        """The regression's columns for feature frame X (apps.ml.features
        columns): every feature except mileage, age², km/10,000, age x tier
        1..5, then one 0/1 column per car model seen in training."""
        D = X[FEATURE_COLUMNS].astype(float).copy()
        D["age_sq"] = D["vehicle_age"] ** 2
        D["km_10k"] = D["mileage"] / 10000.0
        for tier in BRAND_TIERS:
            D[f"age_x_tier{tier}"] = D["vehicle_age"] * (D["brand_code"] == tier)
        D = D.drop(columns=["mileage"])
        K = pd.DataFrame(0.0, index=D.index, columns=[f"{KEY_PREFIX}{k}" for k in self.key_levels])
        if keys is not None:
            for index, key in zip(D.index, keys):
                column = f"{KEY_PREFIX}{key}"
                if column in K.columns:
                    K.at[index, column] = 1.0
        return pd.concat([D, K], axis=1)

    def fit(self, X, y, keys=None):
        """Without keys (an upload with no model_key column) there are no key
        columns."""
        # A blank key (NaN or "") gets no level of its own.
        self.key_levels = (
            sorted({k for k in keys if isinstance(k, str) and k.strip()}) if keys is not None else []
        )
        self.ridge = RidgeCV(alphas=RIDGE_ALPHAS).fit(self.design(X, keys), y)
        return self

    def predict(self, X, keys=None):
        return self.ridge.predict(self.design(X, keys))

    @property
    def alpha(self):
        return float(self.ridge.alpha_)
