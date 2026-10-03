from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_users import exceptions

from app.auth.schemas import AdminUserCreate, UserCreate, UserRead
from app.auth.users import (
    UserManager,
    cookie_backend,
    current_superuser,
    current_user,
    fastapi_users,
    get_user_manager,
)
from app.db.models import User

auth_router = APIRouter(prefix="/auth", tags=["auth"])
# Login/Logout; bewusst kein Register-Router: Benutzer legen Admin oder Seed an.
auth_router.include_router(fastapi_users.get_auth_router(cookie_backend))


@auth_router.get("/me", response_model=UserRead)
def me(user: User = Depends(current_user)) -> User:
    return user


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreate,
    admin: User = Depends(current_superuser),
    manager: UserManager = Depends(get_user_manager),
) -> User:
    """Legt einen normalen Benutzer im Büro des Admins an (Mandantentrennung)."""
    data = UserCreate(email=payload.email, password=payload.password, buero_id=admin.buero_id)
    try:
        return await manager.create(data, safe=True)
    except exceptions.UserAlreadyExists:
        raise HTTPException(status.HTTP_409_CONFLICT, "USER_ALREADY_EXISTS") from None
    except exceptions.InvalidPasswordException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "INVALID_PASSWORD") from None
