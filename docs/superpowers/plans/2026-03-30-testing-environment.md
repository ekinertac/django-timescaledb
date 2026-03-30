# Testing Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pytest-based test suite with Docker Compose local dev, uv-based Python switching, and GitHub Actions CI covering Python 3.9–3.13 × Django 4.2/5.2/6.0.

**Architecture:** Tests live in `timescale/tests/` as a Django app. `--no-migrations` lets pytest-django create tables directly via `TimescaleSchemaEditor`, so hypertable creation is exercised on every test run. `uv` handles Python version switching locally; CI mirrors the same commands in a matrix.

**Tech Stack:** pytest, pytest-django, factory-boy, uv, Docker Compose, GitHub Actions

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `docker-compose.yml` | Create | TimescaleDB service for local dev |
| `pyproject.toml` | Create | pytest config + test optional-deps |
| `Makefile` | Create | `db-up/down`, `test`, `test-39` … `test-all` |
| `timescale/tests/__init__.py` | Modify | register AppConfig |
| `timescale/tests/apps.py` | Create | AppConfig with label `timescale_tests` |
| `timescale/tests/settings.py` | Create | minimal Django settings for tests |
| `timescale/tests/models.py` | Create | `Metric` and `AnotherMetric` test models |
| `timescale/tests/factories.py` | Modify | `MetricFactory` via factory-boy |
| `timescale/tests/conftest.py` | Modify | shared pytest fixtures |
| `timescale/tests/test_models.py` | Modify | manager / queryset method tests |
| `timescale/tests/test_schema.py` | Create | hypertable creation and alter tests |
| `.github/workflows/ci-tests.yml` | Modify | full Python × Django matrix |
| `setup.cfg` | Modify | update classifiers |

---

## Task 1: Docker Compose

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Write docker-compose.yml**

```yaml
services:
  timescaledb:
    image: timescale/timescaledb:latest-pg17
    environment:
      POSTGRES_PASSWORD: password
      POSTGRES_DB: test
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 10
```

- [ ] **Step 2: Start DB and verify it becomes healthy**

```bash
docker compose up -d
docker compose ps
```

Expected: `timescaledb` service shows `healthy` (may take ~15s).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose for local TimescaleDB dev"
```

---

## Task 2: pytest scaffold (pyproject.toml + settings + app config)

**Files:**
- Create: `pyproject.toml`
- Create: `timescale/tests/settings.py`
- Create: `timescale/tests/apps.py`
- Modify: `timescale/tests/__init__.py`

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "django-timescaledb"
version = "0.2.13"

[project.optional-dependencies]
test = [
    "pytest>=7.4",
    "pytest-django>=4.7",
    "factory-boy>=3.3",
    "psycopg2-binary>=2.9",
    "Django>=4.2",
    "python-dateutil>=2.8",
]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "timescale.tests.settings"
addopts = "--no-migrations -v"
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

- [ ] **Step 2: Write timescale/tests/settings.py**

```python
import os

DATABASES = {
    'default': {
        'ENGINE': 'timescale.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'test'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'password'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.postgres',
    'timescale.tests',
]

USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SECRET_KEY = 'test-secret-key-not-for-production'
```

- [ ] **Step 3: Write timescale/tests/apps.py**

```python
from django.apps import AppConfig


class TimescaleTestsConfig(AppConfig):
    name = 'timescale.tests'
    label = 'timescale_tests'
```

- [ ] **Step 4: Update timescale/tests/__init__.py**

Replace the file content with:

```python
default_app_config = 'timescale.tests.apps.TimescaleTestsConfig'
```

- [ ] **Step 5: Verify pytest collects zero tests without errors**

```bash
uv run --extra test pytest --collect-only
```

Expected output contains `no tests ran` with no import errors or Django misconfiguration warnings.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml timescale/tests/settings.py timescale/tests/apps.py timescale/tests/__init__.py
git commit -m "feat: add pytest-django scaffold with test settings and app config"
```

---

## Task 3: Test models

**Files:**
- Create: `timescale/tests/models.py`

- [ ] **Step 1: Write timescale/tests/models.py**

```python
from django.db import models

from timescale.db.models.fields import TimescaleDateTimeField
from timescale.db.models.managers import TimescaleManager
from timescale.db.models.models import TimescaleModel


class Metric(models.Model):
    """
    Test model using TimescaleDateTimeField directly (mirrors production usage pattern).
    Table name: timescale_tests_metric
    """
    time = TimescaleDateTimeField(interval='1 day')
    temperature = models.FloatField(default=0.0)
    device = models.CharField(max_length=50, default='test-device')

    objects = models.Manager()
    timescale = TimescaleManager()

    class Meta:
        app_label = 'timescale_tests'


class AnotherMetric(TimescaleModel):
    """
    Test model using TimescaleModel abstract base class.
    Table name: timescale_tests_anothermetric
    """
    value = models.FloatField(default=0.0)

    class Meta:
        app_label = 'timescale_tests'
```

- [ ] **Step 2: Verify both tables are created and are hypertables**

```bash
uv run --extra test pytest --collect-only
```

Expected: no errors. Then connect to the DB and verify:

```bash
docker compose exec timescaledb psql -U postgres -d test -c \
  "SELECT hypertable_name FROM timescaledb_information.hypertables;"
```

Expected output contains both `timescale_tests_metric` and `timescale_tests_anothermetric`.

- [ ] **Step 3: Commit**

```bash
git add timescale/tests/models.py
git commit -m "feat: add Metric and AnotherMetric test models"
```

---

## Task 4: Factories and conftest

**Files:**
- Modify: `timescale/tests/factories.py`
- Modify: `timescale/tests/conftest.py`

- [ ] **Step 1: Write timescale/tests/factories.py**

```python
import factory
from django.utils import timezone

from timescale.tests.models import Metric


class MetricFactory(factory.django.DjangoModelFactory):
    time = factory.LazyFunction(timezone.now)
    temperature = factory.Faker('pyfloat', min_value=-20.0, max_value=100.0, right_digits=2)
    device = factory.Faker('bothify', text='device-##??')

    class Meta:
        model = Metric
```

- [ ] **Step 2: Write timescale/tests/conftest.py**

```python
import pytest

from timescale.tests.factories import MetricFactory


@pytest.fixture
def make_metric():
    """Factory fixture: call make_metric(temperature=10.0) to create a Metric."""
    def _make(**kwargs):
        return MetricFactory(**kwargs)
    return _make
```

- [ ] **Step 3: Smoke-test the factory in a Django shell**

```bash
uv run --extra test python -c "
import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'timescale.tests.settings'
django.setup()
from timescale.tests.factories import MetricFactory
print('MetricFactory OK:', MetricFactory._meta.model)
"
```

Expected: `MetricFactory OK: <class 'timescale.tests.models.Metric'>`

- [ ] **Step 4: Commit**

```bash
git add timescale/tests/factories.py timescale/tests/conftest.py
git commit -m "feat: add MetricFactory and make_metric fixture"
```

---

## Task 5: test_models.py

**Files:**
- Modify: `timescale/tests/test_models.py`

- [ ] **Step 1: Write the failing tests first, run to confirm they fail**

Write `timescale/tests/test_models.py`:

```python
import pytest
from datetime import datetime, timezone as tz, timedelta

from django.db import models
from django.db.models import Avg

from timescale.db.models.managers import TimescaleManager
from timescale.db.models.models import TimescaleModel
from timescale.db.models.querysets import TimescaleQuerySet
from timescale.tests.factories import MetricFactory
from timescale.tests.models import AnotherMetric, Metric

pytestmark = pytest.mark.django_db


# ── Manager / model structure ────────────────────────────────────────────────

class TestTimescaleModelStructure:
    def test_metric_has_timescale_manager(self):
        assert isinstance(Metric.timescale, TimescaleManager)

    def test_metric_has_objects_manager(self):
        assert isinstance(Metric.objects, models.Manager)

    def test_timescale_manager_returns_timescale_queryset(self):
        qs = Metric.timescale.all()
        assert isinstance(qs, TimescaleQuerySet)

    def test_another_metric_subclasses_timescale_model(self):
        assert issubclass(AnotherMetric, TimescaleModel)

    def test_another_metric_has_timescale_manager(self):
        assert isinstance(AnotherMetric.timescale, TimescaleManager)


# ── time_bucket ──────────────────────────────────────────────────────────────

class TestTimeBucket:
    # Use fixed UTC timestamps to avoid flaky day-boundary issues.
    T1 = datetime(2024, 6, 15, 10, 0, 0, tzinfo=tz.utc)   # day A
    T2 = datetime(2024, 6, 15, 11, 0, 0, tzinfo=tz.utc)   # day A
    T3 = datetime(2024, 6, 13, 10, 0, 0, tzinfo=tz.utc)   # day B (2 days earlier)

    def test_time_bucket_groups_by_day(self):
        MetricFactory(time=self.T1, temperature=10.0)
        MetricFactory(time=self.T2, temperature=20.0)
        MetricFactory(time=self.T3, temperature=30.0)

        results = Metric.timescale.time_bucket('time', '1 day').to_list()
        assert len(results) == 2
        assert 'bucket' in results[0]

    def test_time_bucket_with_annotation(self):
        MetricFactory(time=self.T1, temperature=10.0)
        MetricFactory(time=self.T2, temperature=20.0)

        results = (
            Metric.timescale
            .time_bucket('time', '1 day', {'temperature__avg': Avg('temperature')})
            .to_list()
        )
        assert len(results) == 1
        assert abs(results[0]['temperature__avg'] - 15.0) < 0.001

    def test_to_list_normalise_datetimes_returns_iso_strings(self):
        MetricFactory(time=self.T1, temperature=10.0)

        results = Metric.timescale.time_bucket('time', '1 day').to_list(normalise_datetimes=True)
        assert len(results) == 1
        assert isinstance(results[0]['bucket'], str)


# ── time_bucket_ng ───────────────────────────────────────────────────────────

class TestTimeBucketNg:
    def test_monthly_buckets_with_avg(self):
        from dateutil.relativedelta import relativedelta
        from django.utils import timezone

        timestamp = timezone.now().replace(day=1, hour=12, minute=0, second=0, microsecond=0)

        # current month
        MetricFactory(time=timestamp - relativedelta(days=15), temperature=8.0)
        MetricFactory(time=timestamp - relativedelta(days=10), temperature=10.0)
        # previous month
        MetricFactory(time=timestamp - relativedelta(months=1, days=15), temperature=14.0)
        MetricFactory(time=timestamp - relativedelta(months=1, days=10), temperature=12.0)

        results = Metric.timescale.time_bucket_ng('time', '1 month').annotate(Avg('temperature'))

        assert results[0]['temperature__avg'] == 9.0
        assert results[1]['temperature__avg'] == 13.0


# ── time_bucket_gapfill ──────────────────────────────────────────────────────

class TestTimeBucketGapFill:
    def test_gapfill_produces_none_for_missing_intervals(self):
        START = datetime(2024, 6, 15, 8, 0, 0, tzinfo=tz.utc)
        END   = datetime(2024, 6, 15, 13, 0, 0, tzinfo=tz.utc)

        # data at hours 9 and 12 — hours 8, 10, 11 will be gaps
        MetricFactory(time=datetime(2024, 6, 15, 9, 0, 0, tzinfo=tz.utc), temperature=10.0)
        MetricFactory(time=datetime(2024, 6, 15, 12, 0, 0, tzinfo=tz.utc), temperature=20.0)

        results = (
            Metric.timescale
            .time_bucket_gapfill('time', '1 hour', START, END)
            .annotate(Avg('temperature'))
            .to_list()
        )

        assert len(results) == 5
        none_count = sum(1 for r in results if r['temperature__avg'] is None)
        assert none_count == 3


# ── histogram ────────────────────────────────────────────────────────────────

class TestHistogram:
    def test_histogram_returns_list(self):
        base = datetime(2024, 6, 15, 10, 0, 0, tzinfo=tz.utc)
        for i, temp in enumerate([10.0, 25.0, 50.0, 75.0, 90.0]):
            MetricFactory(time=base + timedelta(minutes=i), temperature=temp)

        results = Metric.timescale.histogram('temperature', 0.0, 100.0, 5).to_list()
        assert len(results) == 1
        assert 'histogram' in results[0]
        assert isinstance(results[0]['histogram'], list)
        assert sum(results[0]['histogram']) == 5
```

- [ ] **Step 2: Run tests — confirm they fail (DB not yet set up for this session)**

```bash
uv run --extra test pytest timescale/tests/test_models.py -v
```

Expected for first run: tests pass if DB is up (they create their own data per test). If DB is down, connection error.
If the DB is up from Task 1, all tests should **pass** on first run.

- [ ] **Step 3: Commit**

```bash
git add timescale/tests/test_models.py
git commit -m "feat: add test_models.py covering managers, querysets, time_bucket, gapfill, histogram"
```

---

## Task 6: test_schema.py

**Files:**
- Create: `timescale/tests/test_schema.py`

- [ ] **Step 1: Write timescale/tests/test_schema.py**

```python
import pytest
from django.db import connection

from timescale.tests.models import AnotherMetric, Metric

pytestmark = pytest.mark.django_db


def _is_hypertable(table_name: str) -> bool:
    """Return True if the table is registered as a TimescaleDB hypertable."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = %s",
            [table_name],
        )
        return cursor.fetchone() is not None


def _get_partition_column(table_name: str) -> str:
    """Return the partition column name for a hypertable."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM timescaledb_information.dimensions "
            "WHERE hypertable_name = %s",
            [table_name],
        )
        row = cursor.fetchone()
        return row[0] if row else None


class TestHypertableCreation:
    def test_metric_table_is_hypertable(self):
        """TimescaleSchemaEditor.create_model must register Metric as a hypertable."""
        assert _is_hypertable('timescale_tests_metric')

    def test_another_metric_table_is_hypertable(self):
        """TimescaleModel subclass must also become a hypertable."""
        assert _is_hypertable('timescale_tests_anothermetric')

    def test_metric_partition_column_is_time(self):
        """Hypertable partition column must be the TimescaleDateTimeField column."""
        assert _get_partition_column('timescale_tests_metric') == 'time'

    def test_another_metric_partition_column_is_time(self):
        assert _get_partition_column('timescale_tests_anothermetric') == 'time'


class TestAlterField:
    def test_alter_interval_does_not_destroy_hypertable(self):
        """
        Calling alter_field to change TimescaleDateTimeField interval must call
        set_chunk_time_interval and leave the table as a hypertable.
        """
        from timescale.db.models.fields import TimescaleDateTimeField

        old_field = Metric._meta.get_field('time')  # interval='1 day'
        new_field = TimescaleDateTimeField(interval='2 days')
        new_field.set_attributes_from_name('time')
        new_field.model = Metric

        try:
            with connection.schema_editor() as editor:
                editor.alter_field(Metric, old_field, new_field)
            # Table must still be a hypertable after the alter
            assert _is_hypertable('timescale_tests_metric')
        finally:
            # Restore original interval so subsequent tests are unaffected
            with connection.schema_editor() as editor:
                editor.alter_field(Metric, new_field, old_field)
```

- [ ] **Step 2: Run tests**

```bash
uv run --extra test pytest timescale/tests/test_schema.py -v
```

Expected: All 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add timescale/tests/test_schema.py
git commit -m "feat: add test_schema.py verifying hypertable creation and alter_field"
```

---

## Task 7: Run full test suite

- [ ] **Step 1: Run all tests together**

```bash
uv run --extra test pytest -v
```

Expected: All tests pass with no warnings about missing DB or misconfiguration.

- [ ] **Step 2: Verify test isolation (run twice)**

```bash
uv run --extra test pytest -v
uv run --extra test pytest -v
```

Both runs must pass — confirms tests clean up after themselves.

---

## Task 8: Makefile

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write Makefile**

```makefile
.PHONY: db-up db-down test test-39 test-310 test-311 test-312 test-313 test-all

db-up:
	docker compose up -d

db-down:
	docker compose down

# Run against the current Python in the uv environment
test:
	uv run --extra test pytest

# Run against specific Python versions (uv downloads the interpreter if absent)
test-39:
	uv run --python 3.9 --extra test --with "Django>=4.2,<5.0" pytest

test-310:
	uv run --python 3.10 --extra test pytest

test-311:
	uv run --python 3.11 --extra test pytest

test-312:
	uv run --python 3.12 --extra test pytest

test-313:
	uv run --python 3.13 --extra test pytest

# Run all Python versions in sequence
test-all: test-39 test-310 test-311 test-312 test-313
```

> Note: `test-39` pins `Django<5.0` because Django 5.x dropped Python 3.9 support.
> The other targets use the `Django>=4.2` bound from `pyproject.toml` (resolves to latest compatible).

- [ ] **Step 2: Verify make test works**

```bash
make test
```

Expected: same output as `uv run --extra test pytest`.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add Makefile with uv-based per-Python test targets"
```

---

## Task 9: Rewrite CI

**Files:**
- Modify: `.github/workflows/ci-tests.yml`

- [ ] **Step 1: Rewrite .github/workflows/ci-tests.yml**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest

    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.9', '3.10', '3.11', '3.12', '3.13']
        django-version: ['4.2', '5.2', '6.0']
        exclude:
          # Django 5.x+ requires Python 3.10+
          - python-version: '3.9'
            django-version: '5.2'
          - python-version: '3.9'
            django-version: '6.0'
          # Django 6.0 requires Python 3.12+
          - python-version: '3.10'
            django-version: '6.0'
          - python-version: '3.11'
            django-version: '6.0'
          # Django 4.2 does not support Python 3.13
          - python-version: '3.13'
            django-version: '4.2'

    services:
      timescaledb:
        image: timescale/timescaledb:latest-pg17
        env:
          POSTGRES_PASSWORD: password
          POSTGRES_DB: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10

    env:
      DB_NAME: test
      DB_USER: postgres
      DB_PASSWORD: password
      DB_HOST: localhost
      DB_PORT: 5432

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Run tests
        run: |
          uv run \
            --python ${{ matrix.python-version }} \
            --extra test \
            --with "Django~=${{ matrix.django-version }}" \
            pytest
```

> `Django~=4.2` resolves to the latest `4.2.x` patch. Same for `5.2` and `6.0`.

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/ci-tests.yml
git commit -m "feat: rewrite CI with Python 3.9-3.13 x Django 4.2/5.2/6.0 matrix"
git push
```

- [ ] **Step 3: Verify CI passes on GitHub**

Open the Actions tab and confirm all 10 matrix jobs go green.

---

## Task 10: Update setup.cfg classifiers

**Files:**
- Modify: `setup.cfg`

- [ ] **Step 1: Replace classifiers block in setup.cfg**

Current classifiers section (lines 11–24):
```ini
classifiers =
    Environment :: Web Environment
    Framework :: Django
    Framework :: Django :: 3.0
    Intended Audience :: Developers
    License :: OSI Approved :: BSD License
    Operating System :: OS Independent
    Programming Language :: Python
    Programming Language :: Python :: 3
    Programming Language :: Python :: 3 :: Only
    Programming Language :: Python :: 3.6
    Programming Language :: Python :: 3.7
    Programming Language :: Python :: 3.8
    Topic :: Internet :: WWW/HTTP
    Topic :: Internet :: WWW/HTTP :: Dynamic Content
```

Replace with:
```ini
classifiers =
    Environment :: Web Environment
    Framework :: Django
    Framework :: Django :: 4.2
    Framework :: Django :: 5.2
    Framework :: Django :: 6.0
    Intended Audience :: Developers
    License :: OSI Approved :: BSD License
    Operating System :: OS Independent
    Programming Language :: Python
    Programming Language :: Python :: 3
    Programming Language :: Python :: 3 :: Only
    Programming Language :: Python :: 3.9
    Programming Language :: Python :: 3.10
    Programming Language :: Python :: 3.11
    Programming Language :: Python :: 3.12
    Programming Language :: Python :: 3.13
    Topic :: Internet :: WWW/HTTP
    Topic :: Internet :: WWW/HTTP :: Dynamic Content
```

- [ ] **Step 2: Commit**

```bash
git add setup.cfg
git commit -m "chore: update classifiers to reflect Django 4.2-6.0 and Python 3.9-3.13 support"
```

---

## Self-Review Checklist

### Spec Coverage
- [x] `docker-compose.yml` — Task 1
- [x] `pyproject.toml` with pytest config + test deps — Task 2
- [x] `timescale/tests/settings.py` — Task 2
- [x] `timescale/tests/apps.py` (needed to register test app) — Task 2
- [x] `timescale/tests/conftest.py` — Task 4
- [x] `timescale/tests/factories.py` — Task 4
- [x] `timescale/tests/models.py` with Metric + AnotherMetric — Task 3
- [x] `timescale/tests/test_models.py` — Task 5
- [x] `timescale/tests/test_schema.py` — Task 6
- [x] `Makefile` with all targets — Task 8
- [x] CI rewrite with full matrix — Task 9
- [x] `setup.cfg` classifiers updated — Task 10
- [x] `TimescaleModel` subclass tested (AnotherMetric) — Tasks 3, 5, 6
- [x] `alter_field` tested — Task 6

### Type Consistency
- `MetricFactory` defined in Task 4 (`factories.py`), imported in Tasks 5 and 6 ✓
- `Metric` and `AnotherMetric` defined in Task 3 (`models.py`), used in Tasks 5 and 6 ✓
- `_is_hypertable` and `_get_partition_column` helpers defined and used within Task 6 ✓
- `make_metric` fixture in conftest uses `MetricFactory` from Task 4 ✓
