import traceback
import secrets
import logging
import psycopg2.extras
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from app.db import get_db_connection
from app.utils import is_valid_email, is_valid_name, is_strong_password
from app.models import User
from app.email_utils import send_verification_email
from app.extensions import limiter

security_logger = logging.getLogger('security')

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register')
def register_page():
    """Страница регистрации."""
    if current_user.is_authenticated:
        return redirect(url_for('profile.profile_page'))
    response = make_response(render_template('auth/register.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@auth_bp.route('/login')
@limiter.limit("5 per minute")
def login_page():
    """Страница входа."""
    if current_user.is_authenticated:
        return redirect(url_for('profile.profile_page'))
    response = make_response(render_template('auth/login.html'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@auth_bp.route('/logout')
@login_required
def logout():
    """Выход из системы."""
    logout_user()
    return redirect(url_for('main.index'))


@auth_bp.route('/api/check-username', methods=['POST'])
@limiter.limit("60 per minute")
def check_username():
    """Проверка доступности имени пользователя (используется при вводе в реальном времени)."""
    import re
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'available': False, 'error': 'Неверный формат запроса'})

    username = (data.get('username') or '').strip()

    if not username:
        return jsonify({'available': False, 'error': 'Имя не может быть пустым'})

    pattern = re.compile(r'^[a-zA-Zа-яА-ЯёЁ][a-zA-Zа-яА-ЯёЁ0-9_.\- ]{0,29}$')
    if not pattern.match(username):
        return jsonify({'available': False, 'error': 'Недопустимые символы в имени'})

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            return jsonify({'available': False})

        # Проверяем только незавершённые регистрации с действующим кодом
        cur.execute("""
            SELECT email FROM email_verifications
            WHERE username = %s AND expires_at > NOW()
        """, (username,))
        if cur.fetchone():
            return jsonify({'available': False})

        return jsonify({'available': True})
    except Exception as e:
        print(f"Ошибка check-username: {e}")
        return jsonify({'available': False, 'error': 'Ошибка сервера'}), 500
    finally:
        conn.close()


@auth_bp.route('/api/register', methods=['POST'])
@limiter.limit("5 per hour")
def register():
    conn = get_db_connection()
    try:
        data = request.json

        # Чистим просроченные коды
        cur_clean = conn.cursor()
        cur_clean.execute("DELETE FROM email_verifications WHERE expires_at < NOW()")
        conn.commit()
        cur_clean.close()

        # Проверка обязательных полей
        if not data.get('email') or not data.get('password') or not data.get('username'):
            return jsonify({'success': False, 'error': 'Заполните все обязательные поля'})

        # Валидация email
        email = data['email'].lower().strip()
        if not is_valid_email(email):
            return jsonify({'success': False, 'error': 'Введите корректный email'})

        # Валидация имени
        username = data['username'].strip()
        if not is_valid_name(username):
            return jsonify({
                'success': False,
                'error': 'Имя должно содержать только русские или английские буквы, цифры, _, пробел. Начинаться с буквы. До 30 символов.'
            })

        # Валидация пароля
        password = data['password']
        if not is_strong_password(password):
            return jsonify({
                'success': False,
                'error': 'Пароль должен содержать минимум 6 символов, включая хотя бы одну заглавную и одну строчную букву (латиницу или кириллицу)'
            })

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Проверяем, не занят ли email в таблице users
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Пользователь с таким email уже существует'})

        # Проверяем, не занят ли username в таблице users
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Это имя пользователя уже занято'})

        # Проверяем, не занят ли username другой незавершённой регистрацией
        # (исключаем текущий email — он может переотправлять код для себя)
        cur.execute("""
            SELECT email FROM email_verifications
            WHERE username = %s AND email != %s AND expires_at > NOW()
        """, (username, email))
        if cur.fetchone():
            return jsonify({'success': False, 'error': 'Это имя пользователя уже занято'})

        code = f"{secrets.randbelow(1000000):06d}"
        code_hash = generate_password_hash(code)

        # Хешируем пароль
        password_hash = generate_password_hash(password)

        # Сохраняем временную запись (или обновляем существующую)
        cur.execute("""
            INSERT INTO email_verifications (email, username, password_hash, code, expires_at)
            VALUES (%s, %s, %s, %s, NOW() + INTERVAL '10 minutes')
            ON CONFLICT (email) DO UPDATE SET
                username = EXCLUDED.username,
                password_hash = EXCLUDED.password_hash,
                code = EXCLUDED.code,
                expires_at = EXCLUDED.expires_at
        """, (email, username, password_hash, code_hash))

        # Пытаемся отправить письмо
        success, error_msg = send_verification_email(email, code, purpose='register')
        if not success:
            conn.rollback()
            return jsonify({
                'success': False,
                'error': f'Не удалось отправить код на email: {error_msg}'
            })

        conn.commit()

        return jsonify({
            'success': True,
            'message': f'Код подтверждения отправлен на {email}'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при регистрации: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера. Попробуйте позже.'})
    finally:
        conn.close()


@auth_bp.route('/api/register-status', methods=['POST'])
def register_status():
    """Проверяет, есть ли незавершённая регистрация для данного email."""
    data = request.get_json(silent=True)
    email = (data.get('email') or '').lower().strip() if data else ''
    if not email:
        return jsonify({'pending': False})

    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT email, username FROM email_verifications
            WHERE email = %s AND expires_at > NOW()
        """, (email,))
        row = cur.fetchone()
        if row:
            return jsonify({'pending': True, 'email': row['email'], 'username': row['username']})
        return jsonify({'pending': False})
    except Exception as e:
        print(f"Ошибка register-status: {e}")
        return jsonify({'pending': False})
    finally:
        conn.close()


@auth_bp.route('/api/register-cancel', methods=['POST'])
def register_cancel():
    """Удаляет незавершённую регистрацию, чтобы пользователь мог начать заново."""
    data = request.get_json(silent=True)
    email = (data.get('email') or '').lower().strip() if data else ''
    if not email:
        return jsonify({'success': False})

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM email_verifications WHERE email = %s", (email,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Ошибка register-cancel: {e}")
        conn.rollback()
        return jsonify({'success': False})
    finally:
        conn.close()


@auth_bp.route('/api/verify-email', methods=['POST'])
@limiter.limit("10 per hour")
def verify_email():
    """Подтверждение кода и создание пользователя."""
    conn = get_db_connection()
    try:
        data = request.json
        email = data.get('email', '').lower().strip()
        code = data.get('code', '').strip()

        if not email or not code:
            return jsonify({'success': False, 'error': 'Email и код обязательны'})

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("""
            SELECT * FROM email_verifications
            WHERE email = %s AND expires_at > NOW()
        """, (email, ))
        verification = cur.fetchone()

        if not verification or not check_password_hash(verification['code'], code):
            return jsonify({'success': False, 'error': 'Неверный или просроченный код'})

        # Повторно проверяем, не успел ли кто-то создать пользователя с таким email
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            cur.execute("DELETE FROM email_verifications WHERE email = %s", (email,))
            conn.commit()
            return jsonify({'success': False, 'error': 'Пользователь с таким email уже существует'})

        # Создаём пользователя
        cur.execute("""
            INSERT INTO users (email, username, password_hash, role)
            VALUES (%s, %s, %s, 'user')
            RETURNING id, email, username, role, avatar_url, is_active, created_at, updated_at
        """, (verification['email'], verification['username'], verification['password_hash']))
        user_data = cur.fetchone()

        cur.execute("DELETE FROM email_verifications WHERE email = %s", (email,))
        conn.commit()

        from app.models import User
        user = User(user_data)
        login_user(user, remember=True)

        return jsonify({
            'success': True,
            'message': 'Регистрация успешна! Добро пожаловать!'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при подтверждении email: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера. Попробуйте позже.'})
    finally:
        conn.close()


@auth_bp.route('/api/resend-code', methods=['POST'])
@limiter.limit("5 per hour")
def resend_code():
    """Повторная отправка кода подтверждения."""
    conn = get_db_connection()
    try:
        data = request.json
        email = data.get('email', '').lower().strip()

        if not email:
            return jsonify({'success': False, 'error': 'Email обязателен'})

        cur = conn.cursor()

        cur.execute("SELECT email FROM email_verifications WHERE email = %s", (email,))
        if not cur.fetchone():
            return jsonify({'success': False, 'error': 'Для этого email не начата регистрация'})

        new_code = f"{secrets.randbelow(1000000):06d}"
        new_code_hash = generate_password_hash(new_code)

        cur.execute("""
            UPDATE email_verifications
            SET code = %s, expires_at = NOW() + INTERVAL '10 minutes'
            WHERE email = %s
        """, (new_code_hash, email))

        conn.commit()

        from app.email_utils import send_verification_email
        success, error_msg = send_verification_email(email, new_code)
        if not success:
            conn.rollback()
            return jsonify({
                'success': False,
                'error': f'Не удалось отправить код: {error_msg}'
            })

        return jsonify({
            'success': True,
            'message': f'Новый код отправлен на {email}'
        })

    except Exception as e:
        conn.rollback()
        print(f"Ошибка при повторной отправке кода: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера. Попробуйте позже.'})
    finally:
        conn.close()


@auth_bp.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute; 20 per hour")
def login():
    """Вход в систему."""
    conn = get_db_connection()
    try:
        data = request.json

        if not data.get('email') or not data.get('password'):
            return jsonify({'success': False, 'error': 'Заполните email и пароль'})

        email = data['email'].lower().strip()

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT * FROM users
            WHERE email = %s AND is_active = true
        """, (email,))

        user_data = cur.fetchone()

        if not user_data:
            return jsonify({'success': False, 'error': 'Пользователь не найден или аккаунт деактивирован'})

        if not check_password_hash(user_data['password_hash'], data['password']):
            security_logger.warning(f"Неудачный вход: {email} | IP: {request.remote_addr}")
            return jsonify({'success': False, 'error': 'Неверный пароль'})

        security_logger.info(f"Успешный вход: {email} | IP: {request.remote_addr}")
        user = User(user_data)
        login_user(user, remember=data.get('remember', False))

        return jsonify({
            'success': True,
            'message': 'Вход выполнен успешно'
        })

    except Exception as e:
        print(f"Ошибка при входе: {e}")
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера. Попробуйте позже.'})
    finally:
        conn.close()


# Страница запроса сброса пароля (ввод email)
@auth_bp.route('/reset-password')
def reset_password_page():
    return render_template('auth/reset_password.html')


# Страница подтверждения кода и ввода нового пароля
@auth_bp.route('/reset-password/confirm')
def reset_password_confirm_page():
    return render_template('auth/reset_password_confirm.html')


@auth_bp.route('/api/forgot-password', methods=['POST'])
@limiter.limit("3 per hour")
def forgot_password():
    """Отправка кода для сброса пароля на email."""
    conn = get_db_connection()
    try:
        data = request.json

        # Чистим просроченные коды
        cur_clean = conn.cursor()
        cur_clean.execute("DELETE FROM password_resets WHERE expires_at < NOW()")
        conn.commit()
        cur_clean.close()

        email = data.get('email', '').lower().strip()
        if not email or not is_valid_email(email):
            return jsonify({'success': False, 'error': 'Введите корректный email'})

        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if not cur.fetchone():
            # Для безопасности всегда отвечаем успехом, но не отправляем код
            return jsonify({'success': True, 'message': 'Если email зарегистрирован, код отправлен'})

        code = f"{secrets.randbelow(1000000):06d}"
        code_hash = generate_password_hash(code)

        cur.execute("""
            INSERT INTO password_resets (email, code, expires_at)
            VALUES (%s, %s, NOW() + INTERVAL '10 minutes')
            ON CONFLICT (email) DO UPDATE SET
                code = EXCLUDED.code, expires_at = EXCLUDED.expires_at
        """, (email, code_hash))

        success, error_msg = send_verification_email(email, code, purpose='reset')
        if not success:
            conn.rollback()
            return jsonify({'success': False, 'error': f'Не удалось отправить код: {error_msg}'})

        conn.commit()
        return jsonify({'success': True, 'message': 'Код для сброса пароля отправлен на email'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка в forgot-password: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        conn.close()


@auth_bp.route('/api/reset-password', methods=['POST'])
@limiter.limit("5 per hour")
def reset_password():
    """Подтверждение кода и установка нового пароля."""
    conn = get_db_connection()
    try:
        data = request.json
        email = data.get('email', '').lower().strip()
        code = data.get('code', '').strip()
        new_password = data.get('new_password', '')

        if not email or not code or not new_password:
            return jsonify({'success': False, 'error': 'Все поля обязательны'})

        if not is_strong_password(new_password):
            return jsonify({
                'success': False,
                'error': 'Пароль должен содержать минимум 6 символов, включая заглавные и строчные буквы'
            })

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Блокируем сброс пароля администратора через публичный эндпоинт
        cur.execute("SELECT role FROM users WHERE email = %s", (email,))
        user_role_row = cur.fetchone()
        if user_role_row and user_role_row['role'] == 'admin':
            security_logger.warning(
                f"Попытка сброса пароля администратора: {email} | IP: {request.remote_addr}"
            )
            return jsonify({
                'success': False,
                'error': 'Сброс пароля через эту форму недоступен. Обратитесь к системному администратору.'
            })

        cur.execute("""
            SELECT * FROM password_resets
            WHERE email = %s AND expires_at > NOW()
        """, (email, ))
        reset_record = cur.fetchone()

        if not reset_record or not check_password_hash(reset_record['code'], code):
            return jsonify({'success': False, 'error': 'Неверный или просроченный код'})

        # Обновляем пароль
        password_hash = generate_password_hash(new_password)
        cur.execute("""
            UPDATE users
            SET password_hash = %s, updated_at = NOW()
            WHERE email = %s
        """, (password_hash, email))

        cur.execute("DELETE FROM password_resets WHERE email = %s", (email,))
        conn.commit()

        return jsonify({'success': True, 'message': 'Пароль успешно изменён. Теперь вы можете войти.'})
    except Exception as e:
        conn.rollback()
        print(f"Ошибка в reset-password: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        conn.close()


@auth_bp.route('/api/verify-reset-code', methods=['POST'])
@limiter.limit("10 per hour")
def verify_reset_code():
    """Проверка кода для сброса пароля (без изменения пароля)."""
    conn = get_db_connection()
    try:
        data = request.json
        email = data.get('email', '').lower().strip()
        code = data.get('code', '').strip()

        if not email or not code:
            return jsonify({'success': False, 'error': 'Email и код обязательны'})

        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT * FROM password_resets
            WHERE email = %s AND expires_at > NOW()
        """, (email, ))
        record = cur.fetchone()

        if not record or not check_password_hash(record['code'], code):
            return jsonify({'success': False, 'error': 'Неверный или просроченный код'})

        return jsonify({'success': True, 'message': 'Код подтверждён'})
    except Exception as e:
        print(f"Ошибка при проверке кода: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'})
    finally:
        conn.close()