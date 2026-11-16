"""
`TimescaleDateTimeField`: the field that marks a model as a hypertable.

Responsibility: carry the chunk `interval`, and report model definitions that
TimescaleDB can never accept, before a migration fails halfway.
Used by: the schema editors in `timescale/db/backends/*/schema.py`, which look
for this field type to decide if a table becomes a hypertable.
Related: `timescale/tests/test_checks.py`.

Constraint: the database backend imports this module, and a backend can be
imported before `django.setup()` has filled the app registry. So this module
must not import or define models at module level.
"""
from django.core import checks
from django.db import connections
from django.db.models import DateTimeField, UniqueConstraint


class TimescaleDateTimeField(DateTimeField):
    def __init__(self, *args, interval, **kwargs):
        self.interval = interval
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs['interval'] = self.interval

        return name, path, args, kwargs

    def check(self, **kwargs):
        errors = super().check(**kwargs)
        if self._is_partition_field():
            errors.extend(self._check_unique_includes_time())
            errors.extend(self._check_no_foreign_key_to_model())
        return errors

    def _is_partition_field(self):
        """
        True when the schema editor will partition the table on this field.

        False for an unmanaged model, and for a project where no database
        uses a Timescale backend (for example a test run on SQLite, where
        this is a plain DateTimeField). Also False for a second
        TimescaleDateTimeField on one model: the schema editor partitions on
        the first one in `local_fields` and treats the others as plain columns.
        shortcut: this does not ask the database routers which database the
        model lives on; one Timescale database turns the checks on for all.
        """
        opts = self.model._meta
        if not opts.managed:
            return False
        first = next(f for f in opts.local_fields if isinstance(f, TimescaleDateTimeField))
        if first is not self:
            return False
        return any(
            hasattr(connections[alias].SchemaEditorClass, '_create_hypertable')
            for alias in connections
        )

    def _check_unique_includes_time(self):
        """
        TimescaleDB builds one index per chunk, so it can only enforce
        uniqueness when the partition column is part of the unique index.
        The primary key is not tested here: the schema editor rebuilds it.
        """
        opts = self.model._meta
        hint = (
            "Remove the single-column uniqueness and add a UniqueConstraint "
            "that includes '%s'." % self.name
        )
        errors = []

        for field in opts.local_fields:
            if field.unique and not field.primary_key and field is not self:
                errors.append(checks.Error(
                    "'%s' is unique, but a hypertable cannot have a unique index "
                    "without its time field '%s'." % (field.name, self.name),
                    hint=hint, obj=field, id='timescale.E001',
                ))

        unique_sets = [(tuple(fields), 'unique_together %s' % (tuple(fields),)) for fields in opts.unique_together]
        unique_sets += [
            (constraint.fields, "UniqueConstraint '%s'" % constraint.name)
            for constraint in opts.constraints
            # A constraint on expressions has no field list to inspect.
            if isinstance(constraint, UniqueConstraint) and constraint.fields
        ]
        for fields, label in unique_sets:
            if self.name not in fields:
                errors.append(checks.Error(
                    "%s does not include the time field '%s'. A hypertable cannot "
                    "have a unique index without it." % (label, self.name),
                    hint="Add '%s' to it." % self.name, obj=self.model, id='timescale.E001',
                ))

        return errors

    def _check_no_foreign_key_to_model(self):
        """
        A foreign key needs a unique index on exactly the referenced column,
        which is the primary key column of this model. With the usual `id`
        key, a hypertable cannot have that index (see above), so no table can
        reference it.

        When the time field itself is the primary key, the index exists.
        TimescaleDB 2.13 still rejects the foreign key and 2.32 accepts it,
        so that case is left to the database.
        """
        opts = self.model._meta
        if self.primary_key:
            return []

        hint = (
            "Set db_constraint=False on the relation, or store the id and the "
            "time in plain fields."
        )
        errors = []

        def has_own_through_model(relation):
            # An explicit through model has its own ForeignKey to this model.
            # That key is reported (or allowed by db_constraint=False) by itself.
            # A through name that does not resolve stays a string; Django
            # reports that as fields.E331.
            through = relation.through
            return isinstance(through, str) or not through._meta.auto_created

        # include_hidden: a relation with related_name='+' still creates the
        # constraint, and `related_objects` leaves it out.
        relations = [
            f for f in opts.get_fields(include_hidden=True)
            if f.auto_created and not f.concrete
            # A relation to a multi-table parent is listed on the child too,
            # but it references the parent's table.
            and f.model is self.model
            # The keys of an automatic join table are reported once, as the
            # ManyToManyField that creates it.
            and not f.field.model._meta.auto_created
        ]
        for relation in relations:
            field = relation.field
            if relation.many_to_many and (
                has_own_through_model(relation)
                # A ManyToManyField to 'self' is reported by the loop below.
                or field.model is self.model
            ):
                continue
            # ForeignKey keeps db_constraint on the field, ManyToManyField on the relation.
            db_constraint = getattr(field, 'db_constraint', getattr(relation, 'db_constraint', True))
            if db_constraint and field.model._meta.managed:
                errors.append(checks.Error(
                    "'%s.%s' is a foreign key to the hypertable model '%s'. The "
                    "database cannot create this constraint." % (
                        field.model._meta.label, field.name, opts.label),
                    hint=hint, obj=field, id='timescale.E002',
                ))

        for field in opts.local_many_to_many:
            if field.remote_field.db_constraint and not has_own_through_model(field.remote_field):
                errors.append(checks.Error(
                    "'%s' is a ManyToManyField on a hypertable model. Its join "
                    "table needs a foreign key to the hypertable, which the "
                    "database cannot create." % field.name,
                    hint=hint, obj=field, id='timescale.E002',
                ))

        return errors
