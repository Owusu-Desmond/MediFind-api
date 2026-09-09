from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
import models, schemas, deps

router = APIRouter(
    prefix="/api/reservations",
    tags=["Reservations"],
)

@router.post("/", response_model=schemas.ReservationResponse)
def create_reservation(
    res_in: schemas.ReservationCreate,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    # Verify pharmacy exists
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == res_in.pharmacy_id).first()
    if not pharmacy:
        raise HTTPException(status_code=404, detail=f"Pharmacy {res_in.pharmacy_id} not found")

    # Calculate total price & prepare items
    total = 0.0
    items_to_create = []

    for item in res_in.items:
        # Check medicine
        medicine = db.query(models.Medicine).filter(models.Medicine.id == item.medicine_id).first()
        if not medicine:
            raise HTTPException(status_code=404, detail=f"Medicine {item.medicine_id} not found")

        # Check or create inventory
        inv = db.query(models.Inventory).filter(
            models.Inventory.medicine_id == item.medicine_id,
            models.Inventory.pharmacy_id == res_in.pharmacy_id
        ).first()

        if not inv:
            # Create a default inventory entry for this pharmacy so reservation succeeds
            inv = models.Inventory(
                pharmacy_id=res_in.pharmacy_id,
                medicine_id=item.medicine_id,
                batch_number="B-AUTO",
                stock_quantity=100,
                price=15.0,
                status="In Stock"
            )
            db.add(inv)
            db.commit()
            db.refresh(inv)

        unit_price = inv.price if inv.price > 0 else 15.0
        total += unit_price * item.quantity
        items_to_create.append({
            "medicine_id": item.medicine_id,
            "quantity": item.quantity,
            "price": unit_price
        })

    new_res = models.Reservation(
        patient_id=current_user.id,
        pharmacy_id=res_in.pharmacy_id,
        fulfillment_method=res_in.fulfillment_method or "Pickup",
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

    for item_data in items_to_create:
        res_item = models.ReservationItem(
            reservation_id=new_res.id,
            medicine_id=item_data["medicine_id"],
            quantity=item_data["quantity"],
            price=item_data["price"]
        )
        db.add(res_item)
    
    db.commit()
    db.refresh(new_res)
    return new_res

@router.get("/", response_model=List[schemas.ReservationResponse])
def get_reservations(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    query = db.query(models.Reservation)

    if current_user.role == models.UserRole.Patient:
        query = query.filter(models.Reservation.patient_id == current_user.id)
    elif current_user.role == models.UserRole.Pharmacist:
        staff = db.query(models.PharmacyStaff).filter(models.PharmacyStaff.user_id == current_user.id).all()
        pharmacy_ids = [s.pharmacy_id for s in staff]
        if pharmacy_ids:
            query = query.filter(models.Reservation.pharmacy_id.in_(pharmacy_ids))
        else:
            # Fallback if pharmacist email matches pharmacy email
            pharma = db.query(models.Pharmacy).filter(models.Pharmacy.email == current_user.email).first()
            if pharma:
                query = query.filter(models.Reservation.pharmacy_id == pharma.id)
            else:
                return []
    # Admin gets all

    if status:
        query = query.filter(models.Reservation.status == status)

    return query.order_by(models.Reservation.date.desc()).offset(skip).limit(limit).all()

@router.get("/{res_id}", response_model=schemas.ReservationResponse)
def get_single_reservation(
    res_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    res = db.query(models.Reservation).filter(models.Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == models.UserRole.Patient and res.patient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this reservation")

    return res

@router.patch("/{res_id}/status", response_model=schemas.ReservationResponse)
def update_status(
    res_id: int,
    status: str,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    res = db.query(models.Reservation).filter(models.Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    status_map = {
        "Pending": models.ReservationStatus.Pending_Pharmacy_Review,
        "Pending Pharmacy Review": models.ReservationStatus.Pending_Pharmacy_Review,
        "Confirmed": models.ReservationStatus.Approved,
        "Approved": models.ReservationStatus.Approved,
        "Paid": models.ReservationStatus.Paid,
        "Ready for Pickup": models.ReservationStatus.Ready_for_Pickup,
        "Ready": models.ReservationStatus.Ready_for_Pickup,
        "Preparing": models.ReservationStatus.Preparing,
        "Out for Delivery": models.ReservationStatus.Out_for_Delivery,
        "Delivered": models.ReservationStatus.Delivered,
        "Picked Up": models.ReservationStatus.Collected,
        "Collected": models.ReservationStatus.Collected,
        "Completed": models.ReservationStatus.Collected,
        "Cancelled": models.ReservationStatus.Cancelled,
        "Rejected": models.ReservationStatus.Rejected,
    }

    if status in status_map:
        new_status = status_map[status]
    else:
        try:
            new_status = models.ReservationStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status '{status}'")

    # If patient is cancelling, verify they own the reservation
    if current_user.role == models.UserRole.Patient:
        if res.patient_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to update this reservation")

    # If approving, decrement inventory stock
    if new_status == models.ReservationStatus.Approved and res.status != models.ReservationStatus.Approved:
        for item in res.items:
            inv = db.query(models.Inventory).filter(
                models.Inventory.medicine_id == item.medicine_id,
                models.Inventory.pharmacy_id == res.pharmacy_id
            ).first()
            if inv:
                inv.stock_quantity = max(0, inv.stock_quantity - item.quantity)
                if inv.stock_quantity <= 0:
                    inv.status = "Out of Stock"
                elif inv.stock_quantity <= 20:
                    inv.status = "Low Stock"

    res.status = new_status
    db.commit()
    db.refresh(res)
    return res

@router.post("/{res_id}/cancel", response_model=schemas.ReservationResponse)
def cancel_reservation(
    res_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    res = db.query(models.Reservation).filter(models.Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == models.UserRole.Patient and res.patient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this reservation")

    res.status = models.ReservationStatus.Cancelled
    db.commit()
    db.refresh(res)
    return res

@router.patch("/{res_id}/fulfillment", response_model=schemas.ReservationResponse)
def update_fulfillment_payment(
    res_id: int,
    method: str,
    payment_pref: str,
    address: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    res = db.query(models.Reservation).filter(models.Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == models.UserRole.Patient and res.patient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this reservation")

    res.fulfillment_method = method
    res.payment_preference = payment_pref
    if address:
        res.fulfillment_address = address

    # Advance status based on fulfillment and payment preference
    if payment_pref == "Pay Online":
        # Keep Approved until payment processed
        pass
    else:
        if method == "Pickup":
            res.status = models.ReservationStatus.Ready_for_Pickup
        else:
            res.status = models.ReservationStatus.Preparing

    db.commit()
    db.refresh(res)
    return res
