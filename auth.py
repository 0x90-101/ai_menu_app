import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

from fastapi import HTTPException, status, APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, field_validator
from dotenv import load_dotenv, find_dotenv
from sqlalchemy import text

from database import db

# Загружаем переменные окружения
dotenv_path = (
        find_dotenv(usecwd=True)
        or find_dotenv("env", usecwd=True)
        or find_dotenv("env.example", usecwd=True)
)
if dotenv_path:
    load_dotenv(dotenv_path)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

auth_router = APIRouter(prefix="/auth", tags=["Аутентификация"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    birth_date: Optional[str] = None  # Добавляем дату рождения (формат: YYYY-MM-DD)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Пароль должен быть не менее 6 символов")
        return v

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            birth_date = datetime.strptime(v, "%Y-%m-%d").date()
            age = datetime.now().date().year - birth_date.year
            # Проверяем, был ли уже день рождения в этом году
            if datetime.now().date().timetuple().tm_yday < birth_date.timetuple().tm_yday:
                age -= 1
            if age < 1 or age > 120:
                raise ValueError("Некорректный возраст (должен быть от 1 до 120 лет)")
            return v
        except ValueError as e:
            if "does not match format" in str(e):
                raise ValueError("Дата рождения должна быть в формате YYYY-MM-DD")
            raise e


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    success: bool
    user_id: str
    email: EmailStr
    birth_date: Optional[str] = None  # Добавляем дату рождения в ответ
    access_token: str
    token_type: str = "bearer"


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def _create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def _ensure_users_table():
    """Проверяет существование таблицы users и создаёт её при необходимости"""
    if db._table_exists("users"):
        # Проверяем наличие колонки birth_date
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT birth_date FROM users LIMIT 1"))
        except Exception:
            # Добавляем колонку birth_date если её нет
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN birth_date DATE"))
        return

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    login TEXT UNIQUE,
                    password_hash TEXT,
                    birth_date DATE,
                    diet_type TEXT,
                    meal_style TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )


def _get_user_by_email(email: str) -> Optional[Dict[str, str]]:
    """Получает пользователя по email"""
    _ensure_users_table()
    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, login, password_hash, birth_date FROM users WHERE login = :email"),
            {"email": email},
        ).fetchone()
        return dict(row._mapping) if row else None


def _create_user(email: str, password_hash: str, birth_date: Optional[str] = None) -> Dict[str, str]:
    """Создаёт нового пользователя"""
    _ensure_users_table()
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO users (login, password_hash, birth_date)
                VALUES (:email, :password_hash, :birth_date)
                """
            ),
            {"email": email, "password_hash": password_hash, "birth_date": birth_date},
        )
        user_id = result.lastrowid
    return {"id": user_id, "login": email, "password_hash": password_hash, "birth_date": birth_date}


@auth_router.post("/register", response_model=AuthResponse, summary="Регистрация")
def register_user(payload: RegisterRequest):
    email = payload.email.lower()

    if _get_user_by_email(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже существует",
        )

    password_hash = _hash_password(payload.password)
    user_row = _create_user(email, password_hash, payload.birth_date)
    user_id = str(user_row["id"])
    birth_date = user_row.get("birth_date")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = _create_access_token(
        data={"sub": user_id, "email": email}, expires_delta=access_token_expires
    )

    return AuthResponse(
        success=True,
        user_id=user_id,
        email=email,
        birth_date=birth_date,
        access_token=access_token,
        token_type="bearer"
    )


@auth_router.post("/login", response_model=AuthResponse, summary="Вход")
def login_user(payload: LoginRequest):
    email = payload.email.lower()
    user = _get_user_by_email(email)

    if not user or not _verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    user_id = str(user["id"])
    birth_date = user.get("birth_date")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = _create_access_token(
        data={"sub": user_id, "email": email}, expires_delta=access_token_expires
    )

    return AuthResponse(
        success=True,
        user_id=user_id,
        email=email,
        birth_date=birth_date,
        access_token=access_token,
        token_type="bearer"
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Получает текущего авторизованного пользователя по токену"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось проверить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        if user_id is None or email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = _get_user_by_email(email)
    if user is None:
        raise credentials_exception

    return {"user_id": user_id, "email": email, "birth_date": user.get("birth_date")}


# Дополнительная функция для получения возраста пользователя
def get_user_age(birth_date_str: Optional[str]) -> Optional[int]:
    """Рассчитывает возраст на основе даты рождения"""
    if not birth_date_str:
        return None
    try:
        birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        age = today.year - birth_date.year
        # Корректируем, если день рождения ещё не наступил в этом году
        if (today.month, today.day) < (birth_date.month, birth_date.day):
            age -= 1
        return age
    except ValueError:
        return None