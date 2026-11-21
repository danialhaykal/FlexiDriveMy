# ML week experiment scripts (15 Oct 2026)

Run from this folder with the backend venv's Python, e.g. `python -I baseline.py`.
They read `../backend/apps/ml/data/raw/resale_car.csv` (override with env var RESALE_CSV). Nothing in the app is changed.

- build_mod.py / training_mod.py: verbatim copies of build_real_ml_dataset.py and training.py with the Django imports stubbed.
- baseline.py: rebuilds the derived CSV, checks it equals the shipped one, reproduces run 8 (RF 0.5612, GB 0.6136).
- feats.py: richer loader (engine litres, body, gearbox, recond, state, model-key recovery).
- exp.py: ablation ladder on the current ratio target.
- exp2.py / exp3.py: log-price target; overall vs within-model R².
- exp4.py: linear model with one term per car model (within-model R² 0.75).
- curves.py: retention curves a log-price model gives the catalog cars.
- final_c.py: exact reference for ML batch 1 (build v2 + log-price training + within-model R²): 983 rows, GB R² 0.8789, within-model 0.6489.
Findings: ../FlexiDriveMy_ML_Week_Findings.md
- curve9.py / age_fix.py / hybrid.py / smooth.py (run 9 verification): import the batch's real features.py/training.py via `_stubs/` (Django models stubbed). curve9 shows run 9's curves; age_fix re-ages rows by listing year (Kaggle 2022, hand-collected 2026); smooth compares GB, monotonic RF/HistGB and a log-linear model with per-model terms.
- final_d.py: exact reference for ML batch 2 (listing year, log-linear candidate, yearly-anchor curves, curve check): RF 0.8603 / GB 0.8776 / log-linear 0.9124 (within 0.7199), only log-linear passes the curve check.
- goldens_run10.py: expected live curve values (months 12-60, standard band 15,000 km) for all 8 catalog cars from the run 10 file, and BMW 48-mo HP TCO net 197,044.35 after deploy. _stubs now hold the batch-2 features/training/log_linear/curve_check.
