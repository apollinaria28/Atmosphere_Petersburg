from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
import psycopg2
import psycopg2.extras
import json
import traceback
from app.db import get_db_connection 
from ..utils import process_place_row, process_categories

from flask_login import login_required

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """Главная страница"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # 3 случайных места с фото
        cur.execute("""
            SELECT id, title, slug, categories,
                   COALESCE(main_photo_url, '') as photo_url,
                   COALESCE(description, '') as description,
                   COALESCE(address, '') as address,
                   COALESCE(timetable, '') as timetable
            FROM places
            WHERE NOT is_closed
              AND main_photo_url IS NOT NULL
            ORDER BY RANDOM()
            LIMIT 3
        """)
        random_places = [process_place_row(row) for row in cur.fetchall()]

        # Все настроения
        cur.execute("SELECT id, name FROM moods ORDER BY id")
        moods = cur.fetchall()

        # 10 случайных мест (можно оставить как есть)
        cur.execute("""
            SELECT id, title, slug, categories,
                   COALESCE(main_photo_url, '') as photo_url,
                   COALESCE(description, '') as description,
                   COALESCE(address, '') as address,
                   COALESCE(timetable, '') as timetable
            FROM places
            WHERE NOT is_closed
            ORDER BY RANDOM()
            LIMIT 10
        """)
        all_places = [process_place_row(row) for row in cur.fetchall()]

        return render_template('index.html',
                               random_places=random_places,
                               moods=moods,
                               all_places=all_places)

    except Exception as e:
        print(f"Ошибка в index(): {e}")
        traceback.print_exc()
        return "Ошибка сервера", 500
    finally:
        cur.close()
        conn.close()

@main_bp.route('/routes')
def routes_page():
    return render_template('routes.html', active_page='routes')


@main_bp.route('/api/random-places')
def get_random_places():
    """API для получения случайных мест"""
    limit = request.args.get('limit', 5, type=int)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("""
            SELECT id, title, slug, categories,
                   COALESCE(main_photo_url, '') as photo_url,
                   COALESCE(description, '') as description,
                   COALESCE(address, '') as address,
                   COALESCE(timetable, '') as timetable
            FROM places
            WHERE NOT is_closed
              AND main_photo_url IS NOT NULL
            ORDER BY RANDOM()
            LIMIT %s
        """, (limit,))
        places = [process_place_row(row) for row in cur.fetchall()]
        return jsonify({'success': True, 'places': places})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@main_bp.route('/api/all-places')
def get_all_places():
    """API для получения всех мест с пагинацией"""
    limit = request.args.get('limit', 10, type=int)
    offset = request.args.get('offset', 0, type=int)
    exclude_ids_str = request.args.get('exclude_ids', '')
    exclude_ids = []
    if exclude_ids_str:
        exclude_ids = [int(id.strip()) for id in exclude_ids_str.split(',') if id.strip()]

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        # Общее количество мест
        cur.execute("SELECT COUNT(*) as total FROM places WHERE NOT is_closed")
        total_count = cur.fetchone()['total']

        if exclude_ids:
            exclude_ids_sql = ','.join(map(str, exclude_ids))
            cur.execute(f"""
                SELECT id, title, slug, categories,
                       COALESCE(main_photo_url, '') as photo_url,
                       COALESCE(description, '') as description,
                       COALESCE(address, '') as address,
                       COALESCE(timetable, '') as timetable
                FROM places
                WHERE NOT is_closed
                  AND id NOT IN ({exclude_ids_sql})
                ORDER BY RANDOM()
                LIMIT %s
            """, (limit,))
        else:
            cur.execute("""
                SELECT id, title, slug, categories,
                       COALESCE(main_photo_url, '') as photo_url,
                       COALESCE(description, '') as description,
                       COALESCE(address, '') as address,
                       COALESCE(timetable, '') as timetable
                FROM places
                WHERE NOT is_closed
                ORDER BY RANDOM()
                LIMIT %s
            """, (limit,))

        places = [process_place_row(row) for row in cur.fetchall()]

        # Оставшееся количество
        if exclude_ids:
            cur.execute(f"""
                SELECT COUNT(*) as remaining
                FROM places
                WHERE NOT is_closed
                  AND id NOT IN ({exclude_ids_sql})
            """)
        else:
            cur.execute("SELECT COUNT(*) as remaining FROM places WHERE NOT is_closed")
        remaining_count = cur.fetchone()['remaining']
        has_more = remaining_count > len(places)

        return jsonify({
            'success': True,
            'places': places,
            'total': total_count,
            'remaining': remaining_count,
            'has_more': has_more
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@main_bp.route('/api/filter-by-mood')
def filter_by_mood():
    """Фильтрация по настроению"""
    mood_id = request.args.get('mood_id', type=int)
    limit = request.args.get('limit', 10, type=int)
    exclude_ids_str = request.args.get('exclude_ids', '')
    exclude_ids = []
    if exclude_ids_str:
        exclude_ids = [int(id.strip()) for id in exclude_ids_str.split(',') if id.strip()]

    if not mood_id:
        return jsonify({'success': False, 'error': 'Не указано настроение'})

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        # Общее количество мест для этого настроения
        cur.execute("SELECT COUNT(*) as total FROM find_places_by_mood(%s)", (mood_id,))
        total_info = cur.fetchone()
        total_count = total_info['total'] if total_info else 0

        if exclude_ids:
            exclude_ids_sql = ','.join(map(str, exclude_ids))
            cur.execute(f"""
                SELECT place_id, title, slug, categories,
                       match_score, match_type,
                       COALESCE(
                           (SELECT main_photo_url FROM places p2 WHERE p2.id = place_id AND NOT p2.is_closed), ''
                       ) as photo_url,
                       COALESCE(
                           (SELECT address FROM places p2 WHERE p2.id = place_id AND NOT p2.is_closed), ''
                       ) as address,
                       COALESCE(
                           (SELECT timetable FROM places p2 WHERE p2.id = place_id AND NOT p2.is_closed), ''
                       ) as timetable,
                       COALESCE(
                           (SELECT description FROM places p2 WHERE p2.id = place_id AND NOT p2.is_closed), ''
                       ) as description
                FROM find_places_by_mood(%s)
                WHERE place_id NOT IN ({exclude_ids_sql})
                ORDER BY RANDOM()
                LIMIT %s
            """, (mood_id, limit))
        else:
            cur.execute("""
                SELECT place_id, title, slug, categories,
                       match_score, match_type,
                       COALESCE(
                           (SELECT main_photo_url FROM places p2 WHERE p2.id = place_id AND NOT p2.is_closed), ''
                       ) as photo_url,
                       COALESCE(
                           (SELECT address FROM places p2 WHERE p2.id = place_id AND NOT p2.is_closed), ''
                       ) as address,
                       COALESCE(
                           (SELECT timetable FROM places p2 WHERE p2.id = place_id AND NOT p2.is_closed), ''
                       ) as timetable,
                       COALESCE(
                           (SELECT description FROM places p2 WHERE p2.id = place_id AND NOT p2.is_closed), ''
                       ) as description
                FROM find_places_by_mood(%s)
                ORDER BY RANDOM()
                LIMIT %s
            """, (mood_id, limit))

        results = cur.fetchall()
        places = []
        for row in results:
            place = dict(row)
            place['id'] = place.pop('place_id')
            places.append(process_place_row(place))

        cur.execute("SELECT name FROM moods WHERE id = %s", (mood_id,))
        mood_info = cur.fetchone()

        # Оставшееся количество
        if exclude_ids:
            exclude_ids_sql = ','.join(map(str, exclude_ids))
            cur.execute(f"""
                SELECT COUNT(*) as remaining
                FROM find_places_by_mood(%s)
                WHERE place_id NOT IN ({exclude_ids_sql})
            """, (mood_id,))
        else:
            cur.execute("SELECT COUNT(*) as remaining FROM find_places_by_mood(%s)", (mood_id,))
        remaining_count = cur.fetchone()['remaining']
        has_more = remaining_count > len(places)

        return jsonify({
            'success': True,
            'mood_id': mood_id,
            'mood_name': mood_info['name'] if mood_info else f'Настроение {mood_id}',
            'places': places,
            'total': total_count,
            'remaining': remaining_count,
            'has_more': has_more
        })
    except Exception as e:
        print(f"Ошибка в filter_by_mood: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

@main_bp.route('/place/<int:place_id>')
def place_detail(place_id):
    """Детальная страница места"""
    from_page = request.args.get('from', 'places')
    back_id = request.args.get('back', type=int)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("SELECT * FROM places WHERE id = %s", (place_id,))
        place = cur.fetchone()
        if not place:
            return "Место не найдено", 404
        place_dict = dict(place)

        # Сбор всех фотографий
        all_photos = []
        if place_dict.get('main_photo_url'):
            all_photos.append({
                'url': place_dict['main_photo_url'],
                'type': 'main',
                'description': 'Главное фото'
            })
        if place_dict.get('photos'):
            try:
                photos_data = place_dict['photos']
                if isinstance(photos_data, str):
                    try:
                        photos_data = json.loads(photos_data)
                    except:
                        pass
                if isinstance(photos_data, list):
                    for i, item in enumerate(photos_data):
                        if isinstance(item, str) and item.strip():
                            all_photos.append({
                                'url': item,
                                'type': 'gallery',
                                'description': f'Фото {i+1}'
                            })
                        elif isinstance(item, dict) and item.get('url'):
                            all_photos.append({
                                'url': item['url'],
                                'type': 'gallery',
                                'description': item.get('description', f'Фото {i+1}')
                            })
                elif isinstance(photos_data, str) and photos_data.strip():
                    all_photos.append({
                        'url': photos_data,
                        'type': 'gallery',
                        'description': 'Дополнительное фото'
                    })
            except Exception as e:
                print(f"Ошибка при обработке photos: {e}")

        # Очистка body_text от img
        clean_body_text = place_dict.get('body_text', '')
        if clean_body_text:
            import re
            img_pattern = r'<img[^>]+src="([^">]+)"'
            img_matches = re.findall(img_pattern, clean_body_text)
            for img_url in img_matches:
                if img_url.startswith('http') and img_url not in [p['url'] for p in all_photos]:
                    all_photos.append({
                        'url': img_url,
                        'type': 'from_text',
                        'description': 'Фото из описания'
                    })
            clean_body_text = re.sub(r'<img[^>]*>', '', clean_body_text)
            clean_body_text = re.sub(r'<p>\s*</p>', '', clean_body_text)
            clean_body_text = re.sub(r'<div>\s*</div>', '', clean_body_text)

        # Категории
        category_names = []
        if place_dict.get('categories'):
            try:
                cats = process_categories(place_dict['categories'])
                for slug in cats:
                    cur.execute("SELECT name FROM categories_api WHERE slug = %s", (slug,))
                    cat_row = cur.fetchone()
                    if cat_row:
                        category_names.append(cat_row['name'])
            except Exception as e:
                print(f"Ошибка при обработке категорий: {e}")

        # Галерея без главного
        gallery_photos = [p for p in all_photos if p.get('type') != 'main']

        # Метро
        subway_info = []
        if place_dict.get('subway'):
            try:
                sub_data = place_dict['subway']
                if isinstance(sub_data, str):
                    sub_data = json.loads(sub_data)
                if isinstance(sub_data, list):
                    for station in sub_data[:5]:
                        if isinstance(station, dict):
                            subway_info.append({
                                'name': station.get('name', ''),
                                'color': station.get('color', '#cccccc'),
                                'distance': station.get('distance_km')
                            })
            except:
                pass

        # Координаты
        coords_info = {}
        if place_dict.get('coords'):
            try:
                c = place_dict['coords']
                if isinstance(c, str):
                    c = json.loads(c)
                if isinstance(c, dict):
                    coords_info = c
            except:
                pass

        # Очистка description
        clean_description = ""
        if place_dict.get('description'):
            import re
            clean_description = re.sub(r'<[^>]+>', '', place_dict['description'])

        # Загружаем данные исходного места если пришли из модалки ближайших
        back_place = None
        if back_id and from_page == 'nearby':
            cur.execute("SELECT id, title FROM places WHERE id = %s", (back_id,))
            back_row = cur.fetchone()
            if back_row:
                back_place = dict(back_row)

        return render_template('place_detail.html',
                               place=place_dict,
                               all_photos=all_photos,
                               gallery_photos=gallery_photos,
                               category_names=category_names,
                               subway_info=subway_info,
                               coords_info=coords_info,
                               clean_body_text=clean_body_text,
                               from_page=from_page,
                               back_place=back_place)

    except Exception as e:
        print(f"Ошибка в place_detail: {e}")
        traceback.print_exc()
        return "Ошибка сервера", 500
    finally:
        cur.close()
        conn.close()

@main_bp.route('/places')
def places_page():
    """Страница со всеми местами"""
    return render_template('places.html')

@main_bp.route('/api/places/search-filter')
def search_filter_places():
    """API для поиска и фильтрации мест"""
    search_query = request.args.get('q', '').strip()
    category_filter = request.args.get('category', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    offset = (page - 1) * per_page
    exclude_ids_str = request.args.get('exclude_ids', '')
    exclude_ids = []
    if exclude_ids_str:
        exclude_ids = [int(id.strip()) for id in exclude_ids_str.split(',') if id.strip()]

    categories_filter = []
    if category_filter:
        categories_filter = [cat.strip() for cat in category_filter.split(',')]

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        sql = """
            SELECT id, title, slug, categories,
                   COALESCE(main_photo_url, '') as photo_url,
                   COALESCE(description, '') as description,
                   COALESCE(address, '') as address,
                   COALESCE(timetable, '') as timetable
            FROM places
            WHERE NOT is_closed
        """
        params = []
        conditions = []

        if search_query:
            conditions.append("""
                (title ILIKE %s OR
                 description ILIKE %s OR
                 address ILIKE %s OR
                 EXISTS (SELECT 1 FROM jsonb_array_elements_text(categories) cat WHERE cat ILIKE %s))
            """)
            search_pattern = f"%{search_query}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

        if categories_filter:
            cat_conditions = []
            for cat in categories_filter:
                cat_conditions.append("categories::jsonb @> %s::jsonb")
                params.append(json.dumps([cat]))
            if cat_conditions:
                conditions.append(f"({' OR '.join(cat_conditions)})")

        if exclude_ids:
            exclude_sql = ','.join(map(str, exclude_ids))
            conditions.append(f"id NOT IN ({exclude_sql})")

        if conditions:
            sql += " AND " + " AND ".join(conditions)

        # Сортировка
        if search_query or categories_filter:
            if search_query:
                sql += """
                    ORDER BY
                        CASE
                            WHEN title ILIKE %s THEN 1
                            WHEN title ILIKE %s THEN 2
                            WHEN description ILIKE %s THEN 3
                            WHEN address ILIKE %s THEN 4
                            ELSE 5
                        END,
                        title ASC
                """
                start_pattern = f"{search_query}%"
                contains_pattern = f"%{search_query}%"
                params.extend([start_pattern, contains_pattern, contains_pattern, contains_pattern])
            else:
                sql += " ORDER BY title ASC"
        else:
            sql += " ORDER BY RANDOM()"

        sql += " LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(sql, params)
        places = [process_place_row(row) for row in cur.fetchall()]

        # Подсчёт общего количества
        count_sql = "SELECT COUNT(*) as total FROM places WHERE NOT is_closed"
        count_params = []
        if conditions:
            count_sql += " AND " + " AND ".join(conditions)
            # Убираем параметры сортировки и пагинации
            if search_query:
                count_params = params[:-6]  # 4 параметра поиска + 2 параметра пагинации?
            else:
                count_params = params[:-2]

        cur.execute(count_sql, count_params)
        total_count = cur.fetchone()['total']

        # Все категории для фильтра
        cur.execute("""
            SELECT DISTINCT ca.slug, ca.name
            FROM categories_api ca
            WHERE EXISTS (
                SELECT 1 FROM places p
                WHERE NOT p.is_closed
                  AND p.categories::jsonb @> jsonb_build_array(ca.slug)
            )
            ORDER BY ca.name
        """)
        all_categories = [{'slug': row['slug'], 'name': row['name']} for row in cur.fetchall()]

        has_more = (offset + len(places)) < total_count

        return jsonify({
            'success': True,
            'places': places,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'has_more': has_more,
            'all_categories': all_categories,
            'search_query': search_query,
            'category_filter': category_filter,
            'is_search_mode': bool(search_query or categories_filter)
        })
    except Exception as e:
        print(f"Ошибка в search_filter_places: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()

# Можно добавить отладочный маршрут, если нужно
@main_bp.route('/api/debug/test-search')
def debug_test_search():
    # здесь код отладочного маршрута, если хотите
    pass