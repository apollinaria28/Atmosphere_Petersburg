-- Улучшенная функция поиска мест для теста
CREATE OR REPLACE FUNCTION find_test_places_v2(
    p_primary_slugs TEXT[],
    p_mood_ids INTEGER[],
    p_secondary_conditions JSONB DEFAULT '[]'::JSONB
) RETURNS TABLE (
                    place_id INTEGER,
                    title VARCHAR,
                    slug VARCHAR,
                    categories JSONB,
                    photo_url VARCHAR,
                    description TEXT,
                    address TEXT,
                    timetable TEXT,
                    body_text TEXT,
                    match_score INTEGER,
                    match_type VARCHAR
                ) AS $$
DECLARE
    condition JSONB;
    keyword JSONB;
    search_conditions TEXT := '';
    condition_count INTEGER := 0;
BEGIN
    -- 1. Условия по primary категориям
    IF array_length(p_primary_slugs, 1) > 0 THEN
        search_conditions := search_conditions ||
                             'EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.categories) cat WHERE cat = ANY($1))';
        condition_count := condition_count + 1;
    END IF;

    -- 2. Условия из secondary_conditions
    IF p_secondary_conditions IS NOT NULL AND p_secondary_conditions != '[]'::JSONB THEN
        FOR condition IN SELECT * FROM jsonb_array_elements(p_secondary_conditions)
            LOOP
                FOR keyword IN SELECT * FROM jsonb_array_elements(condition->'keywords')
                    LOOP
                        IF condition_count > 0 THEN
                            search_conditions := search_conditions || ' OR ';
                        END IF;

                        IF (keyword->>'is_negative')::BOOLEAN = false THEN
                            IF (keyword->>'in_title')::BOOLEAN = true THEN
                                search_conditions := search_conditions ||
                                                     format('p.title ILIKE %L', '%%' || (keyword->>'kw') || '%%');
                                condition_count := condition_count + 1;
                            END IF;

                            IF (keyword->>'in_description')::BOOLEAN = true THEN
                                IF condition_count > 0 AND
                                   NOT search_conditions LIKE '%p.description ILIKE%' THEN
                                    search_conditions := search_conditions || ' OR ';
                                END IF;
                                search_conditions := search_conditions ||
                                                     format('(p.description ILIKE %L OR p.body_text ILIKE %L)',
                                                            '%%' || (keyword->>'kw') || '%%',
                                                            '%%' || (keyword->>'kw') || '%%');
                                condition_count := condition_count + 1;
                            END IF;
                        END IF;
                    END LOOP;
            END LOOP;
    END IF;

    -- 3. Если условий нет, возвращаем пустой результат
    IF condition_count = 0 THEN
        RETURN;
    END IF;

    -- 4. Основной запрос
    RETURN QUERY EXECUTE format('
        SELECT
            p.id as place_id,
            p.title,
            p.slug,
            p.categories,
            COALESCE(p.main_photo_url, '''') as photo_url,
            COALESCE(p.description, '''') as description,
            COALESCE(p.address, '''') as address,
            COALESCE(p.timetable, '''') as timetable,
            COALESCE(p.body_text, '''') as body_text,
            CASE
                WHEN p.categories ?| $1 THEN 100
                ELSE 80
            END as match_score,
            CASE
                WHEN p.categories ?| $1 THEN ''primary_category''
                ELSE ''keyword_match''
            END as match_type
        FROM places p
        WHERE NOT COALESCE(p.is_closed, false)
          AND (%s)
        ORDER BY match_score DESC, RANDOM()
        LIMIT 20',
                                COALESCE(search_conditions, 'true')
                         ) USING p_primary_slugs;
END;
$$ LANGUAGE plpgsql;