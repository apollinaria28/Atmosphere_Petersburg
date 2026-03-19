import json
import os
import traceback
import uuid
import re

import psycopg2.extras
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
from flask_login import login_required, current_user

from app.db import get_db_connection
from app.utils import is_valid_name, save_uploaded_file

profile_bp = Blueprint('profile', __name__, url_prefix='/profile')



# ---------- Страницы ----------



@profile_bp.route('')
@login_required
def profile_page():
    """Личный кабинет пользователя."""
    return render_template('user_profile/profile.html', current_user=current_user)


@profile_bp.route('/suggestions')
@login_required
def profile_suggestions_page():
    """Страница со всеми предложениями пользователя."""
    return render_template('user_profile/profile_suggestions.html')


@profile_bp.route('/reports')
@login_required
def profile_reports_page():
    """Страница со всеми сообщениями об ошибках пользователя."""
    return render_template('user_profile/profile_reports.html')


# Детальные страницы вне /profile, но относящиеся к пользователю
@profile_bp.route('/suggestion/<int:suggestion_id>')
@login_required
def suggestion_detail_page(suggestion_id):
    """Детальная страница предложения."""
    return render_template('user_profile/suggestion_detail.html', suggestion_id=suggestion_id)


@profile_bp.route('/suggestion/<int:suggestion_id>/edit')
@login_required
def suggestion_edit_page(suggestion_id):
    """Страница редактирования предложения."""
    return render_template('user_profile/suggestion_edit.html', suggestion_id=suggestion_id)


@profile_bp.route('/report/<int:report_id>')
@login_required
def report_detail_page(report_id):
    """Детальная страница сообщения об ошибке."""
    return render_template('user_profile/report_detail.html', report_id=report_id)


# ---------- API профиля ----------
@profile_bp.route('/data')
@login_required
def get_profile_data():
    """Получение данных профиля пользователя (дата регистрации и обновления)."""
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT created_at, updated_at
            FROM users
            WHERE id = %s
        """, (current_user.id,))
        user_data = cur.fetchone()
        if user_data:
            return jsonify({
                'success': True,
                'registration_date': user_data['created_at'].isoformat() if user_data['created_at'] else None,
                'last_updated': user_data['updated_at'].isoformat() if user_data['updated_at'] else None
            })
        else:
            return jsonify({'success': False, 'error': 'Пользователь не найден'})
    except Exception as e:
        print(f"Ошибка при получении данных профиля: {e}")
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@profile_bp.route('/api/profile/update', methods=['POST'])
@login_required
def update_profile():
    """Обновление данных профиля пользователя (имя, аватар)."""
    conn = get_db_connection()
    try:
        data = request.json
        if not data.get('username'):
            return jsonify({'success': False, 'error': 'Имя пользователя обязательно'})

        username = data['username'].strip()
        avatar_url = data.get('avatar_url')

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # Проверяем, не занят ли username другим пользователем
        cur.execute("""
            SELECT id FROM users
            WHERE username = %s AND id != %s
        """, (username, current_user.id))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Это имя пользователя уже занято'})

        cur.execute("""
            UPDATE users
            SET username = %s, avatar_url = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id, email, username, avatar_url, role, is_active
        """, (username, avatar_url, current_user.id))
        updated_user = cur.fetchone()
        conn.commit()

        if updated_user:
            # Обновляем данные в сессии Flask-Login (через login_user)
            from app.models import User
            user = User(updated_user)
            from flask_login import login_user
            login_user(user)
            return jsonify({
                'success': True,
                'message': 'Профиль успешно обновлен',
                'user': {
                    'id': str(updated_user['id']),
                    'username': updated_user['username'],
                    'email': updated_user['email'],
                    'avatar_url': updated_user['avatar_url'],
                    'role': updated_user['role']
                }
            })
        else:
            return jsonify({'success': False, 'error': 'Пользователь не найден'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка при обновлении профиля: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        conn.close()


@profile_bp.route('/api/avatars')
@login_required
def get_available_avatars():
    """Получение списка доступных аватаров из папки static/avatars."""
    avatars = []
    avatars_folder = os.path.join(current_app.root_path, 'static', 'avatars')
    os.makedirs(avatars_folder, exist_ok=True)

    allowed_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.webp']
    try:
        for filename in os.listdir(avatars_folder):
            if any(filename.lower().endswith(ext) for ext in allowed_extensions):
                avatar_id = os.path.splitext(filename)[0]
                avatars.append({
                    'id': avatar_id,
                    'url': f'/static/avatars/{filename}',
                    'name': avatar_id.replace('_', ' ').title()
                })
    except Exception as e:
        print(f"Ошибка при чтении папки аватаров: {e}")

    if not avatars:
        # Если аватаров нет, возвращаем список по умолчанию
        for i in range(1, 7):
            avatars.append({
                'id': f'avatar{i}',
                'url': f'/static/avatars/avatar{i}.png',
                'name': f'Аватар {i}'
            })

    return jsonify({'success': True, 'avatars': avatars})


@profile_bp.route('/api/profile/suggestions/stats')
@login_required
def get_suggestions_stats():
    """Статистика предложений пользователя."""
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


# ---------- API для предложений пользователя ----------
@profile_bp.route('/api/user/suggestions')
@login_required
def get_user_suggestions():
    """Список предложений текущего пользователя."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        status = request.args.get('status', 'all')
        # Для блока «последние» можно использовать limit, но пока используем per_page
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

        # Подсчёт общего количества
        count_query = f"SELECT COUNT(*) as total FROM ({query}) as t"
        cur.execute(count_query, params)
        total = cur.fetchone()['total']

        query += " ORDER BY ps.created_at DESC LIMIT %s OFFSET %s"
        params.extend([per_page, offset])

        cur.execute(query, params)
        suggestions = []
        for row in cur.fetchall():
            s = dict(row)
            if s.get('created_at'):
                s['created_at'] = s['created_at'].isoformat()
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


@profile_bp.route('/api/suggestions/<int:suggestion_id>')
@login_required
def get_suggestion_detail_user(suggestion_id):
    """Детальная информация о предложении (для владельца)."""
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

        # Проверка прав: владелец или админ
        if suggestion['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403

        suggestion_dict = dict(suggestion)

        # Обработка JSON полей
        for field in ['user_photos', 'moderated_photos', 'moderated_coords']:
            if suggestion_dict.get(field):
                try:
                    if isinstance(suggestion_dict[field], str):
                        suggestion_dict[field] = json.loads(suggestion_dict[field])
                except:
                    suggestion_dict[field] = []

        # Обработка дат
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


@profile_bp.route('/api/suggestions/<int:suggestion_id>', methods=['PUT'])
@login_required
def update_user_suggestion(suggestion_id):
    """Обновление пользовательских данных предложения (только статус pending)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        # Проверяем существование и статус
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

        # Обновление фотографий
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

        # Обновление категорий
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


@profile_bp.route('/api/suggestions/<int:suggestion_id>/photo', methods=['POST'])
@login_required
def add_suggestion_photo(suggestion_id):
    """Добавление фотографии к предложению (файл или URL)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        # Проверка прав и статуса
        cur.execute("SELECT user_id, status, user_photos FROM place_suggestions WHERE id = %s", (suggestion_id,))
        suggestion = cur.fetchone()
        if not suggestion:
            return jsonify({'success': False, 'error': 'Предложение не найдено'}), 404
        if suggestion['user_id'] != current_user.id and current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Доступ запрещён'}), 403
        if suggestion['status'] != 'pending':
            return jsonify({'success': False, 'error': 'Фото можно добавлять только к заявкам на модерации'}), 400

        # Текущий список фото
        current_photos = suggestion['user_photos']
        if current_photos is None:
            current_photos = []
        elif isinstance(current_photos, str):
            try:
                current_photos = json.loads(current_photos)
            except:
                current_photos = []

        new_photo_url = None

        # Случай 1: загружен файл
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                upload_folder = current_app.config['UPLOAD_FOLDER']
                allowed_extensions = current_app.config['ALLOWED_EXTENSIONS']
                photo_url = save_uploaded_file(file, 'suggestions', upload_folder, allowed_extensions)
                if not photo_url:
                    return jsonify({'success': False, 'error': 'Не удалось сохранить файл'})
                new_photo_url = photo_url

        # Случай 2: передан URL в JSON
        elif request.is_json:
            data = request.get_json()
            if data and 'photo_url' in data:
                url = data['photo_url'].strip()
                if url:
                    new_photo_url = url

        if not new_photo_url:
            return jsonify({'success': False, 'error': 'Не передано фото (файл или URL)'})

        # Добавляем, если ещё нет
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


@profile_bp.route('/api/suggestions/<int:suggestion_id>/photo', methods=['DELETE'])
@login_required
def delete_suggestion_photo(suggestion_id):
    """Удаление фотографии из предложения (удаляет запись в БД и сам файл)."""
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

        # Обновляем главное фото, если удалили его
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

        # Физически удаляем файл, если это локальный файл
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


# ---------- API для сообщений об ошибках пользователя ----------
@profile_bp.route('/api/user/reports')
@login_required
def get_user_reports():
    """Список сообщений об ошибках пользователя."""
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

        # Подсчёт общего количества
        count_query = f"SELECT COUNT(*) as total FROM ({query}) as t"
        cur.execute(count_query, params)
        total = cur.fetchone()['total']

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

        total_pages = (total + per_page - 1) // per_page if per_page > 0 else 1

        # Статистика по статусам
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


@profile_bp.route('/api/user/reports/stats')
@login_required
def get_user_reports_stats():
    """Статистика сообщений об ошибках пользователя."""
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


@profile_bp.route('/api/reports/<int:report_id>')
@login_required
def get_report_detail_user(report_id):
    """Детальная информация о сообщении об ошибке (для владельца)."""
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


@profile_bp.route('/api/reports/<int:report_id>', methods=['PUT'])
@login_required
def update_user_report(report_id):
    """Редактирование сообщения об ошибке (только статус pending)."""
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

@profile_bp.route('/api/profile/delete', methods=['DELETE'])
@login_required
def delete_account():
    """Удаление аккаунта и всех связанных данных пользователя."""
    conn = get_db_connection()
    try:
        user_id = current_user.id
        cur = conn.cursor()

        # Избранное и посещённые
        cur.execute("DELETE FROM favorites WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM visited_places WHERE user_id = %s", (user_id,))

        # Маршруты: сначала места внутри маршрутов, потом сами маршруты
        cur.execute("""
            DELETE FROM route_places
            WHERE route_id IN (SELECT id FROM routes WHERE user_id = %s)
        """, (user_id,))
        cur.execute("DELETE FROM routes WHERE user_id = %s", (user_id,))

        # Жалобы
        cur.execute("DELETE FROM place_reports WHERE user_id = %s", (user_id,))

        # Предложения: сначала зависимые записи
        cur.execute("""
            DELETE FROM place_suggestion_user_categories
            WHERE suggestion_id IN (SELECT id FROM place_suggestions WHERE user_id = %s)
        """, (user_id,))
        cur.execute("""
            DELETE FROM place_suggestion_moderated_categories
            WHERE suggestion_id IN (SELECT id FROM place_suggestions WHERE user_id = %s)
        """, (user_id,))
        cur.execute("DELETE FROM place_suggestions WHERE user_id = %s", (user_id,))

        # Удаляем пользователя
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

        conn.commit()

        from flask_login import logout_user
        logout_user()

        return jsonify({'success': True, 'message': 'Аккаунт удалён'})

    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Ошибка при удалении аккаунта. Попробуйте позже.'})
    finally:
        conn.close()