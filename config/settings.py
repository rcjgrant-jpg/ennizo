"""
Django settings for Ennizo.

One settings file for every environment. Anything that differs between the
laptop and the server is read from an environment variable, so the same
code deploys unchanged (twelve-factor style). Locally those variables come
from .env via python-dotenv; in production the host injects them.

Environment variables read here
--------------------------------
SECRET_KEY                 required
DEBUG                      "True" enables debug mode; anything else is off
ALLOWED_HOSTS              comma-separated hostnames (production only)
CSRF_TRUSTED_ORIGINS       comma-separated origins with scheme, e.g.
                           https://ennizo.onrender.com (production only)
RENDER_EXTERNAL_HOSTNAME   set automatically by Render; added to ALLOWED_HOSTS
HTTPS_ONLY                 "False" disables the HTTPS-only security block
                           (local compose testing only)

DATABASE_URL               postgres://user:pass@host:port/name (preferred)
DB_NAME / DB_USER / DB_PASSWORD / DB_HOST / DB_PORT
                           fallback when DATABASE_URL is absent (local dev)

REDIS_URL                  Celery broker + result backend
CELERY_EAGER               "True" runs tasks inline (tests / no worker)

AWS_STORAGE_BUCKET_NAME    if set, media goes to an S3-compatible bucket
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_S3_ENDPOINT_URL        set for non-AWS providers (Cloudflare R2, MinIO)
AWS_S3_REGION_NAME         "auto" for R2; e.g. "eu-west-2" for AWS
AWS_S3_CUSTOM_DOMAIN       optional public CDN/bucket domain; if set, URLs
                           are plain (unsigned) and the bucket must be public
"""

import os
from pathlib import Path

import environ
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name, default=""):
    """Split a comma-separated environment variable into a clean list."""
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# --- Core ---------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY")

DEBUG = os.getenv("DEBUG") == "True"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
if DEBUG:
    ALLOWED_HOSTS += ["localhost", "127.0.0.1"]

# Render sets this for every web service; adding it here means the blueprint
# does not need to know the hostname in advance.
_render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if _render_host:
    ALLOWED_HOSTS.append(_render_host)

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if _render_host:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")


# --- Applications ---------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    # WhiteNoise's runserver_nostatic makes the dev server serve static files
    # the same way production does, so surprises show up locally.
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'library',
    'accounts',
    'analysis',
    'processing',
    'attribution',
    'social',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Must sit directly after SecurityMiddleware and before everything else.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# --- Database -------------------------------------------------------------------

if os.getenv("DATABASE_URL"):
    # Hosted providers hand over a single connection URL.
    DATABASES = {"default": environ.Env.db_url_config(os.environ["DATABASE_URL"])}
    # Keep connections open between requests rather than reconnecting each time.
    DATABASES["default"]["CONN_MAX_AGE"] = 600
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
else:
    DATABASES = {
        'default': {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME"),
            "USER": os.getenv("DB_USER"),
            "PASSWORD": os.getenv("DB_PASSWORD"),
            "HOST": os.getenv("DB_HOST"),
            "PORT": os.getenv("DB_PORT"),
        }
    }


# --- Auth -----------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = "accounts.User"

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"


# --- Internationalization -------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# --- Celery ---------------------------------------------------------------------

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540

CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_EAGER") == "True"
CELERY_TASK_EAGER_PROPAGATES = True

CELERY_BEAT_SCHEDULE = {
    "reap-abandoned-samples": {
        "task": "library.tasks.reap_abandoned_samples",
        "schedule": 900,  # every 15 minutes
    },
}


# --- Static files (CSS, JS, icons) ---------------------------------------------
# Served by WhiteNoise from STATIC_ROOT after `collectstatic`. The Tailwind
# build output must exist under static/ before collectstatic runs.

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"


# --- Media files (user audio) ---------------------------------------------------
# Local disk by default. Setting AWS_STORAGE_BUCKET_NAME switches the default
# storage to an S3-compatible bucket. Model code is unaffected: FieldFile.save,
# .url, .open and .delete all go through whichever backend is configured, so
# the "file exists iff sample is committed or posted" invariant holds on both.

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

USE_S3_MEDIA = bool(os.getenv("AWS_STORAGE_BUCKET_NAME"))

if USE_S3_MEDIA:
    _custom_domain = os.getenv("AWS_S3_CUSTOM_DOMAIN") or None
    _media_storage = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": os.environ["AWS_STORAGE_BUCKET_NAME"],
            "access_key": os.getenv("AWS_ACCESS_KEY_ID"),
            "secret_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "endpoint_url": os.getenv("AWS_S3_ENDPOINT_URL") or None,
            "region_name": os.getenv("AWS_S3_REGION_NAME") or None,
            "custom_domain": _custom_domain,
            # Never silently overwrite: sample_upload_path already randomises
            # names, this is belt-and-braces.
            "file_overwrite": False,
            # Objects are private; URLs are signed and expire. If a public
            # custom domain is configured, serve plain URLs instead.
            "default_acl": None,
            "querystring_auth": _custom_domain is None,
            "querystring_expire": 3600,
        },
    }
else:
    _media_storage = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

if os.getenv("DJANGO_MANIFEST_STATIC") == "True":
    _static_backend = "whitenoise.storage.CompressedManifestStaticFilesStorage"
else:
    _static_backend = "whitenoise.storage.CompressedStaticFilesStorage"

STORAGES = {
    "default": _media_storage,
    "staticfiles": {"BACKEND": _static_backend},
}

# --- Production security -----------------------------------------------------------
# Render (and most PaaS hosts) terminate HTTPS at their proxy and forward plain
# HTTP to the container, telling Django the original scheme in a header.

# HTTPS_ONLY=False lets the production image run over plain http in the local
# compose stack; it should never be set on the real host.

HTTPS_ONLY = os.getenv("HTTPS_ONLY", "True") == "True"

if not DEBUG and HTTPS_ONLY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days; raise once stable
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"


# --- Logging ------------------------------------------------------------------------
# Everything to stdout so the host's log viewer sees it.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"level": "WARNING"},
    },
}


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'