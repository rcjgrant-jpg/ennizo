# One image serves both the web process and the Celery worker; Render (or
# docker compose) chooses which command to run. python:3.13-slim is Debian
# based, so every compiled dependency in requirements.txt — including the
# pinned Essentia build — installs from a pre-built wheel.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_MANIFEST_STATIC=True

# ffmpeg: record_sample transcodes browser recordings to WAV via subprocess.
# libsndfile1: runtime library behind soundfile/librosa.
# libgomp1: OpenMP runtime some numeric wheels expect.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so this layer is cached between code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# collectstatic needs a settings module but no database or secrets; a
# throwaway SECRET_KEY keeps it happy at build time. The real key is
# injected at runtime by the host.
RUN SECRET_KEY=build-only-not-a-secret DEBUG=False python manage.py collectstatic --noinput --ignore src

# Run as an unprivileged user.
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 8000

# Default command: the web server. The worker service overrides this.
# Shell form so $PORT (set by Render) is expanded; falls back to 8000.
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout 120 --access-logfile - --error-logfile -"]
