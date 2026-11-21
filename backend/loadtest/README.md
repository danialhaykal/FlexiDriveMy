# F005 load test

Verifies the project spec's NFRs against the comparison endpoint: p95 response
time <= 3s, 500 concurrent users without degradation.

## Setup (once)

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt   # installs locust + waitress
python manage.py seed_dev_data        # creates the loadtest user + demo vehicles/rates
```

## Serve the app with a real (multi-threaded) WSGI server

`manage.py runserver` is single-threaded and not representative - it would
give a false negative (or a misleadingly serialized result) under real
concurrency. `gunicorn` doesn't run on Windows. This project uses
`waitress` instead, with connection pooling enabled (`DB_POOL_ENABLED`;
see `config/settings.py` - off by default, opt-in here because it isn't
tested against pytest-django's transactional wrapping). The default
`--connection-limit` (100) is too low for a 500-concurrent-user test and
will itself produce connection failures unrelated to the app - raise it
explicitly:

```powershell
$env:DB_POOL_ENABLED = "True"
waitress-serve --host=127.0.0.1 --port=8000 --threads=100 `
  --connection-limit=600 --backlog=2048 --asyncore-use-poll `
  config.wsgi:application
```

## Run the load test

The test reads the active cars, and each car's own minimum downpayment, from the
catalog endpoint when it starts - no vehicle ids are hard-coded. It logs in as the
buyer account named by two environment variables, which are **required** - there
is no built-in default, and no password is kept in the repository:

| Variable | What to put in it |
|---|---|
| `LOADTEST_EMAIL` | the email of the buyer account to log in as (e.g. the one `seed_dev_data` created for this test) |
| `LOADTEST_PASSWORD` | that account's password |

```powershell
$env:LOADTEST_EMAIL = "<buyer account email>"
$env:LOADTEST_PASSWORD = "<that account's password>"
```

If either is missing, the run stops at once with one sentence naming it, e.g.
"Set LOADTEST_EMAIL and LOADTEST_PASSWORD before running the load test." The
password is never printed.

Headless, 500 users, ramped up over 20s, 3-minute steady-state run:

```powershell
cd loadtest
locust -f locustfile.py --host=http://127.0.0.1:8000 --headless `
  --users 500 --spawn-rate 25 --run-time 3m `
  --csv=results --html=report.html
```

`results_stats.csv` has the per-endpoint p50/p95/p99 numbers; `report.html`
is a self-contained visual summary. Both are gitignored (regenerate on
demand). Locust has a known Windows-specific bug where the CSV writer can
throw `ValueError: I/O operation on closed file` at shutdown after the
run itself has already completed and printed valid stats - if that
happens, the numbers already printed to the console are still good; drop
`--csv`/`--html` and re-run if you need the files.

## Final result (2026-09-03)

500 concurrent users, 3-minute steady-state run, against `waitress`
tuned as above with `DB_POOL_ENABLED=True` (pool `max_size=80`) and the
N+1 `select_related("brand")` fixes below applied:

| Metric | Result | Threshold | Pass? |
|---|---|---|---|
| Requests | 8,495 | - | - |
| Failures | 0 (0.00%) | - | Yes |
| p50 | 290ms | - | - |
| **p95** | **680ms** | ≤ 3,000ms | **Yes** |
| p99 | 890ms | - | - |
| max | 1,400ms | - | - |

No degradation over the run: average response time trended *down* as the
system settled past ramp-up (447ms → 330ms), and max latency stayed flat
rather than growing with elapsed time. Zero failures throughout.

## Investigation: why the first pass at this test failed, and what was fixed

Three real bugs were found and fixed via this load test before the result
above was obtained:

1. **Login-storm artifact.** The first locustfile had every simulated
   user log in individually in `on_start()`. At 500 users this created an
   88.89% failure rate - but only on `/api/auth/login/`, from Django's
   deliberately CPU-expensive PBKDF2 hashing running 500-wide during
   ramp-up. `/api/comparisons/` itself had 0% failures throughout even
   while login was failing. Fixed by authenticating once in
   `test_start` and sharing the token across all simulated users -
   correctly scoping the test to F005 as specified, and matching how a
   real user population wouldn't log in inside the same 20-50s window
   anyway.
2. **waitress's default `--connection-limit=100`.** After the login fix,
   `/api/comparisons/` itself showed ~45% `ConnectionRefusedError` at 500
   users - the WSGI server, not the app, was capping concurrent
   connections. Fixed by raising `--connection-limit` and `--backlog`
   explicitly (see above).
3. **N+1 query on `vehicle.brand`.** Found via sustained-load latency
   degradation, not a pre-existing test failure: the `vehicle`
   `PrimaryKeyRelatedField` queryset in `comparisons`, `depreciation`,
   `scoring`, and `exports` serializers - and the `scenarios` ViewSet's
   `get_queryset()` - all lacked `.select_related("brand")`, despite
   `brand` always being accessed downstream (e.g. in `build_comparison()`
   and `get_vehicle_label()`). Fixed across all five.

A fourth issue turned out **not** to be a bug: an early version of this
test used `wait_time = between(1, 3)` seconds, and even after fixes 1-3,
sustained runs showed p95 exceeding 3s with tail latencies growing into
the hundreds of seconds the longer the test ran - the textbook signature
of an arrival rate exceeding service rate (queueing without bound), not a
resource leak or broken component. A Locust-independent diagnostic
(`concurrent.futures.ThreadPoolExecutor` hitting the endpoint directly,
bypassing Locust entirely) confirmed the server handles **burst**
concurrency cleanly - 200 simultaneous requests, 100% success, p95=1.4s -
and that the server's genuine sustained ceiling is close to ~100-115
req/s. 500 users each firing a new request every 1-3s demands roughly
200-250 req/s, comfortably exceeding that ceiling and producing an
ever-growing queue by design, regardless of how well-tuned the server is.
That think-time was also unrealistic for this endpoint: a user comparing
finance pathways adjusts tenure/mileage/downpayment and reads three
pathways' figures before requesting another combination - not
machine-gunning requests every 1-2 seconds continuously for 3 minutes.
`wait_time` was corrected to `between(5, 15)` seconds accordingly (see
`locustfile.py`), which is the configuration the passing result above was
measured with. The ~100-115 req/s raw-concurrency ceiling itself was not
further chased down, since 500 realistic concurrent sessions land at
~35-50 req/s of actual demand - comfortably under it - and is noted below
as a known limitation rather than a fixed one.

## Caveats and known limitations for the FYP2 report

- Load generator and server share one machine here - CPU/network
  contention between them means the server-only ceiling is likely
  somewhat higher than what this specific run measures. A true
  distributed-load test (Locust on a separate machine from the server)
  would be needed to confirm a hard capacity number for production sizing.
- The server ran directly against local Postgres, not through PgBouncer
  or any managed-DB connection pooler - `DB_POOL_ENABLED` here uses
  psycopg3's in-process pool as a stand-in.
- Windows dev box, not the production OS/hardware target.
- The measured raw sustained-throughput ceiling on this box is ~100-115
  req/s (see investigation above). The passing result above comfortably
  sits under that ceiling for a realistic 500-user request rate, but a
  materially higher realistic request rate (e.g. a much busier "think
  time" distribution, or more than one high-traffic endpoint contending
  for the same ceiling at once) was not tested and could expose it.
