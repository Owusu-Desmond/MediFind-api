import logging
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import models

logger = logging.getLogger("notification_service")

class NotificationService:
    @staticmethod
    def send(
        db: Session,
        recipient_type: models.RecipientType,
        notification_type: str,
        title: str,
        message: str,
        recipient_user_id: Optional[int] = None,
        recipient_pharmacy_id: Optional[int] = None,
        priority: models.NotificationPriority = models.NotificationPriority.NORMAL,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        action_url: Optional[str] = None
    ) -> Optional[models.Notification]:
        """
        Creates and persists a notification in the database.
        Safe: will not crash the caller if an error occurs.
        """
        try:
            notification = models.Notification(
                recipient_type=recipient_type,
                recipient_user_id=recipient_user_id,
                recipient_pharmacy_id=recipient_pharmacy_id,
                notification_type=notification_type,
                title=title,
                message=message,
                priority=priority,
                reference_type=reference_type,
                reference_id=str(reference_id) if reference_id is not None else None,
                action_url=action_url,
                is_read=False,
                created_at=datetime.now(timezone.utc)
            )
            db.add(notification)
            db.flush()
            logger.info(f"[Notification] Sent '{notification_type}' to {recipient_type} (user={recipient_user_id}, pharmacy={recipient_pharmacy_id})")
            return notification
        except Exception as e:
            logger.error(f"[Notification] Failed to send notification: {e}")
            return None

    # ==========================================
    # Patient Mobile App Events
    # ==========================================

    @staticmethod
    def notify_patient_reservation_submitted(db: Session, reservation: models.Reservation, pharmacy_name: str):
        ref = reservation.reservation_code or reservation.ref_number or f"#{reservation.id}"
        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.PATIENT,
            recipient_user_id=reservation.patient_id,
            notification_type=models.NotificationType.RESERVATION_CREATED.value,
            title="Reservation Submitted 🔔",
            message=f"Your reservation ({ref}) at {pharmacy_name} has been submitted and is pending review.",
            reference_type="reservation",
            reference_id=str(reservation.id),
            action_url=f"/reservations/{reservation.id}",
            priority=models.NotificationPriority.NORMAL
        )

    @staticmethod
    def notify_patient_reservation_status(db: Session, reservation: models.Reservation, pharmacy_name: str, new_status: str, rejection_reason: Optional[str] = None):
        ref = reservation.reservation_code or reservation.ref_number or f"#{reservation.id}"
        
        status_configs = {
            models.ReservationStatus.Approved.value: {
                "type": models.NotificationType.RESERVATION_APPROVED.value,
                "title": "Reservation Confirmed ✅",
                "message": f"{pharmacy_name} has confirmed your reservation ({ref}).",
                "priority": models.NotificationPriority.NORMAL
            },
            models.ReservationStatus.Ready_for_Pickup.value: {
                "type": models.NotificationType.MEDICINE_READY_PICKUP.value,
                "title": "Medicine Ready for Pickup 💊",
                "message": f"Your reserved medicine ({ref}) at {pharmacy_name} is ready for pickup!",
                "priority": models.NotificationPriority.HIGH
            },
            models.ReservationStatus.Out_for_Delivery.value: {
                "type": models.NotificationType.DELIVERY_STATUS_CHANGED.value,
                "title": "Out for Delivery 🚚",
                "message": f"Your package from {pharmacy_name} ({ref}) is out for delivery.",
                "priority": models.NotificationPriority.HIGH
            },
            models.ReservationStatus.Delivered.value: {
                "type": models.NotificationType.DELIVERY_STATUS_CHANGED.value,
                "title": "Order Delivered 📦",
                "message": f"Your package from {pharmacy_name} ({ref}) has been delivered successfully.",
                "priority": models.NotificationPriority.NORMAL
            },
            models.ReservationStatus.Collected.value: {
                "type": models.NotificationType.RESERVATION_APPROVED.value,
                "title": "Order Collected 🎉",
                "message": f"Your order ({ref}) has been collected at {pharmacy_name}. Thank you!",
                "priority": models.NotificationPriority.NORMAL
            },
            models.ReservationStatus.Rejected.value: {
                "type": models.NotificationType.RESERVATION_REJECTED.value,
                "title": "Reservation Declined ❌",
                "message": f"Your reservation at {pharmacy_name} could not be fulfilled" + (f": {rejection_reason}" if rejection_reason else "."),
                "priority": models.NotificationPriority.HIGH
            },
            models.ReservationStatus.Cancelled.value: {
                "type": models.NotificationType.RESERVATION_CANCELLED.value,
                "title": "Reservation Cancelled ❌",
                "message": f"Reservation ({ref}) has been cancelled.",
                "priority": models.NotificationPriority.NORMAL
            }
        }

        config = status_configs.get(new_status)
        if not config:
            return None

        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.PATIENT,
            recipient_user_id=reservation.patient_id,
            notification_type=config["type"],
            title=config["title"],
            message=config["message"],
            reference_type="reservation",
            reference_id=str(reservation.id),
            action_url=f"/reservations/{reservation.id}",
            priority=config["priority"]
        )

    @staticmethod
    def notify_patient_payment_result(db: Session, reservation: models.Reservation, pharmacy_name: str, success: bool, reason: Optional[str] = None):
        ref = reservation.reservation_code or reservation.ref_number or f"#{reservation.id}"
        if success:
            return NotificationService.send(
                db=db,
                recipient_type=models.RecipientType.PATIENT,
                recipient_user_id=reservation.patient_id,
                notification_type=models.NotificationType.PAYMENT_SUCCESS.value,
                title="Payment Successful 💳",
                message=f"Payment for your reservation ({ref}) at {pharmacy_name} was successful.",
                reference_type="reservation",
                reference_id=str(reservation.id),
                action_url=f"/reservations/{reservation.id}",
                priority=models.NotificationPriority.NORMAL
            )
        else:
            return NotificationService.send(
                db=db,
                recipient_type=models.RecipientType.PATIENT,
                recipient_user_id=reservation.patient_id,
                notification_type=models.NotificationType.PAYMENT_FAILED.value,
                title="Payment Failed 💰",
                message=f"Payment for reservation ({ref}) could not be completed" + (f": {reason}" if reason else "."),
                reference_type="reservation",
                reference_id=str(reservation.id),
                action_url=f"/reservations/{reservation.id}",
                priority=models.NotificationPriority.HIGH
            )

    # ==========================================
    # Pharmacy Portal Events
    # ==========================================

    @staticmethod
    def notify_pharmacy_new_reservation(db: Session, reservation: models.Reservation, patient_name: str, item_summary: str):
        ref = reservation.reservation_code or reservation.ref_number or f"#{reservation.id}"
        fulfillment_str = f" [{reservation.fulfillment_method}]" if reservation.fulfillment_method else ""
        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.PHARMACY,
            recipient_pharmacy_id=reservation.pharmacy_id,
            notification_type=models.NotificationType.NEW_RESERVATION.value,
            title="New Reservation Received 🔔",
            message=f"New reservation ({ref}) from {patient_name} for {item_summary}{fulfillment_str}.",
            reference_type="reservation",
            reference_id=str(reservation.id),
            action_url=f"/reservations?id={reservation.id}",
            priority=models.NotificationPriority.HIGH
        )

    @staticmethod
    def notify_pharmacy_patient_cancelled(db: Session, reservation: models.Reservation, patient_name: str):
        ref = reservation.reservation_code or reservation.ref_number or f"#{reservation.id}"
        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.PHARMACY,
            recipient_pharmacy_id=reservation.pharmacy_id,
            notification_type=models.NotificationType.PATIENT_CANCELLED.value,
            title="Patient Cancelled Reservation 💊",
            message=f"{patient_name} cancelled reservation ({ref}).",
            reference_type="reservation",
            reference_id=str(reservation.id),
            action_url=f"/reservations?id={reservation.id}",
            priority=models.NotificationPriority.NORMAL
        )

    @staticmethod
    def notify_pharmacy_payment_received(db: Session, reservation: models.Reservation, amount: float, method: str = "Online"):
        ref = reservation.reservation_code or reservation.ref_number or f"#{reservation.id}"
        title = "Online Payment Received 💳" if method.upper() == "PAYSTACK" else "Cash Payment Confirmed 💰"
        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.PHARMACY,
            recipient_pharmacy_id=reservation.pharmacy_id,
            notification_type=models.NotificationType.PAYMENT_RECEIVED.value,
            title=title,
            message=f"Payment of GHS {amount:.2f} received for reservation ({ref}).",
            reference_type="reservation",
            reference_id=str(reservation.id),
            action_url=f"/reservations?id={reservation.id}",
            priority=models.NotificationPriority.NORMAL
        )

    @staticmethod
    def notify_pharmacy_verification_update(db: Session, pharmacy: models.Pharmacy, status: models.PharmacyStatus, reason: Optional[str] = None):
        if status == models.PharmacyStatus.Approved:
            title = "Pharmacy Verification Approved 📋"
            msg = f"Congratulations! Your pharmacy '{pharmacy.name}' has been verified and approved."
            notif_type = models.NotificationType.PHARMACY_APPROVED.value
            priority = models.NotificationPriority.HIGH
        elif status == models.PharmacyStatus.Suspended:
            title = "Pharmacy Account Suspended 🏥"
            msg = f"Your pharmacy account '{pharmacy.name}' has been suspended" + (f": {reason}" if reason else ".")
            notif_type = models.NotificationType.PHARMACY_STATUS_CHANGE.value
            priority = models.NotificationPriority.URGENT
        else:
            title = "Pharmacy Verification Update ❌"
            msg = f"Verification update for '{pharmacy.name}'" + (f": {reason}" if reason else ".")
            notif_type = models.NotificationType.PHARMACY_REJECTED.value
            priority = models.NotificationPriority.HIGH

        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.PHARMACY,
            recipient_pharmacy_id=pharmacy.id,
            notification_type=notif_type,
            title=title,
            message=msg,
            reference_type="pharmacy",
            reference_id=str(pharmacy.id),
            action_url="/profile",
            priority=priority
        )

    @staticmethod
    def notify_pharmacy_low_stock(db: Session, pharmacy_id: int, medicine_name: str, remaining_stock: int):
        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.PHARMACY,
            recipient_pharmacy_id=pharmacy_id,
            notification_type=models.NotificationType.LOW_STOCK_ALERT.value,
            title="Low Stock Alert ⚠️",
            message=f"{medicine_name} is running low ({remaining_stock} units left). Consider restocking soon.",
            reference_type="inventory",
            reference_id=medicine_name,
            action_url="/inventory",
            priority=models.NotificationPriority.HIGH
        )

    # ==========================================
    # Admin Dashboard Events
    # ==========================================

    @staticmethod
    def notify_admin_new_pharmacy(db: Session, pharmacy: models.Pharmacy):
        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.ADMIN,
            notification_type=models.NotificationType.ADMIN_NEW_PHARMACY.value,
            title="New Pharmacy Registered 🏥",
            message=f"'{pharmacy.name}' in {pharmacy.location} has registered and is awaiting verification.",
            reference_type="pharmacy",
            reference_id=str(pharmacy.id),
            action_url=f"/pharmacies",
            priority=models.NotificationPriority.HIGH
        )

    @staticmethod
    def notify_admin_certificate_submitted(db: Session, pharmacy: models.Pharmacy):
        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.ADMIN,
            notification_type=models.NotificationType.ADMIN_CERTIFICATE_SUBMITTED.value,
            title="New Certificate Submitted 📄",
            message=f"'{pharmacy.name}' has uploaded a pharmacy license/certificate for review.",
            reference_type="pharmacy",
            reference_id=str(pharmacy.id),
            action_url=f"/pharmacies",
            priority=models.NotificationPriority.NORMAL
        )

    @staticmethod
    def notify_admin_payment_failure(db: Session, reference: str, error_details: str):
        return NotificationService.send(
            db=db,
            recipient_type=models.RecipientType.ADMIN,
            notification_type=models.NotificationType.ADMIN_PAYMENT_FAILURE.value,
            title="Payment / Webhook Issue 💳",
            message=f"Payment transaction {reference} encountered an issue: {error_details}",
            reference_type="payment",
            reference_id=reference,
            action_url="/payments",
            priority=models.NotificationPriority.HIGH
        )
