FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	APP_ENV=production \
	DEBUG=false

WORKDIR /app

# requirements.lock is optional until `make lock` has been run and committed (the [k] glob lets the
# COPY succeed without it); once it exists the image installs exactly the locked, hash-verified set.
COPY pyproject.toml requirements.loc[k] ./
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN if [ -f requirements.lock ]; then \
        pip install --require-hashes -r requirements.lock && pip install --no-deps . ; \
    else \
        pip install . ; \
    fi \
	&& groupadd --system app \
	&& useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
	&& chown -R app:app /app

USER app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
