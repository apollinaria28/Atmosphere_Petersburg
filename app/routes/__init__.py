# app/routes/__init__.py

from .main import main_bp
from .auth import auth_bp
from .profile import profile_bp
from .favorites import favorites_bp
from .visited import visited_bp
from .suggestions import suggestions_bp
from .admin import admin_bp
from .test import test_bp

__all__ = [
    'main_bp',
    'auth_bp',
    'profile_bp',
    'favorites_bp',
    'visited_bp',
    'suggestions_bp',
    'admin_bp',
    'test_bp',
]