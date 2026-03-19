from flask import Blueprint, jsonify, request
from flask_login import login_required
from app.models import Place

places_bp = Blueprint('places', __name__, url_prefix='/api/places')

@places_bp.route('/<int:place_id>/nearby', methods=['GET'])
@login_required
def nearby_places(place_id):
    """
    Возвращает JSON со списком мест, ближайших к указанному.
    Параметры запроса:
        radius (int) – радиус поиска в метрах (по умолчанию 1000)
        limit (int) – максимальное количество мест (по умолчанию 10)
    """
    radius = request.args.get('radius', 1000, type=int)
    limit = request.args.get('limit', 10, type=int)

    # Проверим, существует ли место с таким ID
    place = Place.get_by_id(place_id)
    if not place:
        return jsonify({'error': 'Place not found'}), 404
    if not place.coords or 'lat' not in place.coords or 'lon' not in place.coords:
        return jsonify({'error': 'Place has no coordinates'}), 400

    nearby = Place.get_nearby(place_id, radius=radius, limit=limit)
    return jsonify(nearby)

