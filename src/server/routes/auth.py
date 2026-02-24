from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.orm import Session
from ..core.database import get_db
from ..core.models import User, AuditLog
from ..auth import (
    get_password_hash, 
    verify_password, 
    create_access_token, 
    decode_access_token, 
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from pydantic import BaseModel
from datetime import timedelta
import logging
import os

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("AuthRoutes")

class LoginRequest(BaseModel):
    username: str
    password: str

class BootstrapRequest(BaseModel):
    username: str
    password: str
    display_name: str = None

@router.get("/initialized")
def is_initialized(db: Session = Depends(get_db)):
    """Check if any user exists in the system."""
    user_count = db.query(User).count()
    return {"initialized": user_count > 0}

@router.post("/login")
@router.post("/login/")
def login(request: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role, "uid": user.id}, expires_delta=access_token_expires
    )
    
    secure_cookie = os.getenv("AOSD_COOKIE_SECURE", "false").lower() in ("1", "true", "yes", "on")

    # Set httpOnly cookie
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    
    # Audit Login
    audit = AuditLog(user_id=user.id, username=user.username, action="login", target="portal")
    db.add(audit)
    db.commit()

    return {"message": "Login successful"}

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out"}

@router.post("/bootstrap")
def bootstrap(request: BootstrapRequest, db: Session = Depends(get_db)):
    # Strict Check: Only allowed if NO users exist
    user_count = db.query(User).count()
    if user_count > 0:
        raise HTTPException(status_code=410, detail="System already initialized. Use normal login.")
    
    hashed_password = get_password_hash(request.password)
    new_user = User(
        username=request.username,
        display_name=request.display_name or request.username,
        password_hash=hashed_password,
        role="admin"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    logger.info(f"System Bootstrap completed. Admin '{new_user.username}' created.")
    return {"message": "System initialized successfully. Please login."}

@router.get("/me")
def read_users_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "display_name": current_user.display_name,
        "role": current_user.role,
        "created_at": current_user.created_at
    }
