"""
A database backend package that subclasses Django's PostgreSQL backend.

Used only by `test_edge_cases.py` to test that `base_impl.backend()` accepts a
`TIMESCALE_DB_BACKEND_BASE` that inherits from the PostgreSQL backend, the way
django-tenants or the PostGIS backend do.
"""
