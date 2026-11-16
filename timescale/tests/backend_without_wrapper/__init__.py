"""
A database backend package with no `DatabaseWrapper`, on purpose.

Used only by `test_edge_cases.py` to test that `base_impl.backend()` rejects a
`TIMESCALE_DB_BACKEND_BASE` setting that points to a module like this one.
"""
