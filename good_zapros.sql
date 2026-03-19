-- Выборка по определенному слову
SELECT id, title, address
FROM places
WHERE title ILIKE '%Юсуповский дворец%';


-- изменить размер первой буквы в строке (с прописной в заглавную)
UPDATE places
SET title = upper(left(title, 1)) || substr(title, 2)
WHERE title ~ '^[а-я]';

-- ИЗМЕНИТЬ РОЛЬ ПОЛЬЗОВАТЕЛЯ
UPDATE users
SET role = '',
    updated_at = NOW()
WHERE email = '';

-- Выборка по определенному слову
SELECT id, title, address, categories
FROM places
WHERE title ILIKE '%%';

-- DELETE FROM places
-- WHERE title ILIKE '%%';
--- ЕСЛИ ТЫ ДУРА И УДАЛИЛА ТО, ЧТО НЕ НАДО БЫЛО, НО ЕСТЬ CSV ФАЙЛ С ДАННЫМИ, ТО
    -- создаем новую такую же таблицу, откуда удалили данные, копируем туда данные и выполняем эти действия

create table dyra (
                      id serial primary key,
                      external_id integer unique,
                      title varchar(300) not null,
                      short_title varchar(200) unique,
                      slug varchar(200) unique,
                      categories jsonb,
                      address text,
                      timetable text,
                      phone varchar(50),
                      description text,
                      body_text text,
                      foreign_url varchar(500),
                      coords jsonb,
                      subway jsonb,
                      is_closed boolean default false,
                      photos JSONB DEFAULT '[]'::jsonb,
                      main_photo_url VARCHAR(500),
                      created_at TIMESTAMP DEFAULT NOW()

);

SELECT *
FROM dyra
WHERE categories ? 'bar';

INSERT INTO places (
    id, external_id, title, short_title, slug, categories,
    address, timetable, phone, description, body_text,
    foreign_url, coords, subway, is_closed, created_at,
    photos, main_photo_url
)
SELECT
    id, external_id, title, short_title, slug, categories,
    address, timetable, phone, description, body_text,
    foreign_url, coords, subway, is_closed, created_at,
    photos, main_photo_url
FROM dyra
WHERE categories ? 'bar'
ON CONFLICT (id) DO NOTHING;

-- НА БУДУЩЕЕ
-- Перед такими чистками

-- BEGIN;
--
-- DELETE FROM places
-- WHERE categories ? 'bar'
-- RETURNING id, title;

-- проверить глазами


--Изменить фотографию в месте, если ее нет
UPDATE places
SET main_photo_url = 'https://www.etovidel.net/appended_files/big/4e17562b8a76b.jpg'
WHERE id = 683;


UPDATE places
SET photos = '[{"url": "https://avatars.mds.yandex.net/get-altay/13061180/2a0000018eb53855469b7808444af4c00926/XXL_height", "source": "custom", "is_main": true}]'::jsonb
WHERE id = 683;



--ЕСЛИ Я ХОЧУ УДАЛИТЬ ИЗ БАЗЫ ДОБАВЛЕННОЕ МЕСТО ОТ ПОЛЬЗОВАТЕЛЯ
-- Шаг 1. Снять одобренный статус с предложения
-- смотрим, какой статус у предложения 'pending' или 'approved' и меняем его на 'rejected', потому что только с этим статусом можно удалять предложения
UPDATE place_suggestions
SET status = 'rejected'
WHERE id = 69 AND status = 'pending';


-- Шаг 2. Удалить само место (если нужно)
DELETE FROM places WHERE id = (SELECT created_place_id FROM place_suggestions WHERE id = 68);

-- Шаг 3. Удалить предложение
DELETE FROM place_suggestions WHERE id = 69;

-- Шаг 3. Удалить сообщение об ошибке
DELETE FROM place_reports WHERE id = 19;