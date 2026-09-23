import bcrypt

BCRYPT_ROUNDS = 12
MAX_PASSWORD_BYTES = 72

def hash_password(password, rounds=BCRYPT_ROUNDS):
    if not password:
        raise ValueError

    encoded_password = password.encode("utf-8")

    if len(encoded_password) > MAX_PASSWORD_BYTES:
        raise ValueError

    salt = bcrypt.gensalt(rounds=rounds)

    hashed_password = bcrypt.hashpw(encoded_password, salt).decode()

    return hashed_password
