# app/decorators.py

from functools import wraps
from flask import jsonify
from flask_login import current_user


def admin_required(f):
    """
    Декоратор для проверки, что текущий пользователь аутентифицирован и имеет роль 'admin'.
    Возвращает JSON-ответ с ошибкой 403, если условие не выполнено.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Требуются права администратора'}), 403
        return f(*args, **kwargs)
    return decorated_function