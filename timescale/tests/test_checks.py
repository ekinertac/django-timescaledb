"""
Tests for the system checks on `TimescaleDateTimeField`
(`timescale/db/models/fields.py`).

The checks report model definitions that fail later in `migrate` with a
database error: a unique index without the time field (timescale.E001) and a
foreign key to a hypertable (timescale.E002). No database access is needed.
Regression source: upstream jamessewell/django-timescaledb issues #55, #27
and the comments of #58.
"""
from types import SimpleNamespace
from unittest import mock

import pytest
from django.db import models
from django.test.utils import isolate_apps

from timescale.db.models.fields import TimescaleDateTimeField

APP = 'timescale_tests'


@pytest.fixture(autouse=True)
def _isolated_apps():
    # isolate_apps as a class decorator needs unittest.TestCase; these are plain pytest classes.
    with isolate_apps('timescale.tests'):
        yield


def _ids(model):
    return sorted(error.id for error in model.check() if error.id.startswith('timescale.'))


class TestUniqueChecks:
    def test_plain_model_has_no_errors(self):
        class Plain(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            value = models.FloatField()

            class Meta:
                app_label = APP

        assert _ids(Plain) == []

    def test_unique_field_is_an_error(self):
        class Event(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            event_id = models.IntegerField(unique=True)

            class Meta:
                app_label = APP

        errors = [e for e in Event.check() if e.id == 'timescale.E001']
        assert len(errors) == 1
        assert "'event_id' is unique" in errors[0].msg
        assert "includes 'time'" in errors[0].hint

    def test_unique_time_field_is_allowed(self):
        class UniqueTime(models.Model):
            time = TimescaleDateTimeField(interval='1 day', unique=True)

            class Meta:
                app_label = APP

        assert _ids(UniqueTime) == []

    def test_primary_key_is_not_reported(self):
        """The schema editor rebuilds the key, so `id` (unique by definition) is fine."""
        class CustomKey(models.Model):
            code = models.CharField(max_length=10, primary_key=True)
            time = TimescaleDateTimeField(interval='1 day')

            class Meta:
                app_label = APP

        assert _ids(CustomKey) == []

    def test_unique_constraint_without_time_is_an_error(self):
        class Reading(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            device = models.IntegerField()
            sensor = models.IntegerField()

            class Meta:
                app_label = APP
                constraints = [models.UniqueConstraint(fields=['device', 'sensor'], name='chk_dev_sensor')]

        assert _ids(Reading) == ['timescale.E001']

    def test_unique_constraint_with_time_is_allowed(self):
        class Reading2(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            device = models.IntegerField()

            class Meta:
                app_label = APP
                constraints = [models.UniqueConstraint(fields=['device', 'time'], name='chk_dev_time')]

        assert _ids(Reading2) == []

    def test_unique_together_without_time_is_an_error(self):
        class Reading3(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            device = models.IntegerField()
            sensor = models.IntegerField()

            class Meta:
                app_label = APP
                unique_together = [('device', 'sensor'), ('device', 'time')]

        assert _ids(Reading3) == ['timescale.E001']


class TestForeignKeyChecks:
    def test_foreign_key_to_hypertable_is_an_error(self):
        class Series(models.Model):
            time = TimescaleDateTimeField(interval='1 day')

            class Meta:
                app_label = APP

        class Note(models.Model):
            series = models.ForeignKey(Series, on_delete=models.CASCADE)

            class Meta:
                app_label = APP

        errors = [e for e in Series.check() if e.id == 'timescale.E002']
        assert len(errors) == 1
        assert 'timescale_tests.Note.series' in errors[0].msg

    def test_foreign_key_without_db_constraint_is_allowed(self):
        class Series2(models.Model):
            time = TimescaleDateTimeField(interval='1 day')

            class Meta:
                app_label = APP

        class Note2(models.Model):
            series = models.ForeignKey(Series2, on_delete=models.DO_NOTHING, db_constraint=False)

            class Meta:
                app_label = APP

        assert _ids(Series2) == []

    def test_foreign_key_from_hypertable_is_allowed(self):
        class Device(models.Model):
            class Meta:
                app_label = APP

        class Series3(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            device = models.ForeignKey(Device, on_delete=models.CASCADE)

            class Meta:
                app_label = APP

        assert _ids(Series3) == []

    def test_many_to_many_on_hypertable_is_an_error(self):
        class Tag(models.Model):
            class Meta:
                app_label = APP

        class Series4(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            tags = models.ManyToManyField(Tag)

            class Meta:
                app_label = APP

        assert _ids(Series4) == ['timescale.E002']

    def test_explicit_through_model_is_judged_by_its_own_foreign_key(self):
        class Series6(models.Model):
            time = TimescaleDateTimeField(interval='1 day')

            class Meta:
                app_label = APP

        class Group6(models.Model):
            series = models.ManyToManyField(Series6, through='Link6')

            class Meta:
                app_label = APP

        class Link6(models.Model):
            series = models.ForeignKey(Series6, on_delete=models.DO_NOTHING, db_constraint=False)
            group = models.ForeignKey(Group6, on_delete=models.CASCADE)

            class Meta:
                app_label = APP

        assert _ids(Series6) == []

    def test_hidden_relation_is_reported(self):
        """related_name='+' hides the reverse accessor, but the constraint is still created."""
        class Series7(models.Model):
            time = TimescaleDateTimeField(interval='1 day')

            class Meta:
                app_label = APP

        class Note7(models.Model):
            series = models.ForeignKey(Series7, on_delete=models.CASCADE, related_name='+')

            class Meta:
                app_label = APP

        assert _ids(Series7) == ['timescale.E002']

    def test_foreign_key_to_multi_table_parent_is_allowed(self):
        """The key references the parent's table, which is not the hypertable."""
        class Parent8(models.Model):
            class Meta:
                app_label = APP

        class Child8(Parent8):
            time = TimescaleDateTimeField(interval='1 day')

            class Meta:
                app_label = APP

        class Note8(models.Model):
            parent = models.ForeignKey(Parent8, on_delete=models.CASCADE)

            class Meta:
                app_label = APP

        assert _ids(Child8) == []

    def test_foreign_key_to_time_primary_key_is_left_to_the_database(self):
        """TimescaleDB 2.32 accepts this key and 2.13 rejects it, so the check stays silent."""
        class Series9(models.Model):
            time = TimescaleDateTimeField(interval='1 day', primary_key=True)

            class Meta:
                app_label = APP

        class Note9(models.Model):
            series = models.ForeignKey(Series9, on_delete=models.CASCADE)

            class Meta:
                app_label = APP

        assert _ids(Series9) == []

    def test_many_to_many_to_self_is_reported_once(self):
        class Series10(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            related = models.ManyToManyField('self')

            class Meta:
                app_label = APP

        assert _ids(Series10) == ['timescale.E002']

    def test_unresolved_through_model_does_not_crash(self):
        """Django reports the wrong name as fields.E331; this check must not raise before that."""
        class Tag11(models.Model):
            class Meta:
                app_label = APP

        class Series11(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            tags = models.ManyToManyField(Tag11, through='Missing11')

            class Meta:
                app_label = APP

        assert 'fields.E331' in [error.id for error in Series11.check()]
        assert _ids(Series11) == []

    def test_many_to_many_to_hypertable_is_an_error(self):
        class Series5(models.Model):
            time = TimescaleDateTimeField(interval='1 day')

            class Meta:
                app_label = APP

        class Group(models.Model):
            series = models.ManyToManyField(Series5)

            class Meta:
                app_label = APP

        assert _ids(Series5) == ['timescale.E002']


class TestChecksAreSkipped:
    def test_unmanaged_model(self):
        class Legacy(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            code = models.IntegerField(unique=True)

            class Meta:
                app_label = APP
                managed = False

        assert _ids(Legacy) == []

    def test_project_without_a_timescale_database(self):
        """On another backend the field is a plain DateTimeField and unique fields are valid."""
        class Portable(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            code = models.IntegerField(unique=True)

            class Meta:
                app_label = APP

        # A connection whose schema editor has no _create_hypertable, as on SQLite.
        other_backend = {'default': SimpleNamespace(SchemaEditorClass=object)}
        with mock.patch('timescale.db.models.fields.connections', other_backend):
            assert _ids(Portable) == []

    def test_second_timescale_field_is_not_the_partition_column(self):
        """The schema editor partitions on the first field only, so only that one is checked."""
        class TwoFields(models.Model):
            time = TimescaleDateTimeField(interval='1 day')
            created = TimescaleDateTimeField(interval='1 day')
            device = models.IntegerField()

            class Meta:
                app_label = APP
                constraints = [models.UniqueConstraint(fields=['device', 'time'], name='chk_two_fields')]

        assert _ids(TwoFields) == []
