# Smarthub Commands

Most commands should be run from the Django project directory:

```bash
cd src
```

## Setup

Install dependencies from `pyproject.toml` and `uv.lock`:

```bash
uv sync
```

Run Django's system checks:

```bash
uv run python manage.py check
```

Apply database migrations:

```bash
uv run python manage.py migrate
```

Create an admin user:

```bash
uv run python manage.py createsuperuser
```

## Development Server

Start the local Django server:

```bash
uv run python manage.py runserver
```

Start the server on a specific host and port:

```bash
uv run python manage.py runserver 0.0.0.0:8000
```

Useful local URLs:

```text
http://127.0.0.1:8000/admin/
http://127.0.0.1:8000/api/ping/
```

Smoke-test the public API endpoint while the server is running:

```bash
curl http://127.0.0.1:8000/api/ping/
```

## Database And Migrations

Create migrations after changing models:

```bash
uv run python manage.py makemigrations
```

Create migrations for a specific app:

```bash
uv run python manage.py makemigrations user_management
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
uv run python manage.py sqlmigrate user_management 0001
```

Open the configured database shell:

```bash
uv run python manage.py dbshell
```

## Users And Admin

Create a superuser:

```bash
uv run python manage.py createsuperuser
```

Change a user's password:

```bash
uv run python manage.py changepassword <email>
```

## Testing And Validation

Run tests:

```bash
uv run python manage.py test
```

Run tests for one app:

```bash
uv run python manage.py test djapps.user_management
```

Run Django deployment checks:

```bash
uv run python manage.py check --deploy
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

Collect static files for deployment:

```bash
uv run python manage.py collectstatic
```

## Packages

Add a package:

```bash
uv add <package_name>
```

Example:

```bash
uv add djangorestframework
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

Show the installed dependency tree:

```bash
uv tree
```

## Project And App Scaffolding

Create a new Django project in the current directory:

```bash
uv run django-admin startproject config .
```

Create a new app at the project root:

```bash
uv run python manage.py startapp <app_name>
```

Create a new app under `djapps/`:

```bash
mkdir -p djapps/<app_name>
uv run python manage.py startapp <app_name> djapps/<app_name>
```

or

```bash
uv run python ../manage.py startapp <app_name>

```

After creating an app under `djapps/`, update its `apps.py` config path and add it to `INSTALLED_APPS`.

## Data Import And Export

Export data:

```bash
uv run python manage.py dumpdata <app_name> --indent 2 > <file_name>.json
```

Import data:

```bash
uv run python manage.py loaddata <file_name>.json
```

## Running From The Repository Root

If you are in the repository root and do not want to `cd src`, use `uv --directory src`:

```bash
uv --directory src sync
uv --directory src run python manage.py check
uv --directory src run python manage.py migrate
uv --directory src run python manage.py runserver
uv --directory src run python manage.py test
```
