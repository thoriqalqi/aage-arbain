"""Login dashboard: JWT + dua peran (admin, staf). Password di-hash PBKDF2-SHA256."""

import base64
import hashlib
import hmac
import os
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import clock
from .config import get_settings
from .db import get_db
from .models import User

settings = get_settings()
_bearer = HTTPBearer(auto_error=False)
_ITER = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(it))
    return hmac.compare_digest(dk, base64.b64decode(hash_b64))


def create_token(user: User) -> str:
    payload = {"sub": str(user.id), "role": user.role, "nama": user.nama,
               "exp": clock.now() + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Silakan login terlebih dahulu")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesi tidak valid, silakan login ulang") from None
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Pengguna tidak ditemukan")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Hanya admin yang boleh melakukan aksi ini")
    return user


# Izin sementara dengan hak paling sempit, sampai CV Arba'in menetapkan kebijakannya. Marketing tidak membuka layar Leads.
IZIN = {
    "leads.lihat": {"admin", "staf"},
    "leads.ubah": {"admin", "staf"},
    "leads.kontak": {"admin", "staf"},
    "leads.ekspor": {"admin"},
}


def require_izin(izin: str):
    peran = IZIN[izin]

    def periksa(user: User = Depends(current_user)) -> User:
        if user.role not in peran:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Peran Anda tidak memiliki izin {izin}")
        return user

    return periksa


def mask_phone(number: str | None, user: User) -> str | None:
    """UU PDP: nomor dimasking untuk peran staf."""
    if not number or user.role == "admin":
        return number
    return number[:4] + "•" * max(0, len(number) - 7) + number[-3:]
