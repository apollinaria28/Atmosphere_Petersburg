# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**«Атмосфера Петербурга»** — a Flask web app for discovering places in Saint Petersburg. The core idea: instead of standard categories (cafés, museums), all places are organised by **5 moods**:

| id | slug | name |
|----|------|------|
| 1 | silence | Тишина и вера |
| 2 | art | Вдохновиться искусством |
| 3 | relax | Отдохнуть от суеты |
| 4 | energy | Драйв и энергия |
| 5 | create | Создавай и пробуй |

Main features: mood-based filtering, interactive quiz, search by category/name, favourites, visited places, custom itineraries, user suggestions for new places, error reports, admin moderation panel.

Place data was imported **once** from the KudaGo public API (`kudago.com`) into the app's own PostgreSQL database. No real-time external API calls are made.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (debug=True, port 5000)
python run.py

# Run with gunicorn (production)
gunicorn -w 4 -b 0.0.0.0:5000 run:app
```

## Deployment

The live site is **https://atmosfera-piter.ru**, served from a VPS (Ubuntu 24.04, 1 core / 1 GB RAM). Everything runs in three Docker containers defined in `docker-compose.yml`:

| Container | Image | Role |
|---|---|---|
| `spb_postgres` | postgres:17 | database, exposed only on `127.0.0.1:5432` |
| `spb_web` | built from `Dockerfile` | gunicorn, 2 workers, port 5000 (internal) |
| `spb_nginx` | nginx:alpine | ports 80/443, TLS termination, serves `/static/` directly |

### Deploying to a fresh server

1. **Server prerequisites** — Ubuntu 24.04, ports 22/80/443 open. On a 1 GB machine a **2 GB swap file is mandatory**, otherwise `pip install` (Pillow, psycopg2) is killed by the OOM killer during the image build:
   ```bash
   fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
   echo '/swapfile none swap sw 0 0' >> /etc/fstab
   ```
2. **Install** Docker (official repository, not `apt install docker.io`) and `certbot`.
3. **Point the domain** — A records for `atmosfera-piter.ru` and `www` must resolve to the server *before* requesting a certificate.
4. **Clone and configure**:
   ```bash
   git clone https://github.com/apollinaria28/Atmosphere_Petersburg.git /root/spb_places
   cd /root/spb_places && mkdir -p certbot/www
   # copy .env from a local machine — it is not in git
   ```
   The production `.env` differs from the local one: `SESSION_COOKIE_SECURE=true`, `DB_HOST=postgres`, `DB_PORT=5432`.
5. **Issue the certificate before the first start** — `nginx.conf` references `ssl_certificate`, so the container will not start without it. Port 80 is still free at this point:
   ```bash
   certbot certonly --standalone -d atmosfera-piter.ru -d www.atmosfera-piter.ru \
       --email <address> --agree-tos --no-eff-email --non-interactive
   ```
6. **Start**: `docker compose up -d --build`. On first start `init-db/00_restore.sh` restores `dump.sql` into the database, then the SQL functions and indices in `init-db/` are applied. Watch with `docker compose logs -f postgres` until "Restore complete".

### Certificate renewal

Renewal **must** use the webroot method, not standalone — port 80 belongs to the nginx container. `/etc/letsencrypt/renewal/atmosfera-piter.ru.conf` sets `authenticator = webroot` with `webroot_path = /root/spb_places/certbot/www`; `nginx.conf` serves `/.well-known/acme-challenge/` from that directory. A deploy hook at `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` runs `docker restart spb_nginx` afterwards. Verify with `certbot renew --dry-run --no-random-sleep-on-renew`.

### Updating the running site

```bash
cd /root/spb_places && git pull && docker compose up -d --build
```

### Database access and backups

Connect a GUI client through an SSH tunnel (postgres is not exposed publicly):
```bash
ssh -i ~/.ssh/server_key -L 5433:127.0.0.1:5432 root@<server> -N
# then connect to localhost:5433, database spb_places
```
`/etc/cron.d/spb-backup` runs `/root/backup_db.sh` daily at 04:00, writing gzipped dumps to `/root/db_backups/` and keeping 7 days. Note: `crontab -` did not persist on this host, hence the file in `/etc/cron.d`.

The `admin` role can only be granted directly in the database:
```sql
UPDATE users SET role = 'admin' WHERE email = '<address>';
```

### Notes on the small server

A single core means pages render in 4-6 seconds and heavy operations (image build, `apt upgrade`) saturate the CPU. While that happens `sshd` may fail to complete its handshake — connections die with `kex_exchange_identification` or time out. This is load, not a broken server: wait until it is idle rather than retrying in a loop.

## Required environment variables

Create a `.env` file in the project root. Two variables are mandatory — the app raises `RuntimeError` on startup if missing:

```
SECRET_KEY=...
DB_PASSWORD=...
```

Database defaults: `localhost:5433`, database `spb_places`, user `apollinaria`. Override via `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`.

Mail settings (optional for auth flows): `MAIL_SERVER` (default `smtp.mail.ru`), `MAIL_PORT` (default `587`, TLS), `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`.

Other defaults: `MAX_CONTENT_LENGTH=50MB`, `UPLOAD_FOLDER=static/uploads`, `PERMANENT_SESSION_LIFETIME=7 days`, `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE=Lax`.

## Architecture

### Application factory

`app/__init__.py` → `create_app()` initializes all extensions and registers all blueprints. Extensions are defined as module-level singletons in `app/extensions.py` and initialized with `init_app()`.

### Database access

No ORM — raw psycopg2 with `DictCursor` throughout. `app/db.py` provides `get_db_connection()` which reads config from `current_app.config`. Every route opens a connection and closes it in `finally`. `conn.autocommit = True` is the default, but routes that need transactions call `conn.commit()` / `conn.rollback()` explicitly.

Key PostgreSQL functions (defined in the DB, not Python): `find_places_by_mood(mood_id)`, `find_test_places_v2(primary_slugs, mood_ids, secondary_conditions)`, `find_places_for_test(...)` (fallback).

### Models

`app/models.py` contains plain Python classes (`User`, `Place`, `Route`, `RoutePlace`) that wrap SQL queries as static/instance methods — not SQLAlchemy models. `User` implements `UserMixin` for Flask-Login. `load_user()` is also in this file.

Key methods:
- `Place.get_by_id(place_id)` — single place lookup
- `Place.get_nearby(place_id, radius=1000, limit=10)` — Haversine formula in SQL (Earth radius constant: 6371000 m); returns distance rounded to 0.1 m
- `Route.add_place(place_id)` — `ON CONFLICT DO NOTHING` (silently ignores duplicates)
- `Route.update(name, description)` — uses `COALESCE`, only provided fields are updated
- `User.get_display_name()` — returns `username` or email prefix if username is not set

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
- **Rate limiting**: Flask-Limiter with in-memory storage (not shared across Gunicorn workers). Full limits:

| Endpoint | Limit |
|----------|-------|
| `POST /api/register` | 5/hour |
| `POST /api/verify-email` | 10/hour |
| `POST /api/resend-code` | 5/hour |
| `POST /api/login` | 5/min + 20/hour |
| `GET /login` (page) | 5/min |
| `POST /api/forgot-password` | 3/hour |
| `POST /api/verify-reset-code` | 10/hour |
| `POST /api/reset-password` | 5/hour |
| `GET /api/check-username` | 60/min |
| `POST /api/suggest-place` | 5/hour |
| `POST /api/suggestions/{id}/photo` | 20/hour |
| `POST /api/report-error` | 10/hour |
| `GET /api/places/search` | 60/min |

- **Admin role**: `role` is a PostgreSQL ENUM (`user_role`: `'user'` | `'admin'`). Default is always `'user'`. Admin role can only be assigned directly in the DB by a developer. `/api/login` never returns the user role — frontend calls `/api/me` after login to detect admin and redirect to `/admin`. Admin password reset is blocked at the public endpoint.
- **Image uploads**: Pillow verifies file content (not just extension) before saving. Files are stored at `static/uploads/<folder>/` with UUID filenames.
- **Security logging**: failed login attempts (email + IP) are written to `security_logger`.
- **Auth pages cache**: `/login` and `/register` are served with `Cache-Control: no-store, no-cache, must-revalidate`.

### Mood quiz feature

`app/test_logic.py` → `TestLogic` class implements a path-branching algorithm. Each answer may fork the state into multiple parallel paths. When a path reaches a terminal option, it queries `find_test_places_v2` (falling back to `find_places_for_test`, then a simple SQL query) to get place recommendations. State is built per-request and passed back and forth as JSON through session — there is no server-side session storage for the quiz.

**Branching mechanics**: when a question has `allow_multiple=True` and the user picks N options, the first option continues the current path; each subsequent option **clones** the path (`clone_path`) with a new `id` and `parent_path_id`. This results in N parallel paths that are all resolved before results are returned. `set` fields (`mood_ids`, `primary_slugs`, etc.) are serialised to `list` for JSON transport and converted back on deserialisation.

**One test exists in the DB**: `slug = 'mood_flow_v1'`. Terminal question: `next_question_seq = NULL`. Debug endpoint: `GET /api/debug/test-search`.

### Mood filtering SQL function

`find_places_by_mood(mood_id)` uses four CTEs:
1. `negative_matches` — places excluded because a negative keyword (`is_negative=true` in `mood_keywords`) was found via `ILIKE` in `title`/`description`
2. `primary_places` — places whose category slug is in `primary_category_moods`; score = `SUM(confidence)`
3. `secondary_places` — places whose category slug is in `secondary_category_moods` AND a positive keyword matches; must not already be in primary
4. Final result: `primary UNION ALL secondary`, remove negatives, sort: PRIMARY first, then by score DESC

Requires extensions: `pg_trgm`. Key indices: `idx_places_categories_gin` (GIN on `categories` JSONB), `idx_places_title_trgm` (GIN trigram on `title`).

### Utility helpers

`app/utils.py` has key functions used across many routes:
- `process_place_row(row)` — normalizes a DB row dict: serialises `datetime` to ISO, parses categories, strips HTML from `description` and truncates to **200 chars**, ensures `photo_url` field exists.
- `process_categories(categories)` — handles categories stored as JSONB (may arrive as list, JSON string, or None).
- `is_valid_email(email)` — regex `^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`
- `is_valid_name(username)` — regex `^[a-zA-Zа-яА-ЯёЁ\s\-]+$`, max 30 chars
- `is_strong_password(password)` — min 6 chars, at least one uppercase `[A-ZА-ЯЁ]` and one lowercase `[a-zа-яё]`
- `save_uploaded_file(file, folder, ...)` — validates via Pillow `verify()`, saves as `uuid4().hex + ext`

---

## Database schema

### Core tables

**`places`** — main table (data from KudaGo, imported once)
- `id SERIAL PK`, `external_id INT UNIQUE`, `title`, `short_title`, `slug UNIQUE`
- `categories JSONB` — array of slug strings: `["park", "museums"]`
- `coords JSONB` — `{"lat": 59.93, "lon": 30.31}`
- `photos JSONB`, `main_photo_url`, `subway JSONB`, `is_closed BOOL DEFAULT false`
- `description`, `body_text`, `address`, `timetable`, `phone`, `foreign_url`

**`categories_api`** — `id SERIAL`, `slug VARCHAR UNIQUE`, `name VARCHAR`. IDs are non-sequential (some were deleted as irrelevant).

**`moods`** — `id SERIAL`, `name`, `slug`. 5 rows (see Project overview).

**`users`** — `id UUID PK DEFAULT gen_random_uuid()`, `email UNIQUE`, `username UNIQUE`, `password_hash`, `role user_role NOT NULL DEFAULT 'user'`, `is_active BOOL DEFAULT true`, `avatar_url`, `created_at`, `updated_at`. Trigger auto-updates `updated_at`. Indices on `email`, `role`, `created_at DESC`, `is_active WHERE true`.

**`routes`** — `id SERIAL`, `user_id UUID REFERENCES users CASCADE`, `name`, `description`, `created_at`, `updated_at`.

**`route_places`** — `route_id`, `place_id`, `order_index INT`, `UNIQUE(route_id, place_id)`.

**`favorites`** — `user_id UUID`, `place_id INT`, `UNIQUE(user_id, place_id)`, both CASCADE on delete.

**`visited_places`** — same structure as `favorites`, `visited_at TIMESTAMP`.

### Mood filtering tables

**`primary_category_moods`** — `(mood_id, categories_api_slug, confidence DECIMAL(3,2))` — categories that match a mood unconditionally.

**`secondary_category_moods`** — same structure — categories that need keyword confirmation.

**`mood_keywords`** — `(mood_id, categories_api_slug, keyword, search_in_title BOOL, search_in_description BOOL, is_negative BOOL)`.

### Quiz tables

**`tests`** — one row: `slug='mood_flow_v1'`.

**`questions`** — `(test_id, seq INT, question_text, allow_multiple BOOL)`, `UNIQUE(test_id, seq)`.

**`options`** — `(question_id, option_key, option_text, mood_id, primary_categories JSONB, secondary_conditions JSONB, negative_keywords JSONB, next_question_seq INT NULL)`. `NULL` = terminal option.

`secondary_conditions` structure:
```json
[{"slug": "restaurants", "keywords": [
  {"kw": "уют", "in_title": true, "in_description": false, "is_negative": false}
]}]
```

### Auth tables (temporary data, TTL 10 min)

**`email_verifications`** — `email PK`, `username`, `password_hash`, `code` (hashed), `expires_at`.

**`password_resets`** — `email PK`, `code` (hashed), `expires_at`.

### Suggestions & reports

**`place_suggestions`** — user fields (`user_title`, `user_description`, `user_address`, `user_timetable`, `user_phone`, `user_foreign_url`, `user_photos JSONB`) + moderator fields (`moderated_title`, `moderated_short_title`, `moderated_slug`, `moderated_coords JSONB`, `moderated_subway JSONB`, `moderated_body_text`, `moderated_is_closed`, `moderated_photos JSONB`) + `status suggestion_status DEFAULT 'pending'`, `created_place_id REFERENCES places`, `moderated_by UUID`, `admin_comment`. Constraint: if `status='approved'` then `created_place_id IS NOT NULL`.

**`place_reports`** — `place_id INT NOT NULL REFERENCES places CASCADE`, `user_id UUID`, `subject VARCHAR(200)`, `message TEXT` (max 2000 chars), `status report_status DEFAULT 'pending'`, `resolved_by UUID`, `resolution_comment`.

**`place_suggestion_user_categories`** / **`place_suggestion_moderated_categories`** — `(suggestion_id, category_id) PK`.

---

## Access control

| Feature | Guest | User | Admin |
|---------|-------|------|-------|
| Browse main page & place list | ✓ | ✓ | ✓ |
| View place detail | ✓ | ✓ | ✓ |
| Mood quiz | — | ✓ | ✓ |
| Favourites / Visited | — | ✓ | ✓ |
| Custom itineraries | — | ✓ | ✓ |
| Suggest new place | — | ✓ | ✓ |
| Report an error | — | ✓ | ✓ |
| Edit own pending submissions | — | ✓ | ✓ |
| Admin panel (`/admin`) | — | — | ✓ |
| Edit any place in DB | — | — | ✓ |
| Approve/reject suggestions | — | — | ✓ |
| Resolve error reports | — | — | ✓ |

---

## Auth flow

### Registration (2-step)
1. `POST /api/register` — validates email/username/password, checks uniqueness in both `users` and `email_verifications` (race condition guard), generates 6-digit code via `secrets.randbelow()`, **hashes the code** with `generate_password_hash` before storing, writes to `email_verifications` (TTL 10 min), sends email.
2. `POST /api/verify-email` — looks up `email_verifications` where `expires_at > NOW()`, verifies code hash, re-checks email uniqueness in `users`, inserts into `users` with `role='user'`, deletes temp record, calls `login_user(user, remember=True)`.

### Login
`POST /api/login` — selects user where `is_active=true`, calls `check_password_hash`, logs failures to `security_logger` (email + IP), calls `login_user`. Frontend then calls `GET /api/me` to detect admin role.

### Password reset (3-step)
1. `POST /api/forgot-password` — always returns success even if email not found (OWASP). Generates + hashes code → `password_resets` TTL 10 min.
2. `POST /api/verify-reset-code` — validates code without changing password; JS shows the new-password form on success.
3. `POST /api/reset-password` — validates code + password strength + **blocks admin accounts**; updates `password_hash`, deletes `password_resets` record.

---

## Feature modules

### Favourites & Visited (`favorites_bp`, `visited_bp`)
Both are join-tables with `UNIQUE(user_id, place_id)` and CASCADE on both FKs. Toggle endpoint returns `{action: 'added'|'removed', count}`. Status endpoint accepts comma-separated `place_ids` and returns the set already in favourites/visited.

### Suggestions & Reports (`suggestions_bp`)
- `POST /api/suggest-place` — accepts `multipart/form-data` OR JSON; required: `user_title`, `user_description`, `user_address`; optional photos as file uploads or comma-separated URLs; first photo becomes `user_main_photo_url`.
- `POST /api/report-error` — validates `place_id` exists and `is_closed=false`; `subject` max 200 chars, `message` max 2000 chars.
- Users can edit own submissions only while `status='pending'`.

### Itineraries (`routes_bp`, prefix `/api/routes`)
`POST /api/routes/{id}/places` accepts a single int or a list. `PUT /api/routes/{id}/places/order` accepts `{order: [id1, id2, ...]}` and updates `order_index` sequentially starting from 1.

### Admin panel (`admin_bp`)
All routes require `@login_required` + `@admin_required`. `/api/me` logs the request with user email and IP.

**Suggestion approval flow**: validate required fields (title, slug) → check slug uniqueness → `INSERT INTO places` (moderator fields take priority over user fields, fallback to user fields) → set `status='approved'`, `created_place_id`, `moderated_by`.

**Dashboard** auto-refreshes stats every 30 seconds via `GET /api/admin/dashboard/stats`.

### Place detail page (`GET /place/<id>`)
Photos are merged from three sources: `main_photo_url`, `photos` JSONB array, `<img>` tags extracted from `body_text` via regex. `subway` JSONB is parsed for up to 5 stations (`name`, `color`, `distance_km`). Query params `back_id` and `from_page` preserve navigation context.

### Search & filter (`GET /api/places/search-filter`)
Search priority: title starts-with → title contains → description contains → address contains → category match. Category filter uses `categories JSONB @> '["slug"]'::jsonb`. Params: `q`, `category` (comma-separated), `page` (default 1), `per_page` (default 12).
