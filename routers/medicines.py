from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func
from typing import List, Optional, Dict, Any
import models, schemas, deps
import math
from datetime import datetime, timezone

router = APIRouter(
    prefix="/api/medicines",
    tags=["Medicines & Catalogue"],
)

@router.get("/categories", response_model=List[str])
def get_medicine_categories(db: Session = Depends(deps.get_db)):
    """Retrieve distinct medicine categories for filtering."""
    categories = db.query(models.Medicine.category).filter(
        models.Medicine.category.isnot(None),
        models.Medicine.category != ""
    ).distinct().all()
    return sorted([c[0] for c in categories if c[0]])

@router.get("/dosage-forms", response_model=List[str])
def get_medicine_dosage_forms(db: Session = Depends(deps.get_db)):
    """Retrieve distinct dosage forms for catalogue filtering."""
    forms = db.query(models.Medicine.dosage_form).filter(
        models.Medicine.dosage_form.isnot(None),
        models.Medicine.dosage_form != ""
    ).distinct().all()
    default_forms = ["Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Inhaler", "Ointment", "Cream", "Eye Drops", "Ear Drops", "Suppository"]
    existing = set([f[0] for f in forms if f[0]])
    return sorted(list(existing.union(default_forms)))

@router.get("/", response_model=List[schemas.MedicineResponse])
def get_medicines(
    q: Optional[str] = None,
    category: Optional[str] = None,
    dosage_form: Optional[str] = None,
    requires_prescription: Optional[bool] = None,
    is_active: Optional[bool] = True,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(deps.get_db)
):
    """
    Browse the Central Medicine Catalogue with multi-parameter search, filtering, and pagination.
    """
    query = db.query(models.Medicine)
    
    if is_active is not None:
        query = query.filter(models.Medicine.is_active == is_active)
        
    if q and q.strip():
        search_term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.Medicine.name.ilike(search_term),
                models.Medicine.generic_name.ilike(search_term),
                models.Medicine.strength.ilike(search_term),
                models.Medicine.dosage.ilike(search_term),
                models.Medicine.category.ilike(search_term),
                models.Medicine.manufacturer.ilike(search_term),
                models.Medicine.tags.ilike(search_term)
            )
        )
        
    if category and category != "All":
        query = query.filter(models.Medicine.category == category)
        
    if dosage_form and dosage_form != "All":
        query = query.filter(models.Medicine.dosage_form == dosage_form)
        
    if requires_prescription is not None:
        query = query.filter(models.Medicine.requires_prescription == requires_prescription)
        
    medicines = query.order_by(models.Medicine.name.asc()).offset(skip).limit(limit).all()
    
    # Enrich with active pharmacies count
    results = []
    for med in medicines:
        active_count = db.query(models.Inventory).join(models.Pharmacy).filter(
            models.Inventory.medicine_id == med.id,
            models.Inventory.is_available == True,
            models.Inventory.stock_quantity > 0,
            models.Pharmacy.status == models.PharmacyStatus.Approved
        ).count()
        med.active_pharmacies_count = active_count
        results.append(med)
        
    return results

@router.get("/search")
def search_medicines(
    q: Optional[str] = "",
    category: Optional[str] = None,
    dosage_form: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    db: Session = Depends(deps.get_db)
):
    """
    Patient Medicine Search: Identifies matching active catalogue medicines and returns
    approved pharmacies stocking the medicine with prices, availability, and distances.
    """
    # 1. Query active inventory joined with medicine and pharmacy
    inv_query = db.query(models.Inventory).options(
        joinedload(models.Inventory.medicine),
        joinedload(models.Inventory.pharmacy)
    ).join(models.Medicine).join(models.Pharmacy).filter(
        models.Medicine.is_active == True,
        models.Pharmacy.status == models.PharmacyStatus.Approved
    )
    
    if q and q.strip():
        term = f"%{q.strip()}%"
        inv_query = inv_query.filter(
            or_(
                models.Medicine.name.ilike(term),
                models.Medicine.generic_name.ilike(term),
                models.Medicine.strength.ilike(term),
                models.Medicine.dosage.ilike(term),
                models.Medicine.category.ilike(term),
                models.Medicine.manufacturer.ilike(term),
                models.Medicine.tags.ilike(term),
                models.Pharmacy.name.ilike(term)
            )
        )
        
    if category and category != "All":
        inv_query = inv_query.filter(models.Medicine.category == category)
        
    if dosage_form and dosage_form != "All":
        inv_query = inv_query.filter(models.Medicine.dosage_form == dosage_form)
        
    inventories = inv_query.all()
    
    results = []
    for inv in inventories:
        med = inv.medicine
        pharma = inv.pharmacy
        if not med or not pharma:
            continue
            
        # Compute GPS distance if coordinates available
        distance = None
        if lat is not None and lng is not None and pharma.lat and pharma.lng:
            R = 6371.0
            dlat = math.radians(pharma.lat - lat)
            dlng = math.radians(pharma.lng - lng)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(pharma.lat)) * math.sin(dlng / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance = round(R * c, 2)
            
        # Clean serialized pharmacy response (excluding sensitive payment info)
        clean_pharmacy = {
            "id": pharma.id,
            "name": pharma.name,
            "location": pharma.location,
            "license_number": pharma.license_number,
            "pharmacist_name": pharma.pharmacist_name,
            "phone": pharma.phone,
            "email": pharma.email,
            "status": pharma.status.value if hasattr(pharma.status, "value") else str(pharma.status),
            "delivery_offered": pharma.delivery_offered,
            "opening_hours": pharma.opening_hours,
            "gps_address": pharma.gps_address,
            "lat": pharma.lat,
            "lng": pharma.lng,
            "verified": pharma.verified,
        }
        
        results.append({
            "medicine": med,
            "pharmacy": clean_pharmacy,
            "inventory": {
                "id": inv.id,
                "price": inv.price,
                "stock_quantity": inv.stock_quantity,
                "batch_number": inv.batch_number,
                "expiry_date": inv.expiry_date.isoformat() if inv.expiry_date else None,
                "status": inv.status,
                "is_available": inv.is_available,
            },
            "distance_km": distance
        })
        
    if lat is not None and lng is not None:
        results.sort(key=lambda x: x["distance_km"] if x["distance_km"] is not None else float('inf'))
        
    return results

@router.get("/admin/duplicates")
def get_duplicate_candidates(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    """
    Administrator endpoint: Scan catalogue for potential duplicate entries.
    """
    medicines = db.query(models.Medicine).all()
    duplicates_groups: Dict[str, List[Any]] = {}
    
    for m in medicines:
        norm_key = f"{m.name.strip().lower()}__{(m.strength or m.dosage or '').strip().lower()}__{(m.dosage_form or '').strip().lower()}"
        if norm_key not in duplicates_groups:
            duplicates_groups[norm_key] = []
        duplicates_groups[norm_key].append({
            "id": m.id,
            "name": m.name,
            "generic_name": m.generic_name,
            "strength": m.strength or m.dosage,
            "dosage_form": m.dosage_form,
            "manufacturer": m.manufacturer,
            "is_active": m.is_active,
            "created_at": m.created_at.isoformat() if m.created_at else None
        })
        
    suspects = [group for group in duplicates_groups.values() if len(group) > 1]
    return {
        "suspect_groups_count": len(suspects),
        "suspect_groups": suspects
    }

@router.get("/{medicine_id}", response_model=schemas.MedicineResponse)
def get_single_medicine(medicine_id: int, db: Session = Depends(deps.get_db)):
    """Retrieve details for a single catalogue medicine."""
    med = db.query(models.Medicine).filter(models.Medicine.id == medicine_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Catalogue medicine not found")
        
    active_count = db.query(models.Inventory).join(models.Pharmacy).filter(
        models.Inventory.medicine_id == med.id,
        models.Inventory.is_available == True,
        models.Inventory.stock_quantity > 0,
        models.Pharmacy.status == models.PharmacyStatus.Approved
    ).count()
    med.active_pharmacies_count = active_count
    return med

@router.get("/{medicine_id}/pharmacies")
def get_medicine_stocking_pharmacies(
    medicine_id: int,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    db: Session = Depends(deps.get_db)
):
    """Find all approved pharmacies currently stocking a specific catalogue medicine."""
    med = db.query(models.Medicine).filter(models.Medicine.id == medicine_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Catalogue medicine not found")
        
    inventories = db.query(models.Inventory).options(
        joinedload(models.Inventory.pharmacy)
    ).join(models.Pharmacy).filter(
        models.Inventory.medicine_id == medicine_id,
        models.Pharmacy.status == models.PharmacyStatus.Approved
    ).all()
    
    results = []
    for inv in inventories:
        pharma = inv.pharmacy
        distance = None
        if lat is not None and lng is not None and pharma.lat and pharma.lng:
            R = 6371.0
            dlat = math.radians(pharma.lat - lat)
            dlng = math.radians(pharma.lng - lng)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(pharma.lat)) * math.sin(dlng / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance = round(R * c, 2)
            
        results.append({
            "pharmacy": {
                "id": pharma.id,
                "name": pharma.name,
                "location": pharma.location,
                "phone": pharma.phone,
                "email": pharma.email,
                "delivery_offered": pharma.delivery_offered,
                "opening_hours": pharma.opening_hours,
                "gps_address": pharma.gps_address,
                "lat": pharma.lat,
                "lng": pharma.lng,
                "verified": pharma.verified,
            },
            "inventory": {
                "id": inv.id,
                "price": inv.price,
                "stock_quantity": inv.stock_quantity,
                "batch_number": inv.batch_number,
                "expiry_date": inv.expiry_date.isoformat() if inv.expiry_date else None,
                "status": inv.status,
                "is_available": inv.is_available,
            },
            "distance_km": distance
        })
        
    if lat is not None and lng is not None:
        results.sort(key=lambda x: x["distance_km"] if x["distance_km"] is not None else float('inf'))
        
    return results

@router.post("/", response_model=schemas.MedicineResponse)
def create_medicine(
    medicine: schemas.MedicineCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Create a new medicine entry in the Central Catalogue.
    Accessible to Administrators (and Pharmacists adding catalog entries).
    Enforces duplicate prevention based on name, strength, dosage form, and manufacturer.
    """
    if current_user.role not in [models.UserRole.Admin, models.UserRole.Pharmacist]:
        raise HTTPException(status_code=403, detail="Not authorized to add catalogue medicines")
        
    # Check for exact duplicate in catalogue
    existing = db.query(models.Medicine).filter(
        func.lower(models.Medicine.name) == medicine.name.strip().lower(),
        func.lower(func.coalesce(models.Medicine.strength, models.Medicine.dosage, '')) == (medicine.strength or medicine.dosage or '').strip().lower(),
        func.lower(func.coalesce(models.Medicine.dosage_form, '')) == (medicine.dosage_form or '').strip().lower(),
        func.lower(func.coalesce(models.Medicine.manufacturer, '')) == (medicine.manufacturer or '').strip().lower()
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Medicine '{medicine.name}' ({medicine.strength or medicine.dosage or 'standard'}) already exists in the central catalogue (ID: {existing.id})."
        )
        
    med_data = medicine.model_dump()
    if not med_data.get("strength") and med_data.get("dosage"):
        med_data["strength"] = med_data["dosage"]
    elif not med_data.get("dosage") and med_data.get("strength"):
        med_data["dosage"] = med_data["strength"]
        
    new_medicine = models.Medicine(**med_data)
    db.add(new_medicine)
    db.commit()
    db.refresh(new_medicine)
    return new_medicine

@router.put("/{medicine_id}", response_model=schemas.MedicineResponse)
def update_medicine(
    medicine_id: int,
    medicine_in: schemas.MedicineUpdate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    """
    Administrator endpoint: Update a central catalogue medicine entry.
    Preserves existing reservations and historical pharmacy stock integrity.
    """
    med = db.query(models.Medicine).filter(models.Medicine.id == medicine_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Catalogue medicine not found")
        
    update_data = medicine_in.model_dump(exclude_unset=True)
    if "strength" in update_data and "dosage" not in update_data:
        update_data["dosage"] = update_data["strength"]
    elif "dosage" in update_data and "strength" not in update_data:
        update_data["strength"] = update_data["dosage"]
        
    for key, value in update_data.items():
        setattr(med, key, value)
        
    med.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(med)
    return med

@router.patch("/{medicine_id}/toggle-active", response_model=schemas.MedicineResponse)
def toggle_medicine_active(
    medicine_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    """
    Administrator endpoint: Deactivate or reactivate a catalogue entry without hard deleting.
    """
    med = db.query(models.Medicine).filter(models.Medicine.id == medicine_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Catalogue medicine not found")
        
    med.is_active = not med.is_active
    med.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(med)
    return med

