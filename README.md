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

- Python 3.13+
- `uv`
- PostgreSQL
- Redis

## Start The Project After Clone

1. Move into the project and Django directories:

```bash
cd Smarthub
cd src
```

1. Make sure the repository root `.env` file exists and has the required settings for your local environment:

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

1. Start Redis:

```bash
docker compose up -d redis
```

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

1. Start the development server:

```bash
uv run python manage.py runserver
```

## Local URLs

After the server starts, open:

- `http://127.0.0.1:8000/admin/`
- `http://127.0.0.1:8000/swagger`
- `http://127.0.0.1:8000/redoc/`

## More Commands

For migrations, tests, app scaffolding, package management, and other project commands, see [commands.md](commands.md).

## Notes

- Most Django commands should be run from the `src/` directory.
- `src/README.md` exists because the Python project metadata points there.
