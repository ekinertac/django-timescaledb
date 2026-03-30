# Edge Cases Design

**Date:** 2026-03-30
**Scope:** Fix four confirmed bugs in django-timescaledb and add regression + edge case tests covering silent failures, queryset edge cases, and invalid input behavior.

---

## Context

After reaching 91% test coverage (excluding PostGIS), a codebase survey identified four unambiguous bugs and several untested edge cases across `schema.py`, `querysets.py`, `expressions.py`, and `managers.py`. This spec covers Option B: fix the bugs and add regression tests asserting correct behavior. Invalid inputs that are silently accepted (but not wrong) get tests that document the current behavior without changing it.

---

## Bugs to Fix

### 1. `schema.py` — bare `except` swallows all exceptions

In `_get_extra_condition()`, a bare `except:` clause silently swallows every exception including DB errors and programming mistakes. The fix is to replace `except:` with `except AttributeError:`, since the only expected failure is a missing `schema_name` attribute (when django-tenants is not installed). All other exceptions now propagate automatically.

**File:** `timescale/db/backends/postgresql/schema.py`

### 2. `querysets.py` — `to_list(normalise_datetimes=True)` KeyError

When `to_list(normalise_datetimes=True)` is called on a queryset that has no `bucket` key (e.g. a plain queryset not produced by `time_bucket()`), the normalisation code crashes with `KeyError`. The fix is to guard the datetime conversion with `if 'bucket' in row`.

**File:** `timescale/db/models/querysets.py`

### 3. `expressions.py` — `TimeBucket` origin+offset conflict silently ignored

`TimeBucket.__init__` accepts both `origin` and `offset` simultaneously. One is silently dropped. The fix is to raise `ValueError("Cannot specify both origin and offset")` when both are provided.

**File:** `timescale/db/models/expressions.py`

### 4. `managers.py` — `annotations={}` treated as falsy

`TimescaleManager.time_bucket()` uses `if annotations:` to decide whether to apply annotations, which treats an empty dict `{}` identically to `None`. This causes `.time_bucket(..., annotations={})` to silently skip annotation application. The fix is `if annotations is not None:`.

**File:** `timescale/db/models/managers.py`

---

## Test Organization

Tests are added to existing files. No new test files are created.

### `timescale/tests/test_models.py`

New test classes added:

**`TestTimeBucketOriginOffsetConflict`**
- `test_raises_when_both_origin_and_offset_given` — asserts `ValueError` is raised when both `origin` and `offset` are passed to `TimeBucket`

**`TestToListEdgeCases`**
- `test_to_list_normalise_datetimes_without_bucket_key` — `to_list(normalise_datetimes=True)` on a plain (non-time-bucketed) queryset does not crash; returns list of dicts
- `test_to_list_empty_queryset` — `to_list()` on a queryset with no rows returns `[]`

**`TestTimeBucketEdgeCases`**
- `test_time_bucket_on_empty_queryset` — `.timescale.time_bucket('time', '1 day')` on an empty queryset returns `[]`
- `test_time_bucket_empty_annotations_dict` — `.time_bucket('time', '1 day', annotations={})` does not raise and returns results without extra annotation columns
- `test_time_bucket_annotations_none_and_empty_dict_equivalent` — `annotations=None` and `annotations={}` produce the same result (no crash, no extra columns)

### `timescale/tests/test_schema.py`

New test class added:

**`TestSchemaEdgeCases`**
- `test_get_extra_condition_exception_surfaces` — a DB error during `create_hypertable` propagates (is not swallowed)
- `test_create_hypertable_idempotent` — calling `create_hypertable` on a table that is already a hypertable does not raise

---

## Behavior Contracts

- **Bugs fixed:** the four defects above are corrected. Regression tests assert the correct post-fix behavior.
- **Silent inputs documented:** `interval=None` and `interval=123` passed to `time_bucket` do not raise (current behavior preserved). This is documented via tests but not changed.
- **No API surface changes** beyond the `ValueError` on `TimeBucket(origin=..., offset=...)`, which was previously undefined behavior.

---

## Out of Scope

- PostGIS backend tests
- Changing silent acceptance of `interval=None` / `interval=123` to hard validation errors
- Any refactoring beyond the four targeted bug fixes
