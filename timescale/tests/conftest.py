import pytest

from timescale.tests.factories import MetricFactory


@pytest.fixture
def make_metric():
    """Factory fixture: call make_metric(temperature=10.0) to create a Metric."""
    def _make(**kwargs):
        return MetricFactory(**kwargs)
    return _make
