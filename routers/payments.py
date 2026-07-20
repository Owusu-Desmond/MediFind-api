from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import models, schemas, deps
import uuid

router = APIRouter(
    prefix="/api/payments",
    tags=["Payments"],
)

@router.post("/initialize")
def initialize_payment(reservation_id: int, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_active_user)):
    res = db.query(models.Reservation).filter(models.Reservation.id == reservation_id, models.Reservation.patient_id == current_user.id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
        
    if res.payment_preference != "Pay Online":
        raise HTTPException(status_code=400, detail="Reservation is not set for online payment")
        
    reference = f"PS-{uuid.uuid4().hex[:12].upper()}"
    
    payment = models.Payment(
        reservation_id=res.id,
        amount=res.total_price,
        method="Paystack",
        status="Pending",
        reference=reference
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    
    return {"authorization_url": f"https://checkout.paystack.com/{reference}", "reference": reference}

@router.post("/verify")
def verify_payment(reference: str, db: Session = Depends(deps.get_db), current_user: models.User = Depends(deps.get_current_active_user)):
    payment = db.query(models.Payment).filter(models.Payment.reference == reference).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
        
    # Mocking successful verification
    payment.status = "Success"
    
    res = payment.reservation
    res.status = models.ReservationStatus.Paid
    
    db.commit()
    db.refresh(payment)
    db.refresh(res)
    
    return {"status": "Success", "message": "Payment verified successfully", "reservation_status": res.status}
