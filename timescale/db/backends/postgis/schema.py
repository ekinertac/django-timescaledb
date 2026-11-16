"""
Schema editor that turns a table into a TimescaleDB hypertable.

Responsibility: after Django creates or alters a table that has a
`TimescaleDateTimeField`, fix the primary key and call `create_hypertable`.
Used by: `DatabaseWrapper.SchemaEditorClass` in `base.py`, so every migration
and `syncdb` on this backend goes through it.
Related: this is a copy of `timescale/db/backends/postgresql/schema.py` with
`PostGISSchemaEditor` as the base class. Change both together. Only the
postgresql copy has tests.

Constraints:
- TimescaleDB needs the partition column in every unique index, the primary
  key included. Django's default key is on `id` only, so it is replaced with
  `(id, time)`.
- Every statement must also work with `collect_sql=True` (`sqlmigrate`), where
  the table does not exist yet. So the key name is looked up by the server in
  a DO block, not from Python.
- Tables are passed to TimescaleDB as a quoted regclass (`'"Name"'`). An
  unquoted name is folded to lower case by PostgreSQL. The two hypertable
  asserts still match by table name; `_get_extra_condition` narrows them to
  one schema for django-tenants.
"""
from django.conf import settings
from django.contrib.gis.db.backends.postgis.schema import PostGISSchemaEditor

from timescale.db.models.fields import TimescaleDateTimeField


class TimescaleSchemaEditor(PostGISSchemaEditor):
    sql_is_hypertable = '''SELECT * FROM timescaledb_information.hypertables 
    WHERE hypertable_name = {table}{extra_condition}'''

    sql_assert_is_hypertable = (
            'DO $do$ BEGIN '
            'IF EXISTS ( '
            + sql_is_hypertable +
            ') '
            'THEN NULL; '
            'ELSE RAISE EXCEPTION {error_message}; '
            'END IF;'
            'END; $do$'
    )
    sql_assert_is_not_hypertable = (
            'DO $do$ BEGIN '
            'IF EXISTS ( '
            + sql_is_hypertable +
            ') '
            'THEN RAISE EXCEPTION {error_message}; '
            'ELSE NULL; '
            'END IF;'
            'END; $do$'
    )

    # The key name is read from pg_constraint: PostgreSQL truncates it at 63
    # bytes, so `<table>_pkey` is wrong for long or multi-byte table names.
    # The foreign key test gives a clear message for the one case where the
    # drop cannot work.
    sql_drop_primary_key = (
        'DO $do$ DECLARE pkey text; BEGIN '
        "IF EXISTS (SELECT 1 FROM pg_constraint WHERE confrelid = {table}::regclass AND contype = 'f') "
        'THEN RAISE EXCEPTION {error_message}; '
        'END IF; '
        "SELECT conname INTO pkey FROM pg_constraint WHERE conrelid = {table}::regclass AND contype = 'p'; "
        'IF pkey IS NOT NULL '
        "THEN EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', {table}::regclass, pkey); "
        'END IF; '
        'END; $do$'
    )

    sql_add_primary_key = 'ALTER TABLE {table} ADD PRIMARY KEY ({columns})'

    sql_add_hypertable = (
        "SELECT create_hypertable("
        "{table}, {partition_column}, "
        "chunk_time_interval => interval {interval}, "
        "migrate_data => {migrate})"
    )

    sql_set_chunk_time_interval = 'SELECT set_chunk_time_interval({table}, interval {interval})'

    sql_hypertable_is_in_schema = '''hypertable_schema = {schema_name}'''

    def _assert_is_hypertable(self, model):
        """
        Assert if the table is a hyper table
        """
        table = self.quote_value(model._meta.db_table)
        error_message = self.quote_value("assert failed - " + table + " should be a hyper table")

        extra_condition = self._get_extra_condition()

        sql = self.sql_assert_is_hypertable.format(table=table, error_message=error_message,
                                                   extra_condition=extra_condition)

        self.execute(sql)

    def _assert_is_not_hypertable(self, model):
        """
        Assert if the table is not a hyper table
        """
        table = self.quote_value(model._meta.db_table)
        error_message = self.quote_value("assert failed - " + table + " should not be a hyper table")

        extra_condition = self._get_extra_condition()

        sql = self.sql_assert_is_not_hypertable.format(table=table, error_message=error_message,
                                                       extra_condition=extra_condition)

        self.execute(sql)

    def _regclass(self, model):
        """
        The table as a string literal that PostgreSQL casts to regclass.
        The inner identifier quotes keep upper case names intact.
        """
        return self.quote_value(self.quote_name(model._meta.db_table))

    def _primary_key_columns(self, model):
        pk = model._meta.pk
        # CompositePrimaryKey (Django 5.2+) has `columns`; a normal field has `column`.
        return list(getattr(pk, 'columns', None) or [pk.column])

    def _drop_primary_key(self, model):
        """
        Drop the primary key, whatever its name is.
        """
        error_message = self.quote_value(
            "cannot convert " + model._meta.db_table + " to a hypertable: "
            "foreign keys in other tables reference it. Remove them first "
            "(for a ForeignKey, set db_constraint=False)."
        )
        sql = self.sql_drop_primary_key.format(table=self._regclass(model), error_message=error_message)

        # params=None: the statement has literal % signs (format()), and the
        # default params=() makes Django run it through % interpolation.
        self.execute(sql, None)

    def _fix_primary_key(self, model, field):
        """
        TimescaleDB rejects a primary key that does not include the partition
        column. A key that includes it (composite key, or the time field as
        the key) stays. Any other key becomes `(<key columns>, <time>)`, so
        the id stays unique per timestamp and stays indexed.
        """
        pk_columns = self._primary_key_columns(model)
        if field.column in pk_columns:
            return

        self._drop_primary_key(model)

        # A null=True time field gets the key too. create_hypertable sets the
        # column NOT NULL in any case, and both statements fail the same way
        # when existing rows have NULL in it.
        columns = ', '.join(self.quote_name(column) for column in pk_columns + [field.column])
        self.execute(self.sql_add_primary_key.format(table=self.quote_name(model._meta.db_table), columns=columns))

    def _create_hypertable(self, model, field, should_migrate=False):
        """
        Create the hypertable with the partition column being the field.
        """
        # assert that the table is not already a hypertable
        self._assert_is_not_hypertable(model)

        self._fix_primary_key(model, field)

        partition_column = self.quote_value(field.column)
        interval = self.quote_value(field.interval)
        table = self._regclass(model)
        migrate = "true" if should_migrate else "false"

        if should_migrate and getattr(settings, "TIMESCALE_MIGRATE_HYPERTABLE_WITH_FRESH_TABLE", False):
            # TODO migrate with fresh table [https://github.com/schlunsen/django-timescaledb/issues/16]
            raise NotImplementedError()
        else:
            sql = self.sql_add_hypertable.format(
                table=table, partition_column=partition_column, interval=interval, migrate=migrate
            )
            self.execute(sql)

    def _set_chunk_time_interval(self, model, field):
        """
        Change time interval for hypertable
        """
        # assert if already a hypertable
        self._assert_is_hypertable(model)

        table = self._regclass(model)
        interval = self.quote_value(field.interval)

        sql = self.sql_set_chunk_time_interval.format(table=table, interval=interval)
        self.execute(sql)

    def create_model(self, model):
        super().create_model(model)

        # scan if any field is of instance `TimescaleDateTimeField`
        for field in model._meta.local_fields:
            if isinstance(field, TimescaleDateTimeField):
                # create hypertable, with the field as partition column
                self._create_hypertable(model, field)
                break

    def add_field(self, model, field):
        super().add_field(model, field)

        # check if this field is type `TimescaleDateTimeField`
        if isinstance(field, TimescaleDateTimeField):
            # migrate existing table to hypertable
            self._create_hypertable(model, field, True)

    def alter_field(self, model, old_field, new_field, strict=False):
        super().alter_field(model, old_field, new_field, strict)

        #  check if old_field is not type `TimescaleDateTimeField` and new_field is
        if not isinstance(old_field, TimescaleDateTimeField) and isinstance(new_field, TimescaleDateTimeField):
            # migrate existing table to hypertable
            self._create_hypertable(model, new_field, True)
        # check if old_field and new_field is type `TimescaleDateTimeField` and `interval` is changed
        elif isinstance(old_field, TimescaleDateTimeField) and isinstance(new_field, TimescaleDateTimeField) \
                and old_field.interval != new_field.interval:
            # change chunk-size
            self._set_chunk_time_interval(model, new_field)

    def _get_extra_condition(self):
        extra_condition = ''

        try:
            if self.connection.schema_name:
                schema_name = self.quote_value(self.connection.schema_name)
                extra_condition = ' AND ' + self.sql_hypertable_is_in_schema.format(schema_name=schema_name)
        except AttributeError:
            pass

        return extra_condition
