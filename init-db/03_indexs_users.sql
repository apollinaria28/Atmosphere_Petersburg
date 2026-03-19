

-- ============================================
-- 3. ИНДЕКСЫ ДЛЯ БЫСТРОГО ПОИСКА
-- ============================================

-- Для быстрого поиска по email (самый частый запрос)
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Для фильтрации по роли
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Для сортировки по дате регистрации
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);

-- Для поиска активных пользователей
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active) WHERE is_active = true;

-- ============================================
-- 4. ТРИГГЕР ДЛЯ АВТООБНОВЛЕНИЯ updated_at
-- ============================================

-- Функция для обновления времени
CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Триггер для таблицы users
DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- Индекс для быстрого поиска маршрутов пользователя
CREATE INDEX idx_routes_user_id ON routes(user_id);
-- Индекс для сортировки и быстрого доступа
CREATE INDEX idx_route_places_route_id ON route_places(route_id);
CREATE INDEX idx_route_places_place_id ON route_places(place_id);