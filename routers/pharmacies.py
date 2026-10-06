import os
import uuid
import math
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func
import models, schemas, deps, auth, storage, paystack_service
from utils import calculate_pharmacy_open_status, send_approval_email, generate_secure_password

router = APIRouter(
    prefix="/api/pharmacies",
    tags=["Pharmacies"],
)

def enrich_pharmacy_response(pharmacy: models.Pharmacy) -> schemas.PharmacyResponse:
    is_open, status_text = calculate_pharmacy_open_status(pharmacy.opening_hours)
    res = schemas.PharmacyResponse.model_validate(pharmacy)
    res.is_open = is_open
    res.open_status_text = status_text
    return res


@router.get("/signed-url")
async def get_signed_url(
    object_path: str,
    current_user: models.User = Depends(deps.get_current_active_user),
):
    """
    Generate a short-lived Supabase Storage signed URL for a private file.
    object_path should be the path inside the bucket, e.g. "certificates/abc123_file.pdf"
    The signed URL is valid for 1 hour (3600 seconds).
    """
    import httpx, os
    from dotenv import load_dotenv
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_KEY", "")
    supabase_bucket = os.getenv("SUPABASE_BUCKET", "certificates")

    if not supabase_url or not supabase_key:
        raise HTTPException(status_code=500, detail="Supabase credentials not configured")

    url = f"{supabase_url.rstrip('/')}/storage/v1/object/sign/{supabase_bucket}/{object_path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apikey": supabase_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(url, json={"expiresIn": 3600}, headers=headers)

    if res.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Supabase error ({res.status_code}): {res.text}"
        )

    data = res.json()
    signed_path = data.get("signedURL") or data.get("signedUrl") or ""
    if not signed_path:
        raise HTTPException(status_code=502, detail=f"Unexpected Supabase response: {data}")

    # Form full URL based on how Supabase returned signed_path
    if signed_path.startswith("http://") or signed_path.startswith("https://"):
        full_url = signed_path
    elif signed_path.startswith("/storage/v1"):
        full_url = f"{supabase_url}{signed_path}"
    else:
        if not signed_path.startswith("/"):
            signed_path = "/" + signed_path
        full_url = f"{supabase_url}/storage/v1{signed_path}"

    return {"signed_url": full_url, "expires_in": 3600}


@router.post("/upload-certificate")
async def upload_certificate(
    file: UploadFile = File(...)
):
    ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Allowed: PDF, PNG, JPG, JPEG")

    contents = await file.read()
    try:
        file_url = await storage.upload_file_to_supabase(
            file_bytes=contents,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            bucket_name="certificates"
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to upload certificate to Supabase: {e}")

    return {"url": file_url, "filename": file.filename}


@router.post("/upload-medicine-image")
async def upload_medicine_image(
    file: UploadFile = File(...),
):
    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported image type '{ext}'. Allowed: PNG, JPG, JPEG, WEBP")

    contents = await file.read()
    try:
        file_url = await storage.upload_file_to_supabase(
            file_bytes=contents,
            filename=file.filename,
            content_type=file.content_type or "image/jpeg",
            bucket_name="medicines"
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to upload medicine image to Supabase: {e}")

    return {"url": file_url, "filename": file.filename}


@router.post("/upload-pharmacy-image")
async def upload_pharmacy_image(
    file: UploadFile = File(...),
):
    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported image type '{ext}'. Allowed: PNG, JPG, JPEG, WEBP")

    contents = await file.read()
    try:
        file_url = await storage.upload_file_to_supabase(
            file_bytes=contents,
            filename=file.filename,
            content_type=file.content_type or "image/jpeg",
            bucket_name="pharmacies"
        )
    except Exception as e:
        # Fallback to medicines bucket if pharmacies bucket is not yet configured in Supabase
        try:
            file_url = await storage.upload_file_to_supabase(
                file_bytes=contents,
                filename=file.filename,
                content_type=file.content_type or "image/jpeg",
                bucket_name="medicines"
            )
        except Exception as e2:
            raise HTTPException(status_code=502, detail=f"Failed to upload pharmacy image to Supabase: {e2}")

    return {"url": file_url, "filename": file.filename}


@router.post("/", response_model=schemas.PharmacyResponse)
def create_pharmacy(pharmacy: schemas.PharmacyCreate, db: Session = Depends(deps.get_db)):
    # Simple check: maybe only allow creation if it doesn't exist
    existing = db.query(models.Pharmacy).filter(models.Pharmacy.license_number == pharmacy.license_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Pharmacy with this license already exists")
    
    new_pharmacy = models.Pharmacy(**pharmacy.model_dump())
    db.add(new_pharmacy)
    db.commit()
    db.refresh(new_pharmacy)
    return enrich_pharmacy_response(new_pharmacy)

@router.get("/", response_model=List[schemas.PharmacyResponse])
def get_pharmacies(status: str = None, skip: int = 0, limit: int = 100, db: Session = Depends(deps.get_db)):
    query = db.query(models.Pharmacy)
    if status:
        query = query.filter(models.Pharmacy.status == status)
    pharmacies = query.offset(skip).limit(limit).all()
    return [enrich_pharmacy_response(p) for p in pharmacies]

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
    return [enrich_pharmacy_response(p) for p in nearby]

@router.patch("/{pharmacy_id}/status", response_model=schemas.PharmacyResponse)
def update_pharmacy_status(pharmacy_id: int, status: str, db: Session = Depends(deps.get_db), current_admin: models.User = Depends(deps.get_current_admin)):
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    
    try:
        pharmacy.status = models.PharmacyStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    # If approved, we should create or update user account for the pharmacist & send email
    if pharmacy.status == models.PharmacyStatus.Approved and pharmacy.email:
        user = db.query(models.User).filter(models.User.email == pharmacy.email).first()
        raw_password = generate_secure_password()
        if not user:
            # Create a generated password for the pharmacist
            default_password = auth.get_password_hash(raw_password)
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
        else:
            # Update password so new approval generates fresh valid credentials
            user.hashed_password = auth.get_password_hash(raw_password)
            db.commit()

        # Send approval notification email with login credentials and link
        send_approval_email(
            email=pharmacy.email,
            pharmacy_name=pharmacy.name,
            password=raw_password,
            login_url="http://localhost:3001/"
        )

    db.commit()
    db.refresh(pharmacy)
    return enrich_pharmacy_response(pharmacy)

@router.put("/{pharmacy_id}", response_model=schemas.PharmacyResponse)
def update_pharmacy(
    pharmacy_id: int,
    pharmacy_data: schemas.PharmacyUpdate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    update_dict = pharmacy_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if key == "status" and value:
            try:
                pharmacy.status = models.PharmacyStatus(value)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status '{value}'")
        else:
            setattr(pharmacy, key, value)

    db.commit()
    db.refresh(pharmacy)
    return enrich_pharmacy_response(pharmacy)

@router.delete("/{pharmacy_id}")
def delete_pharmacy(
    pharmacy_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    # Clean up related child entities to prevent foreign key violations
    db.query(models.PharmacyStaff).filter(models.PharmacyStaff.pharmacy_id == pharmacy_id).delete(synchronize_session=False)
    db.query(models.Inventory).filter(models.Inventory.pharmacy_id == pharmacy_id).delete(synchronize_session=False)
    db.query(models.Reservation).filter(models.Reservation.pharmacy_id == pharmacy_id).delete(synchronize_session=False)

    db.delete(pharmacy)
    db.commit()
    return {"message": "Pharmacy deleted successfully"}


@router.get("/my-pharmacy", response_model=schemas.PharmacyResponse)
def get_my_pharmacy(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    # 1. Check PharmacyStaff relation
    staff = db.query(models.PharmacyStaff).filter(models.PharmacyStaff.user_id == current_user.id).first()
    if staff:
        pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == staff.pharmacy_id).first()
        if pharmacy:
            return enrich_pharmacy_response(pharmacy)

    # 2. Check pharmacy by user email
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.email == current_user.email).first()
    if pharmacy:
        return enrich_pharmacy_response(pharmacy)

    # 3. Fallback: get first available pharmacy or create a default demo pharmacy
    pharmacy = db.query(models.Pharmacy).first()
    if pharmacy:
        return enrich_pharmacy_response(pharmacy)

    default_pharmacy = models.Pharmacy(
        name="Ghana National Pharmacy (Accra Central)",
        location="Ring Road Central, Accra",
        license_number="PHA-GH-2026-8830",
        pharmacist_name=current_user.name,
        email=current_user.email,
        phone=current_user.phone or "+233 30 223 4455",
        status=models.PharmacyStatus.Approved,
        delivery_offered=True,
        opening_hours="08:00 AM - 10:00 PM"
    )
    db.add(default_pharmacy)
    db.commit()
    db.refresh(default_pharmacy)

    staff_link = models.PharmacyStaff(user_id=current_user.id, pharmacy_id=default_pharmacy.id)
    db.add(staff_link)
    db.commit()

    return enrich_pharmacy_response(default_pharmacy)


def verify_pharmacy_access(pharmacy_id: int, user: models.User, db: Session):
    if user.role == models.UserRole.Admin:
        return True
    if user.role == models.UserRole.Pharmacist:
        staff = db.query(models.PharmacyStaff).filter(
            models.PharmacyStaff.user_id == user.id,
            models.PharmacyStaff.pharmacy_id == pharmacy_id
        ).first()
        if staff:
            return True
        pharma = db.query(models.Pharmacy).filter(
            models.Pharmacy.id == pharmacy_id,
            models.Pharmacy.email == user.email
        ).first()
        if pharma:
            return True
    raise HTTPException(status_code=403, detail="You are not authorized to manage inventory for this pharmacy")


@router.get("/{pharmacy_id}/inventory", response_model=List[schemas.InventoryResponse])
def get_pharmacy_inventory(
    pharmacy_id: int,
    q: Optional[str] = None,
    is_available: Optional[bool] = None,
    status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """List all inventory items stocked by a specific pharmacy."""
    query = db.query(models.Inventory).options(
        joinedload(models.Inventory.medicine)
    ).join(models.Medicine).filter(models.Inventory.pharmacy_id == pharmacy_id)

    if is_available is not None:
        query = query.filter(models.Inventory.is_available == is_available)
        
    if status and status != "All":
        query = query.filter(models.Inventory.status == status)

    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                models.Medicine.name.ilike(term),
                models.Medicine.generic_name.ilike(term),
                models.Medicine.strength.ilike(term),
                models.Medicine.dosage.ilike(term),
                models.Medicine.category.ilike(term),
                models.Medicine.manufacturer.ilike(term),
                models.Inventory.batch_number.ilike(term)
            )
        )

    return query.order_by(models.Medicine.name.asc()).all()


@router.post("/{pharmacy_id}/inventory/add-from-catalogue", response_model=schemas.InventoryResponse)
def add_inventory_from_catalogue(
    pharmacy_id: int,
    item_in: schemas.InventoryAddFromCatalogue,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Add a medicine from the Central Medicine Catalogue to the pharmacy's inventory.
    Enforces non-negative price/stock validation and prevents duplicate inventory entries.
    """
    verify_pharmacy_access(pharmacy_id, current_user, db)

    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    if pharmacy.status != models.PharmacyStatus.Approved and current_user.role != models.UserRole.Admin:
        raise HTTPException(status_code=400, detail="Pharmacy is pending approval or suspended")

    if item_in.price < 0:
        raise HTTPException(status_code=400, detail="Selling price cannot be negative")
    if item_in.stock_quantity < 0:
        raise HTTPException(status_code=400, detail="Stock quantity cannot be negative")

    # Verify medicine exists in central catalogue
    medicine = db.query(models.Medicine).filter(models.Medicine.id == item_in.medicine_id).first()
    if not medicine:
        raise HTTPException(status_code=404, detail="Catalogue medicine not found")
    if not medicine.is_active:
        raise HTTPException(status_code=400, detail="This catalogue medicine is currently inactive")

    # Check for duplicate
    existing = db.query(models.Inventory).filter(
        models.Inventory.pharmacy_id == pharmacy_id,
        models.Inventory.medicine_id == item_in.medicine_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{medicine.name}' is already in your inventory (Inventory ID: {existing.id}). Please update its stock or price instead."
        )

    status_str = "In Stock"
    if item_in.stock_quantity <= 0:
        status_str = "Out of Stock"
    elif item_in.stock_quantity <= 20:
        status_str = "Low Stock"
    if not item_in.is_available:
        status_str = "Unavailable"

    expiry_dt = None
    if item_in.expiry_date:
        try:
            from datetime import datetime
            expiry_dt = datetime.strptime(item_in.expiry_date.split("T")[0], "%Y-%m-%d")
        except Exception:
            pass

    new_inventory = models.Inventory(
        pharmacy_id=pharmacy_id,
        medicine_id=medicine.id,
        batch_number=item_in.batch_number,
        stock_quantity=item_in.stock_quantity,
        price=float(item_in.price),
        expiry_date=expiry_dt,
        is_available=item_in.is_available,
        status=status_str
    )
    db.add(new_inventory)
    db.commit()
    db.refresh(new_inventory)
    return new_inventory


@router.post("/{pharmacy_id}/inventory/bulk-add", response_model=schemas.BulkInventoryAddResponse)
def bulk_add_inventory_from_catalogue(
    pharmacy_id: int,
    bulk_in: schemas.BulkInventoryAddRequest,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Bulk Add Feature: Add multiple medicines from the Central Catalogue to a pharmacy's inventory in one operation.
    Skips duplicates without failing the entire batch, and returns a detailed summary report.
    """
    verify_pharmacy_access(pharmacy_id, current_user, db)

    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    if pharmacy.status != models.PharmacyStatus.Approved and current_user.role != models.UserRole.Admin:
        raise HTTPException(status_code=400, detail="Pharmacy is pending approval or suspended")

    # Assemble list of items to process
    items_to_process: List[Dict[str, Any]] = []
    if bulk_in.items and len(bulk_in.items) > 0:
        for it in bulk_in.items:
            items_to_process.append({
                "medicine_id": it.medicine_id,
                "price": it.price if it.price is not None else bulk_in.default_price,
                "stock_quantity": it.stock_quantity if it.stock_quantity is not None else bulk_in.default_quantity,
                "batch_number": it.batch_number,
                "expiry_date": it.expiry_date,
                "is_available": it.is_available if it.is_available is not None else True
            })
    elif bulk_in.medicine_ids and len(bulk_in.medicine_ids) > 0:
        for mid in bulk_in.medicine_ids:
            items_to_process.append({
                "medicine_id": mid,
                "price": bulk_in.default_price or 15.0,
                "stock_quantity": bulk_in.default_quantity or 50,
                "batch_number": None,
                "expiry_date": None,
                "is_available": True
            })
    else:
        raise HTTPException(status_code=400, detail="Please provide a list of medicine IDs to add")

    added_items = []
    existing_ids = []
    invalid_ids = []

    # Query all existing inventory for this pharmacy to quickly check duplicates
    existing_med_ids = set([
        row[0] for row in db.query(models.Inventory.medicine_id).filter(
            models.Inventory.pharmacy_id == pharmacy_id
        ).all()
    ])

    for item in items_to_process:
        med_id = item["medicine_id"]

        if med_id in existing_med_ids:
            existing_ids.append(med_id)
            continue

        med = db.query(models.Medicine).filter(models.Medicine.id == med_id).first()
        if not med or not med.is_active:
            invalid_ids.append(med_id)
            continue

        price = max(0.0, float(item["price"] or 15.0))
        qty = max(0, int(item["stock_quantity"] or 0))

        status_str = "In Stock"
        if qty <= 0:
            status_str = "Out of Stock"
        elif qty <= 20:
            status_str = "Low Stock"
        if not item["is_available"]:
            status_str = "Unavailable"

        expiry_dt = None
        if item.get("expiry_date"):
            try:
                from datetime import datetime
                expiry_dt = datetime.strptime(str(item["expiry_date"]).split("T")[0], "%Y-%m-%d")
            except Exception:
                pass

        new_inv = models.Inventory(
            pharmacy_id=pharmacy_id,
            medicine_id=med.id,
            batch_number=item.get("batch_number"),
            stock_quantity=qty,
            price=price,
            expiry_date=expiry_dt,
            is_available=item.get("is_available", True),
            status=status_str
        )
        db.add(new_inv)
        existing_med_ids.add(med.id)
        added_items.append(new_inv)

    db.commit()
    for it in added_items:
        db.refresh(it)

    return schemas.BulkInventoryAddResponse(
        added_count=len(added_items),
        skipped_count=len(existing_ids) + len(invalid_ids),
        invalid_ids=invalid_ids,
        existing_ids=existing_ids,
        added_items=added_items,
        message=f"Successfully added {len(added_items)} medicines to inventory. ({len(existing_ids)} already existed, {len(invalid_ids)} invalid/inactive)."
    )


@router.post("/{pharmacy_id}/inventory", response_model=schemas.InventoryResponse)
def add_pharmacy_inventory(
    pharmacy_id: int,
    item_in: schemas.InventoryMedicineCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Add a medicine to pharmacy inventory.
    If the medicine already exists in the central catalogue, connects to it.
    If not, creates a new catalogue entry and connects it.
    """
    verify_pharmacy_access(pharmacy_id, current_user, db)

    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    if item_in.price < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    if item_in.stock_quantity < 0:
        raise HTTPException(status_code=400, detail="Stock quantity cannot be negative")

    # Match or create in central catalogue
    strength_val = item_in.strength or item_in.dosage or "500mg"
    medicine = db.query(models.Medicine).filter(
        func.lower(models.Medicine.name) == item_in.name.strip().lower(),
        func.lower(func.coalesce(models.Medicine.strength, models.Medicine.dosage, '')) == strength_val.strip().lower()
    ).first()

    if not medicine:
        medicine = models.Medicine(
            name=item_in.name.strip(),
            generic_name=item_in.generic_name,
            strength=strength_val,
            dosage=strength_val,
            dosage_form=item_in.dosage_form or "Tablet",
            route_of_administration=item_in.route_of_administration or "Oral",
            dosage_instructions=item_in.dosage_instructions,
            category=item_in.category or "General",
            description=item_in.description,
            manufacturer=item_in.manufacturer,
            precautions=item_in.precautions,
            side_effects=item_in.side_effects,
            tags=item_in.tags,
            image_url=item_in.image_url,
            requires_prescription=item_in.requires_prescription,
            is_active=True
        )
        db.add(medicine)
        db.commit()
        db.refresh(medicine)

    # Check if this pharmacy already has this medicine in inventory
    existing_inv = db.query(models.Inventory).filter(
        models.Inventory.pharmacy_id == pharmacy_id,
        models.Inventory.medicine_id == medicine.id
    ).first()
    if existing_inv:
        # Update existing inventory rather than creating a duplicate
        existing_inv.stock_quantity = item_in.stock_quantity
        existing_inv.price = float(item_in.price)
        if item_in.batch_number:
            existing_inv.batch_number = item_in.batch_number
        if item_in.stock_quantity <= 0:
            existing_inv.status = "Out of Stock"
        elif item_in.stock_quantity <= 20:
            existing_inv.status = "Low Stock"
        else:
            existing_inv.status = "In Stock"
        existing_inv.is_available = item_in.is_available
        existing_inv.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing_inv)
        return existing_inv

    status_str = "In Stock"
    if item_in.stock_quantity <= 0:
        status_str = "Out of Stock"
    elif item_in.stock_quantity <= 20:
        status_str = "Low Stock"
    if not item_in.is_available:
        status_str = "Unavailable"

    expiry_dt = None
    if item_in.expiry_date:
        try:
            from datetime import datetime
            expiry_dt = datetime.strptime(str(item_in.expiry_date).split("T")[0], "%Y-%m-%d")
        except Exception:
            pass

    new_inventory = models.Inventory(
        pharmacy_id=pharmacy_id,
        medicine_id=medicine.id,
        batch_number=item_in.batch_number,
        stock_quantity=item_in.stock_quantity,
        price=float(item_in.price),
        expiry_date=expiry_dt,
        is_available=item_in.is_available,
        status=status_str
    )
    db.add(new_inventory)
    db.commit()
    db.refresh(new_inventory)
    return new_inventory


@router.put("/{pharmacy_id}/inventory/{inventory_id}", response_model=schemas.InventoryResponse)
def update_pharmacy_inventory(
    pharmacy_id: int,
    inventory_id: int,
    item_in: schemas.InventoryMedicineUpdate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Update a pharmacy's inventory pricing, quantity, batch, or availability.
    Crucially, changes to a pharmacy's inventory record DO NOT alter the central catalogue attributes.
    """
    verify_pharmacy_access(pharmacy_id, current_user, db)

    inv = db.query(models.Inventory).filter(
        models.Inventory.id == inventory_id,
        models.Inventory.pharmacy_id == pharmacy_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    if item_in.batch_number is not None:
        inv.batch_number = item_in.batch_number
    if item_in.stock_quantity is not None:
        if item_in.stock_quantity < 0:
            raise HTTPException(status_code=400, detail="Stock quantity cannot be negative")
        inv.stock_quantity = item_in.stock_quantity
        if inv.stock_quantity <= 0:
            inv.status = "Out of Stock"
        elif inv.stock_quantity <= 20:
            inv.status = "Low Stock"
        else:
            inv.status = "In Stock"
    if item_in.price is not None:
        if item_in.price < 0:
            raise HTTPException(status_code=400, detail="Selling price cannot be negative")
        inv.price = float(item_in.price)
    if item_in.is_available is not None:
        inv.is_available = item_in.is_available
        if not inv.is_available:
            inv.status = "Unavailable"
    if item_in.expiry_date is not None:
        try:
            inv.expiry_date = datetime.strptime(str(item_in.expiry_date).split("T")[0], "%Y-%m-%d")
        except Exception:
            pass

    inv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(inv)
    return inv


@router.delete("/{pharmacy_id}/inventory/{inventory_id}")
def delete_pharmacy_inventory(
    pharmacy_id: int,
    inventory_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Remove a medicine from a pharmacy's inventory without deleting the Central Catalogue entry.
    """
    verify_pharmacy_access(pharmacy_id, current_user, db)

    inv = db.query(models.Inventory).filter(
        models.Inventory.id == inventory_id,
        models.Inventory.pharmacy_id == pharmacy_id
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    db.delete(inv)
    db.commit()
    return {"message": "Inventory item successfully removed from pharmacy stock"}


@router.get("/{pharmacy_id}/staff", response_model=List[schemas.StaffResponse])
def get_pharmacy_staff(
    pharmacy_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    staff_records = db.query(models.PharmacyStaff).filter(models.PharmacyStaff.pharmacy_id == pharmacy_id).all()
    results = []
    for s in staff_records:
        u = db.query(models.User).filter(models.User.id == s.user_id).first()
        if u:
            results.append({
                "id": s.id,
                "user_id": u.id,
                "name": u.name,
                "email": u.email,
                "phone": u.phone,
                "role": u.role.value if hasattr(u.role, "value") else str(u.role)
            })
    return results


@router.post("/{pharmacy_id}/staff", response_model=schemas.StaffResponse)
def add_pharmacy_staff(
    pharmacy_id: int,
    staff_in: schemas.AddStaffRequest,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    existing_user = db.query(models.User).filter(models.User.email == staff_in.email).first()
    if existing_user:
        existing_link = db.query(models.PharmacyStaff).filter(
            models.PharmacyStaff.user_id == existing_user.id,
            models.PharmacyStaff.pharmacy_id == pharmacy_id
        ).first()
        if existing_link:
            raise HTTPException(status_code=400, detail="This email is already registered as staff for this pharmacy.")
        target_user = existing_user
    else:
        hashed_pw = auth.get_password_hash(staff_in.password)
        target_user = models.User(
            email=staff_in.email,
            name=staff_in.name,
            hashed_password=hashed_pw,
            phone=staff_in.phone,
            role=models.UserRole.Pharmacist
        )
        db.add(target_user)
        db.commit()
        db.refresh(target_user)

    staff_link = models.PharmacyStaff(user_id=target_user.id, pharmacy_id=pharmacy_id)
    db.add(staff_link)
    db.commit()
    db.refresh(staff_link)

    return {
        "id": staff_link.id,
        "user_id": target_user.id,
        "name": target_user.name,
        "email": target_user.email,
        "phone": target_user.phone,
        "role": target_user.role.value if hasattr(target_user.role, "value") else str(target_user.role)
    }


@router.delete("/{pharmacy_id}/staff/{staff_id}")
def delete_pharmacy_staff(
    pharmacy_id: int,
    staff_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    staff_link = db.query(models.PharmacyStaff).filter(
        models.PharmacyStaff.id == staff_id,
        models.PharmacyStaff.pharmacy_id == pharmacy_id
    ).first()
    if not staff_link:
        raise HTTPException(status_code=404, detail="Staff member record not found.")

    db.delete(staff_link)
    db.commit()
    return {"message": "Staff member removed from pharmacy."}


@router.post("/{pharmacy_id}/paystack/subaccount", response_model=schemas.PharmacyPayoutResponse)
async def setup_pharmacy_subaccount(
    pharmacy_id: int,
    payout_data: schemas.PharmacyPayoutSetupRequest,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Configure payout details and register/link Paystack subaccount for the pharmacy.
    """
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    # Verify authorization
    if current_user.role == models.UserRole.Pharmacist:
        staff = db.query(models.PharmacyStaff).filter(
            models.PharmacyStaff.user_id == current_user.id,
            models.PharmacyStaff.pharmacy_id == pharmacy_id
        ).first()
        if not staff and pharmacy.email != current_user.email:
            raise HTTPException(status_code=403, detail="Not authorized to configure payout for this pharmacy")
    elif current_user.role != models.UserRole.Admin:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Determine settlement bank code
    settlement_bank = payout_data.bank_code or (
        "MTN" if payout_data.mobile_money_provider == "MTN" else
        "VOD" if payout_data.mobile_money_provider in ("VOD", "Telecel", "Vodafone") else
        "ATL" if payout_data.mobile_money_provider in ("ATL", "AirtelTigo", "AT") else
        "040100" # fallback GCB
    )

    account_num = payout_data.account_number or payout_data.mobile_money_number or ""

    # Call Paystack API
    paystack_res = await paystack_service.create_paystack_subaccount(
        business_name=pharmacy.name,
        settlement_bank=settlement_bank,
        account_number=account_num,
        description=f"MediFind Payout for {pharmacy.name} ({pharmacy.license_number})"
    )

    now = datetime.now(timezone.utc)

    # Update pharmacy record
    pharmacy.payment_account_type = payout_data.payment_account_type
    pharmacy.bank_name = payout_data.bank_name
    pharmacy.bank_code = settlement_bank
    pharmacy.account_name = payout_data.account_name
    pharmacy.account_number = account_num
    pharmacy.mobile_money_provider = payout_data.mobile_money_provider
    pharmacy.mobile_money_number = payout_data.mobile_money_number

    if paystack_res.get("status") and paystack_res.get("subaccount_code"):
        pharmacy.paystack_subaccount_code = paystack_res["subaccount_code"]
        pharmacy.paystack_subaccount_id = paystack_res.get("subaccount_id")
        pharmacy.paystack_subaccount_status = "ACTIVE"
        pharmacy.payment_account_verified = True
        pharmacy.payment_account_verified_at = now
    else:
        pharmacy.paystack_subaccount_status = "PENDING"
        pharmacy.payment_account_verified = False

    db.commit()
    db.refresh(pharmacy)

    # Mask account number for safe frontend display (e.g. "024****890")
    masked_account = account_num
    if len(account_num) > 4:
        masked_account = f"{account_num[:3]}****{account_num[-3:]}"

    return schemas.PharmacyPayoutResponse(
        pharmacy_id=pharmacy.id,
        paystack_subaccount_code=pharmacy.paystack_subaccount_code,
        paystack_subaccount_status=pharmacy.paystack_subaccount_status,
        payment_account_type=pharmacy.payment_account_type,
        bank_name=pharmacy.bank_name,
        account_name=pharmacy.account_name,
        account_number_masked=masked_account,
        mobile_money_provider=pharmacy.mobile_money_provider,
        payment_account_verified=pharmacy.payment_account_verified or False,
        message=paystack_res.get("message", "Payout setup updated"),
    )


@router.get("/{pharmacy_id}/paystack/subaccount", response_model=schemas.PharmacyPayoutResponse)
def get_pharmacy_subaccount(
    pharmacy_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Get safe payout & subaccount status for a pharmacy with masked sensitive account number.
    """
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    account_num = pharmacy.account_number or pharmacy.mobile_money_number or ""
    masked_account = account_num
    if len(account_num) > 4:
        masked_account = f"{account_num[:3]}****{account_num[-3:]}"

    return schemas.PharmacyPayoutResponse(
        pharmacy_id=pharmacy.id,
        paystack_subaccount_code=pharmacy.paystack_subaccount_code,
        paystack_subaccount_status=pharmacy.paystack_subaccount_status or "PENDING",
        payment_account_type=pharmacy.payment_account_type,
        bank_name=pharmacy.bank_name,
        account_name=pharmacy.account_name,
        account_number_masked=masked_account,
        mobile_money_provider=pharmacy.mobile_money_provider,
        payment_account_verified=pharmacy.payment_account_verified or False,
    )



