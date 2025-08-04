from fastapi import Header, HTTPException, Depends
from typing import Optional
from .firebase_client import verify_firebase_token

def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header format")
    token = authorization.split(" ", 1)[1]
    try:
        decoded = verify_firebase_token(token)
        return decoded  # contiene uid, email, etc.
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
