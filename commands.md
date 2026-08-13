# Smarthub Commands

This file is the project command reference. Run Docker commands from the repository root. Run local Django commands from `src/`, unless the command explicitly uses `uv --directory src`.

## Project Paths

```text
Smarthub/
  Dockerfile
  docker-compose.yml
  .env.docker.example
  commands.md
  src/
    manage.py
    pyproject.toml
    config/
    djapps/
```

## Environment Files

Docker uses `.env.docker` from the repository root:

```bash
cp .env.docker.example .env.docker
```

Local non-Docker Django commands use `.env` from the repository root.

```bash
cp .env.example .env
```

Do not commit real secrets. Keep real values in `.env` or `.env.docker`, and keep shareable placeholders in example files.

## Required Docker Environment

These values are required by `docker-compose.yml` and Django settings:

```env
SECRET_KEY=change-me
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

DB_NAME=smarthub
DB_USER=smarthub
DB_PASSWORD=change-me
DB_HOST=postgres
DB_PORT=5432

POSTGRES_PORT=5432
REDIS_PORT=6379
WEB_PORT=8000
PGADMIN_PORT=5050
PGADMIN_DEFAULT_EMAIL=admin@smarthub.local
PGADMIN_DEFAULT_PASSWORD=change-me

CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:4200
CSRF_TRUSTED_ORIGINS=http://localhost:3000,http://localhost:4200
```

For Docker, `DB_HOST=postgres` and `redis://redis:6379/0` are correct because containers talk to each other by Compose service name.

## Optional Environment

Useful optional values currently supported by settings:

```env
AUTH_ACCESS_COOKIE_NAME=access_token
AUTH_REFRESH_COOKIE_NAME=refresh_token
AUTH_ACCESS_COOKIE_SECURE=False
AUTH_REFRESH_COOKIE_SECURE=False
AUTH_ACCESS_COOKIE_SAMESITE=Lax
AUTH_REFRESH_COOKIE_SAMESITE=Lax
CSRF_COOKIE_NAME=csrftoken
CSRF_COOKIE_SECURE=False
CSRF_COOKIE_SAMESITE=Lax

JWT_ACCESS_TOKEN_LIFETIME_MINUTES=15
JWT_REFRESH_TOKEN_LIFETIME_DAYS=7
JWT_ROTATE_REFRESH_TOKENS=True
JWT_BLACKLIST_AFTER_ROTATION=True

DRF_THROTTLE_ANON_RATE=100/hour
DRF_THROTTLE_USER_RATE=1000/day
DRF_THROTTLE_AUTH_CSRF_RATE=120/minute
DRF_THROTTLE_AUTH_SENSITIVE_RATE=20/minute
DRF_THROTTLE_AUTH_REFRESH_RATE=60/minute

DATASET_MAX_UPLOAD_SIZE=52428800
DATASET_ALLOWED_FILE_EXTENSIONS=.csv,.json,.pdf,.tsv,.txt,.xls,.xlsx,.xml,.sdmx,.zip

GITHUB_OAUTH_CLIENT_ID=
GITHUB_OAUTH_CLIENT_SECRET=
GITHUB_OAUTH_ALLOWED_REDIRECT_URIS=http://localhost:3000/auth/github/callback,http://localhost:4200/auth/github/callback

DEFAULT_FROM_EMAIL=no-reply@smarthub.local
FRONTEND_PASSWORD_RESET_URL=
FRONTEND_EMAIL_VERIFICATION_URL=
PASSWORD_RESET_TOKEN_MAX_AGE=3600
EMAIL_VERIFICATION_TOKEN_MAX_AGE=86400
```

For production, set cookie `SECURE=True`, use HTTPS origins, use real secrets, and do not use `DEBUG=True`.

## Docker First-Time Setup

From the repository root:

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d web celery_worker
docker compose --env-file .env.docker --profile tools run --rm migrate
docker compose --env-file .env.docker run --rm web python manage.py seed_roles
docker compose --env-file .env.docker run --rm web python manage.py createsuperuser
```

Open:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/admin/
http://127.0.0.1:8000/redoc/
http://127.0.0.1:8000/api/v1/schema/
```

## Docker Daily Commands

Start Django and Celery:

```bash
docker compose --env-file .env.docker up -d web celery_worker
```

View logs:

```bash
docker compose --env-file .env.docker logs -f web
docker compose --env-file .env.docker logs -f celery_worker
```

Stop services:

```bash
docker compose --env-file .env.docker down
```

Stop services and remove local database, Redis, media, and static volumes:

```bash
docker compose --env-file .env.docker down -v
```

Rebuild after dependency or Dockerfile changes:

```bash
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d web celery_worker
```

## Docker Django Commands

Run migrations:

```bash
docker compose --env-file .env.docker --profile tools run --rm migrate
```

Create migrations:

```bash
docker compose --env-file .env.docker run --rm web python manage.py makemigrations
```

Seed roles and permissions:

```bash
docker compose --env-file .env.docker run --rm web python manage.py seed_roles
```

Create a superuser:

```bash
docker compose --env-file .env.docker run --rm web python manage.py createsuperuser
```

Open Django shell:

```bash
docker compose --env-file .env.docker run --rm web python manage.py shell
```

Collect static files:

```bash
docker compose --env-file .env.docker --profile tools run --rm collectstatic
```

Run tests:

```bash
docker compose --env-file .env.docker --profile tools run --rm test
```

Run a specific test module:

```bash
docker compose --env-file .env.docker run --rm web python manage.py test djapps.datasets.tests
```

Validate OpenAPI schema:

```bash
docker compose --env-file .env.docker run --rm web python manage.py spectacular --validate --file /tmp/schema.yml
```

## Docker Services

`docker-compose.yml` defines these services:

```text
postgres       PostgreSQL database
redis          Redis broker/result backend
web            Django development server
celery_worker  Celery worker for background tasks
migrate        One-off migration runner, profile: tools
test           One-off test runner, profile: tools
collectstatic  One-off static file collector, profile: tools
```

Start only PostgreSQL and Redis:

```bash
docker compose --env-file .env.docker up -d postgres redis
```

Start pgAdmin:

```bash
docker compose --env-file .env.docker up -d pgadmin
```

Open pgAdmin:

```text
http://localhost:5050
```

Register the Docker Postgres server in pgAdmin with:

```text
Host: postgres
Port: 5432
Database: smarthub
Username: smarthub
Password: value of DB_PASSWORD from .env.docker
```

Restart one service:

```bash
docker compose --env-file .env.docker restart web
docker compose --env-file .env.docker restart celery_worker
```

## Local Setup Without Docker

Install locally:

```text
Python 3.13+
uv
PostgreSQL
Redis
```

For local `.env`, use local service hosts:

```env
DB_HOST=localhost
DB_PORT=5432
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

Then run from `src/`:

```bash
cp ../.env.example ../.env
uv sync
uv run python manage.py check
uv run python manage.py migrate
uv run python manage.py seed_roles
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Start Celery in another terminal from `src/`:

```bash
uv run celery -A config worker -l info
```

If you want to use Docker only for Redis during local development:

```bash
docker compose --env-file .env.docker up -d redis
```

## Local Daily Commands

Run from `src/`:

```bash
uv run python manage.py check
uv run python manage.py migrate
uv run python manage.py runserver
uv run celery -A config worker -l info
```

Run from the repository root with `uv --directory src`:

```bash
uv --directory src sync
uv --directory src run python manage.py check
uv --directory src run python manage.py migrate
uv --directory src run python manage.py runserver
uv --directory src run python manage.py test
```

## API Documentation

OpenAPI schema:

```bash
uv run python manage.py spectacular --validate --file /tmp/smarthub-schema.yml
```

Browsable docs while the server is running:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/redoc/
http://127.0.0.1:8000/api/schema/
```

Smoke-test the public ping endpoint:

```bash
curl http://127.0.0.1:8000/api/v1/ping/
```

## Auth And CSRF Smoke Test

Get a CSRF cookie:

```bash
curl -i -c cookies.txt http://127.0.0.1:8000/api/v1/auth/csrf/
```

Login with cookies and CSRF:

```bash
curl -i -b cookies.txt -c cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: <csrftoken-from-cookie>" \
  -d '{"email":"admin@example.com","password":"your-password"}' \
  http://127.0.0.1:8000/api/v1/auth/login/
```

Check current user:

```bash
curl -i -b cookies.txt http://127.0.0.1:8000/api/v1/auth/me/
```

## Celery

Run Celery locally from `src/`:

```bash
uv run celery -A config worker -l info
```

Run Celery in Docker:

```bash
docker compose --env-file .env.docker up -d celery_worker
docker compose --env-file .env.docker logs -f celery_worker
```

Run a quick probe task from `src/`:

```bash
uv run python manage.py shell -c "from djapps.datasets.tasks import bulk_action_probe; print(bulk_action_probe.delay(action='approve', dataset_ids=['1', '2']).id)"
```

## Database And Migrations

Create migrations after model changes:

```bash
uv run python manage.py makemigrations
```

Create migrations for one app:

```bash
uv run python manage.py makemigrations datasets
uv run python manage.py makemigrations user_management
uv run python manage.py makemigrations gateway
```

Apply migrations:

```bash
uv run python manage.py migrate
```

Show migration status:

```bash
uv run python manage.py showmigrations
```

Preview SQL for a migration:

```bash
uv run python manage.py sqlmigrate <app_name> <migration_number>
```

Example:

```bash
uv run python manage.py sqlmigrate datasets 0018
```

Open the configured database shell:

```bash
uv run python manage.py dbshell
```

## Roles And Users

Seed authorization groups and permissions:

```bash
uv run python manage.py seed_roles
```

Create a superuser:

```bash
uv run python manage.py createsuperuser
```

Change a user's password:

```bash
uv run python manage.py changepassword <email>
```

## Dataset Utilities

Import existing files from `src/config/media/dataset_files`:

```bash
uv run python manage.py import_dataset_files
```

Show command help:

```bash
uv run python manage.py import_dataset_files --help
```

## Testing And Validation

Run all tests:

```bash
uv run python manage.py test
```

Run tests for one app:

```bash
uv run python manage.py test djapps.user_management
uv run python manage.py test djapps.datasets
uv run python manage.py test djapps.gateway
```

Run one test class or method:

```bash
uv run python manage.py test djapps.datasets.tests.DatasetWorkflowTests
uv run python manage.py test djapps.datasets.tests.DatasetWorkflowTests.test_admin_bulk_action_is_idempotent_for_same_request
```

Run Django deployment checks:

```bash
uv run python manage.py check --deploy
```

Check pending model migrations:

```bash
uv run python manage.py makemigrations --check --dry-run
```

## Django Shell

Open the Django shell:

```bash
uv run python manage.py shell
```

Run a one-line Django command:

```bash
uv run python manage.py shell -c "<python_code>"
```

Example:

```bash
uv run python manage.py shell -c "from djapps.user_management.models import User; print(User.objects.count())"
```

## Static Files

Collect static files locally:

```bash
uv run python manage.py collectstatic --noinput
```

Collect static files in Docker:

```bash
docker compose --env-file .env.docker --profile tools run --rm collectstatic
```

## Packages

Run package commands from `src/`.

Install dependencies from `uv.lock`:

```bash
uv sync
```

Install exactly from lockfile:

```bash
uv sync --frozen
```

Add a package:

```bash
uv add <package_name>
```

Example for extras in zsh:

```bash
uv add 'psycopg[binary,pool]'
```

Remove a package:

```bash
uv remove <package_name>
```

Update the lockfile:

```bash
uv lock
```

Upgrade locked dependencies:

```bash
uv lock --upgrade
```

Show dependency tree:

```bash
uv tree
```

## Project And App Scaffolding

Create a new Django app under `src/djapps/`:

```bash
cd src
mkdir -p djapps/<app_name>
uv run python manage.py startapp <app_name> djapps/<app_name>
```

Then update `djapps/<app_name>/apps.py` so `name` is:

```python
name = "djapps.<app_name>"
```

Add the app to `INSTALLED_APPS` in `src/config/settings/settings.py`.

## Data Import And Export

Export data:

```bash
uv run python manage.py dumpdata <app_name> --indent 2 > <file_name>.json
```

Import data:

```bash
uv run python manage.py loaddata <file_name>.json
```
