import hashlib

# Проверяет, соответствует ли пароль сохранённому хешу формата "hash:salt"
def _verify_password(password: str, stored_hash: str) -> bool:
        # Пустые значения не проверяем — сразу False
        if not password or not stored_hash:
            return False
        try:
            # Разделяем строку на сам хеш и соль (по первому двоеточию)
            stored_hash, salt = stored_hash.split(":", 1)
            # Считаем SHA-256 от "пароль+соль" и переводим в hex
            password_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
            # Печатаем вычисленный хеш (для отладки)
            print(password_hash)
            # Сравниваем вычисленный хеш с сохранённым
            return password_hash == stored_hash
        except:
            # Если строка битая/без соли — считаем пароль неверным
            return False

# Проверяем пароль "cook_125552" против указанного хеша и соли
a = _verify_password("cook_125552", "7fd9cecd4559402d678105f6792cc2acfe2f7f992e1b15965b521f05f890def5:661c0f81ab810c4a7fcab6874a0e2622")

# Печатаем результат проверки (True/False)
print(a)
