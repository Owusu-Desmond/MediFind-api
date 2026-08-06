from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import models, schemas, deps, auth

router = APIRouter(
    prefix="/api/users",
    tags=["Users"],
)

@router.get("/", response_model=List[schemas.UserResponse])
def get_users(skip: int = 0, limit: int = 100, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_admin)):
    users = db.query(models.User).offset(skip).limit(limit).all()
    return users

@router.post("/", response_model=schemas.UserResponse)
def create_user(
    user_in: schemas.UserCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    existing = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    target_role = models.UserRole.Patient
    if user_in.role:
        try:
            target_role = models.UserRole(user_in.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role '{user_in.role}'")

    hashed_password = auth.get_password_hash(user_in.password)
    new_user = models.User(
        email=user_in.email,
        name=user_in.name,
        hashed_password=hashed_password,
        phone=user_in.phone,
        location=user_in.location,
        age=user_in.age,
        role=target_role,
        status=models.UserStatus.Active
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.put("/{user_id}", response_model=schemas.UserResponse)
def update_user(
    user_id: int,
    user_in: schemas.UserUpdate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user_in.email and user_in.email != user.email:
        existing = db.query(models.User).filter(models.User.email == user_in.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="User with this email already exists")
        user.email = user_in.email

    if user_in.name is not None:
        user.name = user_in.name
    if user_in.phone is not None:
        user.phone = user_in.phone
    if user_in.location is not None:
        user.location = user_in.location
    if user_in.age is not None:
        user.age = user_in.age
    if user_in.role is not None:
        try:
            user.role = models.UserRole(user_in.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role '{user_in.role}'")
    if user_in.status is not None:
        try:
            user.status = models.UserStatus(user_in.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status '{user_in.status}'")

    db.commit()
    db.refresh(user)
    return user

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

@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully"}
