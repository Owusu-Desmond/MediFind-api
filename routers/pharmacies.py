import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
import models, schemas, deps, auth, storage
import math
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

    print(f"[Supabase] Generated signed URL: {full_url}")
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
def get_pharmacies(skip: int = 0, limit: int = 100, db: Session = Depends(deps.get_db)):
    pharmacies = db.query(models.Pharmacy).offset(skip).limit(limit).all()
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


@router.get("/{pharmacy_id}/inventory", response_model=List[schemas.InventoryResponse])
def get_pharmacy_inventory(
    pharmacy_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    return db.query(models.Inventory).filter(models.Inventory.pharmacy_id == pharmacy_id).all()


@router.post("/{pharmacy_id}/inventory", response_model=schemas.InventoryResponse)
def add_pharmacy_inventory(
    pharmacy_id: int,
    item_in: schemas.InventoryMedicineCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    medicine = db.query(models.Medicine).filter(models.Medicine.name == item_in.name, models.Medicine.dosage == item_in.dosage).first()
    if not medicine:
        medicine = models.Medicine(
            name=item_in.name,
            dosage=item_in.dosage,
            dosage_instructions=item_in.dosage_instructions,
            category=item_in.category,
            description=item_in.description,
            manufacturer=item_in.manufacturer,
            precautions=item_in.precautions,
            side_effects=item_in.side_effects,
            tags=item_in.tags,
            image_url=item_in.image_url
        )
        db.add(medicine)
        db.commit()
        db.refresh(medicine)
    else:
        # Update existing medicine attributes if provided
        if item_in.dosage_instructions:
            medicine.dosage_instructions = item_in.dosage_instructions
        if item_in.description:
            medicine.description = item_in.description
        if item_in.precautions:
            medicine.precautions = item_in.precautions
        if item_in.side_effects:
            medicine.side_effects = item_in.side_effects
        if item_in.tags:
            medicine.tags = item_in.tags
        if item_in.manufacturer:
            medicine.manufacturer = item_in.manufacturer
        if item_in.image_url:
            medicine.image_url = item_in.image_url

    status_str = "In Stock"
    if item_in.stock_quantity <= 0:
        status_str = "Out of Stock"
    elif item_in.stock_quantity <= 20:
        status_str = "Low Stock"

    expiry_dt = None
    if item_in.expiry_date:
        try:
            from datetime import datetime
            expiry_dt = datetime.strptime(item_in.expiry_date, "%Y-%m-%d")
        except Exception:
            pass

    new_inventory = models.Inventory(
        pharmacy_id=pharmacy_id,
        medicine_id=medicine.id,
        batch_number=item_in.batch_number,
        stock_quantity=item_in.stock_quantity,
        price=item_in.price,
        expiry_date=expiry_dt,
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
    inv = db.query(models.Inventory).filter(models.Inventory.id == inventory_id, models.Inventory.pharmacy_id == pharmacy_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    if item_in.batch_number is not None:
        inv.batch_number = item_in.batch_number
    if item_in.stock_quantity is not None:
        inv.stock_quantity = item_in.stock_quantity
        if inv.stock_quantity <= 0:
            inv.status = "Out of Stock"
        elif inv.stock_quantity <= 20:
            inv.status = "Low Stock"
        else:
            inv.status = "In Stock"
    if item_in.price is not None:
        inv.price = item_in.price
    if item_in.expiry_date is not None:
        try:
            from datetime import datetime
            inv.expiry_date = datetime.strptime(item_in.expiry_date, "%Y-%m-%d")
        except Exception:
            pass

    med = inv.medicine
    if med:
        if item_in.name is not None:
            med.name = item_in.name
        if item_in.dosage is not None:
            med.dosage = item_in.dosage
        if item_in.dosage_instructions is not None:
            med.dosage_instructions = item_in.dosage_instructions
        if item_in.category is not None:
            med.category = item_in.category
        if item_in.description is not None:
            med.description = item_in.description
        if item_in.manufacturer is not None:
            med.manufacturer = item_in.manufacturer
        if item_in.precautions is not None:
            med.precautions = item_in.precautions
        if item_in.side_effects is not None:
            med.side_effects = item_in.side_effects
        if item_in.tags is not None:
            med.tags = item_in.tags
        if item_in.image_url is not None:
            med.image_url = item_in.image_url

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
    inv = db.query(models.Inventory).filter(models.Inventory.id == inventory_id, models.Inventory.pharmacy_id == pharmacy_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    db.delete(inv)
    db.commit()
    return {"message": "Inventory item deleted"}


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


