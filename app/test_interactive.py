import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_runner import TestRunner

def interactive_mode():
    """Интерактивный режим тестирования"""
    runner = TestRunner()

    try:
        print("Интерактивное тестирование теста")
        print("Выберите вариант:")
        print("1. Протестировать все пути")
        print("2. Протестировать конкретный путь")
        print("3. Проверить структуру теста")
        print("4. Проверить наличие категорий в базе")
        choice = input("Ваш выбор (1-4): ").strip()

        if choice == "1":
            print("\nЗапуск полного тестирования...")
            results = runner.explore_all_paths()
            runner.save_results_to_file(results)

        elif choice == "2":
            print("\nВведите путь в формате: вопрос1:вариант1,вопрос2:вариант2,...")
            print("Пример: 1:1,9:1 (С любимым → Необычные впечатления)")
            path_str = input("Путь: ").strip()

            # Парсим путь
            steps = []
            for step in path_str.split(','):
                q, o = step.split(':')
                steps.append((int(q.strip()), int(o.strip())))

            description = input("Описание пути: ").strip()
            places = runner.simulate_path(steps, description)

            if not places:
                print("\n⚠️  Мест не найдено!")
                print("\nВозможные причины:")
                print("1. Неправильные категории в варианте ответа")
                print("2. Нет мест с такими категориями в базе")
                print("3. Все места с такими категориями закрыты (is_closed=true)")

                # Проверяем категории
                print("\nПроверяем категории в базе...")
                runner.cur.execute("SELECT slug, name FROM categories_api")
                all_cats = {row['slug']: row['name'] for row in runner.cur.fetchall()}

                # Получаем критерии из симуляции
                print("\nИщем, какие категории должны быть:")
                # Нужно немного изменить simulate_path чтобы вернуть критерии

            else:
                print(f"\n✅ Найдено {len(places)} мест")
                for i, place in enumerate(places[:5], 1):
                    print(f"\n{i}. {place['title']}")
                    print(f"   Категории: {place.get('categories_list', [])}")

        elif choice == "3":
            print("\nСтруктура теста:")
            structure = runner.load_test_structure()

            print(f"\nТест: {structure['test']['title']}")
            print(f"Вопросов: {len(structure['questions'])}")

            for seq, question in structure['questions'].items():
                print(f"\nВопрос {seq}: {question['question_text']}")
                options = structure['options'].get(seq, [])
                print(f"  Вариантов: {len(options)}")

                for opt in options:
                    categories = opt.get('primary_categories', [])
                    cat_str = ', '.join(categories) if categories else "нет"
                    print(f"    - {opt['option_text']} [категории: {cat_str}]")

        elif choice == "4":
            print("\nПроверка категорий в базе:")
            runner.cur.execute("""
                               SELECT c.slug, c.name,
                                      COUNT(p.id) as places_count
                               FROM categories_api c
                                        LEFT JOIN places p ON c.slug = ANY(p.categories::text[])
                               GROUP BY c.slug, c.name
                               ORDER BY c.name
                               """)

            categories = runner.cur.fetchall()

            print(f"\nВсего категорий: {len(categories)}")
            print("\nКатегории с количеством мест:")

            for cat in categories:
                if cat['places_count'] > 0:
                    print(f"  {cat['name']} ({cat['slug']}): {cat['places_count']} мест")

            print("\nКатегории без мест:")
            for cat in categories:
                if cat['places_count'] == 0:
                    print(f"  {cat['name']} ({cat['slug']})")

        else:
            print("Неверный выбор")

    finally:
        runner.close()

if __name__ == "__main__":
    interactive_mode()