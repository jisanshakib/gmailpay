"""
auth.py — JWT token creation/verification + Bcrypt password hashing.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

import config

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=config.ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, config.SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


# --- FastAPI Dependencies ---

def get_current_admin(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Returns {'id': int, 'username': str, 'role': str}."""
    p = verify_token(creds.credentials)
    if not p.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return {"id": int(p["sub"]), "username": p.get("username"), "role": p.get("role")}

def require_owner(admin: dict = Depends(get_current_admin)) -> dict:
    if admin.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Owner privileges required")
    return admin
