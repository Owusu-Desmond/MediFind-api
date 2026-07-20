from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import uuid
import models, schemas, deps

router = APIRouter(
    prefix="/api/reservations",
    tags=["Reservations"],
)

@router.post("/", response_model=schemas.ReservationResponse)
def create_reservation(res_in: schemas.ReservationCreate, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_active_user)):
    # Calculate total price
    total = 0.0
    for item in res_in.items:
        inv = db.query(models.Inventory).filter(models.Inventory.medicine_id == item.medicine_id, models.Inventory.pharmacy_id == res_in.pharmacy_id).first()
        if not inv:
            raise HTTPException(status_code=400, detail=f"Medicine {item.medicine_id} not available at pharmacy")
        if inv.stock_quantity < item.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for medicine {item.medicine_id}")
        total += inv.price * item.quantity

    new_res = models.Reservation(
        patient_id=current_user.id,
        pharmacy_id=res_in.pharmacy_id,
        fulfillment_method=res_in.fulfillment_method,
        fulfillment_address=res_in.fulfillment_address,
        fulfillment_time=res_in.fulfillment_time,
        notes=res_in.notes,
        total_price=total,
        ref_number=f"MF-{uuid.uuid4().hex[:8].upper()}",
        status=models.ReservationStatus.Pending_Pharmacy_Review
    )
    db.add(new_res)
    db.commit()
    db.refresh(new_res)

    for item in res_in.items:
        inv = db.query(models.Inventory).filter(models.Inventory.medicine_id == item.medicine_id, models.Inventory.pharmacy_id == res_in.pharmacy_id).first()
        res_item = models.ReservationItem(
            reservation_id=new_res.id,
            medicine_id=item.medicine_id,
            quantity=item.quantity,
            price=inv.price
        )
        db.add(res_item)
    
    db.commit()
    db.refresh(new_res)
    return new_res

@router.get("/", response_model=List[schemas.ReservationResponse])
def get_reservations(skip: int = 0, limit: int = 100, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_active_user)):
    if current_user.role == models.UserRole.Patient:
        return db.query(models.Reservation).filter(models.Reservation.patient_id == current_user.id).offset(skip).limit(limit).all()
    elif current_user.role == models.UserRole.Pharmacist:
        # Get pharmacies this pharmacist manages
        staff = db.query(models.PharmacyStaff).filter(models.PharmacyStaff.user_id == current_user.id).all()
        pharmacy_ids = [s.pharmacy_id for s in staff]
        return db.query(models.Reservation).filter(models.Reservation.pharmacy_id.in_(pharmacy_ids)).offset(skip).limit(limit).all()
    else: # Admin
        return db.query(models.Reservation).offset(skip).limit(limit).all()

@router.patch("/{res_id}/status", response_model=schemas.ReservationResponse)
def update_status(res_id: int, status: str, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_active_user)):
    res = db.query(models.Reservation).filter(models.Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
        
    try:
        new_status = models.ReservationStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")
        
    # If approving, we might want to decrement stock
    if new_status == models.ReservationStatus.Approved and res.status != models.ReservationStatus.Approved:
        for item in res.items:
            inv = db.query(models.Inventory).filter(models.Inventory.medicine_id == item.medicine_id, models.Inventory.pharmacy_id == res.pharmacy_id).first()
            if inv:
                inv.stock_quantity = max(0, inv.stock_quantity - item.quantity)
                
    res.status = new_status
    db.commit()
    db.refresh(res)
    return res

@router.patch("/{res_id}/fulfillment", response_model=schemas.ReservationResponse)
def update_fulfillment_payment(res_id: int, method: str, payment_pref: str, address: str = None, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_active_user)):
    res = db.query(models.Reservation).filter(models.Reservation.id == res_id, models.Reservation.patient_id == current_user.id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
        
    res.fulfillment_method = method
    res.payment_preference = payment_pref
    if address:
        res.fulfillment_address = address
        
    # According to step 7/8, if they choose pay online, they go to online payment
    if payment_pref == "Pay Online":
        pass # status remains Approved until payment is successful
    else:
        if method == "Pickup":
            res.status = models.ReservationStatus.Ready_for_Pickup
        else:
            res.status = models.ReservationStatus.Preparing
            
    db.commit()
    db.refresh(res)
    return res
