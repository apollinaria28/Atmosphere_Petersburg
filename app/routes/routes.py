from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.models import Route, RoutePlace  # импортируем наши новые модели

routes_bp = Blueprint('routes', __name__, url_prefix='/api/routes')

@routes_bp.route('', methods=['GET'])
@login_required
def get_routes():
    routes = Route.get_by_user(current_user.id)
    result = []
    for r in routes:
        places_data = r.get_places()
        places = []
        for row in places_data:
            places.append({
                'id': row['id'],
                'title': row['title'],
                'coords': row['coords'],
                'order_index': row['order_index'],
                'address': row['address'],
                'main_photo_url': row['main_photo_url'],
                'photos': row['photos'],
            })
        result.append({
            'id': r.id,
            'name': r.name,
            'description': r.description,
            'created_at': r.created_at.isoformat() if r.created_at else None,
            'places_count': len(places),
            'places': places
        })
    return jsonify(result)

@routes_bp.route('', methods=['POST'])
@login_required
def create_route():
    """Создать новый маршрут."""
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    description = data.get('description')
    route = Route.create(current_user.id, name, description)
    if len(name) > 200:
        return jsonify({'error': 'Название слишком длинное'}), 400
    if not route:
        return jsonify({'error': 'Could not create route'}), 500
    return jsonify({
        'id': route.id,
        'name': route.name,
        'description': route.description,
        'created_at': route.created_at.isoformat() if route.created_at else None
    }), 201

@routes_bp.route('/<int:route_id>', methods=['GET'])
@login_required
def get_route(route_id):
    """Получить детальную информацию о маршруте (включая места)."""
    route = Route.get_by_id(route_id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404
    if route.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    # Получаем места маршрута с координатами
    places_data = route.get_places()  # возвращает список dict-строк из БД
    places = []
    for row in places_data:
        places.append({
            'id': row['id'],
            'title': row['title'],
            'coords': row['coords'],
            'order_index': row['order_index'],
            'address': row['address'],           # ← добавить
            'main_photo_url': row['main_photo_url'],  # ← добавить
            'photos': row['photos'],             # ← добавить
        })

    return jsonify({
        'id': route.id,
        'name': route.name,
        'description': route.description,
        'created_at': route.created_at.isoformat() if route.created_at else None,
        'places': places
    })

@routes_bp.route('/<int:route_id>', methods=['PUT'])
@login_required
def update_route(route_id):
    """Обновить название и/или описание маршрута."""
    route = Route.get_by_id(route_id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404
    if route.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    route.update(name=name, description=description)
    return jsonify({'message': 'Route updated'})

@routes_bp.route('/<int:route_id>', methods=['DELETE'])
@login_required
def delete_route(route_id):
    """Удалить маршрут."""
    route = Route.get_by_id(route_id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404
    if route.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    route.delete()
    return jsonify({'message': 'Route deleted'})

@routes_bp.route('/<int:route_id>/places', methods=['POST'])
@login_required
def add_place_to_route(route_id):
    """Добавить одно или несколько мест в маршрут."""
    route = Route.get_by_id(route_id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404
    if route.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json()
    place_ids = data.get('place_ids')
    if not place_ids:
        return jsonify({'error': 'place_ids required'}), 400

    # Если передано одно число, преобразуем в список
    if isinstance(place_ids, int):
        place_ids = [place_ids]

    added = []
    for pid in place_ids:
        rp = route.add_place(pid)
        if rp:
            added.append(pid)
    return jsonify({'message': f'Added {len(added)} places', 'added': added}), 200

@routes_bp.route('/<int:route_id>/places/<int:place_id>', methods=['DELETE'])
@login_required
def remove_place_from_route(route_id, place_id):
    """Удалить место из маршрута."""
    route = Route.get_by_id(route_id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404
    if route.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    success = route.remove_place(place_id)
    if success:
        return jsonify({'message': 'Place removed'})
    else:
        return jsonify({'error': 'Place not found in route'}), 404

@routes_bp.route('/<int:route_id>/places/order', methods=['PUT'])
@login_required
def update_places_order(route_id):
    """Обновить порядок мест в маршруте."""
    route = Route.get_by_id(route_id)
    if not route:
        return jsonify({'error': 'Route not found'}), 404
    if route.user_id != current_user.id:
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json()
    order = data.get('order')  # ожидаем список ID мест в нужном порядке
    if not order or not isinstance(order, list):
        return jsonify({'error': 'order list required'}), 400

    # Проверим, что все ID действительно принадлежат этому маршруту
    # (можно довериться методу update_places_order, который обновит только существующие)
    route.update_places_order(order)
    return jsonify({'message': 'Order updated'})