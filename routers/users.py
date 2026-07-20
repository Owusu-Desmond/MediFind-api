from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import models, schemas, deps

router = APIRouter(
    prefix="/api/users",
    tags=["Users"],
)

@router.get("/", response_model=List[schemas.UserResponse])
def get_users(skip: int = 0, limit: int = 100, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_admin)):
    users = db.query(models.User).offset(skip).limit(limit).all()
    return users

@router.patch("/{user_id}/status", response_model=schemas.UserResponse)
def update_user_status(user_id: int, status: str, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        user.status = models.UserStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")
        
    db.commit()
    db.refresh(user)
    return user
