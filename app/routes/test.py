# app/routes/test.py
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
import psycopg2
import psycopg2.extras
import json
import traceback

# Импортируем логику теста (предполагается, что test_logic.py лежит в корне проекта)
from ..test_logic import TestLogic

from app.db import get_db_connection 

# Импортируем вспомогательные функции из utils
from app.utils import process_place_row


# Создаём blueprint
test_bp = Blueprint('test', __name__)

# Инициализируем логику теста с конфигурацией БД
# (Конфигурация должна быть доступна; можно импортировать из app.config)
from app.config import Config
db_config = {
    'host': Config.DB_HOST,
    'port': Config.DB_PORT,
    'database': Config.DB_NAME,
    'user': Config.DB_USER,
    'password': Config.DB_PASSWORD
}
test_logic = TestLogic(db_config)


@test_bp.route('/test')
def test_page():
    """Страница прохождения теста"""
    return render_template('test.html')


@test_bp.route('/api/test/start')
def start_test():
    """Начинает новый тест и возвращает первый вопрос"""
    conn = get_db_connection()
    try:
        # Инициализируем состояние
        state = test_logic.get_initial_state()

        # Получаем первый вопрос
        next_q = test_logic.get_next_question(state)
        if not next_q:
            return jsonify({'success': False, 'error': 'No active paths'})

        # Загружаем вопрос
        question = test_logic.load_question(conn, 'mood_flow_v1', next_q['question_seq'])
        if not question:
            return jsonify({'success': False, 'error': 'Question not found'})

        # Загружаем варианты
        options = test_logic.load_options_for_question(conn, question['id'])

        # Сериализуем состояние
        serializable_state = {
            'active_paths': [
                {
                    'id': path['id'],
                    'current_question_seq': path['current_question_seq'],
                    'mood_ids': list(path['mood_ids']),
                    'primary_slugs': list(path['primary_slugs']),
                    'secondary_conditions': path['secondary_conditions'],
                    'negative_keywords': list(path['negative_keywords']),
                    'answers': path['answers'],
                    'parent_path_id': path.get('parent_path_id')
                }
                for path in state['active_paths']
            ],
            'completed_paths': [],  # Начальное состояние - нет завершенных путей
            'next_path_id': state['next_path_id']
        }

        return jsonify({
            'success': True,
            'state': serializable_state,
            'question': {
                'path_id': next_q['path_id'],
                'question': question,
                'options': options
            }
        })

    except Exception as e:
        print(f"ERROR in start_test: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@test_bp.route('/api/test/answer', methods=['POST'])
def process_test_answer():
    """Обрабатывает ответ пользователя и возвращает следующий вопрос или результаты"""
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    conn = get_db_connection()
    try:
        data = request.json

        # Восстанавливаем состояние
        state = {
            'active_paths': [],
            'completed_paths': data.get('state', {}).get('completed_paths', []),
            'next_path_id': data.get('state', {}).get('next_path_id', 2)
        }

        # Восстанавливаем активные пути с множествами
        for path_data in data.get('state', {}).get('active_paths', []):
            path = {
                'id': path_data['id'],
                'current_question_seq': path_data['current_question_seq'],
                'mood_ids': set(path_data['mood_ids']),
                'primary_slugs': set(path_data['primary_slugs']),
                'secondary_conditions': path_data['secondary_conditions'],
                'negative_keywords': set(path_data['negative_keywords']),
                'answers': path_data['answers'],
                'parent_path_id': path_data.get('parent_path_id')
            }
            state['active_paths'].append(path)

        # Обрабатываем ответ
        updated_state = test_logic.process_answer(
            conn,
            state,
            data.get('path_id'),
            data.get('question_id'),
            data.get('option_ids', [])
        )

        # Проверяем, завершен ли тест
        if test_logic.is_test_completed(updated_state):
            # Получаем все результаты
            all_places = test_logic.get_all_results(updated_state)

            # Обрабатываем каждое место с учетом сериализации дат
            processed_places = []
            for place in all_places:
                # Конвертируем Row/Dict в dict и обрабатываем даты
                place_dict = dict(place)

                # Сериализуем даты, если они есть
                for key, value in place_dict.items():
                    if hasattr(value, 'isoformat'):  # Для datetime объектов
                        place_dict[key] = value.isoformat()

                processed_place = process_place_row(place_dict)
                processed_place['path_id'] = place.get('path_id')
                processed_places.append(processed_place)

            # Сериализуем состояние - для завершенных путей структура другая
            serializable_state = {
                'active_paths': [],
                'completed_paths': [
                    {
                        'id': path['id'],
                        'parent_path_id': path.get('parent_path_id'),
                        'criteria': path.get('criteria', {}),
                        'places': path.get('places', []),
                        'answers': path.get('answers', [])
                    }
                    for path in updated_state['completed_paths']
                ],
                'next_path_id': updated_state['next_path_id']
            }

            return jsonify({
                'success': True,
                'finished': True,
                'places': processed_places,
                'state': serializable_state
            })

        else:
            # Получаем следующий вопрос
            next_q = test_logic.get_next_question(updated_state)
            if not next_q:
                return jsonify({'success': False, 'error': 'No next question found'})

            # Загружаем вопрос
            question = test_logic.load_question(conn, 'mood_flow_v1', next_q['question_seq'])
            options = test_logic.load_options_for_question(conn, question['id'])

            # Сериализуем состояние - для активных путей есть current_question_seq
            serializable_state = {
                'active_paths': [
                    {
                        'id': path['id'],
                        'current_question_seq': path['current_question_seq'],
                        'mood_ids': list(path.get('mood_ids', [])),
                        'primary_slugs': list(path.get('primary_slugs', [])),
                        'secondary_conditions': path['secondary_conditions'],
                        'negative_keywords': list(path.get('negative_keywords', [])),
                        'answers': path['answers'],
                        'parent_path_id': path.get('parent_path_id')
                    }
                    for path in updated_state['active_paths']
                ],
                'completed_paths': [
                    {
                        'id': path['id'],
                        'parent_path_id': path.get('parent_path_id'),
                        'criteria': path.get('criteria', {}),
                        'places': path.get('places', []),
                        'answers': path.get('answers', [])
                    }
                    for path in updated_state['completed_paths']
                ],
                'next_path_id': updated_state['next_path_id']
            }

            return jsonify({
                'success': True,
                'finished': False,
                'state': serializable_state,
                'question': {
                    'path_id': next_q['path_id'],
                    'question': question,
                    'options': options
                }
            })

    except Exception as e:
        print(f"ERROR in process_test_answer: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()


@test_bp.route('/api/debug/test-search')
def debug_test_search():
    """Диагностический поиск мест по критериям теста"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    try:
        # Критерии из лога
        primary_slugs = ['bar', 'clubs', 'concert-hall']
        mood_id = 4
        secondary_conditions = [{
            'slug': 'amusement',
            'keywords': [
                {'kw': 'ночн', 'in_title': True, 'is_negative': False, 'in_description': False},
                {'kw': 'вечеринка', 'in_title': True, 'is_negative': False, 'in_description': False}
            ]
        }]

        # 1. Проверяем места по каждой категории отдельно
        category_stats = {}
        for slug in primary_slugs:
            cur.execute("""
                SELECT COUNT(*) as count
                FROM places
                WHERE NOT is_closed
                  AND categories @> %s::jsonb
            """, (json.dumps([slug]),))
            result = cur.fetchone()
            category_stats[slug] = result['count'] if result else 0

        # 2. Проверяем места по ключевым словам
        keyword_stats = {}
        for keyword in ['ночн', 'вечеринка']:
            cur.execute("""
                SELECT COUNT(*) as count
                FROM places
                WHERE NOT is_closed
                  AND title ILIKE %s
            """, (f'%{keyword}%',))
            result = cur.fetchone()
            keyword_stats[keyword] = result['count'] if result else 0

        # 3. Проверяем функцию find_places_by_mood
        cur.execute("SELECT * FROM find_places_by_mood(%s)", (mood_id,))
        mood_results = cur.fetchall()

        # 4. Проверяем вручную поиск по категориям и ключевым словам
        cur.execute("""
            SELECT p.id, p.title, p.slug, p.categories
            FROM places p
            WHERE NOT p.is_closed
              AND (
                EXISTS (
                    SELECT 1 FROM jsonb_array_elements_text(p.categories) cat
                    WHERE cat IN ('bar', 'clubs', 'concert-hall')
                )
                OR p.title ILIKE '%ночн%'
                OR p.title ILIKE '%вечеринка%'
              )
            ORDER BY RANDOM()
            LIMIT 20
        """)
        manual_results = [dict(row) for row in cur.fetchall()]

        # 5. Проверяем структуру категорий в базе
        cur.execute("""
            SELECT DISTINCT jsonb_array_elements_text(categories) as category
            FROM places
            WHERE NOT is_closed
            ORDER BY category
        """)
        all_categories = [row['category'] for row in cur.fetchall()]

        # 6. Ищем места с категорией amusement
        cur.execute("""
            SELECT COUNT(*) as count
            FROM places
            WHERE NOT is_closed
              AND categories @> '["amusement"]'::jsonb
        """)
        amusement_count = cur.fetchone()['count']

        # 7. Ищем конкретные места с категориями бар/клубы
        cur.execute("""
            SELECT p.id, p.title, p.slug, p.categories
            FROM places p
            WHERE NOT p.is_closed
              AND (
                EXISTS (
                    SELECT 1 FROM jsonb_array_elements_text(p.categories) cat
                    WHERE cat IN ('bar', 'clubs', 'concert-hall')
                )
              )
            LIMIT 10
        """)
        bar_club_places = [dict(row) for row in cur.fetchall()]

        return jsonify({
            'success': True,
            'category_stats': category_stats,
            'keyword_stats': keyword_stats,
            'mood_results_count': len(mood_results),
            'manual_results_count': len(manual_results),
            'manual_results': manual_results,
            'all_categories_count': len(all_categories),
            'all_categories_sample': all_categories[:20],
            'amusement_category_count': amusement_count,
            'bar_club_places': bar_club_places,
            'debug_info': {
                'primary_slugs': primary_slugs,
                'mood_id': mood_id,
                'secondary_conditions': secondary_conditions
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
    finally:
        cur.close()
        conn.close()