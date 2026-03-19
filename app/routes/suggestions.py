# app/routes/suggestions.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from flask import current_app
from app.extensions import limiter
import psycopg2
import psycopg2.extras
import json
import traceback
import os

from app.utils import (
    process_place_row,
    save_uploaded_file,
    allowed_file,
    is_valid_email,
    is_valid_name,
    is_strong_password
)
from app.db import get_db_connection 

# upload_folder = current_app.config['UPLOAD_FOLDER']
# allowed_extensions = current_app.config['ALLOWED_EXTENSIONS']
# photo_url = save_uploaded_file(file, 'suggestions', upload_folder, allowed_extensions)

suggestions_bp = Blueprint('suggestions', __name__)

# ============ СТРАНИЦЫ ============

@suggestions_bp.route('/suggest')
@login_required
def suggest_page():
    """Единая страница для предложения места и сообщения об ошибке"""
    active_tab = request.args.get('tab', 'suggest')
    if active_tab not in ['suggest', 'report']:
        active_tab = 'suggest'
    return render_template('user_profile/user_suggestions.html',
                           current_user=current_user,
                           active_tab=active_tab)

@suggestions_bp.route('/suggest-place')
@login_required
def suggest_place_page():
    # Перенаправляем на /suggest?tab=suggest
    return redirect(url_for('suggestions.suggest_page', tab='suggest'))

@suggestions_bp.route('/report-error')
@login_required
def report_error_page():
    # Перенаправляем на /suggest?tab=report
    return redirect(url_for('suggestions.suggest_page', tab='report'))

# ============ API ДЛЯ ПОЛЬЗОВАТЕЛЯ (ПРЕДЛОЖЕНИЯ) ============

@suggestions_bp.route('/api/categories')
@login_required
def get_categories():
    """Получение списка всех категорий для формы предложения места"""
    from app.utils import get_categories_safe
    try:
        categories = get_categories_safe()
        return jsonify({'success': True, 'categories': categories})
    except Exception as e:
        print(f"Ошибка при получении категорий: {e}")
        return jsonify({'success': False, 'error': str(e)})

@suggestions_bp.route('/api/suggest-place', methods=['POST'])
@limiter.limit("5 per hour")
@login_required
def submit_suggestion():
    """Отправка предложения нового места"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        data = {}
        uploaded_photos = []

        if request.content_type and 'multipart/form-data' in request.content_type:
            data = {
                'user_title': request.form.get('user_title', '').strip(),
                'user_description': request.form.get('user_description', '').strip(),
                'user_address': request.form.get('user_address', '').strip(),
                'user_timetable': request.form.get('user_timetable', '').strip(),
                'user_phone': request.form.get('user_phone', '').strip(),
                'user_foreign_url': request.form.get('user_foreign_url', '').strip(),
                'user_photos_url': request.form.get('user_photos_url', '').strip(),
            }

            category_ids_str = request.form.get('category_ids', '')
            if category_ids_str:
                data['category_ids'] = [int(id.strip()) for id in category_ids_str.split(',') if id.strip()]
            else:
                data['category_ids'] = []

            if 'user_photos' in request.files:
                upload_folder = current_app.config['UPLOAD_FOLDER']
                allowed_extensions = current_app.config['ALLOWED_EXTENSIONS']
                files = request.files.getlist('user_photos')
                for file in files:
                    if file.filename and file.filename != '':
                        photo_url = save_uploaded_file(file, 'suggestions', upload_folder, allowed_extensions)
                        if photo_url:
                            uploaded_photos.append(photo_url)
        else:
            data = request.get_json()
            if data is None:
                return jsonify({'success': False, 'error': 'Invalid JSON data'})
            data['category_ids'] = data.get('category_ids', [])
            uploaded_photos = []

        required_fields = ['user_title', 'user_description', 'user_address']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return jsonify({'success': False, 'error': f'Заполните обязательные поля: {", ".join(missing_fields)}'})

        category_ids = data.get('category_ids', [])
        if not category_ids:
            return jsonify({'success': False, 'error': 'Выберите хотя бы одну категорию'})

        if category_ids:
            placeholders = ','.join(['%s'] * len(category_ids))
            cur.execute(f"""
                SELECT COUNT(*) as count 
                FROM categories_api 
                WHERE id IN ({placeholders})
            """, tuple(category_ids))
            count = cur.fetchone()['count']
            if count != len(category_ids):
                return jsonify({'success': False, 'error': 'Некоторые категории не существуют'})

        all_photos = []
        all_photos.extend(uploaded_photos)

        if 'user_photos_url' in data:
            photos_url = data.get('user_photos_url', '')
            if photos_url:
                url_photos = [url.strip() for url in photos_url.split(',') if url.strip()]
                all_photos.extend(url_photos)

        user_main_photo_url = all_photos[0] if all_photos else None

        cur.execute("""
            INSERT INTO place_suggestions
            (
                user_id,
                user_title, user_description, user_address,
                user_timetable, user_phone, user_foreign_url,
                user_photos, user_main_photo_url,
                status, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'pending', NOW(), NOW())
            RETURNING id
        """, (
            current_user.id,
            data['user_title'],
            data['user_description'],
            data['user_address'],
            data.get('user_timetable', ''),
            data.get('user_phone', ''),
            data.get('user_foreign_url', ''),
            json.dumps(all_photos),
            user_main_photo_url
        ))

        suggestion_id = cur.fetchone()['id']

        for category_id in category_ids:
            cur.execute("""
                INSERT INTO place_suggestion_user_categories (suggestion_id, category_id)
                VALUES (%s, %s)
            """, (suggestion_id, category_id))

        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Спасибо! Ваше предложение отправлено на модерацию.',
            'suggestion_id': suggestion_id,
            'uploaded_photos': len(uploaded_photos)
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при сохранении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/user/suggestions')
@login_required
def get_user_suggestions():
    """Получение списка предложений текущего пользователя"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        status = request.args.get('status', 'all')
        limit = request.args.get('limit', per_page)
        offset = (page - 1) * per_page

        query = """
            SELECT
                ps.id, ps.user_title, ps.status, ps.created_at,
                ps.admin_comment, ps.created_place_id,
                p.title as place_title, p.slug as place_slug
            FROM place_suggestions ps
            LEFT JOIN places p ON ps.created_place_id = p.id
            WHERE ps.user_id = %s
        """
        params = [current_user.id]

        if status != 'all':
            query += " AND ps.status = %s"
            params.append(status)

        count_query = f"SELECT COUNT(*) as total FROM ({query}) as t"
        cur.execute(count_query, params)
        total = cur.fetchone()['total']

        query += " ORDER BY ps.created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        suggestions = []
        for row in cur.fetchall():
            s = dict(row)
            s['created_at'] = s['created_at'].isoformat() if s['created_at'] else None
            suggestions.append(s)

        total_pages = (total + per_page - 1) // per_page if per_page > 0 else 1

        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })
    except Exception as e:
        print(f"Ошибка при получении предложений пользователя: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/suggestions/<int:suggestion_id>')
@login_required
def get_suggestion_detail_user(suggestion_id):
    """Детальная информация о предложении для владельца или админа"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("""
            SELECT
                ps.*,
                u.username as user_username,
                u.email as user_email,
                p.title as place_title,
                p.slug as place_slug,
                p.id as place_id,
                array_agg(DISTINCT c.name) as user_category_names
            FROM place_suggestions ps
            LEFT JOIN users u ON ps.user_id = u.id
            LEFT JOIN place_suggestion_user_categories psuc ON ps.id = psuc.suggestion_id
            LEFT JOIN categories_api c ON psuc.category_id = c.id
            LEFT JOIN places p ON ps.created_place_id = p.id
            WHERE ps.id = %s
            GROUP BY ps.id, u.id, p.id
        """, (suggestion_id,))

        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404

        if suggestion['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

        suggestion_dict = dict(suggestion)

        for field in ['user_photos', 'moderated_photos', 'moderated_coords']:
            if suggestion_dict.get(field):
                try:
                    if isinstance(suggestion_dict[field], str):
                        suggestion_dict[field] = json.loads(suggestion_dict[field])
                except:
                    suggestion_dict[field] = []

        for date_field in ['created_at', 'updated_at']:
            if suggestion_dict.get(date_field):
                suggestion_dict[date_field] = suggestion_dict[date_field].isoformat()

        return jsonify({'success': True, 'suggestion': suggestion_dict})
    except Exception as e:
        print(f"Ошибка при получении деталей предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/suggestions/<int:suggestion_id>', methods=['PUT'])
@login_required
def update_user_suggestion(suggestion_id):
    """Обновление пользовательских данных предложения (только pending)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("SELECT user_id, status FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404
        if suggestion['user_id'] != current_user.id:
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Редактирование доступно только для заявок на модерации'}), 400

        data = request.json

        updatable_fields = [
            'user_title', 'user_description', 'user_address',
            'user_timetable', 'user_phone', 'user_foreign_url'
        ]

        update_fields = []
        update_values = []

        for field in updatable_fields:
            if field in data:
                update_fields.append(f"{field} = %s")
                update_values.append(data[field])

        if 'user_photos' in data:
            update_fields.append("user_photos = %s::jsonb")
            update_values.append(json.dumps(data['user_photos']))
            if data['user_photos']:
                update_fields.append("user_main_photo_url = %s")
                update_values.append(data['user_photos'][0])
            else:
                update_fields.append("user_main_photo_url = %s")
                update_values.append(None)

        if update_fields:
            update_query = f"""
                UPDATE place_suggestions
                SET {', '.join(update_fields)}, updated_at = NOW()
                WHERE id = %s
            """
            update_values.append(suggestion_id)
            cur.execute(update_query, tuple(update_values))

        if 'category_ids' in data:
            cur.execute("DELETE FROM place_suggestion_user_categories WHERE suggestion_id = %s", (suggestion_id,))
            for cat_id in data['category_ids']:
                cur.execute("""
                    INSERT INTO place_suggestion_user_categories (suggestion_id, category_id)
                    VALUES (%s, %s) ON CONFLICT DO NOTHING
                """, (suggestion_id, cat_id))

        conn.commit()
        return jsonify({'success': True, 'message': 'Предложение успешно обновлено'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении предложения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/suggestions/<int:suggestion_id>/photo', methods=['POST'])
@limiter.limit("20 per hour")
@login_required
def add_suggestion_photo(suggestion_id):
    """Добавление фотографии к предложению (файл или URL)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("SELECT user_id, status, user_photos FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404
        if suggestion['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Фото можно добавлять только к заявкам на модерации'}), 400

        current_photos = suggestion['user_photos']
        if current_photos is None:
            current_photos = []
        elif isinstance(current_photos, str):
            try:
                current_photos = json.loads(current_photos)
            except:
                current_photos = []

        new_photo_url = None

        if 'photo' in request.files:
            upload_folder = current_app.config['UPLOAD_FOLDER']
            allowed_extensions = current_app.config['ALLOWED_EXTENSIONS']
            file = request.files['photo']
            if file and file.filename:
                photo_url = save_uploaded_file(file, 'suggestions', upload_folder, allowed_extensions)
                if not photo_url:
                    return jsonify({'success': False, 'error': 'Не удалось сохранить файл'})
                new_photo_url = photo_url

        elif request.is_json:
            data = request.get_json()
            if data and 'photo_url' in data:
                url = data['photo_url'].strip()
                if url:
                    new_photo_url = url

        if not new_photo_url:
            return jsonify({'success': False, 'error': 'Не передано фото (файл или URL)'})

        if new_photo_url not in current_photos:
            current_photos.append(new_photo_url)

            cur.execute("""
                UPDATE place_suggestions
                SET user_photos = %s::jsonb,
                    user_main_photo_url = COALESCE(user_main_photo_url, %s),
                    updated_at = NOW()
                WHERE id = %s
            """, (json.dumps(current_photos), new_photo_url, suggestion_id))

            conn.commit()
            return jsonify({'success': True, 'message': 'Фото добавлено', 'photo_url': new_photo_url})
        else:
            return jsonify({'success': False, 'error': 'Это фото уже есть в списке'})

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при добавлении фото: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/suggestions/<int:suggestion_id>/photo', methods=['DELETE'])
@login_required
def delete_suggestion_photo(suggestion_id):
    """Удаление фотографии из предложения"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        data = request.get_json()
        if not data or 'photo_url' not in data:
            return jsonify({'success': False, 'error': 'Не указан URL фото'}), 400

        photo_url = data['photo_url'].strip()

        cur.execute("SELECT user_id, status, user_photos FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404
        if suggestion['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Фото можно удалять только из заявок на модерации'}), 400

        current_photos = suggestion['user_photos']
        if current_photos is None:
            current_photos = []
        elif isinstance(current_photos, str):
            try:
                current_photos = json.loads(current_photos)
            except:
                current_photos = []

        if photo_url not in current_photos:
            return jsonify({'success': False, 'error': 'Фото не найдено в списке'}), 404

        current_photos.remove(photo_url)

        new_main = None
        if current_photos:
            cur.execute("SELECT user_main_photo_url FROM place_suggestions WHERE id = %s", (suggestion_id,))
            old_main = cur.fetchone()['user_main_photo_url']
            if old_main == photo_url:
                new_main = current_photos[0]
        else:
            new_main = None

        cur.execute("""
            UPDATE place_suggestions
            SET user_photos = %s::jsonb,
                user_main_photo_url = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (json.dumps(current_photos), new_main, suggestion_id))

        if photo_url.startswith('/static/uploads/'):
            file_path = os.path.join(current_app.root_path, photo_url.lstrip('/'))
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Не удалось удалить файл {file_path}: {e}")

        conn.commit()
        return jsonify({'success': True, 'message': 'Фото удалено'})

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при удалении фото: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


# ============ API ДЛЯ ПОЛЬЗОВАТЕЛЯ (СООБЩЕНИЯ ОБ ОШИБКАХ) ============

@suggestions_bp.route('/api/places/search')
@limiter.limit("60 per minute")
@login_required
def search_places():
    """Поиск мест по названию для формы сообщения об ошибке"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        query = request.args.get('q', '').strip()
        limit = request.args.get('limit', 10, type=int)

        if not query or len(query) < 2:
            return jsonify({
                'success': True,
                'places': [],
                'message': 'Введите минимум 2 символа для поиска'
            })

        search_term = f"%{query}%"
        cur.execute("""
            SELECT id, title, slug, address, main_photo_url
            FROM places
            WHERE NOT is_closed
              AND (title ILIKE %s OR address ILIKE %s)
            ORDER BY
                CASE
                    WHEN title ILIKE %s THEN 1
                    WHEN address ILIKE %s THEN 2
                    ELSE 3
                END,
                title
            LIMIT %s
        """, (search_term, search_term, f"{query}%", f"{query}%", limit))

        places = []
        for row in cur.fetchall():
            place = dict(row)
            place['photo_url'] = place.get('main_photo_url', '')
            places.append(place)

        return jsonify({
            'success': True,
            'places': places,
            'count': len(places)
        })

    except Exception as e:
        print(f"Ошибка при поиске мест: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/report-error', methods=['POST'])
@limiter.limit("10 per hour")
@login_required
def submit_report():
    """Отправка сообщения об ошибке в существующем месте"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        data = request.json

        required_fields = ['place_id', 'subject', 'message']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            return jsonify({
                'success': False,
                'error': f'Заполните обязательные поля: {", ".join(missing_fields)}'
            })

        place_id = data['place_id']
        subject = data['subject'].strip()
        message = data['message'].strip()

        cur.execute("SELECT id FROM places WHERE id = %s AND NOT is_closed", (place_id,))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Место не найдено или закрыто'})

        if len(subject) > 200:
            return jsonify({'success': False, 'error': 'Тема слишком длинная (максимум 200 символов)'})
        if len(message) > 2000:
            return jsonify({'success': False, 'error': 'Сообщение слишком длинное (максимум 2000 символов)'})

        cur.execute("""
            INSERT INTO place_reports
                (place_id, user_id, subject, message, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'pending', NOW(), NOW())
            RETURNING id
        """, (place_id, current_user.id, subject, message))

        report_id = cur.fetchone()['id']
        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Спасибо! Ваше сообщение об ошибке отправлено на рассмотрение.',
            'report_id': report_id
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при сохранении сообщения об ошибке: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/user/reports')
@login_required
def get_user_reports():
    """Получение сообщений об ошибках пользователя"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        status = request.args.get('status', 'all')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        offset = (page - 1) * per_page

        query = """
            SELECT
                pr.*,
                p.title as place_title,
                p.slug as place_slug,
                p.main_photo_url as place_photo,
                u_mod.username as resolved_by_username
            FROM place_reports pr
            JOIN places p ON pr.place_id = p.id
            LEFT JOIN users u_mod ON pr.resolved_by = u_mod.id
            WHERE pr.user_id = %s
        """
        params = [current_user.id]

        if status != 'all':
            query += " AND pr.status = %s"
            params.append(status)

        query += " ORDER BY pr.created_at DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(query, params)

        reports = []
        for row in cur.fetchall():
            report = dict(row)
            for date_field in ['created_at', 'updated_at']:
                if report.get(date_field):
                    report[date_field] = report[date_field].isoformat()
            reports.append(report)

        count_query = """
            SELECT COUNT(*) as total
            FROM place_reports pr
            WHERE pr.user_id = %s
        """
        count_params = [current_user.id]
        if status != 'all':
            count_query += " AND pr.status = %s"
            count_params.append(status)

        cur.execute(count_query, count_params)
        total = cur.fetchone()['total']
        total_pages = (total + per_page - 1) // per_page

        cur.execute("""
            SELECT status, COUNT(*) as count
            FROM place_reports
            WHERE user_id = %s
            GROUP BY status
        """, (current_user.id,))
        stats = {row['status']: row['count'] for row in cur.fetchall()}

        return jsonify({
            'success': True,
            'reports': reports,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            },
            'stats': stats
        })

    except Exception as e:
        print(f"Ошибка при получении сообщений пользователя: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/reports/<int:report_id>')
@login_required
def get_report_detail_user(report_id):
    """Детальная информация о сообщении об ошибке для владельца или админа"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("""
            SELECT
                pr.*,
                p.title as place_title,
                p.slug as place_slug,
                p.address as place_address,
                u_mod.username as resolved_by_username
            FROM place_reports pr
            JOIN places p ON pr.place_id = p.id
            LEFT JOIN users u_mod ON pr.resolved_by = u_mod.id
            WHERE pr.id = %s
        """, (report_id,))

        report = cur.fetchone()
        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено'}), 404

        if report['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

        report_dict = dict(report)
        for date_field in ['created_at', 'updated_at']:
            if report_dict.get(date_field):
                report_dict[date_field] = report_dict[date_field].isoformat()

        return jsonify({'success': True, 'report': report_dict})
    except Exception as e:
        print(f"Ошибка при получении деталей сообщения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/reports/<int:report_id>', methods=['PUT'])
@login_required
def update_user_report(report_id):
    """Редактирование сообщения об ошибке (только для статуса pending)"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cur.execute("SELECT user_id, status FROM place_reports WHERE id = %s", (report_id,))
        report = cur.fetchone()
        if not report:
            return jsonify({'success': False, 'error': 'Сообщение не найдено'}), 404
        if report['user_id'] != current_user.id:
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if report['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Редактирование доступно только для сообщений на рассмотрении'}), 400

        data = request.json
        update_fields = []
        update_values = []

        if 'subject' in data:
            update_fields.append("subject = %s")
            update_values.append(data['subject'].strip()[:200])
        if 'message' in data:
            update_fields.append("message = %s")
            update_values.append(data['message'].strip()[:2000])

        if update_fields:
            update_fields.append("updated_at = NOW()")
            update_query = f"UPDATE place_reports SET {', '.join(update_fields)} WHERE id = %s"
            update_values.append(report_id)
            cur.execute(update_query, tuple(update_values))
            conn.commit()
            return jsonify({'success': True, 'message': 'Сообщение обновлено'})
        else:
            return jsonify({'success': False, 'error': 'Нет данных для обновления'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении сообщения: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        cur.close()
        conn.close()


@suggestions_bp.route('/api/user/reports/stats')
@login_required
def get_user_reports_stats():
    """Статистика сообщений об ошибках текущего пользователя"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'resolved') as resolved
            FROM place_reports
            WHERE user_id = %s
        """, (current_user.id,))
        stats = cur.fetchone()
        return jsonify({
            'success': True,
            'total': stats['total'],
            'pending': stats['pending'],
            'resolved': stats['resolved']
        })
    except Exception as e:
        print(f"Ошибка получения статистики сообщений: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@suggestions_bp.route('/api/profile/suggestions/stats')
@login_required
def get_suggestions_stats():
    """Получение статистики предложений пользователя"""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'approved') as approved,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                COUNT(*) as total
            FROM place_suggestions
            WHERE user_id = %s
        """, (current_user.id,))
        stats = cur.fetchone()
        return jsonify({
            'success': True,
            'pending': stats['pending'] if stats else 0,
            'approved': stats['approved'] if stats else 0,
            'rejected': stats['rejected'] if stats else 0,
            'total': stats['total'] if stats else 0
        })
    except Exception as e:
        print(f"Ошибка при получении статистики предложений: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()