from fastapi import APIRouter

from app.api.v1.routes.branches import router as branches_router
from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.ingredients import router as ingredients_router
from app.api.v1.routes.menu_availability import router as menu_availability_router
from app.api.v1.routes.menu_items import router as menu_items_router
from app.api.v1.routes.recipe_items import router as recipe_items_router
from app.api.v1.routes.suppliers import router as suppliers_router

router = APIRouter(prefix="/api/v1")
router.include_router(chat_router)
router.include_router(branches_router)
router.include_router(suppliers_router)
router.include_router(ingredients_router)
router.include_router(menu_items_router)
router.include_router(menu_availability_router)
router.include_router(recipe_items_router)
