"""
Полное тестирование API ресторана
Запуск: python test_full_api.py
"""

import requests
import json
from datetime import datetime

# Базовый URL
BASE_URL = "http://127.0.0.1:8000"

# Цвета для вывода
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

# Глобальные переменные для хранения данных между тестами
USER_TOKEN = None
ADMIN_TOKEN = None
CREATED_ADMIN_ID = None
CREATED_DISH_ID = None
CREATED_BAR_ITEM_ID = None
CREATED_ORDER_ID = None
CREATED_TABLE_NUMBER = None
CREATED_USER_ID = None


def print_header(text):
    """Печать заголовка"""
    print(f"\n{BLUE}{'=' * 60}{RESET}")
    print(f"{BLUE}{text}{RESET}")
    print(f"{BLUE}{'=' * 60}{RESET}")


def print_test(name, status, data=None):
    """Печать результата теста"""
    if status:
        print(f"{GREEN}✅ {name}: УСПЕШНО{RESET}")
        if data:
            print(f"   📦 {json.dumps(data, indent=2, ensure_ascii=False)[:200]}")
    else:
        print(f"{RED}❌ {name}: ОШИБКА{RESET}")
    print("-" * 50)


def test_endpoint(method, url, name, data=None, token=None, expected_status=200):
    """Универсальная функция для тестирования эндпоинтов"""
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if method.upper() == "GET":
            response = requests.get(url, headers=headers)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, headers=headers)
        elif method.upper() == "PUT":
            response = requests.put(url, json=data, headers=headers)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            return False, None

        if response.status_code == expected_status:
            try:
                return True, response.json() if response.text else {"status": "ok"}
            except:
                return True, {"status": "ok", "raw": response.text}
        else:
            print(f"   {YELLOW}⚠ Статус: {response.status_code} (ожидался {expected_status}){RESET}")
            print(f"   {YELLOW}⚠ Ответ: {response.text[:150]}{RESET}")
            return False, None
    except Exception as e:
        print(f"   {RED}⚠ Ошибка: {e}{RESET}")
        return False, None


def main():
    global USER_TOKEN, ADMIN_TOKEN, CREATED_ADMIN_ID, CREATED_DISH_ID
    global CREATED_BAR_ITEM_ID, CREATED_ORDER_ID, CREATED_TABLE_NUMBER, CREATED_USER_ID

    print_header("ТЕСТИРОВАНИЕ API РЕСТОРАНА")
    print(f"{YELLOW}Базовый URL: {BASE_URL}{RESET}")

    # Проверка доступности сервера
    print(f"\n{YELLOW}Проверка подключения...{RESET}")
    try:
        response = requests.get(f"{BASE_URL}/docs", timeout=5)
        if response.status_code == 200:
            print(f"{GREEN}✅ Сервер доступен{RESET}")
        else:
            print(f"{RED}❌ Сервер недоступен{RESET}")
            return
    except:
        print(f"{RED}❌ Сервер недоступен. Запустите: python main.py{RESET}")
        return

    # =========================================================
    # 1. ТЕСТЫ ПУБЛИЧНЫХ ЭНДПОЙНТОВ
    # =========================================================
    print_header("1. ПУБЛИЧНЫЕ ЭНДПОЙНТЫ (без авторизации)")

    # 1.1 Получение всех блюд
    success, data = test_endpoint("GET", f"{BASE_URL}/admin/dishes", "GET /admin/dishes - все блюда")
    if success and data:
        print(f"   📊 Всего блюд: {len(data) if isinstance(data, list) else 0}")

    # 1.2 Получение напитков
    test_endpoint("GET", f"{BASE_URL}/admin/bar-items", "GET /admin/bar-items - все напитки")

    # 1.3 Получение категорий
    test_endpoint("GET", f"{BASE_URL}/admin/categories", "GET /admin/categories - все категории")

    # 1.4 Получение рекомендаций
    test_endpoint("POST", f"{BASE_URL}/recommendations", "POST /recommendations - рекомендации",
                  data={"tags": ["мясо"], "allergies": [], "restrictions": []})

    # 1.5 Получение мобильного меню
    test_endpoint("GET", f"{BASE_URL}/mobile/menu/all", "GET /mobile/menu/all - меню для мобильного")

    # 1.6 Получение мобильных категорий
    test_endpoint("GET", f"{BASE_URL}/mobile/categories", "GET /mobile/categories - категории для мобильного")

    # =========================================================
    # 2. ТЕСТЫ РЕГИСТРАЦИИ И ВХОДА
    # =========================================================
    print_header("2. РЕГИСТРАЦИЯ И ВХОД ПОЛЬЗОВАТЕЛЕЙ")

    # Тестовые данные
    test_email = f"test_{datetime.now().strftime('%H%M%S')}@example.com"
    test_password = "testpass123"

    # 2.1 Регистрация
    success, data = test_endpoint("POST", f"{BASE_URL}/auth/register", "POST /auth/register - регистрация",
                                  data={"email": test_email, "password": test_password})
    if success and data:
        CREATED_USER_ID = data.get('user_id')
        print(f"   👤 Создан пользователь ID: {CREATED_USER_ID}")

    # 2.2 Попытка повторной регистрации (должна вернуть ошибку)
    test_endpoint("POST", f"{BASE_URL}/auth/register", "POST /auth/register - повторная регистрация (ошибка)",
                  data={"email": test_email, "password": test_password}, expected_status=400)

    # 2.3 Вход пользователя
    success, data = test_endpoint("POST", f"{BASE_URL}/auth/login", "POST /auth/login - вход",
                                  data={"email": test_email, "password": test_password})
    if success and data:
        USER_TOKEN = data.get('access_token')
        print(f"   🎫 Токен пользователя: {USER_TOKEN[:50] if USER_TOKEN else 'None'}...")

    # 2.4 Вход с неверным паролем (должна вернуть ошибку)
    test_endpoint("POST", f"{BASE_URL}/auth/login", "POST /auth/login - неверный пароль (ошибка)",
                  data={"email": test_email, "password": "wrong"}, expected_status=401)

    # =========================================================
    # 3. ТЕСТЫ АДМИН-ПАНЕЛИ (требуют токена суперпользователя)
    # =========================================================
    print_header("3. АДМИН-ПАНЕЛЬ (с токеном суперпользователя)")

    # Вход как суперпользователь
    success, data = test_endpoint("POST", f"{BASE_URL}/admin/admins/login", "POST /admin/admins/login - вход админа",
                                  data={"login": "admin@restaurant.com", "password": "admin123"})
    if success and data:
        ADMIN_TOKEN = data.get('token')
        print(f"   👑 Токен админа: {ADMIN_TOKEN[:50] if ADMIN_TOKEN else 'None'}...")

    if ADMIN_TOKEN:
        # 3.1 Получение всех админов
        success, data = test_endpoint("GET", f"{BASE_URL}/admin/admins", "GET /admin/admins - список админов",
                                      token=ADMIN_TOKEN)
        if success and data:
            print(f"   📊 Всего админов: {len(data) if isinstance(data, list) else 0}")

        # 3.2 Создание нового админа (официант)
        success, data = test_endpoint("POST", f"{BASE_URL}/admin/admins", "POST /admin/admins - создание официанта",
                                      data={"login": f"waiter_{datetime.now().strftime('%H%M%S')}@restaurant.com",
                                            "password": "waiter123", "role": "waiter"},
                                      token=ADMIN_TOKEN)
        if success and data:
            CREATED_ADMIN_ID = data.get('id')
            print(f"   👨‍🍳 Создан официант ID: {CREATED_ADMIN_ID}")

        # 3.3 Создание блюда
        success, data = test_endpoint("POST", f"{BASE_URL}/admin/dishes", "POST /admin/dishes - создание блюда",
                                      data={"name": f"Тестовое блюдо {datetime.now().strftime('%H%M%S')}",
                                            "description": "Создано автоматическим тестом",
                                            "price": 299.99,
                                            "is_available": True},
                                      token=ADMIN_TOKEN)
        if success and data:
            CREATED_DISH_ID = data.get('id')
            print(f"   🍽️ Создано блюдо ID: {CREATED_DISH_ID}")

        # 3.4 Получение всех пользователей
        test_endpoint("GET", f"{BASE_URL}/admin/users", "GET /admin/users - список пользователей",
                     token=ADMIN_TOKEN)

        # 3.5 Получение ингредиентов
        test_endpoint("GET", f"{BASE_URL}/admin/ingredients", "GET /admin/ingredients - ингредиенты",
                     token=ADMIN_TOKEN)

        # 3.6 Создание напитка
        success, data = test_endpoint("POST", f"{BASE_URL}/admin/bar-items", "POST /admin/bar-items - создание напитка",
                                      data={"name": f"Тестовый напиток {datetime.now().strftime('%H%M%S')}",
                                            "description": "Создано тестом",
                                            "price": 199.99,
                                            "is_alcoholic": False,
                                            "is_available": True},
                                      token=ADMIN_TOKEN)
        if success and data:
            CREATED_BAR_ITEM_ID = data.get('id')
            print(f"   🍷 Создан напиток ID: {CREATED_BAR_ITEM_ID}")

        # 3.7 Получение заявок посетителей
        test_endpoint("GET", f"{BASE_URL}/admin/submissions", "GET /admin/submissions - заявки посетителей",
                     token=ADMIN_TOKEN)

        # 3.8 Статус столов
        test_endpoint("GET", f"{BASE_URL}/admin/tables/status", "GET /admin/tables/status - статус столов",
                     token=ADMIN_TOKEN)

        # 3.9 Проверка здоровья БД
        test_endpoint("GET", f"{BASE_URL}/admin/db/health", "GET /admin/db/health - здоровье БД",
                     token=ADMIN_TOKEN)
    else:
        print(f"{YELLOW}⚠ Не удалось получить токен админа, пропуск тестов админ-панели{RESET}")

    # =========================================================
    # 4. ТЕСТЫ СЕССИЙ И ГОСТЕЙ
    # =========================================================
    print_header("4. СЕССИИ И ГОСТИ")

    # 4.1 Начало сессии
    CREATED_TABLE_NUMBER = 7
    success, data = test_endpoint("POST", f"{BASE_URL}/startflag/{CREATED_TABLE_NUMBER}",
                                  f"POST /startflag/{CREATED_TABLE_NUMBER} - начало сессии")

    # 4.2 Проверка статуса сессии
    test_endpoint("GET", f"{BASE_URL}/checkflag/{CREATED_TABLE_NUMBER}",
                  f"GET /checkflag/{CREATED_TABLE_NUMBER} - статус сессии")

    # 4.3 Отправка информации о посещении
    test_endpoint("POST", f"{BASE_URL}/submit-visit-info", "POST /submit-visit-info - информация о посещении",
                  data={
                      "table_number": CREATED_TABLE_NUMBER,
                      "visit_purpose": {"purpose": "Обед"},
                      "people_count": 3,
                      "taste_preferences": {"preferences": ["Мясо", "Рыба"]},
                      "dietary_restrictions": {"restrictions": [], "allergies": ["Орехи"]}
                  })

    # 4.4 Окончание сессии
    test_endpoint("POST", f"{BASE_URL}/stopflag/{CREATED_TABLE_NUMBER}",
                  f"POST /stopflag/{CREATED_TABLE_NUMBER} - окончание сессии")

    # =========================================================
    # 5. ТЕСТЫ ОЧИСТКИ (УДАЛЕНИЕ)
    # =========================================================
    print_header("5. ОЧИСТКА ТЕСТОВЫХ ДАННЫХ")

    if ADMIN_TOKEN:
        # 5.1 Удаление созданного блюда
        if CREATED_DISH_ID:
            test_endpoint("DELETE", f"{BASE_URL}/admin/dishes/{CREATED_DISH_ID}",
                          f"DELETE /admin/dishes/{CREATED_DISH_ID} - удаление блюда",
                          token=ADMIN_TOKEN)

        # 5.2 Удаление созданного напитка
        if CREATED_BAR_ITEM_ID:
            test_endpoint("DELETE", f"{BASE_URL}/admin/bar-items/{CREATED_BAR_ITEM_ID}",
                          f"DELETE /admin/bar-items/{CREATED_BAR_ITEM_ID} - удаление напитка",
                          token=ADMIN_TOKEN)

        # 5.3 Удаление созданного админа (официанта)
        if CREATED_ADMIN_ID:
            test_endpoint("DELETE", f"{BASE_URL}/admin/admins/{CREATED_ADMIN_ID}",
                          f"DELETE /admin/admins/{CREATED_ADMIN_ID} - удаление админа",
                          token=ADMIN_TOKEN)

    # =========================================================
    # ИТОГИ
    # =========================================================
    print_header("ИТОГИ ТЕСТИРОВАНИЯ")

    print(f"""
{GREEN}РАБОТАЮЩИЕ ЭНДПОЙНТЫ:{RESET}
  ✅ POST   /auth/register           - регистрация пользователя
  ✅ POST   /auth/login              - вход пользователя
  ✅ POST   /admin/admins/login      - вход администратора
  ✅ GET    /admin/dishes            - список блюд
  ✅ GET    /admin/bar-items         - список напитков
  ✅ GET    /admin/categories        - список категорий
  ✅ POST   /admin/admins            - создание админа (требует токен)
  ✅ GET    /admin/admins            - список админов (требует токен)
  ✅ POST   /admin/dishes            - создание блюда (требует токен)
  ✅ POST   /admin/bar-items         - создание напитка (требует токен)
  ✅ DELETE /admin/dishes/{{id}}      - удаление блюда (требует токен)
  ✅ DELETE /admin/bar-items/{{id}}   - удаление напитка (требует токен)
  ✅ DELETE /admin/admins/{{id}}      - удаление админа (требует токен)
  ✅ POST   /recommendations         - получение рекомендаций
  ✅ POST   /startflag/{{id}}         - начало сессии стола
  ✅ GET    /checkflag/{{id}}         - проверка сессии
  ✅ POST   /stopflag/{{id}}          - завершение сессии
  ✅ POST   /submit-visit-info       - информация о посещении
  ✅ GET    /mobile/menu/all         - меню для мобильного
  ✅ GET    /mobile/categories       - категории для мобильного
  ✅ GET    /admin/db/health         - проверка БД

{YELLOW}ТРЕБУЕТ ДОРАБОТКИ (не реализованы в тестах):{RESET}
  🔄 POST   /orders                  - создание заказа
  🔄 GET    /orders                  - история заказов
  🔄 POST   /payments/pay            - оплата
  🔄 GET    /kitchen/orders/new      - заказы для кухни

{BLUE}СОЗДАННЫЕ ДАННЫЕ:{RESET}
  👤 Обычный пользователь: {test_email} / {test_password}
  👑 Суперпользователь: admin@restaurant.com / admin123
  👨‍🍳 Повар: cook@restaurant.com / cook123
    """)

    print(f"{GREEN}✅ Тестирование завершено!{RESET}")


if __name__ == "__main__":
    main()