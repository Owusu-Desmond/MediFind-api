from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, func, text
from typing import List, Optional, Dict, Any, Tuple
import models, schemas, deps
import math
from datetime import datetime, timezone

router = APIRouter(
    prefix="/api/medicines",
    tags=["Medicines & Catalogue"],
)

def levenshtein_similarity(s1: str, s2: str) -> float:
    """Calculate normalized similarity between two strings."""
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    if s1 in s2 or s2 in s1:
        return 0.85

    len1, len2 = len(s1), len(s2)
    dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        dp[i][0] = i
    for j in range(len2 + 1):
        dp[0][j] = j

    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,      # deletion
                dp[i][j - 1] + 1,      # insertion
                dp[i - 1][j - 1] + cost # substitution
            )

    dist = dp[len1][len2]
    max_len = max(len1, len2)
    return max(0.0, 1.0 - (dist / max_len))


def resolve_canonical_medicines(
    db: Session,
    query_str: Optional[str] = None,
    category: Optional[str] = None,
    dosage_form: Optional[str] = None,
    requires_prescription: Optional[bool] = None,
    is_active: Optional[bool] = True,
    skip: int = 0,
    limit: int = 25
) -> Tuple[List[Tuple[models.Medicine, str, float]], int]:
    """
    5-Tier Intelligent Canonical Medicine Resolution:
    1. Exact Name match (Score: 100)
    2. Exact Alias match (Score: 90)
    3. Generic INN match (Score: 80)
    4. Partial / Substring match (Score: 60)
    5. Typo-Tolerant Fuzzy match (Score: 40)
    
    Returns (ranked_matches_slice, total_count)
    """
    base_query = db.query(models.Medicine).options(joinedload(models.Medicine.aliases))
    if is_active is not None:
        base_query = base_query.filter(models.Medicine.is_active == is_active)
    if category and category != "All":
        base_query = base_query.filter(
            or_(
                models.Medicine.category == category,
                models.Medicine.therapeutic_category == category
            )
        )
    if dosage_form and dosage_form != "All":
        base_query = base_query.filter(models.Medicine.dosage_form == dosage_form)
    if requires_prescription is not None:
        base_query = base_query.filter(models.Medicine.requires_prescription == requires_prescription)

    if not query_str or not query_str.strip():
        total_count = base_query.count()
        paged_meds = base_query.order_by(models.Medicine.name.asc()).offset(skip).limit(limit).all()
        return [(m, "all", 100.0) for m in paged_meds], total_count

    q_clean = query_str.strip().lower()

    # Map medicine_id -> (Medicine, matched_by, score)
    ranked_matches: Dict[int, Tuple[models.Medicine, str, float]] = {}

    def consider_match(med: models.Medicine, match_type: str, score: float):
        if med.id not in ranked_matches or ranked_matches[med.id][2] < score:
            ranked_matches[med.id] = (med, match_type, score)

    # 1. Fast SQL Filter: narrow down candidates at the database level in milliseconds
    search_sql_filter = or_(
        models.Medicine.name.ilike(f"%{q_clean}%"),
        models.Medicine.generic_name.ilike(f"%{q_clean}%"),
        models.Medicine.manufacturer.ilike(f"%{q_clean}%"),
        models.Medicine.tags.ilike(f"%{q_clean}%"),
        models.Medicine.description.ilike(f"%{q_clean}%"),
        models.Medicine.aliases.any(models.MedicineAlias.alias.ilike(f"%{q_clean}%"))
    )
    candidates = base_query.filter(search_sql_filter).limit(150).all()

    # If no direct SQL substring match found and query has at least 2 chars, fetch prefix candidates for typo tolerance
    if not candidates and len(q_clean) >= 2:
        prefix = q_clean[:2]
        prefix_filter = or_(
            models.Medicine.name.ilike(f"{prefix}%"),
            models.Medicine.generic_name.ilike(f"{prefix}%"),
            models.Medicine.aliases.any(models.MedicineAlias.alias.ilike(f"{prefix}%"))
        )
        candidates = base_query.filter(prefix_filter).limit(100).all()

    for m in candidates:
        name_lower = (m.name or "").strip().lower()
        gen_lower = (m.generic_name or "").strip().lower()
        strength_lower = (m.strength or m.dosage or "").strip().lower()
        tags_lower = (m.tags or "").strip().lower()
        desc_lower = (m.description or "").strip().lower()

        # 1. Exact Canonical Name Match (Score: 100)
        if name_lower == q_clean:
            consider_match(m, "exact_name", 100.0)
            continue

        # 2. Exact Alias Match (Score: 90, e.g. Panadol, PCM, APAP, Cipro)
        alias_exact = any((al.alias or "").strip().lower() == q_clean for al in m.aliases)
        if alias_exact:
            consider_match(m, "alias", 90.0)
            continue

        # 3. Generic INN Match (Score: 80, e.g. Acetaminophen, Ciprofloxacin)
        if gen_lower and gen_lower == q_clean:
            consider_match(m, "generic_name", 80.0)
            continue

        # 4. Partial / Substring Match across Name, Generic Name, Strength, Tags (Score: 60)
        if (
            q_clean in name_lower
            or (gen_lower and q_clean in gen_lower)
            or (strength_lower and q_clean in strength_lower)
            or (tags_lower and q_clean in tags_lower)
            or (desc_lower and q_clean in desc_lower)
        ):
            consider_match(m, "partial", 60.0)
            continue

        # 4b. Partial Alias Match (Score: 55)
        alias_partial = any(q_clean in (al.alias or "").strip().lower() for al in m.aliases)
        if alias_partial:
            consider_match(m, "partial_alias", 55.0)
            continue

        # 5. Typo-Tolerant Fuzzy / Trigram Match (Score: 40-50, e.g. "pareta", "paracetmol")
        sim_name = levenshtein_similarity(q_clean, name_lower)
        sim_gen = levenshtein_similarity(q_clean, gen_lower) if gen_lower else 0.0
        best_alias_sim = 0.0
        for al in m.aliases:
            al_clean = (al.alias or "").strip().lower()
            sim_al = levenshtein_similarity(q_clean, al_clean)
            if sim_al > best_alias_sim:
                best_alias_sim = sim_al

        best_sim = max(sim_name, sim_gen, best_alias_sim)
        if best_sim >= 0.55:  # Typo threshold
            fuzzy_score = 40.0 + (best_sim * 10.0)
            consider_match(m, "fuzzy", fuzzy_score)

    sorted_results = sorted(ranked_matches.values(), key=lambda x: (-x[2], x[0].name))
    total_count = len(sorted_results)
    return sorted_results[skip:skip + limit], total_count


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
    response: Response,
    q: Optional[str] = None,
    category: Optional[str] = None,
    dosage_form: Optional[str] = None,
    requires_prescription: Optional[bool] = None,
    is_active: Optional[bool] = True,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    skip: int = 0,
    limit: Optional[int] = None,
    db: Session = Depends(deps.get_db)
):
    """
    Browse the Central Medicine Catalogue with intelligent canonical search, alias resolution,
    and fast pagination. Supports both page/page_size and skip/limit query parameters.
    Returns pagination headers: X-Total-Count, X-Page, X-Page-Size, X-Total-Pages.
    """
    if page is not None and page > 0:
        actual_limit = page_size if page_size and page_size > 0 else 25
        actual_skip = (page - 1) * actual_limit
        current_page = page
    else:
        actual_limit = limit if limit is not None and limit > 0 else (page_size if page_size and page_size > 0 else 25)
        actual_skip = skip if skip >= 0 else 0
        current_page = (actual_skip // actual_limit) + 1 if actual_limit > 0 else 1

    sliced, total_count = resolve_canonical_medicines(
        db=db,
        query_str=q,
        category=category,
        dosage_form=dosage_form,
        requires_prescription=requires_prescription,
        is_active=is_active,
        skip=actual_skip,
        limit=actual_limit
    )
    
    med_ids = [med.id for med, _, _ in sliced]
    count_map = {}
    if med_ids:
        counts = db.query(
            models.Inventory.medicine_id,
            func.count(models.Inventory.id)
        ).join(models.Pharmacy).filter(
            models.Inventory.medicine_id.in_(med_ids),
            models.Inventory.is_available == True,
            models.Inventory.stock_quantity > 0,
            models.Pharmacy.status == models.PharmacyStatus.Approved
        ).group_by(models.Inventory.medicine_id).all()
        count_map = {row[0]: row[1] for row in counts}

    results = []
    for med, matched_by, score in sliced:
        med.active_pharmacies_count = count_map.get(med.id, 0)
        med.matched_by = matched_by
        results.append(med)

    total_pages = max(1, math.ceil(total_count / actual_limit)) if actual_limit > 0 else 1

    response.headers["X-Total-Count"] = str(total_count)
    response.headers["X-Page"] = str(current_page)
    response.headers["X-Page-Size"] = str(actual_limit)
    response.headers["X-Total-Pages"] = str(total_pages)
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count, X-Page, X-Page-Size, X-Total-Pages"
        
    return results

@router.get("/search")
def search_medicines(
    response: Response,
    q: Optional[str] = "",
    category: Optional[str] = None,
    dosage_form: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    skip: int = 0,
    limit: int = 20,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    db: Session = Depends(deps.get_db)
):
    """
    Patient Medicine Search: Resolves canonical medicine identity across exact names,
    aliases (e.g. Panadol -> Paracetamol), generic INN, abbreviations, and typos.
    Returns approved pharmacies stocking the medicine with prices, availability, and distances.
    Supports pagination (default 20 items per page, with subsequent pages e.g. 10 items).
    """
    actual_skip = (page - 1) * page_size if (page is not None and page_size is not None) else max(0, skip)
    actual_limit = page_size if (page is not None and page_size is not None) else max(1, limit)

    q_str = (q or "").strip()

    if not q_str:
        # Exploration Mode: Retrieve active inventory from all approved pharmacies directly
        inv_query = db.query(models.Inventory).options(
            joinedload(models.Inventory.medicine).joinedload(models.Medicine.aliases),
            joinedload(models.Inventory.pharmacy)
        ).join(models.Pharmacy).join(models.Medicine).filter(
            models.Pharmacy.status == models.PharmacyStatus.Approved,
            models.Medicine.is_active == True,
            models.Inventory.is_available == True
        )
        if category and category != "All":
            inv_query = inv_query.filter(
                or_(
                    models.Medicine.category == category,
                    models.Medicine.therapeutic_category == category
                )
            )
        if dosage_form and dosage_form != "All":
            inv_query = inv_query.filter(models.Medicine.dosage_form == dosage_form)

        inventories = inv_query.order_by(models.Inventory.id.desc()).all()
        med_lookup = {inv.medicine_id: (inv.medicine, "catalogue") for inv in inventories if inv.medicine}
    else:
        # Search Mode: Resolve canonical medicine matches
        resolved_meds, _ = resolve_canonical_medicines(
            db=db,
            query_str=q_str,
            category=category,
            dosage_form=dosage_form,
            is_active=True,
            skip=0,
            limit=100
        )

        if not resolved_meds:
            response.headers["X-Total-Count"] = "0"
            response.headers["X-Has-More"] = "false"
            response.headers["Access-Control-Expose-Headers"] = "X-Total-Count, X-Has-More, X-Skip, X-Limit"
            return []

        med_lookup = {med.id: (med, matched_by) for med, matched_by, score in resolved_meds}
        med_ids = list(med_lookup.keys())

        # Query active pharmacy inventories for these canonical medicines
        inventories = db.query(models.Inventory).options(
            joinedload(models.Inventory.medicine).joinedload(models.Medicine.aliases),
            joinedload(models.Inventory.pharmacy)
        ).join(models.Pharmacy).filter(
            models.Inventory.medicine_id.in_(med_ids),
            models.Pharmacy.status == models.PharmacyStatus.Approved,
            models.Inventory.is_available == True
        ).all()

    results = []
    for inv in inventories:
        med = inv.medicine
        pharma = inv.pharmacy
        if not med or not pharma:
            continue

        matched_by = med_lookup.get(med.id, (med, "match"))[1]

        # Compute GPS distance if coordinates available
        distance = None
        if lat is not None and lng is not None and pharma.lat and pharma.lng:
            R = 6371.0
            dlat = math.radians(pharma.lat - lat)
            dlng = math.radians(pharma.lng - lng)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(pharma.lat)) * math.sin(dlng / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance = round(R * c, 2)

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
            "image_url": pharma.image_url,
            "logo_url": pharma.logo_url,
        }

        # Format medicine with matched_by annotation
        med_dict = {
            "id": med.id,
            "name": med.name,
            "generic_name": med.generic_name,
            "strength": med.strength or med.dosage,
            "dosage_form": med.dosage_form,
            "route_of_administration": med.route_of_administration,
            "dosage": med.dosage or med.strength,
            "dosage_instructions": med.dosage_instructions,
            "category": med.category,
            "description": med.description,
            "manufacturer": med.manufacturer,
            "precautions": med.precautions,
            "side_effects": med.side_effects,
            "tags": med.tags,
            "image_url": med.image_url,
            "requires_prescription": med.requires_prescription,
            "is_active": med.is_active,
            "matched_by": matched_by,
            "aliases": [{"id": a.id, "alias": a.alias, "alias_type": a.alias_type} for a in med.aliases]
        }

        results.append({
            "medicine": med_dict,
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

    total_count = len(results)
    paged_results = results[actual_skip : actual_skip + actual_limit]
    has_more = (actual_skip + actual_limit) < total_count

    response.headers["X-Total-Count"] = str(total_count)
    response.headers["X-Has-More"] = "true" if has_more else "false"
    response.headers["X-Skip"] = str(actual_skip)
    response.headers["X-Limit"] = str(actual_limit)
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count, X-Has-More, X-Skip, X-Limit"

    return paged_results

@router.get("/admin/duplicates")
def get_duplicate_candidates(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    """Administrator endpoint: Scan catalogue for potential duplicate entries."""
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
    """Retrieve details for a single catalogue medicine including aliases."""
    med = db.query(models.Medicine).options(joinedload(models.Medicine.aliases)).filter(models.Medicine.id == medicine_id).first()
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
    Create a new medicine entry in the Central Catalogue with optional initial aliases.
    Accessible to Administrators (and Pharmacists submitting custom additions).
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

    med_data = medicine.model_dump(exclude={"aliases"})
    if not med_data.get("strength") and med_data.get("dosage"):
        med_data["strength"] = med_data["dosage"]
    elif not med_data.get("dosage") and med_data.get("strength"):
        med_data["dosage"] = med_data["strength"]

    new_medicine = models.Medicine(**med_data)
    db.add(new_medicine)
    db.commit()
    db.refresh(new_medicine)

    # Attach initial aliases if provided
    if medicine.aliases:
        for alias_str in medicine.aliases:
            if alias_str and alias_str.strip():
                clean_alias = alias_str.strip()
                alias_obj = models.MedicineAlias(
                    medicine_id=new_medicine.id,
                    alias=clean_alias,
                    alias_type=models.AliasType.BRAND.value
                )
                db.add(alias_obj)
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
    """Administrator endpoint: Update a central catalogue medicine entry."""
    med = db.query(models.Medicine).options(joinedload(models.Medicine.aliases)).filter(models.Medicine.id == medicine_id).first()
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
    """Administrator endpoint: Deactivate or reactivate a catalogue entry."""
    med = db.query(models.Medicine).options(joinedload(models.Medicine.aliases)).filter(models.Medicine.id == medicine_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Catalogue medicine not found")

    med.is_active = not med.is_active
    med.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(med)
    return med

# =========================================================================
# MEDICINE ALIASES MANAGEMENT ENDPOINTS
# =========================================================================

@router.get("/{medicine_id}/aliases", response_model=List[schemas.MedicineAliasResponse])
def get_medicine_aliases(medicine_id: int, db: Session = Depends(deps.get_db)):
    """Retrieve all search aliases for a canonical medicine."""
    med = db.query(models.Medicine).filter(models.Medicine.id == medicine_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Catalogue medicine not found")

    aliases = db.query(models.MedicineAlias).filter(models.MedicineAlias.medicine_id == medicine_id).all()
    return aliases

@router.post("/{medicine_id}/aliases", response_model=schemas.MedicineAliasResponse, status_code=status.HTTP_201_CREATED)
def add_medicine_alias(
    medicine_id: int,
    alias_in: schemas.MedicineAliasCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    """
    Administrator endpoint: Add a new alias / brand synonym / abbreviation to a canonical medicine.
    """
    med = db.query(models.Medicine).filter(models.Medicine.id == medicine_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Catalogue medicine not found")

    clean_alias = alias_in.alias.strip()
    if not clean_alias:
        raise HTTPException(status_code=400, detail="Alias cannot be empty")

    existing = db.query(models.MedicineAlias).filter(
        models.MedicineAlias.medicine_id == medicine_id,
        func.lower(models.MedicineAlias.alias) == clean_alias.lower()
    ).first()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alias '{clean_alias}' already exists for medicine '{med.name}'."
        )

    new_alias = models.MedicineAlias(
        medicine_id=medicine_id,
        alias=clean_alias,
        alias_type=alias_in.alias_type or models.AliasType.BRAND.value
    )
    db.add(new_alias)
    db.commit()
    db.refresh(new_alias)
    return new_alias

@router.put("/aliases/{alias_id}", response_model=schemas.MedicineAliasResponse)
def update_medicine_alias(
    alias_id: int,
    alias_in: schemas.MedicineAliasUpdate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    """Administrator endpoint: Update an existing medicine alias."""
    alias_obj = db.query(models.MedicineAlias).filter(models.MedicineAlias.id == alias_id).first()
    if not alias_obj:
        raise HTTPException(status_code=404, detail="Medicine alias not found")

    update_data = alias_in.model_dump(exclude_unset=True)
    if "alias" in update_data and update_data["alias"]:
        update_data["alias"] = update_data["alias"].strip()
    for key, value in update_data.items():
        setattr(alias_obj, key, value)

    db.commit()
    db.refresh(alias_obj)
    return alias_obj

@router.delete("/aliases/{alias_id}")
def delete_medicine_alias(
    alias_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_admin)
):
    """Administrator endpoint: Remove an alias from a medicine."""
    alias_obj = db.query(models.MedicineAlias).filter(models.MedicineAlias.id == alias_id).first()
    if not alias_obj:
        raise HTTPException(status_code=404, detail="Medicine alias not found")

    db.delete(alias_obj)
    db.commit()
    return {"message": f"Alias '{alias_obj.alias}' deleted successfully"}


