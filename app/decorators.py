from functools import wraps
from flask import jsonify, redirect, url_for, request
from flask_login import current_user


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            # API-запросы получают JSON, страницы — редирект
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Требуются права администратора'}), 403
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated_function