# database.py
import os
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, text, inspect, MetaData
from sqlalchemy.orm import sessionmaker
import hashlib
import secrets
from dotenv import load_dotenv

load_dotenv()


class Database:
    # Хеширует пароль: SHA-256 от "пароль+соль", возвращает строку "хеш:соль".
    # Соль генерируется случайно, если не передана.
    @staticmethod
    def _hash_password(password: str, salt: str = None) -> str:
        if not password:
            raise ValueError("Пароль не может быть пустым")
        if not salt:
            salt = secrets.token_hex(16)
        password_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
        return f"{password_hash}:{salt}"

    # Проверяет пароль: разбивает "хеш:соль", пересчитывает хеш и сравнивает.
    # При любой ошибке (пустые данные, битый формат) возвращает False.
    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        if not password or not stored_hash:
            return False
        try:
            stored_hash, salt = stored_hash.split(":", 1)
            password_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
            return password_hash == stored_hash
        except:
            return False

    # Генерирует случайный пароль заданной длины из букв, цифр и спецсимволов.
    @staticmethod
    def _generate_password(length: int = 12) -> str:
        import string
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    # Проверяет «силу» пароля: минимум 8 символов, есть строчная, заглавная и цифра.
    @staticmethod
    def _check_password_strength(password: str) -> bool:
        if len(password) < 8:
            return False
        has_lower = any(c.islower() for c in password)
        has_upper = any(c.isupper() for c in password)
        has_digit = any(c.isdigit() for c in password)
        return has_lower and has_upper and has_digit

    # Конструктор: читает DATABASE_URL, создаёт engine и фабрику сессий,
    # сразу инициализирует подключение через _init_database().
    def __init__(self, db_path: str = None):
        self.database_url = os.getenv("DATABASE_URL")
        self.engine = None
        self.Session = None
        self.metadata = MetaData()
        self._init_database()

    # Создаёт engine: по DATABASE_URL, а если он не задан — SQLite-файл restaurant.db.
    # Делает тестовый запрос SELECT 1, чтобы убедиться, что соединение живое.
    def _init_database(self):
        try:
            if self.database_url:
                self.engine = create_engine(
                    self.database_url,
                    #connect_args={"sslmode": "require"},
                    pool_pre_ping=True,
                    pool_recycle=50
                )
            else:
                # Fallback на SQLite только если DATABASE_URL не задан
                db_path = "restaurant.db"
                self.engine = create_engine(f"sqlite:///{db_path}")
            self.Session = sessionmaker(bind=self.engine)
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            raise

    # Проверяет существование таблицы по имени. При ошибке — False.
    def _table_exists(self, table_name: str) -> bool:
        try:
            inspector = inspect(self.engine)
            return table_name in inspector.get_table_names()
        except:
            return False

    # Проверяет, есть ли колонка с заданным именем в таблице.
    def _column_exists(self, table_name: str, column_name: str) -> bool:
        try:
            inspector = inspect(self.engine)
            columns = inspector.get_columns(table_name)
            return any(col['name'] == column_name for col in columns)
        except:
            return False

    # Возвращает список имён колонок таблицы. При ошибке — пустой список.
    def _get_table_columns(self, table_name: str) -> List[str]:
        try:
            inspector = inspect(self.engine)
            columns = inspector.get_columns(table_name)
            return [col['name'] for col in columns]
        except:
            return []

    # Возвращает список админов (id, login, role) без паролей.
    # Если таблицы нет — пустой список.
    def get_all_admin_users(self) -> List[Dict[str, Any]]:
        try:
            if not self._table_exists('admin_users'):
                return []
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id, login, role 
                    FROM admin_users 
                    ORDER BY id
                """))
                rows = result.fetchall()
                result.close()
                return [dict(row._mapping) for row in rows]
        except Exception:
            return []

    # Создаёт админа: при необходимости создаёт таблицу admin_users,
    # проверяет уникальность логина, хеширует пароль и вставляет запись.
    # Возвращает id, login, role созданного админа.
    def create_admin_user(self, admin_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not self._table_exists('admin_users'):
                with self.engine.connect() as conn:
                    conn.execute(text("""
                        CREATE TABLE admin_users (
                            id SERIAL PRIMARY KEY,
                            login TEXT NOT NULL UNIQUE,
                            password_hash TEXT NOT NULL,
                            role TEXT NOT NULL DEFAULT 'admin',
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """))
                    conn.commit()

            with self.engine.connect() as conn:
                # Проверка существования - нужно закрыть результат
                check_result = conn.execute(
                    text("SELECT id FROM admin_users WHERE login = :login"),
                    {"login": admin_data.get('login')}
                )
                existing = check_result.fetchone()
                check_result.close()

                if existing:
                    raise ValueError(f"Администратор с логином '{admin_data.get('login')}' уже существует")

                password = admin_data.get('password', admin_data.get('password_hash', ''))
                if not password:
                    raise ValueError("Пароль не может быть пустым")

                hashed_password = self._hash_password(password)

                insert_data = {
                    "login": admin_data.get('login'),
                    "password_hash": hashed_password,
                    "role": admin_data.get('role', 'admin')
                }

                result = conn.execute(
                    text("""
                        INSERT INTO admin_users (login, password_hash, role)
                        VALUES (:login, :password_hash, :role)
                        RETURNING id, login, role
                    """),
                    insert_data
                )
                row = result.fetchone()
                result.close()  # ← Закрываем результат
                conn.commit()  # ← Коммит после закрытия
                return dict(row._mapping)
        except ValueError:
            raise
        except Exception as e:
            print(f"Ошибка: {e}")
            raise

    # Обновляет админа по id: можно менять login, role и пароль.
    # Пароль хешируется. Проверяет уникальность нового логина.
    # Если данных для обновления нет — возвращает текущую запись.
    def update_admin_user(self, admin_id: int, admin_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('admin_users'):
                return None

            with self.engine.connect() as conn:
                check_result = conn.execute(
                    text("SELECT id FROM admin_users WHERE id = :id"),
                    {"id": admin_id}
                )
                if not check_result.fetchone():
                    return None

                if 'login' in admin_data and admin_data['login']:
                    check_login_result = conn.execute(
                        text("SELECT id FROM admin_users WHERE login = :login AND id != :id"),
                        {"login": admin_data['login'], "id": admin_id}
                    )
                    if check_login_result.fetchone():
                        raise ValueError(f"Администратор с логином '{admin_data['login']}' уже существует")

                update_data = {k: v for k, v in admin_data.items() if v is not None}
                if not update_data:
                    result = conn.execute(
                        text("SELECT id, login, role FROM admin_users WHERE id = :id"),
                        {"id": admin_id}
                    )
                    row = result.fetchone()
                    return dict(row._mapping) if row else None

                if 'password' in update_data:
                    password = update_data['password']
                    if password and password.strip():
                        update_data['password_hash'] = self._hash_password(password)
                        del update_data['password']
                    else:
                        del update_data['password']
                elif 'password_hash' in update_data:
                    password = update_data['password_hash']
                    if password and password.strip():
                        update_data['password_hash'] = self._hash_password(password)
                    else:
                        del update_data['password_hash']

                if not update_data:
                    result = conn.execute(
                        text("SELECT id, login, role FROM admin_users WHERE id = :id"),
                        {"id": admin_id}
                    )
                    row = result.fetchone()
                    return dict(row._mapping) if row else None

                set_parts = [f"{k} = :{k}" for k in update_data.keys()]
                params = {"id": admin_id, **update_data}
                query = f"UPDATE admin_users SET {', '.join(set_parts)} WHERE id = :id"
                result = conn.execute(text(query), params)
                conn.commit()

                if result.rowcount > 0:
                    result2 = conn.execute(
                        text("SELECT id, login, role FROM admin_users WHERE id = :id"),
                        {"id": admin_id}
                    )
                    row = result2.fetchone()
                    return dict(row._mapping) if row else None
                return None
        except ValueError:
            raise
        except Exception:
            import traceback
            traceback.print_exc()
            raise

    # Удаляет админа по id. Запрещает удалять последнего админа (ValueError).
    # Возвращает True, если строка удалена.
    def delete_admin_user(self, admin_id: int) -> bool:
        try:
            if not self._table_exists('admin_users'):
                return False

            with self.engine.connect() as conn:
                count_result = conn.execute(text("SELECT COUNT(*) FROM admin_users"))
                total_admins = count_result.scalar() or 0
                count_result.close()

                if total_admins <= 1:
                    raise ValueError("Нельзя удалить последнего администратора")

                result = conn.execute(
                    text("DELETE FROM admin_users WHERE id = :id"),
                    {"id": admin_id}
                )
                result.close()
                conn.commit()
                return result.rowcount > 0
        except ValueError:
            raise
        except Exception as e:
            print(f"Ошибка удаления: {e}")
            return False

    # Проверяет логин/пароль админа. Если всё ок — возвращает id, login, role
    # (без password_hash), иначе None.
    def verify_admin_password(self, login: str, password: str) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('admin_users'):
                return None
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT id, login, role, password_hash FROM admin_users WHERE login = :login"),
                    {"login": login}
                )
                row = result.fetchone()
                if not row:
                    return None
                admin_data = dict(row._mapping)
                stored_hash = admin_data.pop('password_hash', '')
                if self._verify_password(password, stored_hash):
                    return admin_data
                else:
                    return None
        except Exception:
            return None

    # Меняет пароль админа: сначала проверяет старый, затем сохраняет хеш нового.
    # Возвращает True при успехе.
    def change_admin_password(self, admin_id: int, old_password: str, new_password: str) -> bool:
        try:
            if not self._table_exists('admin_users'):
                return False
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT password_hash FROM admin_users WHERE id = :id"),
                    {"id": admin_id}
                )
                row = result.fetchone()
                if not row:
                    return False
                stored_hash = row[0]
                if not self._verify_password(old_password, stored_hash):
                    return False
                new_hashed_password = self._hash_password(new_password)
                update_result = conn.execute(
                    text("UPDATE admin_users SET password_hash = :password_hash WHERE id = :id"),
                    {"id": admin_id, "password_hash": new_hashed_password}
                )
                conn.commit()
                return update_result.rowcount > 0
        except Exception:
            return False

    # Возвращает одного админа (id, login, role) по id или None.
    def get_admin_user_by_id(self, admin_id: int) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('admin_users'):
                return None
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT id, login, role FROM admin_users WHERE id = :id"),
                    {"id": admin_id}
                )
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception:
            return None

    # Считает количество админов в таблице.
    def get_admin_users_count(self) -> int:
        try:
            if not self._table_exists('admin_users'):
                return 0
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM admin_users"))
                return result.scalar() or 0
        except Exception:
            return 0

    # Возвращает всех обычных пользователей. Набор колонок подбирается динамически:
    # birth_date/diet_type/meal_style добавляются, только если они есть в таблице.
    def get_all_users(self) -> List[Dict[str, Any]]:
        try:
            if not self._table_exists('users'):
                return []
            with self.engine.connect() as conn:
                columns = self._get_table_columns('users')
                select_cols = ['id', 'login']
                if 'birth_date' in columns:
                    select_cols.append('birth_date')
                if 'diet_type' in columns:
                    select_cols.append('diet_type')
                if 'meal_style' in columns:
                    select_cols.append('meal_style')
                query = f"SELECT {', '.join(select_cols)} FROM users ORDER BY id"
                result = conn.execute(text(query))
                return [dict(row._mapping) for row in result]
        except Exception as e:
            print(f"⚠️ Ошибка при получении пользователей: {e}")
            return []

    # Возвращает одного пользователя по id (id, login и birth_date, если колонка есть).
    # Если не найден — None.
    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('users'):
                return None
            with self.engine.connect() as conn:
                columns = self._get_table_columns('users')
                select_cols = ['id', 'login']
                if 'birth_date' in columns:
                    select_cols.append('birth_date')
                query = f"SELECT {', '.join(select_cols)} FROM users WHERE id = :id"
                result = conn.execute(text(query), {"id": user_id})
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception:
            return None

    # Удаляет пользователя по id. Возвращает True, если строка была удалена.
    def delete_user(self, user_id: int) -> bool:
        try:
            if not self._table_exists('users'):
                return False
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": user_id}
                )
                conn.commit()
                return result.rowcount > 0
        except Exception as e:
            print(f"Ошибка при удалении пользователя: {e}")
            return False

    # Возвращает список блюд. Можно фильтровать по category_id (если колонка есть).
    # Преобразует is_available в bool и подтягивает category_name по category_id.
    def get_all_dishes(self, category_id: Optional[int] = None, available_only: bool = False) -> List[Dict[str, Any]]:
        try:
            if not self._table_exists('dishes'):
                return []
            with self.engine.connect() as conn:
                query = "SELECT * FROM dishes WHERE 1=1"
                params = {}
                if category_id and self._column_exists('dishes', 'category_id'):
                    query += " AND category_id = :category_id"
                    params["category_id"] = category_id
                query += " ORDER BY name"
                result = conn.execute(text(query), params)
                dishes = []
                for row in result:
                    dish = dict(row._mapping)
                    if 'is_available' in dish:
                        dish['is_available'] = bool(dish['is_available'])
                    if 'category_id' in dish and dish['category_id']:
                        dish['category_name'] = self._get_category_name(dish['category_id'])
                    dishes.append(dish)
                return dishes
        except Exception as e:
            print(f"Ошибка при получении блюд: {e}")
            return []

    # Возвращает одно блюдо по id (с bool-флагом и category_name) или None.
    def get_dish_by_id(self, dish_id: int) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('dishes'):
                return None
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT * FROM dishes WHERE id = :id"),
                    {"id": dish_id}
                )
                row = result.fetchone()
                if row:
                    dish = dict(row._mapping)
                    if 'is_available' in dish:
                        dish['is_available'] = bool(dish['is_available'])
                    if 'category_id' in dish and dish['category_id']:
                        dish['category_name'] = self._get_category_name(dish['category_id'])
                    return dish
                return None
        except Exception as e:
            print(f"Ошибка при получении блюда: {e}")
            return None

    # Вспомогательный метод: возвращает имя категории по id.
    # Работает с таблицей visit_categories.
    def _get_category_name(self, category_id: Optional[int]) -> Optional[str]:
        if not category_id or not self._table_exists('visit_categories'):
            return None
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT name FROM visit_categories WHERE id = :id"),
                    {"id": category_id}
                )
                row = result.fetchone()
                return row[0] if row else None
        except:
            return None

    # Создаёт блюдо. Фильтрует входные данные по реальным колонкам таблицы,
    # приводит is_available к bool, возвращает созданную запись.
    def create_dish(self, dish_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if 'is_available' in dish_data:
                dish_data['is_available'] = bool(dish_data['is_available'])
            with self.engine.connect() as conn:
                columns = self._get_table_columns('dishes')
                filtered_data = {k: v for k, v in dish_data.items() if k in columns and v is not None}
                columns_str = ', '.join(filtered_data.keys())
                values_str = ', '.join([f':{k}' for k in filtered_data.keys()])
                query = f"INSERT INTO dishes ({columns_str}) VALUES ({values_str}) RETURNING *"
                result = conn.execute(text(query), filtered_data)
                row = result.fetchone()
                result.close()
                conn.commit()
                return dict(row._mapping)
        except Exception as e:
            print(f"Ошибка при создании блюда: {e}")
            raise

    # Обновляет блюдо по id: берёт только непустые поля из разрешённых колонок,
    # приводит is_available к bool, возвращает обновлённую запись с category_name.
    # Если обновлять нечего — возвращает текущую запись.
    def update_dish(self, dish_id: int, dish_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('dishes'):
                return None
            if 'is_available' in dish_data:
                dish_data['is_available'] = bool(dish_data['is_available'])
            update_data = {k: v for k, v in dish_data.items() if v is not None}
            if not update_data:
                return self.get_dish_by_id(dish_id)
            columns = self._get_table_columns('dishes')
            valid_update_data = {k: v for k, v in update_data.items() if k in columns}
            if not valid_update_data:
                return self.get_dish_by_id(dish_id)
            set_parts = [f"{k} = :{k}" for k in valid_update_data.keys()]
            params = {"id": dish_id, **valid_update_data}
            query = f"UPDATE dishes SET {', '.join(set_parts)} WHERE id = :id RETURNING *"
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params)
                conn.commit()
                if result.rowcount > 0:
                    row = result.fetchone()
                    dish = dict(row._mapping)
                    if 'category_id' in dish and dish['category_id']:
                        dish['category_name'] = self._get_category_name(dish['category_id'])
                    return dish
                return None
        except Exception as e:
            print(f"Ошибка при обновлении блюда: {e}")
            raise

    # Удаляет блюдо по id. Возвращает True, если строка была удалена.
    def delete_dish(self, dish_id: int) -> bool:
        try:
            if not self._table_exists('dishes'):
                return False
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("DELETE FROM dishes WHERE id = :id"),
                    {"id": dish_id}
                )
                conn.commit()
                return result.rowcount > 0
        except Exception as e:
            print(f"Ошибка при удалении блюда: {e}")
            return False

    # Возвращает список категорий (id, name) из таблицы visit_categories.
    def get_all_categories(self) -> List[Dict[str, Any]]:
        try:
            if not self._table_exists('visit_categories'):
                return []
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT id, name FROM visit_categories ORDER BY name"))
                return [dict(row._mapping) for row in result]
        except Exception as e:
            print(f"Ошибка при получении категорий: {e}")
            return []

    # Возвращает все напитки бара. Флаги is_alcoholic и is_available приводятся к bool.
    def get_all_bar_items(self) -> List[Dict[str, Any]]:
        try:
            if not self._table_exists('bar_items'):
                return []
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT * FROM bar_items ORDER BY name"))
                items = []
                for row in result:
                    item = dict(row._mapping)
                    if 'is_alcoholic' in item:
                        item['is_alcoholic'] = bool(item['is_alcoholic'])
                    if 'is_available' in item:
                        item['is_available'] = bool(item['is_available'])
                    items.append(item)
                return items
        except Exception as e:
            print(f"Ошибка при получении напитков: {e}")
            return []

    # Возвращает один напиток по id (с bool-флагами) или None.
    def get_bar_item_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('bar_items'):
                return None
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT * FROM bar_items WHERE id = :id"),
                    {"id": item_id}
                )
                row = result.fetchone()
                if row:
                    item = dict(row._mapping)
                    if 'is_alcoholic' in item:
                        item['is_alcoholic'] = bool(item['is_alcoholic'])
                    if 'is_available' in item:
                        item['is_available'] = bool(item['is_available'])
                    return item
                return None
        except Exception as e:
            print(f"Ошибка при получении напитка: {e}")
            return None

    # Создаёт напиток. Приводит bool-флаги, фильтрует по колонкам, возвращает запись.
    def create_bar_item(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            for flag in ('is_available', 'is_alcoholic'):
                if flag in item_data:
                    item_data[flag] = bool(item_data[flag])
            with self.engine.connect() as conn:
                columns = self._get_table_columns('bar_items')
                filtered_data = {k: v for k, v in item_data.items() if k in columns and v is not None}
                columns_str = ', '.join(filtered_data.keys())
                values_str = ', '.join([f':{k}' for k in filtered_data.keys()])
                query = f"INSERT INTO bar_items ({columns_str}) VALUES ({values_str}) RETURNING *"
                result = conn.execute(text(query), filtered_data)
                row = result.fetchone()
                result.close()
                conn.commit()
                return dict(row._mapping)
        except Exception as e:
            print(f"Ошибка при создании напитка: {e}")
            raise

    # Обновляет напиток: bool-флаги, только непустые валидные поля.
    # Возвращает обновлённую запись с bool-флагами или None.
    def update_bar_item(self, item_id: int, item_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('bar_items'):
                return None
            for flag in ('is_available', 'is_alcoholic'):
                if flag in item_data:
                    item_data[flag] = bool(item_data[flag])
            update_data = {k: v for k, v in item_data.items() if v is not None}
            if not update_data:
                return self.get_bar_item_by_id(item_id)
            columns = self._get_table_columns('bar_items')
            valid_update_data = {k: v for k, v in update_data.items() if k in columns}
            if not valid_update_data:
                return self.get_bar_item_by_id(item_id)
            set_parts = [f"{k} = :{k}" for k in valid_update_data.keys()]
            params = {"id": item_id, **valid_update_data}
            query = f"UPDATE bar_items SET {', '.join(set_parts)} WHERE id = :id RETURNING *"
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params)
                conn.commit()
                if result.rowcount > 0:
                    row = result.fetchone()
                    item = dict(row._mapping)
                    if 'is_alcoholic' in item:
                        item['is_alcoholic'] = bool(item['is_alcoholic'])
                    if 'is_available' in item:
                        item['is_available'] = bool(item['is_available'])
                    return item
                return None
        except Exception as e:
            print(f"Ошибка при обновлении напитка: {e}")
            raise

    # Удаляет напиток по id. Возвращает True, если строка была удалена.
    def delete_bar_item(self, item_id: int) -> bool:
        try:
            if not self._table_exists('bar_items'):
                return False
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("DELETE FROM bar_items WHERE id = :id"),
                    {"id": item_id}
                )
                conn.commit()
                return result.rowcount > 0
        except Exception as e:
            print(f"Ошибка при удалении напитка: {e}")
            return False

    # Возвращает все ингредиенты со склада, приводя current_stock и min_stock_level к float.
    def get_all_ingredients(self) -> List[Dict[str, Any]]:
        try:
            if not self._table_exists('ingredients'):
                return []
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT * FROM ingredients ORDER BY name"))
                ingredients = []
                for row in result:
                    ingredient = dict(row._mapping)
                    if 'current_stock' in ingredient:
                        ingredient['current_stock'] = float(ingredient.get('current_stock', 0))
                    if 'min_stock_level' in ingredient:
                        ingredient['min_stock_level'] = float(ingredient.get('min_stock_level', 0))
                    ingredients.append(ingredient)
                return ingredients
        except Exception as e:
            print(f"Ошибка при получении ингредиентов: {e}")
            return []

    # Создаёт ингредиент. При необходимости создаёт таблицу ingredients.
    # Числовые поля приводит к float, возвращает созданную запись.
    def create_ingredient(self, ingredient_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not self._table_exists('ingredients'):
                with self.engine.connect() as conn:
                    conn.execute(text("""
                        CREATE TABLE ingredients (
                            id SERIAL PRIMARY KEY,
                            name TEXT NOT NULL,
                            unit TEXT NOT NULL,
                            current_stock REAL DEFAULT 0,
                            min_stock_level REAL DEFAULT 0
                        )
                    """))
                    conn.commit()

            with self.engine.connect() as conn:
                for field in ['current_stock', 'min_stock_level']:
                    if field in ingredient_data:
                        ingredient_data[field] = float(ingredient_data[field])
                query = """
                    INSERT INTO ingredients (name, unit, current_stock, min_stock_level)
                    VALUES (:name, :unit, :current_stock, :min_stock_level)
                    RETURNING *
                """
                result = conn.execute(text(query), ingredient_data)
                conn.commit()
                row = result.fetchone()
                ingredient = dict(row._mapping)
                ingredient['current_stock'] = float(ingredient.get('current_stock', 0))
                ingredient['min_stock_level'] = float(ingredient.get('min_stock_level', 0))
                return ingredient
        except Exception as e:
            print(f"Ошибка при создании ингредиента: {e}")
            raise

    # Обновляет ингредиент: числовые поля к float, только непустые валидные колонки.
    # Возвращает обновлённую запись (с float-полями) или None.
    def update_ingredient(self, ingredient_id: int, ingredient_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if not self._table_exists('ingredients'):
                return None
            for numeric in ('current_stock', 'min_stock_level'):
                if numeric in ingredient_data and ingredient_data[numeric] is not None:
                    ingredient_data[numeric] = float(ingredient_data[numeric])
            update_data = {k: v for k, v in ingredient_data.items() if v is not None}
            if not update_data:
                return None
            columns = self._get_table_columns('ingredients')
            valid_update_data = {k: v for k, v in update_data.items() if k in columns}
            if not valid_update_data:
                return None
            set_parts = [f"{k} = :{k}" for k in valid_update_data.keys()]
            params = {"id": ingredient_id, **valid_update_data}
            query = f"UPDATE ingredients SET {', '.join(set_parts)} WHERE id = :id RETURNING *"
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params)
                conn.commit()
                if result.rowcount > 0:
                    row = result.fetchone()
                    ingredient = dict(row._mapping)
                    if 'current_stock' in ingredient:
                        ingredient['current_stock'] = float(ingredient.get('current_stock', 0))
                    if 'min_stock_level' in ingredient:
                        ingredient['min_stock_level'] = float(ingredient.get('min_stock_level', 0))
                    return ingredient
                return None
        except Exception as e:
            print(f"Ошибка при обновлении ингредиента: {e}")
            raise

    # Удаляет ингредиент по id. Возвращает True, если строка была удалена.
    def delete_ingredient(self, ingredient_id: int) -> bool:
        try:
            if not self._table_exists('ingredients'):
                return False
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("DELETE FROM ingredients WHERE id = :id"),
                    {"id": ingredient_id}
                )
                conn.commit()
                return result.rowcount > 0
        except Exception as e:
            print(f"Ошибка при удалении ингредиента: {e}")
            return False

    # Возвращает список всех таблиц в БД через SQLAlchemy inspector.
    def get_all_tables(self) -> List[str]:
        try:
            inspector = inspect(self.engine)
            return inspector.get_table_names()
        except:
            return []

    # Считает количество строк в таблице users.
    def get_users_count(self) -> int:
        try:
            if not self._table_exists('users'):
                return 0
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM users"))
                return result.scalar() or 0
        except:
            return 0

    # Считает количество строк в таблице dishes.
    def get_dishes_count(self) -> int:
        try:
            if not self._table_exists('dishes'):
                return 0
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM dishes"))
                return result.scalar() or 0
        except:
            return 0

    # Считает количество строк в таблице bar_items.
    def get_bar_items_count(self) -> int:
        try:
            if not self._table_exists('bar_items'):
                return 0
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM bar_items"))
                return result.scalar() or 0
        except:
            return 0


# Создаёт пользователя в таблице users: при необходимости создаёт её,
# вставляет login/пароль/дату рождения и возвращает id, login, birth_date.
def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Создаёт нового пользователя с email, паролем и опциональной датой рождения
    """
    try:
        # Проверяем, существует ли таблица users
        if not self._table_exists('users'):
            with self.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        login TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        birth_date DATE,
                        diet_type TEXT,
                        meal_style TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.commit()

        with self.engine.connect() as conn:
            # Вставляем нового пользователя
            result = conn.execute(
                text("""
                    INSERT INTO users (login, password_hash, birth_date)
                    VALUES (:email, :password_hash, :birth_date)
                    RETURNING id, login, birth_date
                """),
                {
                    "email": user_data.get('email'),
                    "password_hash": user_data.get('password_hash'),
                    "birth_date": user_data.get('birth_date')
                }
            )
            row = result.fetchone()
            result.close()
            conn.commit()
            return dict(row._mapping)
    except Exception as e:
        print(f"Ошибка при создании пользователя: {e}")
        raise


# Ищет пользователя по email (по колонке login). Возвращает id, login,
# password_hash, birth_date или None.
def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
    """
    Получает пользователя по email (логину)
    """
    try:
        if not self._table_exists('users'):
            return None
        with self.engine.connect() as conn:
            result = conn.execute(
                text("SELECT id, login, password_hash, birth_date FROM users WHERE login = :email"),
                {"email": email}
            )
            row = result.fetchone()
            result.close()
            return dict(row._mapping) if row else None
    except Exception as e:
        print(f"Ошибка при получении пользователя: {e}")
        return None


# Обновляет дату рождения пользователя по id. Возвращает True при успехе.
def update_user_birth_date(self, user_id: int, birth_date: str) -> bool:
    """
    Обновляет дату рождения пользователя
    """
    try:
        if not self._table_exists('users'):
            return False
        with self.engine.connect() as conn:
            result = conn.execute(
                text("UPDATE users SET birth_date = :birth_date WHERE id = :id"),
                {"id": user_id, "birth_date": birth_date}
            )
            conn.commit()
            return result.rowcount > 0
    except Exception as e:
        print(f"Ошибка при обновлении даты рождения: {e}")
        return False


# Готовый экземпляр для использования в других модулях: from database import db
db = Database()
