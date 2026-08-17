# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (debug=True, port 5000)
python run.py

# Run with gunicorn (production)
gunicorn -w 4 -b 0.0.0.0:5000 run:app
```

## Required environment variables

Create a `.env` file in the project root. Two variables are mandatory — the app raises `RuntimeError` on startup if missing:

```
SECRET_KEY=...
DB_PASSWORD=...
```

Database defaults: `localhost:5433`, database `spb_places`, user `apollinaria`. Override via `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`.

Mail settings (optional for auth flows): `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`.

## Architecture

### Application factory

`app/__init__.py` → `create_app()` initializes all extensions and registers all blueprints. Extensions are defined as module-level singletons in `app/extensions.py` and initialized with `init_app()`.

### Database access

No ORM — raw psycopg2 with `DictCursor` throughout. `app/db.py` provides `get_db_connection()` which reads config from `current_app.config`. Every route opens a connection and closes it in `finally`. `conn.autocommit = True` is the default, but routes that need transactions call `conn.commit()` / `conn.rollback()` explicitly.

Key PostgreSQL functions (defined in the DB, not Python): `find_places_by_mood(mood_id)`, `find_test_places_v2(primary_slugs, mood_ids, secondary_conditions)`, `find_places_for_test(...)` (fallback).

### Models

`app/models.py` contains plain Python classes (`User`, `Place`, `Route`, `RoutePlace`) that wrap SQL queries as static/instance methods — not SQLAlchemy models. `User` implements `UserMixin` for Flask-Login. `load_user()` is also in this file.

### Blueprints

| Blueprint | Prefix | Purpose |
|---|---|---|
| `main_bp` | none | Index page, `/places`, `/place/<id>`, mood filter API |
| `auth_bp` | none | Login/register pages + all `/api/register`, `/api/login`, `/api/verify-email`, password reset endpoints |
| `profile_bp` | `/profile` | User profile page and API |
| `favorites_bp` | none | `/favorites` page + `/api/favorites/*` |
| `visited_bp` | none | `/visited` page + `/api/visited/*` |
| `suggestions_bp` | none | `/suggest` page + `/api/suggestions/*` |
| `admin_bp` | none | `/admin/*` pages + `/api/me` (role check after login) |
| `routes_bp` | `/api/routes` | User-created custom routes CRUD |
| `places_bp` | `/api/places` | Nearby places API |
| `test_bp` | none | `/test` page + quiz flow API |

### Security model

- **CSRF**: `CSRFProtect` is initialized but all blueprints are explicitly exempted — API routes rely on CORS + `Content-Type: application/json` instead.
- **Rate limiting**: Flask-Limiter with in-memory storage. Limits are per-route (e.g. login: `5/minute; 20/hour`, register: `5/hour`).
- **Admin role**: `/api/login` never returns the user role. The frontend calls `/api/me` after login to get the role, then redirects to `/admin` if applicable. Admin password reset is blocked at the public endpoint.
- **Image uploads**: Pillow verifies file content (not just extension) before saving. Files are stored at `static/uploads/<folder>/` with UUID filenames.

### Mood quiz feature

`app/test_logic.py` → `TestLogic` class implements a path-branching algorithm. Each answer may fork the state into multiple parallel paths. When a path reaches a terminal option, it queries `find_test_places_v2` (falling back to `find_places_for_test`, then a simple SQL query) to get place recommendations. State is built per-request and passed back and forth as JSON through session — there is no server-side session storage for the quiz.

### Utility helpers

`app/utils.py` has two key functions used across many routes:
- `process_place_row(row)` — normalizes a DB row dict: parses categories, strips HTML from description, ensures `photo_url` field exists.
- `process_categories(categories)` — handles categories stored as JSONB (may arrive as list, JSON string, or None).
