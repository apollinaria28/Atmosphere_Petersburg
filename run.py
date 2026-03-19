import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    # Создаём необходимые папки, если их нет
    os.makedirs('static/uploads/suggestions', exist_ok=True)
    os.makedirs('static/avatars', exist_ok=True)

    # Запускаем приложение
    app.run(debug=True, port=5000, host='0.0.0.0')