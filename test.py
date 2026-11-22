import hashlib

def _verify_password(password: str, stored_hash: str) -> bool:
        if not password or not stored_hash:
            return False
        try:
            stored_hash, salt = stored_hash.split(":", 1)
            password_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
            print(password_hash)
            return password_hash == stored_hash
        except:
            return False

a = _verify_password("cook_125552", "7fd9cecd4559402d678105f6792cc2acfe2f7f992e1b15965b521f05f890def5:661c0f81ab810c4a7fcab6874a0e2622")

print(a)