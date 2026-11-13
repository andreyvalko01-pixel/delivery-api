from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, User
from ..schemas import Token, UserCreate, UserOut
from ..security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Авторизація"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)):
    """Реєстрація клієнта. Кур'єрів і диспетчерів створює адміністратор."""
    if db.query(User).filter(User.email == data.email.lower()).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Користувач з таким email вже існує")

    user = User(
        email=data.email.lower(),
        full_name=data.full_name,
        phone=data.phone,
        password_hash=hash_password(data.password),
        role=Role.client,
    )
    db.add(user)
    db.commit()
    return user


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username.lower()).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний email або пароль")
    return Token(access_token=create_access_token(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
