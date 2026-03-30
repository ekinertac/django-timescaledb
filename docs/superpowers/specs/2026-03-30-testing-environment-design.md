# Testing Environment Design

**Date:** 2026-03-30
**Scope:** Build a proper pytest-based testing environment for django-timescaledb and update CI to cover the full Python × Django compatibility matrix.

---

## Context

`django-timescaledb` is a Django database backend for TimescaleDB. The repo is at v0.2.13 and has been largely unmaintained — it targets Django 3.0 and Python 3.6–3.8. The `timescale/tests/` directory exists but all files are empty. The only real tests live in `example/metrics/tests.py` and run via Django's `manage.py test` against a live Docker DB.

The driver for this work: a production project running Python 3.9 + Django 4.2 depends on this library and cannot upgrade until django-timescaledb supports newer Django/Python versions. The solution is to add a proper test suite with broad backward compatibility coverage.

---

## Goals

1. A working local test environment: `docker-compose up && pytest`
2. Tests that cover the actual library (not the example app)
3. Frictionless local switching between Python versions via `uv`
4. Updated CI running the full Python × Django matrix automatically

---

## Compatibility Matrix

| Python | Django 4.2 | Django 5.2 (LTS) | Django 6.0 |
|--------|-----------|-----------------|-----------|
| 3.9    | ✓         | ✗               | ✗         |
| 3.10   | ✓         | ✓               | ✗         |
| 3.11   | ✓         | ✓               | ✗         |
| 3.12   | ✓         | ✓               | ✓         |
| 3.13   | ✗         | ✓               | ✓         |

Invalid combinations are excluded from the CI matrix.

---

## File Structure

```
docker-compose.yml              # TimescaleDB service for local dev
pyproject.toml                  # pytest config + test dependencies (optional-deps group: test)
Makefile                        # convenience targets
timescale/tests/
  settings.py                   # minimal Django settings module for tests
  conftest.py                   # DB URL from env, test model definition, fixtures
  test_models.py                # TimescaleModel, manager, queryset method tests
  test_schema.py                # hypertable creation/alter via SchemaEditor tests
  factories.py                  # factory_boy factories for test data
.github/workflows/
  ci-tests.yml                  # rewritten with full Python × Django matrix
```

The `example/` app is preserved as a demo but is not part of the test suite.

---

## Local Dev Setup

### docker-compose.yml
- Single service: `timescale/timescaledb:latest-pg17`
- Port: `5432:5432`
- Healthcheck: `pg_isready` so pytest waits for DB readiness
- Environment: `POSTGRES_PASSWORD`, `POSTGRES_DB`

### pyproject.toml
- `[tool.pytest.ini_options]`: sets `DJANGO_SETTINGS_MODULE = timescale.tests.settings`, `python_files = test_*.py`, `addopts = -v`
- `[project.optional-dependencies]`: `test` group includes `pytest`, `pytest-django`, `factory-boy`, `psycopg2-binary`

### timescale/tests/settings.py
- Minimal Django settings module: `INSTALLED_APPS`, `DATABASES`, `USE_TZ = True`, `DEFAULT_AUTO_FIELD`
- `DATABASES` reads `DATABASE_URL` from environment, defaults to `postgresql://postgres:password@localhost:5432/test`
- `ENGINE` set to `timescale.db.backends.postgresql`

### conftest.py
- Defines a minimal `TimescaleModel` subclass (`Metric`) for use across all tests
- Shared fixtures (e.g. `metric_factory`)

### Makefile targets
```
make db-up       # docker-compose up -d
make db-down     # docker-compose down
make test        # uv run pytest
make test-39     # uv run --python 3.9 pytest
make test-310    # uv run --python 3.10 pytest
make test-311    # uv run --python 3.11 pytest
make test-312    # uv run --python 3.12 pytest
make test-313    # uv run --python 3.13 pytest
make test-all    # runs all python version targets in sequence
```

---

## Test Suite

### timescale/tests/settings.py
- Minimal Django settings module referenced via `DJANGO_SETTINGS_MODULE`
- DB connection from `DATABASE_URL` env var, defaults to localhost:5432

### timescale/tests/conftest.py
- Minimal `Metric` model subclassing `TimescaleModel` for test fixtures
- Shared pytest fixtures

### timescale/tests/test_models.py
- `TimescaleModel` can be subclassed and has both `objects` and `timescale` managers
- `TimescaleManager` returns a `TimescaleQuerySet`
- `time_bucket(field, interval)` returns expected grouped results
- `time_bucket_ng(field, interval)` returns expected grouped results
- `time_bucket_gapfill(field, interval, start, end)` fills gaps correctly
- `histogram(field, min, max, buckets)` returns histogram data
- `to_list()` returns a plain list
- `to_list(normalise_datetimes=True)` converts bucket datetimes to ISO strings

### timescale/tests/test_schema.py
- Creating a model with `TimescaleDateTimeField` creates a hypertable (verified via `timescaledb_information.hypertables`)
- Altering `interval` on `TimescaleDateTimeField` calls `set_chunk_time_interval`
- Adding `TimescaleDateTimeField` to existing model migrates it to a hypertable

### timescale/tests/factories.py
- `MetricFactory` using `factory_boy` — creates `Metric` instances with realistic timestamps and values

---

## CI (GitHub Actions)

Rewrite `.github/workflows/ci-tests.yml`:

**Triggers:** `push` to `main`, all `pull_request` events

**Matrix:** Python 3.9–3.13 × Django 4.2, 5.2, 6.0 with invalid combos excluded

**Each job steps:**
1. Checkout code
2. Install `uv`
3. Start TimescaleDB as a service container (`timescale/timescaledb:latest-pg17`)
4. Wait for DB healthcheck
5. `uv run --python {python} --with "Django=={django}" pytest`

**Keep** the existing `python-publish.yml` unchanged.

---

## Out of Scope

- Updating the `example/` app to use pytest
- Supporting Django 5.0 or 5.1 (5.2 LTS is the representative for the 5.x line)
- PostGIS backend tests (separate concern)
- Publishing a new package version (separate step after tests pass)
