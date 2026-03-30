import factory
from django.utils import timezone

from timescale.tests.models import Metric


class MetricFactory(factory.django.DjangoModelFactory):
    time = factory.LazyFunction(timezone.now)
    temperature = factory.Faker('pyfloat', min_value=-20.0, max_value=100.0, right_digits=2)
    device = factory.Faker('bothify', text='device-##??')

    class Meta:
        model = Metric
