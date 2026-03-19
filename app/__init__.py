# app/__init__.py
import os
from flask import Flask, jsonify
from .config import Config
from .extensions import login_manager, limiter, talisman, csrf, cors
from .models import load_user

# Импортируем все blueprints
from .routes.main import main_bp
from .routes.auth import auth_bp
from .routes.profile import profile_bp
from .routes.favorites import favorites_bp
from .routes.visited import visited_bp
from .routes.suggestions import suggestions_bp
from .routes.admin import admin_bp
from .routes.test import test_bp

from app.routes.routes import routes_bp
from app.routes.places import places_bp


def create_app(config_class=Config):
    app = Flask(__name__,
                static_folder='static',
                template_folder='templates')

    app.config.from_object(config_class)
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')

    # Инициализация расширений
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login_page'
    login_manager.login_message = 'Пожалуйста, войдите в систему для доступа к этой странице'
    login_manager.login_message_category = 'info'
    login_manager.user_loader(load_user)

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import request, redirect, url_for
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'unauthorized'}), 401
        return redirect(url_for('auth.login_page'))

    limiter.init_app(app)

    talisman.init_app(
        app,
        force_https=False,
        content_security_policy=False
    )

    # CSRF — защищает только HTML-формы (страницы входа, регистрации и т.д.)
    # API роуты (/api/*) исключены — они защищены CORS + JSON Content-Type
    csrf.init_app(app)
    csrf.exempt(auth_bp)
    csrf.exempt(main_bp)
    csrf.exempt(profile_bp)
    csrf.exempt(favorites_bp)
    csrf.exempt(visited_bp)
    csrf.exempt(suggestions_bp)
    csrf.exempt(admin_bp)
    csrf.exempt(test_bp)
    csrf.exempt(routes_bp)
    csrf.exempt(places_bp)

    # CORS — разрешаем запросы только со своего домена
    cors.init_app(app, resources={
        r"/api/*": {
            "origins": ["http://localhost:5000"],
            "supports_credentials": True
        }
    })

    # Обработчик превышения лимита запросов
    from flask_limiter.errors import RateLimitExceeded
    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(e):
        return jsonify({
            'success': False,
            'error': 'Слишком много запросов. Попробуйте позже.'
        }), 429

    # Регистрация blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp, url_prefix='/profile')
    app.register_blueprint(favorites_bp)
    app.register_blueprint(visited_bp)
    app.register_blueprint(suggestions_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(test_bp)
    app.register_blueprint(routes_bp)
    app.register_blueprint(places_bp)

    # Контекстный процессор
    @app.context_processor
    def inject_navbar_vars():
        from flask import request
        def get_active_page():
            if request.endpoint == 'main.index':
                return 'index'
            elif request.endpoint == 'main.places_page':
                return 'places'
            elif request.endpoint == 'favorites.favorites_page':
                return 'favorites'
            elif request.endpoint == 'suggestions.suggest_page':
                return 'suggest'
            elif request.endpoint == 'profile.profile_page':
                return 'profile'
            elif request.endpoint == 'test.test_page':
                return 'test'
            elif request.endpoint == 'main.place_detail':
                return 'places'
            elif request.endpoint == 'visited.visited_page':
                return 'visited'
            return None
        return {'active_page': get_active_page()}

    # Игнорирование запросов Chrome DevTools
    @app.route('/.well-known/appspecific/<path:dummy>')
    def ignore_chrome_requests(dummy):
        return '', 204

    return app