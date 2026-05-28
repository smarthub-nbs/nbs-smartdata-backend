# Smarthub

Smarthub is a Django project scaffold for building user-focused backend features.
The current codebase includes a basic project configuration, an admin route, and a
`user_management` app with a custom `User` model draft.

## Project Layout

- `src/` - Django project source
- `src/config/` - project settings, URLs, and WSGI/ASGI entry points
- `src/djapps/user_management/` - user management app
- `models.py` - shared abstract timestamp base model
- `commands.md` - handy project setup commands

## Current Status

The project is still at an early scaffold stage:

- Admin is available at `/admin/`
- The `user_management` app exists, but its views, tests, and admin registration are still placeholders
- The custom `User` model includes timestamps, names, email, password hash, user type, and active status fields

## Requirements

- Python 3.13+
- `uv`

## Getting Started

From the `src/` directory:

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Then open:

- `http://127.0.0.1:8000/admin/`

## Useful Commands

- Start the project:
  - `uv run django-admin startproject config .`
- Add an app:
  - `uv run ../manage.py startapp user_management`
- Add a package:
  - `uv add <package_name>`

## Notes

- `src/README.md` is also present because the Python project metadata points to a README in that directory.
- The project currently uses SQLite for local development.
