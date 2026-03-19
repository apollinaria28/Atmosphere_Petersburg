# test_logic.py
import json
from typing import Dict, List, Any, Optional
import psycopg2
import psycopg2.extras
import traceback


class TestLogic:
    def __init__(self, db_config):
        self.db_config = db_config

    def get_conn(self):
        """Создает соединение с БД"""
        return psycopg2.connect(
            **self.db_config,
            cursor_factory=psycopg2.extras.DictCursor
        )

    def get_initial_state(self) -> Dict[str, Any]:
        """Инициализирует состояние теста с одним начальным путем"""
        initial_path = {
            'id': 1,
            'current_question_seq': 1,
            'mood_ids': set(),
            'primary_slugs': set(),
            'secondary_conditions': [],
            'negative_keywords': set(),
            'answers': [],
            'parent_path_id': None
        }

        return {
            'active_paths': [initial_path],  # Незавершенные пути
            'completed_paths': [],           # Завершенные пути с результатами
            'next_path_id': 2                # ID для новых путей
        }

    def load_question(self, conn, test_slug: str, seq: int) -> Optional[Dict[str, Any]]:
        """Загружает вопрос по slug теста и порядковому номеру"""
        sql = """
              SELECT q.* FROM questions q
                                  JOIN tests t ON q.test_id = t.id
              WHERE t.slug = %s AND q.seq = %s \
              """
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (test_slug, seq))
            row = cur.fetchone()
            if row:
                # DictRow уже ведёт себя как словарь, но для безопасности преобразуем
                return {key: row[key] for key in row.keys()}
            return None

    def load_options_for_question(self, conn, question_id: int) -> List[Dict[str, Any]]:
        """Загружает варианты ответа для вопроса"""
        sql = """
              SELECT * FROM options
              WHERE question_id = %s
              ORDER BY id \
              """
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (question_id,))
            rows = cur.fetchall()
            if rows:
                return [{key: row[key] for key in row.keys()} for row in rows]
            return []

    def merge_option_into_state(self, path: Dict[str, Any], option: Dict[str, Any]):
        """Объединяет критерии выбранного варианта с путем"""
        print(f"DEBUG merge_option_into_state: option keys = {option.keys()}")

        # Настроения
        if option.get('mood_id'):
            path['mood_ids'].add(option['mood_id'])

        # Основные категории
        if option.get('primary_categories'):
            prim = option['primary_categories']
            if isinstance(prim, str):
                try:
                    prim = json.loads(prim)
                except:
                    prim = []
            elif isinstance(prim, list):
                pass
            else:
                prim = []

            for item in prim:
                if item and item not in path['primary_slugs']:
                    path['primary_slugs'].add(item)

        # Дополнительные условия (ключевые слова)
        if option.get('secondary_conditions'):
            sec = option['secondary_conditions']
            if isinstance(sec, str):
                try:
                    sec = json.loads(sec)
                except:
                    sec = []
            elif isinstance(sec, list):
                pass
            else:
                sec = []

            for cond in sec:
                if isinstance(cond, dict) and cond not in path['secondary_conditions']:
                    path['secondary_conditions'].append(cond)

        # Исключающие ключевые слова
        if option.get('negative_keywords'):
            neg = option['negative_keywords']
            if isinstance(neg, str):
                try:
                    neg = json.loads(neg)
                except:
                    neg = []
            elif isinstance(neg, list):
                pass
            else:
                neg = []

            for n in neg:
                if isinstance(n, dict) and n.get('kw'):
                    path['negative_keywords'].add(n['kw'])

    def clone_path(self, original_path: Dict[str, Any], new_id: int) -> Dict[str, Any]:
        """Создает копию пути для ветвления"""
        return {
            'id': new_id,
            'current_question_seq': original_path['current_question_seq'],
            'mood_ids': set(original_path['mood_ids']),
            'primary_slugs': set(original_path['primary_slugs']),
            'secondary_conditions': original_path['secondary_conditions'].copy(),
            'negative_keywords': set(original_path['negative_keywords']),
            'answers': original_path['answers'].copy(),
            'parent_path_id': original_path['id']
        }

    def get_places_for_path(self, conn, path: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
        """Получает места для завершенного пути - ОБНОВЛЕННАЯ ВЕРСИЯ"""
        primary_slugs = list(path['primary_slugs'])
        mood_ids = list(path['mood_ids'])
        secondary_conditions = path['secondary_conditions']

        print(f"DEBUG get_places_for_path:")
        print(f"  - primary_slugs: {primary_slugs}")
        print(f"  - mood_ids: {mood_ids}")
        print(f"  - secondary_conditions: {secondary_conditions}")
        print(f"  - negative_keywords: {list(path['negative_keywords'])}")

        # Если нет критериев, возвращаем пустой список
        if not primary_slugs and not secondary_conditions:
            print("DEBUG: Нет критериев для поиска")
            return []

        try:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                # Пробуем использовать новую улучшенную функцию
                try:
                    cur.execute("""
                                SELECT * FROM find_test_places_v2(%s, %s, %s::JSONB)
                                LIMIT %s
                                """, (
                                    primary_slugs,
                                    mood_ids,
                                    json.dumps(secondary_conditions) if secondary_conditions else '[]',
                                    limit
                                ))

                    rows = cur.fetchall()
                    print(f"DEBUG: Найдено {len(rows)} мест через find_test_places_v2")

                    if rows:
                        return [{key: row[key] for key in row.keys()} for row in rows]
                    else:
                        print("DEBUG: Функция find_test_places_v2 не вернула результатов")
                except Exception as func_error:
                    print(f"DEBUG: Ошибка функции find_test_places_v2: {func_error}")
                    # Пробуем старую функцию
                    try:
                        # Собираем все ключевые слова из secondary_conditions
                        all_keywords = []
                        for condition in secondary_conditions:
                            if condition.get('keywords'):
                                for keyword in condition['keywords']:
                                    if keyword.get('kw') and not keyword.get('is_negative', False):
                                        all_keywords.append(keyword)

                        keywords_json = json.dumps(all_keywords) if all_keywords else '[]'

                        cur.execute("""
                                    SELECT * FROM find_places_for_test(%s, %s, %s::JSONB)
                                    LIMIT %s
                                    """, (primary_slugs, mood_ids, keywords_json, limit))

                        rows = cur.fetchall()
                        print(f"DEBUG: Найдено {len(rows)} мест через find_places_for_test")

                        if rows:
                            return [{key: row[key] for key in row.keys()} for row in rows]
                    except Exception as func_error2:
                        print(f"DEBUG: Ошибка функции find_places_for_test: {func_error2}")

                # Если функции не сработали, используем простой запрос
                print("DEBUG: Используем простой запрос")
                return self.simple_places_query(conn, path, limit)

        except Exception as e:
            print(f"Ошибка при поиске мест: {e}")
            traceback.print_exc()
            return self.simple_places_query(conn, path, limit)

    def simple_places_query(self, conn, path: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Простой запрос мест (резервный вариант) - ОБНОВЛЕННАЯ ВЕРСИЯ"""
        primary_slugs = list(path['primary_slugs'])

        sql = """
              SELECT
                  p.id, p.title, p.slug, p.categories,
                  COALESCE(p.main_photo_url, '') as photo_url,
                  COALESCE(p.description, '') as description,
                  COALESCE(p.address, '') as address,
                  COALESCE(p.timetable, '') as timetable,
                  p.body_text
              FROM places p
              WHERE NOT COALESCE(p.is_closed, false) \
              """

        params = []

        if primary_slugs:
            sql += """
                AND EXISTS (
                    SELECT 1 FROM jsonb_array_elements_text(p.categories) cat
                    WHERE cat = ANY(%s)
                )
            """
            params.append(primary_slugs)
        else:
            # Если нет primary_slugs, ищем по ключевым словам из secondary_conditions
            all_keywords = []
            for condition in path['secondary_conditions']:
                if condition.get('keywords'):
                    for keyword in condition['keywords']:
                        if keyword.get('kw') and not keyword.get('is_negative', False):
                            all_keywords.append(keyword.get('kw'))

            if all_keywords:
                keyword_conditions = []
                for keyword in all_keywords:
                    keyword_conditions.append("p.title ILIKE %s")
                    params.append(f"%{keyword}%")

                sql += " AND (" + " OR ".join(keyword_conditions) + ")"
            else:
                # Если совсем нет критериев, возвращаем случайные места
                sql += " AND TRUE"

        sql += " ORDER BY RANDOM() LIMIT %s"
        params.append(limit)

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            if rows:
                print(f"DEBUG: Простой запрос вернул {len(rows)} мест")
                return [{key: row[key] for key in row.keys()} for row in rows]

        return []

    def process_answer(self, conn, state: Dict[str, Any], path_id: int,
                       question_id: int, option_ids: List[int]) -> Dict[str, Any]:
        """Обрабатывает ответ пользователя для конкретного пути"""
        # Находим активный путь
        active_path = None
        path_index = -1
        for i, path in enumerate(state['active_paths']):
            if path['id'] == path_id:
                active_path = path
                path_index = i
                break

        if not active_path:
            raise ValueError(f"Путь с id {path_id} не найден")

        print(f"DEBUG process_answer:")
        print(f"  - path_id: {path_id}")
        print(f"  - question_id: {question_id}")
        print(f"  - option_ids: {option_ids}")
        print(f"  - текущий путь до обработки: {active_path}")

        # Загружаем вопрос и выбранные варианты
        sql = """
              SELECT o.*, q.allow_multiple, q.seq as question_seq
              FROM options o
                       JOIN questions q ON o.question_id = q.id
              WHERE o.id = ANY(%s) \
              """
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql, (option_ids,))
            rows = cur.fetchall()
            selected_options = [{key: row[key] for key in row.keys()} for row in rows]

        if not selected_options:
            print("DEBUG: Нет выбранных опций")
            return state

        # Определяем, разрешен ли множественный выбор
        allow_multiple = selected_options[0]['allow_multiple']
        current_question_seq = selected_options[0]['question_seq']

        print(f"DEBUG: allow_multiple = {allow_multiple}, question_seq = {current_question_seq}")

        # Сохраняем ответы в историю
        for option in selected_options:
            active_path['answers'].append({
                'question_id': question_id,
                'question_seq': current_question_seq,
                'option_id': option['id'],
                'option_key': option.get('option_key'),
                'option_text': option.get('option_text')
            })

        # Логика ветвления
        if allow_multiple and len(selected_options) > 1:
            # МНОЖЕСТВЕННЫЙ ВЫБОР (вопрос 3)
            print("DEBUG: Множественный выбор")
            new_paths = []

            # Первый вариант продолжает текущий путь
            first_option = selected_options[0]
            self.merge_option_into_state(active_path, first_option)

            if first_option.get('next_question_seq'):
                # Продолжаем текущий путь
                active_path['current_question_seq'] = first_option['next_question_seq']
                print(f"DEBUG: Первый вариант продолжает путь, next_seq = {first_option['next_question_seq']}")
            else:
                # Терминальный вариант - завершаем путь
                print("DEBUG: Первый вариант терминальный, завершаем путь")
                self.complete_path(conn, state, active_path)
                state['active_paths'].pop(path_index)

            # Для остальных вариантов создаем новые пути
            for option in selected_options[1:]:
                new_path = self.clone_path(active_path, state['next_path_id'])
                state['next_path_id'] += 1

                # Добавляем критерии этого варианта
                self.merge_option_into_state(new_path, option)

                if option.get('next_question_seq'):
                    # Продолжаем новый путь
                    new_path['current_question_seq'] = option['next_question_seq']
                    new_paths.append(new_path)
                    print(f"DEBUG: Создан новый путь {new_path['id']} с next_seq = {option['next_question_seq']}")
                else:
                    # Терминальный вариант
                    print(f"DEBUG: Вариант терминальный, завершаем путь {new_path['id']}")
                    self.complete_path(conn, state, new_path)

            # Добавляем новые активные пути
            if new_paths:
                state['active_paths'].extend(new_paths)

        else:
            # ОДИНОЧНЫЙ ВЫБОР
            option = selected_options[0]
            print(f"DEBUG: Одиночный выбор, option = {option}")
            self.merge_option_into_state(active_path, option)

            if option.get('next_question_seq'):
                # Продолжаем текущий путь
                active_path['current_question_seq'] = option['next_question_seq']
                print(f"DEBUG: Продолжаем путь, next_seq = {option['next_question_seq']}")
            else:
                # Терминальный вариант - завершаем путь
                print("DEBUG: Терминальный вариант, завершаем путь")
                self.complete_path(conn, state, active_path)
                state['active_paths'].pop(path_index)

        print(f"DEBUG: Состояние после обработки:")
        print(f"  - active_paths: {len(state['active_paths'])}")
        print(f"  - completed_paths: {len(state['completed_paths'])}")

        return state

    def complete_path(self, conn, state: Dict[str, Any], path: Dict[str, Any]):
        """Завершает путь и добавляет найденные места"""
        print(f"DEBUG complete_path: Завершаем путь {path['id']}")

        # Получаем места для этого пути
        places = self.get_places_for_path(conn, path, limit=10)
        print(f"DEBUG: Для пути {path['id']} найдено {len(places)} мест")

        # Создаем завершенный путь
        completed_path = {
            'id': path['id'],
            'parent_path_id': path.get('parent_path_id'),
            'criteria': {
                'mood_ids': list(path['mood_ids']),
                'primary_slugs': list(path['primary_slugs']),
                'secondary_conditions': path['secondary_conditions'],
                'negative_keywords': list(path['negative_keywords'])
            },
            'places': places,
            'answers': path['answers']
        }

        state['completed_paths'].append(completed_path)

    def get_next_question(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Возвращает информацию о следующем вопросе"""
        if not state['active_paths']:
            print("DEBUG: Нет активных путей, тест завершен")
            return None  # Все пути завершены

        # Берем первый активный путь
        active_path = state['active_paths'][0]
        result = {
            'path_id': active_path['id'],
            'question_seq': active_path['current_question_seq']
        }
        print(f"DEBUG get_next_question: {result}")
        return result

    def is_test_completed(self, state: Dict[str, Any]) -> bool:
        """Проверяет, завершен ли тест (нет активных путей)"""
        result = len(state['active_paths']) == 0
        print(f"DEBUG is_test_completed: {result}")
        return result

    def get_all_results(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Возвращает все результаты из завершенных путей"""
        all_places = []
        seen_place_ids = set()

        print(f"DEBUG get_all_results: Обрабатываем {len(state['completed_paths'])} завершенных путей")

        for completed_path in state['completed_paths']:
            print(f"DEBUG: Путь {completed_path['id']} имеет {len(completed_path.get('places', []))} мест")
            for place in completed_path.get('places', []):
                place_id = place.get('place_id') or place.get('id')
                if place_id and place_id not in seen_place_ids:
                    place['id'] = place_id  # Убедимся, что есть поле id
                    place['path_id'] = completed_path['id']
                    all_places.append(place)
                    seen_place_ids.add(place_id)

        print(f"DEBUG: Всего уникальных мест: {len(all_places)}")
        return all_places

    def get_complete_test_data(self, conn, test_slug: str) -> Dict[str, Any]:
        """Возвращает все вопросы и варианты теста (для отладки)"""
        sql = """
              SELECT
                  q.id as question_id,
                  q.seq,
                  q.question_text,
                  q.allow_multiple,
                  o.id as option_id,
                  o.option_key,
                  o.option_text,
                  o.next_question_seq,
                  o.is_terminal
              FROM questions q
                       JOIN tests t ON q.test_id = t.id
                       LEFT JOIN options o ON q.id = o.question_id
              WHERE t.slug = %s
              ORDER BY q.seq, o.id \
              """

        with conn.cursor() as cur:
            cur.execute(sql, (test_slug,))
            rows = cur.fetchall()

            if rows:
                result = {}
                for row in rows:
                    row_dict = {key: row[key] for key in row.keys()}
                    seq = row_dict['seq']

                    if seq not in result:
                        result[seq] = {
                            'id': row_dict['question_id'],
                            'seq': seq,
                            'text': row_dict['question_text'],
                            'allow_multiple': row_dict['allow_multiple'],
                            'options': []
                        }

                    if row_dict['option_id']:
                        result[seq]['options'].append({
                            'id': row_dict['option_id'],
                            'key': row_dict['option_key'],
                            'text': row_dict['option_text'],
                            'next_question_seq': row_dict['next_question_seq'],
                            'is_terminal': row_dict['is_terminal']
                        })

                return list(result.values())
            return []
