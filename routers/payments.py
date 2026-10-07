import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.orm import Session
from typing import List, Optional

import models
import schemas
import deps
import paystack_service
from notification_service import NotificationService

router = APIRouter(
    prefix="/api/payments",
    tags=["Payments"],
)

@router.get("/banks")
async def get_banks():
    """
    List supported Ghana banks and mobile money channels from Paystack.
    """
    banks = await paystack_service.fetch_paystack_banks(country="ghana")
    return banks

@router.post("/initialize", response_model=schemas.PaymentInitializeResponse)
async def initialize_payment(
    req: schemas.PaymentInitializeRequest,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Initialize a Paystack transaction for a reservation with server-side authoritative
    amount calculation and Paystack subaccount split payment routing.
    """
    # 1. Fetch reservation and verify ownership
    res = db.query(models.Reservation).filter(
        models.Reservation.id == req.reservation_id
    ).first()

    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if current_user.role == models.UserRole.Patient and res.patient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to pay for this reservation")

    # 2. Prevent double payment
    if res.payment_status == models.PaymentStatus.PAID:
        raise HTTPException(status_code=400, detail="This reservation has already been paid")

    if res.status in (models.ReservationStatus.Cancelled, models.ReservationStatus.Expired):
        raise HTTPException(status_code=400, detail=f"Cannot pay for a {res.status.value} reservation")

    # 3. Check expiration
    if res.expires_at and res.expires_at < datetime.now(timezone.utc):
        res.status = models.ReservationStatus.Expired
        db.commit()
        raise HTTPException(status_code=400, detail="This reservation has expired")

    # 4. Calculate authoritative amount from items
    total_amount = 0.0
    for item in res.items:
        # Check current inventory price
        inv = db.query(models.Inventory).filter(
            models.Inventory.medicine_id == item.medicine_id,
            models.Inventory.pharmacy_id == res.pharmacy_id
        ).first()
        unit_price = inv.price if (inv and inv.price > 0) else (item.price or 15.0)
        total_amount += unit_price * item.quantity

    if total_amount <= 0:
        total_amount = res.total_price if res.total_price > 0 else 15.0

    # Ensure reservation total_price is up to date
    res.total_price = total_amount
    res.payment_method = models.PaymentMethod.PAYSTACK
    res.payment_preference = "Pay Online"

    # 5. Calculate platform fee & pharmacy split
    fee_calc = paystack_service.calculate_fees(total_amount)
    platform_fee = fee_calc["platform_fee"]
    pharmacy_amount = fee_calc["pharmacy_amount"]

    # 6. Fetch pharmacy Paystack subaccount
    pharmacy = db.query(models.Pharmacy).filter(models.Pharmacy.id == res.pharmacy_id).first()
    subaccount_code = pharmacy.paystack_subaccount_code if pharmacy else None

    # 7. Generate unique Paystack transaction reference
    reference = f"MF-PS-{uuid.uuid4().hex[:12].upper()}"

    # 8. Create pending PaymentTransaction record
    tx = models.PaymentTransaction(
        reservation_id=res.id,
        pharmacy_id=res.pharmacy_id,
        patient_id=res.patient_id,
        payment_method=models.PaymentMethod.PAYSTACK,
        payment_status=models.PaymentStatus.PENDING,
        amount=total_amount,
        currency="GHS",
        platform_fee=platform_fee,
        pharmacy_amount=pharmacy_amount,
        paystack_reference=reference,
        paystack_status="pending",
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    # 9. Call Paystack API to initialize transaction
    paystack_res = await paystack_service.initialize_paystack_transaction(
        email=current_user.email,
        amount_in_ghs=total_amount,
        reference=reference,
        callback_url=req.callback_url or f"https://medifind.gh/checkout/callback?reference={reference}",
        subaccount_code=subaccount_code,
        metadata={
            "reservation_id": res.id,
            "pharmacy_id": res.pharmacy_id,
            "patient_id": res.patient_id,
            "ref_number": res.ref_number or res.reservation_code,
        }
    )

    if not paystack_res.get("status"):
        tx.payment_status = models.PaymentStatus.FAILED
        tx.paystack_status = "initialization_failed"
        db.commit()
        raise HTTPException(
            status_code=502,
            detail=f"Paystack initialization failed: {paystack_res.get('message', 'Unknown error')}"
        )

    return schemas.PaymentInitializeResponse(
        status=True,
        authorization_url=paystack_res.get("authorization_url", ""),
        access_code=paystack_res.get("access_code"),
        reference=reference,
        amount=total_amount,
        currency="GHS",
        platform_fee=platform_fee,
        pharmacy_amount=pharmacy_amount,
        is_mock=paystack_res.get("is_mock", False),
    )

@router.get("/verify/{reference}", response_model=schemas.PaymentVerifyResponse)
@router.post("/verify", response_model=schemas.PaymentVerifyResponse)
async def verify_payment(
    reference: Optional[str] = None,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Idempotent server-side payment verification with Paystack API.
    Verifies transaction status and updates reservation & payment records.
    """
    if not reference:
        raise HTTPException(status_code=400, detail="Payment reference is required")

    # Find the corresponding transaction
    tx = db.query(models.PaymentTransaction).filter(
        models.PaymentTransaction.paystack_reference == reference
    ).first()

    if not tx:
        raise HTTPException(status_code=404, detail=f"Transaction with reference '{reference}' not found")

    res = tx.reservation
    if not res:
        raise HTTPException(status_code=404, detail="Associated reservation not found")

    # Idempotent check: If already marked PAID, return success immediately
    if tx.payment_status == models.PaymentStatus.PAID and res.payment_status == models.PaymentStatus.PAID:
        return schemas.PaymentVerifyResponse(
            status="Success",
            message="Payment already verified and confirmed",
            reservation_id=res.id,
            reservation_status=res.status.value if hasattr(res.status, "value") else str(res.status),
            payment_status=res.payment_status.value if hasattr(res.payment_status, "value") else str(res.payment_status),
            payment_method="PAYSTACK",
            amount=tx.amount,
            currency=tx.currency,
            reference=reference,
            paid_at=tx.paid_at,
        )

    # Call Paystack to verify
    verification = await paystack_service.verify_paystack_transaction(reference)

    now = datetime.now(timezone.utc)

    if verification.get("status") and verification.get("transaction_status") == "success":
        tx.payment_status = models.PaymentStatus.PAID
        tx.paystack_status = "success"
        tx.paid_at = now
        if verification.get("transaction_id"):
            tx.paystack_transaction_id = verification["transaction_id"]

        res.payment_status = models.PaymentStatus.PAID
        res.payment_method = models.PaymentMethod.PAYSTACK
        res.paid_at = now
        res.payment_verified_at = now
        
        # Advance reservation status
        if res.fulfillment_method == "Delivery":
            res.status = models.ReservationStatus.Preparing
        else:
            res.status = models.ReservationStatus.Ready_for_Pickup

        # Decrement inventory stock idempotently
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

                if inv.stock_quantity <= 5:
                    med_name = item.medicine.name if item.medicine else "Medicine"
                    NotificationService.notify_pharmacy_low_stock(db, res.pharmacy_id, med_name, inv.stock_quantity)

        # Dispatch notifications
        pharmacy_name = res.pharmacy.name if res.pharmacy else "Pharmacy"
        NotificationService.notify_patient_payment_result(db, res, pharmacy_name, success=True)
        NotificationService.notify_pharmacy_payment_received(db, res, tx.amount, method="PAYSTACK")

        db.commit()
        db.refresh(tx)
        db.refresh(res)

        return schemas.PaymentVerifyResponse(
            status="Success",
            message="Payment successfully verified",
            reservation_id=res.id,
            reservation_status=res.status.value if hasattr(res.status, "value") else str(res.status),
            payment_status=models.PaymentStatus.PAID.value,
            payment_method="PAYSTACK",
            amount=tx.amount,
            currency=tx.currency,
            reference=reference,
            paid_at=now,
        )
    else:
        tx.payment_status = models.PaymentStatus.FAILED
        tx.paystack_status = verification.get("transaction_status", "failed")
        
        # Dispatch failure notifications
        pharmacy_name = res.pharmacy.name if res.pharmacy else "Pharmacy"
        err_msg = verification.get("message", "Payment verification failed or transaction not completed")
        NotificationService.notify_patient_payment_result(db, res, pharmacy_name, success=False, reason=err_msg)
        NotificationService.notify_admin_payment_failure(db, reference, err_msg)

        db.commit()

        return schemas.PaymentVerifyResponse(
            status="Failed",
            message=err_msg,
            reservation_id=res.id,
            reservation_status=res.status.value if hasattr(res.status, "value") else str(res.status),
            payment_status=models.PaymentStatus.FAILED.value,
            payment_method="PAYSTACK",
            amount=tx.amount,
            currency=tx.currency,
            reference=reference,
            paid_at=None,
        )

@router.post("/paystack/webhook")
async def paystack_webhook(
    request: Request,
    db: Session = Depends(deps.get_db),
    x_paystack_signature: Optional[str] = Header(None, alias="x-paystack-signature")
):
    """
    Paystack Webhook Endpoint.
    Validates HMAC SHA512 signature and processes payment events idempotently.
    """
    body_bytes = await request.body()

    # 1. Validate signature
    if not paystack_service.verify_paystack_webhook_signature(body_bytes, x_paystack_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        event_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event_data.get("event")
    data = event_data.get("data", {})
    reference = data.get("reference")

    if not reference:
        return {"status": "ignored", "message": "No reference in payload"}

    if event_type == "charge.success":
        tx = db.query(models.PaymentTransaction).filter(
            models.PaymentTransaction.paystack_reference == reference
        ).first()

        if tx and tx.payment_status != models.PaymentStatus.PAID:
            now = datetime.now(timezone.utc)
            tx.payment_status = models.PaymentStatus.PAID
            tx.paystack_status = "success"
            tx.paid_at = now
            if data.get("id"):
                tx.paystack_transaction_id = str(data["id"])

            res = tx.reservation
            if res:
                res.payment_status = models.PaymentStatus.PAID
                res.payment_method = models.PaymentMethod.PAYSTACK
                res.paid_at = now
                res.payment_verified_at = now

                if res.fulfillment_method == "Delivery":
                    res.status = models.ReservationStatus.Preparing
                else:
                    res.status = models.ReservationStatus.Ready_for_Pickup

                # Decrement inventory stock
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

                        if inv.stock_quantity <= 5:
                            med_name = item.medicine.name if item.medicine else "Medicine"
                            NotificationService.notify_pharmacy_low_stock(db, res.pharmacy_id, med_name, inv.stock_quantity)

                # Notifications
                pharmacy_name = res.pharmacy.name if res.pharmacy else "Pharmacy"
                NotificationService.notify_patient_payment_result(db, res, pharmacy_name, success=True)
                NotificationService.notify_pharmacy_payment_received(db, res, tx.amount, method="PAYSTACK")

            db.commit()
    elif event_type in ("charge.failed", "transfer.failed"):
        NotificationService.notify_admin_payment_failure(db, reference, f"Webhook received {event_type}")
        db.commit()

    return {"status": "ok"}

@router.get("/transactions", response_model=List[schemas.PaymentTransactionResponse])
def get_payment_transactions(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    pharmacy_id: Optional[int] = None,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    List payment transactions for Admin or Pharmacy Staff.
    """
    query = db.query(models.PaymentTransaction)

    if current_user.role == models.UserRole.Patient:
        query = query.filter(models.PaymentTransaction.patient_id == current_user.id)
    elif current_user.role == models.UserRole.Pharmacist:
        staff = db.query(models.PharmacyStaff).filter(models.PharmacyStaff.user_id == current_user.id).all()
        pharmacy_ids = [s.pharmacy_id for s in staff]
        if pharmacy_ids:
            query = query.filter(models.PaymentTransaction.pharmacy_id.in_(pharmacy_ids))
        else:
            pharma = db.query(models.Pharmacy).filter(models.Pharmacy.email == current_user.email).first()
            if pharma:
                query = query.filter(models.PaymentTransaction.pharmacy_id == pharma.id)
            else:
                return []
    else:
        # Admin can filter by pharmacy_id if requested
        if pharmacy_id:
            query = query.filter(models.PaymentTransaction.pharmacy_id == pharmacy_id)

    if status:
        query = query.filter(models.PaymentTransaction.payment_status == status)

    return query.order_by(models.PaymentTransaction.created_at.desc()).offset(skip).limit(limit).all()
