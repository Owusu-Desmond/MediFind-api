from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
import models, schemas, deps
import math

router = APIRouter(
    prefix="/api/medicines",
    tags=["Medicines"],
)

@router.post("/", response_model=schemas.MedicineResponse)
def create_medicine(medicine: schemas.MedicineCreate, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_active_user)):
    # Any active user can potentially add a medicine to the catalog, or restrict to Admin/Pharmacist
    if current_user.role not in [models.UserRole.Admin, models.UserRole.Pharmacist]:
        raise HTTPException(status_code=403, detail="Not authorized to add medicines")
        
    new_medicine = models.Medicine(**medicine.model_dump())
    db.add(new_medicine)
    db.commit()
    db.refresh(new_medicine)
    return new_medicine

@router.get("/", response_model=List[schemas.MedicineResponse])
def get_medicines(skip: int = 0, limit: int = 100, db: Session = Depends(deps.get_db)):
    return db.query(models.Medicine).offset(skip).limit(limit).all()

@router.get("/search")
def search_medicines(q: str, lat: Optional[float] = None, lng: Optional[float] = None, db: Session = Depends(deps.get_db)):
    medicines = db.query(models.Medicine).filter(
        or_(
            models.Medicine.name.ilike(f"%{q}%"),
            models.Medicine.generic_name.ilike(f"%{q}%")
        )
    ).all()
    
    results = []
    for med in medicines:
        # Get inventory for this medicine
        inventories = db.query(models.Inventory).filter(models.Inventory.medicine_id == med.id).all()
        for inv in inventories:
            pharmacy = inv.pharmacy
            # calculate distance if lat lng provided
            distance = None
            if lat is not None and lng is not None and pharmacy.lat and pharmacy.lng:
                R = 6371.0
                dlat = math.radians(pharmacy.lat - lat)
                dlng = math.radians(pharmacy.lng - lng)
                a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(pharmacy.lat)) * math.sin(dlng / 2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                distance = R * c
            
            results.append({
                "medicine": med,
                "pharmacy": pharmacy,
                "inventory": inv,
                "distance_km": distance
            })
            
    # sort by distance if available
    if lat is not None and lng is not None:
        results.sort(key=lambda x: x["distance_km"] if x["distance_km"] is not None else float('inf'))
        
    return results

@router.post("/{medicine_id}/inventory", response_model=schemas.InventoryResponse)
def add_inventory(medicine_id: int, inventory: schemas.InventoryCreate, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_pharmacist)):
    # Verify pharmacist owns pharmacy
    staff = db.query(models.PharmacyStaff).filter(
        models.PharmacyStaff.user_id == current_user.id,
        models.PharmacyStaff.pharmacy_id == inventory.pharmacy_id
    ).first()
    if not staff and current_user.role != models.UserRole.Admin:
        raise HTTPException(status_code=403, detail="Not authorized for this pharmacy")
        
    new_inv = models.Inventory(**inventory.model_dump())
    db.add(new_inv)
    db.commit()
    db.refresh(new_inv)
    return new_inv
