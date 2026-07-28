# Smarthub

Smarthub is a Django backend for user management, dataset workflows, and public/developer gateway APIs.

## Project Layout

- `src/` - Django project source
- `src/config/` - settings, URLs, WSGI, and ASGI entry points
- `src/djapps/user_management/` - authentication, users, roles, and permissions
- `src/djapps/datasets/` - dataset workflow, metadata, files, and audit logs
- `src/djapps/gateway/` - public/developer API gateway endpoints
- `models.py` - shared abstract base models
- `commands.md` - command reference for setup, migrations, testing, and maintenance

## Requirements

Choose one setup path.

Docker workflow:

- Docker
- Docker Compose

Python, `uv`, PostgreSQL, and Redis are installed inside containers for the Docker workflow.

Local workflow:

- Python 3.13+
- `uv`
- PostgreSQL
- Redis

## Start With Docker

1. Move into the project directory:

```bash
cd Smarthub
```

1. Review the Docker environment file:

```bash
cp .env.docker.example .env.docker
```

The repository includes a development `.env.docker`; use the command above when you want to reset it from the example.

1. Review `.env.docker` and update secrets or OAuth values as needed:

- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `CORS_ALLOWED_ORIGINS`
- `CSRF_TRUSTED_ORIGINS`
- `GITHUB_OAUTH_CLIENT_ID`
- `GITHUB_OAUTH_CLIENT_SECRET`

PostgreSQL, Redis, and Celery connection values are loaded from `.env.docker`.

1. Build the application image:

```bash
docker compose --env-file .env.docker build
```

1. Start PostgreSQL, Redis, Django, and Celery:

```bash
docker compose --env-file .env.docker up web celery_worker
```

1. Apply database migrations in another terminal:

```bash
docker compose --env-file .env.docker --profile tools run --rm migrate
```

1. Create an admin user if you need Django admin access:

```bash
docker compose --env-file .env.docker run --rm web python manage.py createsuperuser
```

## Start Without Docker

1. Move into the Django project directory:

```bash
cd Smarthub
cd src
```

1. Make sure the repository root `.env` file exists and has the required settings for your local machine:

- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `CORS_ALLOWED_ORIGINS`
- `CSRF_TRUSTED_ORIGINS`

1. Start Redis locally or with Docker:

```bash
docker compose --env-file .env.docker up -d redis
```

1. Make sure PostgreSQL is running and matches your `.env` database settings.

1. Install dependencies:

```bash
uv sync
```

1. Apply database migrations:

```bash
uv run python manage.py migrate
```

1. Create an admin user if you need Django admin access:

```bash
uv run python manage.py createsuperuser
```

1. Start the Django development server:

```bash
uv run python manage.py runserver
```

1. Start the Celery worker in another terminal if you need background jobs:

```bash
uv run celery -A config worker -l info
```

## Docker Commands

```bash
docker compose --env-file .env.docker up web celery_worker
docker compose --env-file .env.docker --profile tools run --rm migrate
docker compose --env-file .env.docker --profile tools run --rm test
docker compose --env-file .env.docker --profile tools run --rm collectstatic
docker compose --env-file .env.docker run --rm web python manage.py shell
docker compose --env-file .env.docker down
```

## Local Commands

Run these from `src/`:

```bash
uv sync
uv run python manage.py check
uv run python manage.py migrate
uv run python manage.py test
uv run python manage.py runserver
uv run celery -A config worker -l info
```

## Local URLs

After the server starts, open:

- `http://127.0.0.1:8000/admin/`
- `http://127.0.0.1:8000/swagger`
- `http://127.0.0.1:8000/redoc/`

## More Commands

For migrations, tests, app scaffolding, package management, and other project commands, see [commands.md](commands.md).

## Notes

- Docker commands should be run from the repository root.
- Docker uses `.env.docker`; local Python commands can continue using `.env`.
- Local non-Docker Django commands should still be run from the `src/` directory.
- `src/README.md` exists because the Python project metadata points there.
