"""
The smallest valid base for `TIMESCALE_DB_BACKEND_BASE`: a subclass of
Django's PostgreSQL `DatabaseWrapper`. See the package docstring.
"""
from django.db.backends.postgresql.base import DatabaseWrapper as PostgresDatabaseWrapper


class DatabaseWrapper(PostgresDatabaseWrapper):
    pass
