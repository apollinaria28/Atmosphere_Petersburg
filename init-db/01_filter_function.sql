--ФУНКЦИЯ ДЛЯ ФИЛЬТРАЦИИ

CREATE OR REPLACE FUNCTION find_places_by_mood(mood_id_param INTEGER)
    RETURNS TABLE(
                     place_id INTEGER,
                     title VARCHAR(300),
                     slug VARCHAR(200),
                     categories JSONB,
                     match_score DECIMAL,
                     match_type TEXT
                 ) AS $$
BEGIN
    RETURN QUERY
        WITH negative_matches AS (
            -- Находим места с отрицательными ключевыми словами
            SELECT DISTINCT p.id
            FROM places p
                     CROSS JOIN LATERAL jsonb_array_elements_text(p.categories) AS cat_slug
                     INNER JOIN mood_keywords mk ON mk.categories_api_slug = cat_slug
                AND mk.mood_id = mood_id_param
            WHERE mk.is_negative = true
              AND (
                (mk.search_in_title AND p.title ILIKE '%' || mk.keyword || '%')
                    OR (mk.search_in_description AND COALESCE(p.description, '') ILIKE '%' || mk.keyword || '%')
                )
        ),
             primary_places AS (
                 -- Места с ОСНОВНЫМИ категориями (точно подходят)
                 SELECT
                     p.id,
                     p.title,
                     p.slug,
                     p.categories,
                     SUM(pcm.confidence) as score,
                     'PRIMARY' as match_type
                 FROM places p
                          CROSS JOIN LATERAL jsonb_array_elements_text(p.categories) AS cat_slug
                          INNER JOIN primary_category_moods pcm ON pcm.categories_api_slug = cat_slug
                     AND pcm.mood_id = mood_id_param
                 WHERE NOT p.is_closed
                 GROUP BY p.id, p.title, p.slug, p.categories
             ),
             secondary_places AS (
                 -- Места с ВТОРИЧНЫМИ категориями + ключевые слова
                 SELECT
                     p.id,
                     p.title,
                     p.slug,
                     p.categories,
                     SUM(scm.confidence) as score,
                     'SECONDARY' as match_type
                 FROM places p
                          CROSS JOIN LATERAL jsonb_array_elements_text(p.categories) AS cat_slug
                          INNER JOIN secondary_category_moods scm ON scm.categories_api_slug = cat_slug
                     AND scm.mood_id = mood_id_param
                 WHERE NOT p.is_closed
                   -- Проверяем наличие ключевых слов
                   AND EXISTS (
                     SELECT 1
                     FROM mood_keywords mk
                     WHERE mk.mood_id = mood_id_param
                       AND mk.categories_api_slug = cat_slug
                       AND mk.is_negative = false
                       AND (
                         (mk.search_in_title AND p.title ILIKE '%' || mk.keyword || '%')
                             OR (mk.search_in_description AND COALESCE(p.description, '') ILIKE '%' || mk.keyword || '%')
                         )
                 )
                   -- Исключаем места, которые уже попали в основные
                   AND p.id NOT IN (SELECT id FROM primary_places)
                 GROUP BY p.id, p.title, p.slug, p.categories
             ),
             combined_results AS (
                 SELECT * FROM primary_places
                 UNION ALL
                 SELECT * FROM secondary_places
             )
        SELECT
            cr.id,
            cr.title,
            cr.slug,
            cr.categories,
            cr.score,
            cr.match_type
        FROM combined_results cr
        WHERE cr.id NOT IN (SELECT id FROM negative_matches)
        ORDER BY
            -- Сначала ВСЕ основные места
            CASE WHEN cr.match_type = 'PRIMARY' THEN 1 ELSE 2 END,
            -- Потом сортируем по убыванию score внутри каждой группы
            cr.score DESC;
END;
$$ LANGUAGE plpgsql;


CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Основные индексы для таблиц настроений
CREATE INDEX idx_primary_category_moods_mood ON primary_category_moods(mood_id);
CREATE INDEX idx_secondary_category_moods_mood ON secondary_category_moods(mood_id);
CREATE INDEX idx_mood_keywords_mood_slug ON mood_keywords(mood_id, categories_api_slug);

-- Индексы для таблицы places
CREATE INDEX idx_places_categories_gin ON places USING GIN (categories);
CREATE INDEX idx_places_title_trgm ON places USING GIN (title gin_trgm_ops);
CREATE INDEX idx_places_is_closed ON places(is_closed);