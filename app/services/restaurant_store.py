from app.repositories.restaurant_repository import RestaurantRepository


class RestaurantStore(RestaurantRepository):
    """Service layer entry point.

    Spring 기준으로 보면 Service에 해당한다. 기존 router/core import 경로를
    유지하면서 실제 저장소 구현은 repositories 레이어에 위임한다.
    """


restaurant_store = RestaurantStore()
