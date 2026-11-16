import os

DATABASES = {
    'default': {
        # The CI job `postgis` sets DB_ENGINE=timescale.db.backends.postgis
        # to run the same suite on the PostGIS copy of the backend.
        'ENGINE': os.getenv('DB_ENGINE', 'timescale.db.backends.postgresql'),
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
