import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import models, schemas, deps, auth
import math

router = APIRouter(
    prefix="/api/pharmacies",
    tags=["Pharmacies"],
)

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads", "certificates")

@router.post("/upload-certificate")
async def upload_certificate(
    file: UploadFile = File(...),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Allowed: PDF, PNG, JPG, JPEG")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    unique_filename = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)

    relative_url = f"/uploads/certificates/{unique_filename}"
    return {"url": relative_url, "filename": file.filename}

@router.post("/", response_model=schemas.PharmacyResponse)
def create_pharmacy(pharmacy: schemas.PharmacyCreate, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_active_user)):
    # Simple check: maybe only allow creation if it doesn't exist
    existing = db.query(models.Pharmacy).filter(models.Pharmacy.license_number == pharmacy.license_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Pharmacy with this license already exists")
    
    new_pharmacy = models.Pharmacy(**pharmacy.model_dump())
    db.add(new_pharmacy)
    db.commit()
    db.refresh(new_pharmacy)
    return new_pharmacy

@router.get("/", response_model=List[schemas.PharmacyResponse])
def get_pharmacies(skip: int = 0, limit: int = 100, db: Session = Depends(deps.get_db)):
    return db.query(models.Pharmacy).offset(skip).limit(limit).all()

@router.get("/nearby", response_model=List[schemas.PharmacyResponse])
def get_nearby_pharmacies(lat: float, lng: float, radius_km: float = 10.0, db: Session = Depends(deps.get_db)):
    # A simple mock distance filter in python since SQLite/Postgres without PostGIS is harder
    # For a real app, use PostGIS or Haversine formula in SQL
    all_pharmacies = db.query(models.Pharmacy).filter(models.Pharmacy.status == models.PharmacyStatus.Approved).all()
    nearby = []
    for p in all_pharmacies:
        if p.lat and p.lng:
            # Haversine distance
            R = 6371.0 # Earth radius in kilometers
            dlat = math.radians(p.lat - lat)
            dlng = math.radians(p.lng - lng)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(p.lat)) * math.sin(dlng / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance = R * c
            if distance <= radius_km:
                nearby.append(p)
    return nearby

@router.patch("/{pharmacy_id}/status", response_model=schemas.PharmacyResponse)
def update_pharmacy_status(pharmacy_id: int, status: str, db: Session = Depends(deps.get_db), current_admin: models.User = Depends(deps.get_current_admin)):
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    try:
        pharmacy.status = models.PharmacyStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    # If approved, we should create a user account for the pharmacist if it doesn't exist
    if pharmacy.status == models.PharmacyStatus.Approved and pharmacy.email:
        user = db.query(models.User).filter(models.User.email == pharmacy.email).first()
        if not user:
            # Create a default password for the pharmacist
            default_password = auth.get_password_hash("pharmacist123")
            new_user = models.User(
                email=pharmacy.email,
                name=pharmacy.pharmacist_name or f"{pharmacy.name} Admin",
                hashed_password=default_password,
                role=models.UserRole.Pharmacist
            )
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            
            # Link staff
            staff = models.PharmacyStaff(user_id=new_user.id, pharmacy_id=pharmacy.id)
            db.add(staff)

    db.commit()
    db.refresh(pharmacy)
    return pharmacy
