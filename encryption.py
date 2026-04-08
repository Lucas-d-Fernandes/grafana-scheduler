from cryptography.fernet import Fernet, InvalidToken
import os

from paths import data_path


SECRET_KEY_FILE = data_path("secret.key")

def generate_key():
    if not os.path.exists(SECRET_KEY_FILE):
        key = Fernet.generate_key()
        with open(SECRET_KEY_FILE, "wb") as key_file:
            key_file.write(key)
    else:
        with open(SECRET_KEY_FILE, "rb") as key_file:
            key = key_file.read()
    return key

SECRET_KEY = generate_key()
cipher_suite = Fernet(SECRET_KEY)

def encrypt_password(password):
    if not password:
        return ""
    return cipher_suite.encrypt(password.encode()).decode()

def decrypt_password(encrypted_password):
    if not encrypted_password:
        return ""
    try:
        return cipher_suite.decrypt(encrypted_password.encode()).decode()
    except (InvalidToken, Exception):
        return ""
