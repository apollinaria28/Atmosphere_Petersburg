# Атмосфера Петербурга — полное техническое описание проекта

## 1. Общее описание

**«Атмосфера Петербурга»** — веб-приложение для планирования досуга в Санкт-Петербурге.
Ключевая идея: вместо стандартных категорий (кафе, рестораны, музеи) все места разбиты по **5 настроениям**:

| ID | Slug | Название |
|----|------|----------|
| 1 | silence | Тишина и вера |
| 2 | art | Вдохновиться искусством |
| 3 | relax | Отдохнуть от суеты |
| 4 | energy | Драйв и энергия |
| 5 | create | Создавай и пробуй |

Основной функционал:
- Фильтрация мест по настроению на главной странице
- Интерактивный квиз — пользователь отвечает на вопросы, система подбирает места
- Поиск по категориям и названию
- Избранное и посещённые места
- Составление личных маршрутов
- Предложение новых мест и сообщения об ошибках
- Административная панель модерации

---

## 2. Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Backend | Python 3, Flask |
| База данных | PostgreSQL (порт 5433, БД `spb_places`) |
| Доступ к БД | psycopg2 (raw SQL, без ORM) |
| Авторизация | Flask-Login |
| Шаблонизатор | Jinja2 |
| Frontend | HTML, CSS, JavaScript, Bootstrap 5 |
| Карты | Leaflet.js + OpenStreetMap |
| Безопасность | Flask-Limiter, Flask-Talisman, Flask-WTF (CSRF) |
| Email | SMTP (smtplib) |
| Внешний API | KudaGo API (данные загружены однократно, хранятся в БД) |
| Деплой | Gunicorn + Nginx + Docker |

---

## 3. Архитектура

Классическая клиент-серверная архитектура:
- Страницы рендерятся на сервере через Jinja2 (server-side rendering)
- Динамические операции (избранное, фильтрация, маршруты) — AJAX + REST API → JSON

Код организован через **Application Factory** (`create_app()` в `app/__init__.py`) и **Blueprints** — каждый модуль изолирован.

### Blueprints

| Blueprint | Prefix | Назначение |
|-----------|--------|-----------|
| `main_bp` | — | Главная, список мест, детальная страница |
| `auth_bp` | — | Регистрация, логин, верификация email, сброс пароля |
| `profile_bp` | `/profile` | Личный кабинет пользователя |
| `favorites_bp` | — | Избранное |
| `visited_bp` | — | Посещённые места |
| `suggestions_bp` | — | Предложение мест и сообщения об ошибках |
| `admin_bp` | — | Панель администратора |
| `test_bp` | — | Интерактивный квиз |
| `routes_bp` | `/api/routes` | Маршруты пользователя |
| `places_bp` | `/api/places` | Поиск ближайших мест |

### Безопасность
- **CSRF**: `CSRFProtect` инициализирован, но все blueprints исключены — API защищён через CORS + `Content-Type: application/json`
- **Rate Limiting**: in-memory, per-route (логин: 5/мин + 20/час; регистрация: 5/час)
- **Talisman**: security headers
- **Загрузка файлов**: Pillow верифицирует содержимое (не только расширение), UUID-имена файлов
- **Роль admin**: `/api/login` роль не возвращает — фронтенд отдельно вызывает `/api/me`

---

## 4. Структура проекта

```
spb_places/
├── app/
│   ├── __init__.py          # create_app(), регистрация blueprints
│   ├── config.py            # Конфигурация из .env
│   ├── db.py                # get_db_connection()
│   ├── models.py            # User, Place, Route, RoutePlace
│   ├── extensions.py        # login_manager, limiter, talisman, csrf, cors
│   ├── decorators.py        # @admin_required
│   ├── email_utils.py       # send_verification_email()
│   ├── utils.py             # process_place_row(), process_categories()
│   ├── test_logic.py        # Алгоритм ветвящегося квиза
│   ├── routes/
│   │   ├── main.py
│   │   ├── auth.py
│   │   ├── profile.py
│   │   ├── favorites.py
│   │   ├── visited.py
│   │   ├── routes.py
│   │   ├── test.py
│   │   ├── suggestions.py
│   │   ├── places.py
│   │   └── admin.py         # ~1300 строк
│   ├── templates/
│   │   ├── index.html
│   │   ├── places.html
│   │   ├── place_detail.html
│   │   ├── favorites.html
│   │   ├── visited.html
│   │   ├── routes.html
│   │   ├── test.html
│   │   ├── auth/
│   │   ├── user_profile/
│   │   └── admin/           # 7 шаблонов
│   └── static/
│       ├── avatars/
│       └── uploads/suggestions/
├── init-db/                 # SQL скрипты инициализации
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── run.py
└── dump.sql
```

---

## 5. База данных — схема таблиц

### Таблица мест — `places`
Основная таблица. Данные загружены из KudaGo API однократно Python-скриптом.
- `categories` — JSONB-массив slug-ов из `categories_api` (пример: `["park", "restaurants"]`)
- `coords` — JSONB `{"lat": 59.93, "lon": 30.31}`
- `photos` — JSONB-массив
- `is_closed` — флаг закрытия места

### Таблица категорий — `categories_api`
- `slug` — уникальный текстовый идентификатор (напр. `park`, `museums`)
- Часть категорий удалена как нерелевантная → id идут не по порядку

### Полный список используемых категорий
`amusement`, `anticafe`, `art-centers`, `art-space`, `attractions`, `bar`, `bridge`, `business`, `church`, `clubs`, `concert-hall`, `coworking`, `culture`, `dance-studio`, `education-centers`, `fountain`, `handmade`, `homesteads`, `inn`, `library`, `monastery`, `museums`, `observatory`, `palace`, `park`, `photo-places`, `prirodnyj-zapovednik`, `questroom`, `restaurants`, `rynok`, `salons`, `sights`, `stable`, `suburb`, `synagogue`, `temple`, `theatre`, `workshops`, `cinema`, `recreation`

### Таблица настроений — `moods`
5 записей (см. раздел 1).

### Таблица пользователей — `users`
- `id` — UUID (PK)
- `email`, `username`, `password_hash`
- `role` — ENUM `user_role` ('user' | 'admin'), **всегда 'user' по умолчанию**
- `is_active`, `avatar_url`, `created_at`, `updated_at`
- Индексы: по email, role, created_at DESC, is_active
- Триггер автообновления `updated_at`

### Таблицы фильтрации по настроениям
- `primary_category_moods` — основные категории (точно подходят без ключевых слов)
- `secondary_category_moods` — вторичные категории (нужны ключевые слова)
- `mood_keywords` — ключевые слова для вторичных категорий (с флагами `search_in_title`, `search_in_description`, `is_negative`)

### Таблицы теста
- `tests` — один тест: `slug = 'mood_flow_v1'`
- `questions` — вопросы (с `seq` — порядковый номер)
- `options` — варианты ответов: `mood_id`, `primary_categories` (JSONB), `secondary_conditions` (JSONB), `negative_keywords` (JSONB), `next_question_seq` (NULL = терминал)

### Таблицы авторизации (временные данные)
- `email_verifications` — незавершённые регистрации, TTL 10 минут
- `password_resets` — коды сброса пароля, TTL 10 минут

### Таблицы избранного и посещённых
- `favorites (user_id UUID, place_id INTEGER)` — UNIQUE constraint
- `visited_places (user_id UUID, place_id INTEGER)` — UNIQUE constraint
- CASCADE удаление при удалении пользователя или места

### Таблицы предложений и ошибок
- `place_suggestions` — предложения новых мест (хранит и пользовательские, и модерированные поля)
- `place_reports` — сообщения об ошибках в существующих местах
- `place_suggestion_user_categories` — категории от пользователя
- `place_suggestion_moderated_categories` — категории от модератора
- Статусы: `suggestion_status` ENUM ('pending', 'approved', 'rejected')
- `report_status` ENUM ('pending', 'resolved')

### Таблицы маршрутов
- `routes (id, user_id UUID, name, description, created_at, updated_at)`
- `route_places (route_id, place_id, order_index)` — UNIQUE(route_id, place_id)
- Индексы по `user_id`, `route_id`, `place_id`

---

## 6. Источник данных — KudaGo API

Данные о местах загружены **однократно** Python-скриптом из публичного API `kudago.com`:
- Отсортированы по городу Санкт-Петербург
- Сохранены в собственную БД (не real-time обращение к API)

**Почему такой подход:**
1. Нет зависимости от доступности стороннего сервиса
2. Можно редактировать данные (удалять нерелевантные, добавлять координаты)
3. Реализуема сложная SQL-фильтрация (GIN-индексы, хранимые функции)

**Что импортировано:** title, short_title, description, body_text, address, timetable, phone, foreign_url, categories (slugs), coords (lat/lon), subway, photos.

---

## 7. Система фильтрации по настроению

### SQL-функция `find_places_by_mood(mood_id_param)`

Принимает ID настроения, возвращает отсортированный список мест.
Вызывается как при прямой фильтрации на главной, так и по результатам теста.

**Алгоритм работы:**

1. **Раскрытие категорий**: `jsonb_array_elements_text(p.categories)` → сравнение каждого slug с таблицами настроений

2. **negative_matches**: Место исключается если: есть категория из `mood_keywords` + `is_negative=true` + ключевое слово найдено в `title`/`description` через ILIKE

3. **primary_places**: Место попадает если хоть одна категория есть в `primary_category_moods` для данного mood_id. Score = SUM(confidence) по всем подходящим категориям. Закрытые места исключаются.

4. **secondary_places**: Место попадает если: категория есть в `secondary_category_moods` + для этой же категории в `mood_keywords` найдено ключевое слово (`is_negative=false`) + место не попало в primary + не закрыто.

5. **Итог**: PRIMARY UNION ALL SECONDARY → убрать negative_matches → сортировка: сначала все PRIMARY, внутри каждой группы — по убыванию score.

### Индексы для фильтрации
```sql
idx_primary_category_moods_mood ON primary_category_moods(mood_id)
idx_secondary_category_moods_mood ON secondary_category_moods(mood_id)
idx_mood_keywords_mood_slug ON mood_keywords(mood_id, categories_api_slug)
idx_places_categories_gin ON places USING GIN(categories)
idx_places_title_trgm ON places USING GIN(title gin_trgm_ops)
idx_places_is_closed ON places(is_closed)
```

### Распределение категорий по настроениям (confidence)

**Тишина и вера (id=1):**
- 1.0: church, monastery, synagogue, temple
- attractions — ключ. слова: храм, собор

**Вдохновиться искусством (id=2):**
- 1.0: museums, palace; 0.9: theatre; 0.8: concert-hall
- attractions — ключ. слова: двор, парк, маяк, музей, дворец, улица, площадь, ротон, особняк, павил
- bridge (0.6); business — ключ. слова: лахта, небоскреб (0.5)

**Отдохнуть от суеты (id=3):**
- 1.0: homesteads, palace, park
- restaurants — ключ. слова включения: тихо, уют, спокойно, кондитер, пекарня, кофе, кафе; **исключения**: бар, джаз, паб, клуб, club, pub, теплоход
- attractions — ключ. слова: сад, парк, усадьба, дворец, двор, дом, дача, сквер, башня, набережная, особняк, каньон, памятник, коты, поле

**Драйв и энергия (id=4):**
- 1.0: bar, clubs; amusement — ключ. слова: ночн, шоу, вирт, развлек, кино, аэро, спорт, рол
- questroom (0.8), stable (0.8); dance-studio (0.5)

**Создавай и пробуй (id=5):**
- 1.0: coworking, handmade, workshops
- amusement — ключ. слова: Third, школа, курсы, студия, танц, филармон, коворк
- education-centers (0.8); dance-studio (0.6); culture (0.5)

---

## 8. Интерактивный квиз

### Принцип работы
- Дерево вопросов с **ветвящимися путями**
- Один тест в системе: `slug = 'mood_flow_v1'`
- Состояние теста передаётся как JSON туда-обратно (без серверного хранения)
- Терминальный вопрос: `next_question_seq = NULL` → запускается поиск мест

### Логика `test_logic.py`
- `get_initial_state()` — создаёт начальное состояние с одним активным путём
- `get_next_question(state)` — определяет следующий вопрос
- `process_answer(state, path_id, question_id, option_ids)` — обновляет критерии пути, создаёт дочерние пути при множественном выборе
- `is_test_completed(state)` — все ли пути достигли терминала
- `get_all_results(state)` — поиск мест по критериям всех завершённых путей

### Структура ветвления (главный вопрос → С кем хочешь провести время?)

**Один:**
- Уединиться и перезагрузиться → Какая атмосфера? (2 варианта)
  - Уютно посидеть → Формат заведения (тихое кафе / вид / гастро-ресторан)
  - Неспешно прогуляться → Куда? (парк / архитектура)
  - Погрузиться в искусство → Куда? (музей/галерея / арт-пространство / театр / исторические)
  - Найти внутреннее спокойствие → [church, temple, monastery, synagogue] + attractions(храм, собор)
- Активно провести время → Какой активности?
  - Создать своими руками → [workshops, handmade] + education-centers + amusement(аэро, студия)
  - Шумное весёлое место → [bar, concert-hall] + amusement(ночн, шоу, вирт, развлек, кино)
  - Заняться спортом → amusement(кон, аэро, спорт, рол, студия, танц) + recreation(кон, батут, спорт, аква)

**С любимым человеком:** → Прогуляться / Необычные впечатления / Культурное событие / Романтический ужин

**С семьёй:** → Спокойно прогуляться / Уютное место / Познавательное

**С друзьями:** → Повеселиться / Искусство / Сотворить новое

### `secondary_conditions` структура
```json
[{
  "slug": "restaurants",
  "keywords": [
    {"kw": "уют", "in_title": true, "in_description": false, "is_negative": false},
    {"kw": "бар", "in_title": true, "in_description": false, "is_negative": true}
  ]
}]
```
Флаг `is_negative = true` → место с этим словом **исключается** из результата.

### API теста
| Метод | Маршрут | Описание |
|-------|---------|---------|
| GET | `/api/test/start` | Начать новый тест |
| POST | `/api/test/answer` | Отправить ответ на вопрос |

---

## 9. Авторизация

### Регистрация (2 этапа)

**Этап 1** (`POST /api/register`):
1. Валидация: email (`is_valid_email()`), username (`is_valid_name()`), password (`is_strong_password()` — мин. 6 символов, заглавные + строчные)
2. Проверка уникальности в `users` и `email_verifications`
3. Генерация 6-значного кода через `secrets.randbelow()`; код и пароль хэшируются до записи
4. Запись в `email_verifications` (TTL 10 мин)
5. Отправка кода на email через SMTP
- Лимит: 5 запросов/час

**Этап 2** (`POST /api/verify-email`):
1. Поиск в `email_verifications` по email + `expires_at > NOW()`
2. Проверка кода через `check_password_hash()`
3. Повторная проверка уникальности email в `users` (race condition protection)
4. INSERT в `users` с ролью 'user' по умолчанию
5. Удаление из `email_verifications`
6. Автоматический логин `login_user(user, remember=True)`
- Лимит: 10 запросов/час

### Вход (`POST /api/login`)
1. SELECT из `users` по email с `is_active = true`
2. `check_password_hash()` — при неудаче логируется в `security_logger` (email + IP)
3. `login_user(user, remember=...)` — Flask-Login записывает ID в зашифрованную сессию
4. После входа: вызов `/api/me` → если роль 'admin' → редирект на `/admin`, иначе на `/`
- Лимит: 5/мин + 20/час
- Страницы `/login` и `/register` возвращаются с `Cache-Control: no-store`

### Сброс пароля (3 шага)
1. Ввод email → генерация кода → запись в `password_resets` (TTL 10 мин). Если email не найден — всё равно возвращается успех (OWASP). Лимит: 3/час.
2. Проверка кода (без смены пароля) — JS показывает форму нового пароля
3. Установка нового пароля: проверка стойкости + роли + кода → обновление `password_hash` → удаление из `password_resets`

---

## 10. Избранное и Посещённые

Два симметричных модуля. Таблицы — join-таблицы с UNIQUE(user_id, place_id) и CASCADE.

### API Избранного
| Метод | Маршрут | Описание |
|-------|---------|---------|
| POST | `/api/favorites/toggle` | Добавить/убрать из избранного |
| GET | `/api/favorites/status` | Какие места в избранном |
| GET | `/api/favorites/list` | Список с пагинацией |
| GET | `/api/favorites/count` | Количество |

### API Посещённых
| Метод | Маршрут | Описание |
|-------|---------|---------|
| POST | `/api/visited/toggle` | Отметить/снять отметку |
| GET | `/api/visited/status` | Статус посещённости для нескольких мест |
| GET | `/api/visited/list` | Список с пагинацией |
| GET | `/api/visited/count` | Количество |

---

## 11. Предложение мест и сообщения об ошибках

### Предложение нового места
Пользователь заполняет форму → запись в `place_suggestions` со статусом `pending`.

**Пользовательские поля:** `user_title`, `user_description`, `user_address`, `user_timetable`, `user_phone`, `user_foreign_url`, `user_photos`, категории в `place_suggestion_user_categories`.

**Поля модератора (заполняет admin):** `moderated_title`, `moderated_short_title`, `moderated_slug`, `moderated_coords`, `moderated_subway`, `moderated_body_text`, `moderated_is_closed`, категории в `place_suggestion_moderated_categories`.

После одобрения → автоматически создаётся запись в `places`. `approved_must_have_created_place` constraint гарантирует заполнение `created_place_id` при статусе 'approved'.

### Сообщение об ошибке
Пользователь указывает `place_id`, `subject`, `message` → запись в `place_reports` со статусом `pending`.
Администратор просматривает, редактирует место и закрывает с `resolution_comment`.

### Пользователь может редактировать свои заявки только в статусе `pending`.

---

## 12. Маршруты пользователя

Упорядоченный именованный набор мест.

### 2 сценария добавления места:
1. **Через ближайшие места**: детальная страница → «Ближайшие места» → карта Leaflet с маркерами → клик на место → добавить в маршрут
2. **Через кнопку «Добавить в маршрут»**: выбор существующего маршрута или создание нового

### Поиск ближайших мест
Координаты в JSONB `{"lat": ..., "lon": ...}`. Используется **формула Haversine**, реализованная прямо в SQL.

### API маршрутов
| Метод | Маршрут | Описание |
|-------|---------|---------|
| GET | `/api/routes` | Список маршрутов пользователя |
| POST | `/api/routes` | Создать маршрут |
| GET | `/api/routes/{id}` | Детали маршрута |
| PUT | `/api/routes/{id}` | Обновить название/описание |
| DELETE | `/api/routes/{id}` | Удалить маршрут |
| POST | `/api/routes/{id}/places` | Добавить места |
| DELETE | `/api/routes/{id}/places/{place_id}` | Убрать место |
| PUT | `/api/routes/{id}/places/order` | Изменить порядок мест |

---

## 13. Административная панель

Доступна только пользователям с `role = 'admin'`. Все маршруты защищены `@login_required` + `@admin_required`.

### Роли и доступ
- Назначение роли admin — **только разработчик напрямую в БД**
- `/api/login` роль не возвращает → фронт вызывает `/api/me` после логина
- Если admin → редирект на `/admin`

### Dashboard (`/admin`)
- Статистика: количество мест, pending-предложений, pending-отчётов
- Лента последних 10 активностей (предложения, отчёты, одобрения)
- Автообновление каждые 30 секунд

### Управление местами
- `/admin/places` — список всех мест с поиском и пагинацией
- `/admin/place/{id}` — редактирование: title, short_title, slug, address, timetable, phone, description, body_text, foreign_url, coords, categories, photos, is_closed

### Модерация предложений (`/admin/suggestions`)
1. Просмотр списка (фильтр по статусу: pending/approved/rejected)
2. Детальная страница — видны пользовательские данные + поля для заполнения модератором
3. Проверка дубликатов перед одобрением (`/api/admin/suggestions/{id}/check-duplicates`)
4. Загрузка фото модератором
5. **Одобрение** → валидация required полей + проверка уникальности slug → INSERT в `places` (данные модератора приоритетны над пользовательскими) → статус 'approved' + `created_place_id`
6. **Отклонение** → статус 'rejected' + `admin_comment`

### Модерация отчётов об ошибках (`/admin/reports`)
1. Просмотр списка (фильтр: pending/resolved)
2. Детальная страница — отчёт + полные данные места
3. Обновление места без закрытия (`/api/admin/reports/{id}/update-place`)
4. Закрытие отчёта с `resolution_comment` (`/api/admin/reports/{id}/resolve`)

### Полный список API endpoints администратора

| Метод | Маршрут | Описание |
|-------|---------|---------|
| GET | `/api/me` | Текущий пользователь + роль (с логированием IP) |
| GET | `/api/admin/dashboard/stats` | Статистика дашборда |
| GET | `/api/admin/dashboard/activities` | Последние 10 активностей |
| GET | `/api/admin/places` | Список мест |
| GET | `/api/admin/place/{id}` | Полные данные места |
| POST | `/api/admin/place/{id}/update` | Сохранить изменения места |
| GET | `/api/admin/suggestions` | Список предложений |
| GET | `/api/admin/suggestions/{id}` | Детали предложения |
| PUT | `/api/admin/suggestions/{id}` | Обновить поля предложения |
| POST | `/api/admin/suggestions/{id}/approve` | Одобрить → создать место |
| POST | `/api/admin/suggestions/{id}/reject` | Отклонить |
| POST | `/api/admin/suggestions/{id}/check-duplicates` | Проверить дубликаты |
| POST | `/api/admin/suggestions/upload-photo` | Загрузить фото |
| GET | `/api/admin/categories` | Категории со статистикой |
| GET | `/api/admin/reports` | Список отчётов |
| GET | `/api/admin/reports/{id}` | Детали отчёта |
| POST | `/api/admin/reports/{id}/resolve` | Закрыть отчёт |
| POST | `/api/admin/reports/{id}/update-place` | Обновить место по отчёту |

---

## 14. Профиль пользователя

Доступен по `/profile`. Функционал:
- Просмотр данных профиля
- Изменение имени пользователя
- Загрузка/смена аватара (через Pillow-валидацию + UUID-имя)
- Просмотр своих предложений и отчётов (с историей статусов)
- Редактирование pending-заявок
- Удаление аккаунта

> Все маршруты `profile_bp` зарегистрированы с префиксом `/profile`, поэтому полный путь начинается с него.

| Метод | Маршрут | Описание |
|-------|---------|---------|
| GET | `/profile/data` | Данные профиля |
| POST | `/profile/api/profile/update` | Обновить имя + аватар |
| GET | `/profile/api/profile/suggestions/stats` | Статистика предложений по статусам |
| GET | `/profile/api/avatars` | Доступные аватары |
| DELETE | `/profile/api/profile/delete` | Удалить аккаунт |

---

## 15. Основные API endpoints (сводная таблица)

### Места и главная страница
| Метод | Маршрут | Описание |
|-------|---------|---------|
| GET | `/api/random-places` | Случайные места с фото |
| GET | `/api/all-places` | Все активные места с пагинацией |
| GET | `/api/filter-by-mood` | Места по настроению |
| GET | `/api/places/search-filter` | Поиск + фильтрация |
| GET | `/api/places/search` | Быстрый поиск по названию |
| GET | `/api/places/{place_id}/nearby` | Ближайшие места (Haversine) |

### Модели данных (`app/models.py`)
Четыре plain Python класса (не SQLAlchemy):
- `User(UserMixin)` — Flask-Login интеграция
- `Place` — read-only обёртка, `get_nearby()` использует Haversine в SQL
- `Route` — CRUD маршрутов
- `RoutePlace` — junction table

---

## 16. Конфигурация и деплой

**Обязательные переменные окружения:**
- `SECRET_KEY` — Flask session security
- `DB_PASSWORD` — пароль PostgreSQL

**База данных по умолчанию:** `localhost:5433`, db=`spb_places`, user=`apollinaria`

**Файловые загрузки:**
- `MAX_CONTENT_LENGTH = 50MB`
- Допустимые расширения: png, jpg, jpeg, gif, webp
- Пути: `static/uploads/<folder>/` + `static/avatars/`
- UUID-имена файлов

**Продакшн:** сервер `195.19.153.51`, домен `atmosfera-piter.ru`, HTTPS.
Gunicorn → Nginx. Конфиг Nginx в `nginx/`. Docker Compose для локального запуска.

**Полный список переменных конфигурации:**
| Переменная | Значение по умолчанию | Описание |
|------------|----------------------|---------|
| `SECRET_KEY` | — (обязательна) | Flask session |
| `DB_PASSWORD` | — (обязательна) | Пароль PostgreSQL |
| `DB_HOST` | `localhost` | Хост БД |
| `DB_PORT` | `5433` | Порт БД |
| `DB_NAME` | `spb_places` | Имя БД |
| `DB_USER` | `apollinaria` | Пользователь БД |
| `MAIL_SERVER` | `smtp.mail.ru` | SMTP-сервер |
| `MAIL_PORT` | `587` | SMTP-порт (TLS) |
| `MAIL_USE_TLS` | `true` | Использовать TLS |
| `MAX_CONTENT_LENGTH` | `52428800` (50MB) | Максимум загрузки |
| `UPLOAD_FOLDER` | `static/uploads` | Папка загрузок |
| `SESSION_COOKIE_HTTPONLY` | `True` | JS не видит cookie |
| `SESSION_COOKIE_SAMESITE` | `Lax` | Защита от CSRF |
| `SESSION_COOKIE_SECURE` | `true` (из env) | Только HTTPS |
| `PERMANENT_SESSION_LIFETIME` | `7 days` | Срок жизни сессии |

---

## 17. Права доступа по ролям

### Неавторизованный пользователь
- Просмотр главной страницы (`index.html`) с подборкой по настроениям
- Просмотр страницы детального описания места (`place_detail.html`)
- Просмотр страницы со списком всех мест (`places.html`) — поиск + фильтрация по категориям

### Авторизованный пользователь (`role = 'user'`)
Всё, что доступно гостю, плюс:
- Прохождение квиза для подбора мест
- Избранное (добавление/удаление, список с пагинацией)
- Посещённые места (отметка/снятие, список с пагинацией)
- Создание и управление маршрутами
- Личный кабинет (смена имени, аватара)
- Предложение новых мест (с прикреплением фотографий)
- Сообщения об ошибках в существующих местах
- Просмотр статуса своих заявок
- Редактирование заявок в статусе `pending`

### Администратор (`role = 'admin'`)
Всё, что доступно пользователю, плюс панель `/admin`:
- Редактирование всех мест в БД
- Модерация предложений (исправить → одобрить / отклонить)
- Модерация отчётов об ошибках
- Просмотр статистики и ленты активности

**Как назначается роль admin:** только разработчик вручную через прямой SQL в БД. Публичные endpoint-ы роль не раскрывают и не позволяют её установить.

---

## 18. Валидация данных

### Точные правила (`app/utils.py`)

**Email** (`is_valid_email`):
```
^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$
```

**Username** (`is_valid_name`):
```
^[a-zA-Zа-яА-ЯёЁ\s\-]+$
```
- Допустимы: буквы латиницы и кириллицы, пробелы, дефисы
- Максимум 30 символов
- Только буквы в начале

**Пароль** (`is_strong_password`):
- Минимум 6 символов
- Обязательно есть хотя бы одна заглавная буква `[A-ZА-ЯЁ]`
- Обязательно есть хотя бы одна строчная буква `[a-zа-яё]`

**Проверка занятости username** (`/api/check-username`):
- Проверяет таблицу `users` И таблицу `email_verifications` (незавершённые регистрации, не истёкшие)
- Лимит: 60 запросов/минуту

### Валидация файлов (`save_uploaded_file`)
1. Проверка расширения из whitelist: `{png, jpg, jpeg, gif, webp}`
2. Открытие через `PIL.Image` и вызов `verify()` — проверяет содержимое файла
3. Генерация UUID-имени: `uuid4().hex + '.' + ext`
4. Сохранение в `static/uploads/{folder}/{uuid}.ext`

### Ограничения полей сообщений об ошибках
- `subject` — максимум 200 символов
- `message` — максимум 2000 символов

---

## 19. Rate Limiting — сводная таблица

| Endpoint | Лимит |
|----------|-------|
| `POST /api/register` | 5 / час |
| `POST /api/verify-email` | 10 / час |
| `POST /api/resend-code` | 5 / час |
| `POST /api/login` | 5 / мин + 20 / час |
| `GET /login` (страница) | 5 / мин |
| `POST /api/forgot-password` | 3 / час |
| `POST /api/verify-reset-code` | 10 / час |
| `POST /api/reset-password` | 5 / час |
| `GET /api/check-username` | 60 / мин |
| `POST /api/suggest-place` | 5 / час |
| `POST /api/suggestions/{id}/photo` | 20 / час |
| `POST /api/report-error` | 10 / час |
| `GET /api/places/search` | 60 / мин |

Rate Limiting реализован через **Flask-Limiter** с **in-memory** хранилищем. Ключ — IP-адрес клиента (`get_remote_address`). При превышении возвращается HTTP 429.

> ⚠️ In-memory хранилище не подходит для нескольких воркеров Gunicorn — лимиты не разделяются между процессами.

---

## 20. Логика ключевых страниц

### Главная страница (`GET /`)
При рендере `index.html` загружается:
1. **3 случайных места с фото** — `WHERE NOT is_closed AND main_photo_url IS NOT NULL ORDER BY RANDOM() LIMIT 3`
2. **Все 5 настроений** из таблицы `moods`
3. **10 случайных мест** (без требования к фото) для дополнительного блока

### Страница детального места (`GET /place/<place_id>`)
Сложная обработка перед рендером:

**Фотографии:** объединяются из трёх источников:
1. Поле `main_photo_url` (если заполнено)
2. Массив `photos` (JSONB)
3. URL-адреса `<img>` тегов из `body_text` — извлекаются через regex

**Очистка контента:** из `body_text` и `description` удаляются HTML-теги (`<img>`, `<p>`, `<div>` и другие).

**Метро:** `subway` (JSONB) парсится до 5 станций с полями `name`, `color`, `distance_km`.

**Координаты:** `coords` (JSONB) парсится в `lat` / `lon`.

**Категории:** slug-и из `categories` JSONB-массива обогащаются именами через JOIN с `categories_api`.

**Навигация:** параметры `back_id` и `from_page` сохраняются для отображения кнопки «назад».

### Страница списка мест (`GET /api/places/search-filter`)
Поиск работает с приоритетами:
1. title **начинается** с запроса (наивысший приоритет)
2. title **содержит** запрос
3. description **содержит** запрос
4. address **содержит** запрос
5. совпадение по категории

Фильтрация по категориям: `categories JSONB @> '["slug"]'::jsonb` — проверяет наличие slug в JSONB-массиве.

Параметры: `q` (строка поиска), `category` (через запятую), `page` (default 1), `per_page` (default 12).

### Случайные места (`GET /api/all-places`)
Параметры: `limit` (default 10), `offset` (default 0), `exclude_ids` (через запятую — места, уже показанные).

---

## 21. Механика квиза — детали реализации

### Состояние теста (`state`)
Общее состояние, которое сервер отдаёт клиенту и принимает обратно, состоит из трёх полей:
```python
{
  "active_paths": [...],     # незавершённые пути (по ним ещё есть вопросы)
  "completed_paths": [...],  # завершённые пути с уже найденными местами
  "next_path_id": 2          # счётчик ID для новых путей при ветвлении
}
```

### Состояние пути (`path`)
Каждый активный путь хранит:
```python
{
  "id": 1,
  "parent_path_id": None,      # ID родительского пути при ветвлении
  "current_question_seq": 1,   # на каком вопросе сейчас находится путь
  "mood_ids": set(),            # накопленные ID настроений
  "primary_slugs": set(),       # накопленные основные категории
  "secondary_conditions": [],   # накопленные вторичные условия
  "negative_keywords": set(),   # накопленные исключающие слова
  "answers": []                 # история ответов пользователя на этом пути
}
```
При сериализации в JSON: поля-множества (`set`) → `list` (и обратно при десериализации).
Завершённый путь хранится отдельно в `completed_paths` и имеет другую структуру:
`id`, `parent_path_id`, `criteria` (итоговые критерии поиска), `places` (найденные места), `answers`.

### Ветвление при множественном выборе (`allow_multiple = True`)
- Первый выбранный вариант → **продолжает текущий путь**
- Каждый последующий вариант → **клонирует путь** (`clone_path`) с новым `id` и `parent_path_id`
- Итог: N выбранных вариантов → N параллельных путей

### Завершение пути
Если ответ ведёт к `next_question_seq = NULL` → путь завершён → вызывается `complete_path()`:

**Стратегия поиска мест (3 уровня fallback):**
1. `find_test_places_v2(primary_slugs, mood_ids, secondary_conditions::JSONB)` — основная функция
2. `find_places_for_test(primary_slugs, mood_ids, keywords::JSONB)` — упрощённый вариант
3. Простой SQL-запрос по категориям — последний резерв

### Финальные результаты
`get_all_results()` объединяет места из всех завершённых путей, **дедуплицирует по place_id**.

### Debug endpoint
`GET /api/debug/test-search` — проверяет: статистику категорий, ключевых слов, результаты `find_places_by_mood`, список категорий в БД.

---

## 22. Модели данных — полные сигнатуры

### `User(UserMixin)`
```python
User(user_data: dict)    # принимает строку-словарь из БД (DictCursor)
# Атрибуты: id (str), email, username, role, avatar_url,
#           _active (bool), created_at, updated_at

user.get_display_name()  # → username или email-префикс
user.get_id()            # → str(id), нужен Flask-Login
user.is_active           # → property, bool
```

### `Place`
```python
Place.get_by_id(place_id: int) -> Place | None

Place.get_nearby(place_id: int, radius: int = 1000, limit: int = 10) -> list[dict]
# Haversine SQL:
# distance = 6371000 * 2 * asin(sqrt(
#   power(sin((lat2-lat1)/2), 2) +
#   cos(lat1) * cos(lat2) * power(sin((lon2-lon1)/2), 2)
# ))
# WHERE distance < radius ORDER BY distance
# Возвращает: id, title, coords, distance (округл. до 0.1м), description, address, main_photo_url, photos
```

### `Route`
```python
Route.create(user_id, name, description) -> Route
Route.get_by_id(route_id) -> Route | None
Route.get_by_user(user_id) -> list[Route]   # ORDER BY created_at DESC

route.update(name=None, description=None)   # COALESCE — обновляет только заполненные
route.delete()
route.add_place(place_id)                   # ON CONFLICT DO NOTHING (дубли игнорируются)
route.remove_place(place_id) -> bool
route.get_places() -> list[dict]            # ORDER BY order_index
route.update_places_order(place_ids_in_order: list[int])
```

### `RoutePlace`
```python
RoutePlace.get_by_route_and_place(route_id, place_id) -> RoutePlace | None
```

---

## 23. Обработка данных — утилиты (`app/utils.py`)

### `process_place_row(row: dict) -> dict`
Нормализует строку из БД перед отдачей в шаблон или JSON:
1. `datetime` объекты сериализуются в ISO-формат строки
2. Поле `categories_list` извлекается из JSONB
3. `photo_url` проверяется (не пустая строка)
4. `description` очищается от HTML-тегов и усекается до **200 символов**
5. Гарантирует наличие поля `title`

### `process_categories(categories)`
Обрабатывает три формата входных данных:
- `None` → `[]`
- `str` → `json.loads(str)`
- `list` → возвращает как есть

### `get_db_connection()`
- Создаёт `psycopg2` соединение из `current_app.config`
- Устанавливает `autocommit = True` по умолчанию
- Использует `DictCursor` — строки доступны как словари

---

## 24. Email-уведомления

### `send_verification_email(recipient_email, code, purpose)`
- `purpose = 'register'` → тема: **«Код подтверждения регистрации»**
- `purpose = 'reset'` → тема: **«Код для сброса пароля»**
- HTML-письмо с кодом крупным шрифтом (32px)
- Указывается срок действия: **10 минут**
- Отправка через SMTP с TLS (`MAIL_SERVER`, `MAIL_PORT=587`)
- Возвращает `(success: bool, error_msg: str | None)`

---

## 25. Сценарий удаления аккаунта

`DELETE /profile/api/profile/delete` — удаление выполняется одной транзакцией, все связанные записи стираются явными `DELETE` в правильном порядке (зависимые — раньше родительских):
1. `DELETE FROM favorites WHERE user_id`
2. `DELETE FROM visited_places WHERE user_id`
3. `DELETE FROM route_places` (по маршрутам пользователя через подзапрос)
4. `DELETE FROM routes WHERE user_id`
5. `DELETE FROM place_reports WHERE user_id` — отчёты пользователя удаляются физически
6. `DELETE FROM place_suggestion_user_categories` (по заявкам пользователя)
7. `DELETE FROM place_suggestion_moderated_categories` (по заявкам пользователя)
8. `DELETE FROM place_suggestions WHERE user_id` — предложения пользователя удаляются физически
9. `DELETE FROM users WHERE id`
10. `conn.commit()` + `logout_user()` — фиксация транзакции и завершение сессии

> Места (`places`), созданные на основе одобренных предложений пользователя, при удалении аккаунта **не трогаются** — они уже часть общего каталога.

---

## 26. Статические ресурсы

### Шрифты (`static/fonts/`)
- **Montserrat** — основной шрифт интерфейса: Regular (TTF + WOFF + WOFF2), Bold и Medium (WOFF + WOFF2)
- **Kreadon Medium** — акцентный шрифт для заголовков (TTF + WOFF + WOFF2)

### Изображения (`static/images/`)
- Фоновые фотографии для главной: `colonna`, `kazan`, `streat`, `kazanski` и другие
- `favicon`, `placeholder`, `no_foto` — служебные

### CSS-файлы (`static/`)
| Файл | Назначение |
|------|-----------|
| `style.css` | Глобальные стили |
| `index.css` | Главная страница |
| `place.css` | Список мест |
| `place_detail.css` | Детальная страница места |
| `favorites.css` | Избранное |
| `visited.css` | Посещённые места |
| `routes.css` | Маршруты |
| `test.css` | Квиз |
| `header.css` | Шапка/навигация |
| `auth/login.css` | Страница входа |
| `auth/register.css` | Страница регистрации |
| `admin/admin.css` | Общие стили панели |
| `admin/admin_form.css` | Формы модерации |
| `profile/profile.css` | Личный кабинет |
| `profile/edit.css` | Форма редактирования профиля |
| `profile/profile_rep_sug_about.css` | Карточка заявки/отчёта |
| `profile/profile_rep_sug_view.css` | Просмотр заявки/отчёта |
| `profile/user_suggestions.css` | Список заявок пользователя |
| `adapt/place_list_adapt.css` | Адаптив списка мест |

### Документы (`static/doc/`)
- `cookie_policy.pdf` — политика cookies
- `privacy_policy.pdf` — политика конфиденциальности
