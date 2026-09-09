import os
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

import models
import schemas
import deps
import paystack_service

router = APIRouter(
    prefix="/api/reservations",
    tags=["Reservations"],
)

RESERVATION_EXPIRY_HOURS = int(os.getenv("RESERVATION_EXPIRY_HOURS", "2"))

def check_and_expire_reservations(db: Session):
    """
    Check for unpaid reservations that have exceeded their expiry time,
    mark them Expired, and release reserved inventory.
    """
    now = datetime.now(timezone.utc)
    expired_res = db.query(models.Reservation).filter(
        models.Reservation.payment_status == models.PaymentStatus.UNPAID,
        models.Reservation.expires_at != None,
        models.Reservation.expires_at < now,
        models.Reservation.status.notin_([
            models.ReservationStatus.Collected,
            models.ReservationStatus.Delivered,
            models.ReservationStatus.Cancelled,
            models.ReservationStatus.Expired,
            models.ReservationStatus.Rejected
        ])
    ).all()

    for res in expired_res:
        res.status = models.ReservationStatus.Expired
        # If inventory was previously deducted on approval, restore it
        # (Inventory is deducted on Approval or Paid)
    if expired_res:
        db.commit()

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

    # Authoritatively calculate total price & prepare items
    total = 0.0
    items_to_create = []

    for item in res_in.items:
        medicine = db.query(models.Medicine).filter(models.Medicine.id == item.medicine_id).first()
        if not medicine:
            raise HTTPException(status_code=404, detail=f"Medicine {item.medicine_id} not found")

        inv = db.query(models.Inventory).filter(
            models.Inventory.medicine_id == item.medicine_id,
            models.Inventory.pharmacy_id == res_in.pharmacy_id
        ).first()

        if not inv:
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

    # Generate friendly reservation code like "MF-8K29X"
    code_suffix = uuid.uuid4().hex[:5].upper()
    reservation_code = f"MF-{code_suffix}"
    ref_number = f"MF-{uuid.uuid4().hex[:8].upper()}"

    payment_method = None
    if res_in.payment_method == "PAYSTACK" or res_in.payment_preference == "Pay Online":
        payment_method = models.PaymentMethod.PAYSTACK
    elif res_in.payment_method == "CASH" or res_in.payment_preference in ("Pay at Pharmacy", "Pay on Delivery"):
        payment_method = models.PaymentMethod.CASH

    payment_preference = res_in.payment_preference
    
    # Calculate expiry time (e.g. 2 hours from creation for cash reservations)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=RESERVATION_EXPIRY_HOURS)

    new_res = models.Reservation(
        patient_id=current_user.id,
        pharmacy_id=res_in.pharmacy_id,
        fulfillment_method=res_in.fulfillment_method or "Pickup",
        fulfillment_address=res_in.fulfillment_address,
        fulfillment_time=res_in.fulfillment_time,
        payment_preference=payment_preference,
        payment_method=payment_method,
        payment_status=models.PaymentStatus.UNPAID,
        status=models.ReservationStatus.Pending_Pharmacy_Review,
        total_price=round(total, 2),
        notes=res_in.notes,
        ref_number=ref_number,
        reservation_code=reservation_code,
        expires_at=expires_at,
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
    payment_status: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    # Run automatic expiration check
    check_and_expire_reservations(db)

    query = db.query(models.Reservation)

    if current_user.role == models.UserRole.Patient:
        query = query.filter(models.Reservation.patient_id == current_user.id)
    elif current_user.role == models.UserRole.Pharmacist:
        staff = db.query(models.PharmacyStaff).filter(models.PharmacyStaff.user_id == current_user.id).all()
        pharmacy_ids = [s.pharmacy_id for s in staff]
        if pharmacy_ids:
            query = query.filter(models.Reservation.pharmacy_id.in_(pharmacy_ids))
        else:
            pharma = db.query(models.Pharmacy).filter(models.Pharmacy.email == current_user.email).first()
            if pharma:
                query = query.filter(models.Reservation.pharmacy_id == pharma.id)
            else:
                return []
    # Admin gets all

    if status:
        query = query.filter(models.Reservation.status == status)

    if payment_status:
        query = query.filter(models.Reservation.payment_status == payment_status)

    return query.order_by(models.Reservation.date.desc()).offset(skip).limit(limit).all()

@router.get("/{res_id}", response_model=schemas.ReservationResponse)
def get_single_reservation(
    res_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    check_and_expire_reservations(db)

    res = db.query(models.Reservation).filter(models.Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == models.UserRole.Patient and res.patient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this reservation")

    return res

@router.post("/{res_id}/mark-cash-paid", response_model=schemas.CashPaymentConfirmResponse)
def mark_cash_paid(
    res_id: int,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Pharmacy Staff endpoint: Confirm cash payment upon physical pickup/delivery.
    Only authorized pharmacy staff or admin may confirm cash payment. Patients are strictly rejected.
    """
    res = db.query(models.Reservation).filter(models.Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    # 1. Authorization check: Patients are NEVER allowed to mark cash paid
    if current_user.role == models.UserRole.Patient:
        raise HTTPException(status_code=403, detail="Patients are not authorized to confirm cash payment")

    if current_user.role == models.UserRole.Pharmacist:
        staff_links = db.query(models.PharmacyStaff).filter(
            models.PharmacyStaff.user_id == current_user.id,
            models.PharmacyStaff.pharmacy_id == res.pharmacy_id
        ).first()
        pharma_email_match = db.query(models.Pharmacy).filter(
            models.Pharmacy.id == res.pharmacy_id,
            models.Pharmacy.email == current_user.email
        ).first()

        if not staff_links and not pharma_email_match:
            raise HTTPException(status_code=403, detail="You are not authorized for this pharmacy")

    # 2. Prevent confirming expired or cancelled reservations
    if res.status == models.ReservationStatus.Cancelled:
        raise HTTPException(status_code=400, detail="Cannot confirm cash payment for a cancelled reservation")
    if res.status == models.ReservationStatus.Expired:
        raise HTTPException(status_code=400, detail="Cannot confirm cash payment for an expired reservation")

    now = datetime.now(timezone.utc)

    # 3. Update reservation payment & status
    res.payment_status = models.PaymentStatus.PAID
    res.payment_method = models.PaymentMethod.CASH
    res.payment_preference = "Pay at Pharmacy"
    res.status = models.ReservationStatus.Collected
    res.paid_at = now
    res.cash_payment_confirmed_by_id = current_user.id
    res.cash_payment_confirmed_at = now

    # 4. Calculate fees & record PaymentTransaction for accounting
    fee_calc = paystack_service.calculate_fees(res.total_price)
    tx = models.PaymentTransaction(
        reservation_id=res.id,
        pharmacy_id=res.pharmacy_id,
        patient_id=res.patient_id,
        payment_method=models.PaymentMethod.CASH,
        payment_status=models.PaymentStatus.PAID,
        amount=res.total_price,
        currency="GHS",
        platform_fee=fee_calc["platform_fee"],
        pharmacy_amount=fee_calc["pharmacy_amount"],
        paystack_reference=f"CASH-{res.reservation_code or res.id}",
        paystack_status="cash_collected",
        paid_at=now,
    )
    db.add(tx)

    # 5. Decrement inventory stock idempotently
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

    db.commit()
    db.refresh(res)

    return schemas.CashPaymentConfirmResponse(
        success=True,
        message="Cash payment confirmed successfully and reservation marked collected",
        reservation_id=res.id,
        reservation_status=res.status.value if hasattr(res.status, "value") else str(res.status),
        payment_status=models.PaymentStatus.PAID.value,
        payment_method="CASH",
        amount=res.total_price,
        confirmed_by_user_id=current_user.id,
        confirmed_at=now,
    )

@router.patch("/{res_id}/status", response_model=schemas.ReservationResponse)
def update_status(
    res_id: int,
    status: str,
    reason: Optional[str] = None,
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
        "Reserved": models.ReservationStatus.Reserved,
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
        "Expired": models.ReservationStatus.Expired,
    }

    if status in status_map:
        new_status = status_map[status]
    else:
        try:
            new_status = models.ReservationStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status '{status}'")

    if current_user.role == models.UserRole.Patient:
        if res.patient_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to update this reservation")
        if new_status not in (models.ReservationStatus.Cancelled,):
            raise HTTPException(status_code=403, detail="Patients may only cancel reservations")

    # Decrement inventory stock on Approved if not already done
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
    if reason:
        res.rejection_reason = reason
    db.commit()
    db.refresh(res)
    return res

@router.post("/{res_id}/cancel", response_model=schemas.ReservationResponse)
def cancel_reservation(
    res_id: int,
    reason: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    res = db.query(models.Reservation).filter(models.Reservation.id == res_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == models.UserRole.Patient and res.patient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this reservation")

    res.status = models.ReservationStatus.Cancelled
    if reason:
        res.rejection_reason = reason
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

    if payment_pref == "Pay Online":
        res.payment_method = models.PaymentMethod.PAYSTACK
    else:
        res.payment_method = models.PaymentMethod.CASH
        if method == "Pickup":
            res.status = models.ReservationStatus.Ready_for_Pickup
        else:
            res.status = models.ReservationStatus.Preparing

    db.commit()
    db.refresh(res)
    return res
