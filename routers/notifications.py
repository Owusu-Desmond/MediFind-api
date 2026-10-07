from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc
from typing import List, Optional
from datetime import datetime, timezone

from database import get_db
import models, schemas, deps

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"]
)

def _get_user_notification_filter(current_user: models.User, db: Session):
    """
    Builds the base SQLAlchemy filter condition depending on the authenticated user's role:
    - Admin: RecipientType.ADMIN or direct user notification
    - Pharmacist: RecipientType.PHARMACY for all assigned pharmacies or direct user notification
    - Patient: RecipientType.PATIENT and direct user notification
    """
    if current_user.role == models.UserRole.Admin:
        return or_(
            models.Notification.recipient_type == models.RecipientType.ADMIN,
            models.Notification.recipient_user_id == current_user.id
        )
    elif current_user.role == models.UserRole.Pharmacist:
        staff_records = db.query(models.PharmacyStaff).filter(models.PharmacyStaff.user_id == current_user.id).all()
        pharmacy_ids = [s.pharmacy_id for s in staff_records]
        
        conditions = [models.Notification.recipient_user_id == current_user.id]
        if pharmacy_ids:
            conditions.append(
                and_(
                    models.Notification.recipient_type == models.RecipientType.PHARMACY,
                    models.Notification.recipient_pharmacy_id.in_(pharmacy_ids)
                )
            )
        return or_(*conditions)
    else: # Patient
        return and_(
            models.Notification.recipient_type == models.RecipientType.PATIENT,
            models.Notification.recipient_user_id == current_user.id
        )

@router.get("", response_model=schemas.NotificationListResponse)
@router.get("/", response_model=schemas.NotificationListResponse)
def get_notifications(
    unread_only: bool = Query(False, description="Filter only unread notifications"),
    limit: int = Query(50, ge=1, le=100, description="Max notifications to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db)
):
    base_filter = _get_user_notification_filter(current_user, db)
    
    query = db.query(models.Notification).filter(base_filter)
    
    total = query.count()
    unread_count = query.filter(models.Notification.is_read == False).count()
    
    if unread_only:
        query = query.filter(models.Notification.is_read == False)
        
    items = query.order_by(desc(models.Notification.created_at)).offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "unread_count": unread_count,
        "items": items
    }

@router.get("/unread-count", response_model=schemas.UnreadCountResponse)
def get_unread_count(
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db)
):
    base_filter = _get_user_notification_filter(current_user, db)
    unread_count = db.query(models.Notification).filter(
        base_filter,
        models.Notification.is_read == False
    ).count()
    
    return {"unread_count": unread_count}

@router.patch("/{notification_id}/read", response_model=schemas.NotificationResponse)
def mark_notification_read(
    notification_id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db)
):
    base_filter = _get_user_notification_filter(current_user, db)
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        base_filter
    ).first()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
        
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
        
    return notification

@router.post("/mark-all-read", response_model=schemas.MarkReadResponse)
def mark_all_notifications_read(
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db)
):
    base_filter = _get_user_notification_filter(current_user, db)
    now = datetime.now(timezone.utc)
    
    updated_count = db.query(models.Notification).filter(
        base_filter,
        models.Notification.is_read == False
    ).update(
        {
            models.Notification.is_read: True,
            models.Notification.read_at: now
        },
        synchronize_session=False
    )
    db.commit()
    
    return {
        "success": True,
        "message": "All notifications marked as read",
        "marked_count": updated_count
    }

@router.delete("/clear-all", response_model=schemas.ClearNotificationsResponse)
def clear_all_notifications(
    read_only: bool = Query(False, description="If true, clears only read notifications; otherwise clears all"),
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db)
):
    base_filter = _get_user_notification_filter(current_user, db)
    query = db.query(models.Notification).filter(base_filter)
    if read_only:
        query = query.filter(models.Notification.is_read == True)
        
    cleared_count = query.delete(synchronize_session=False)
    db.commit()
    
    return {
        "success": True,
        "message": "Notifications cleared successfully",
        "cleared_count": cleared_count
    }

@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notification_id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(get_db)
):
    base_filter = _get_user_notification_filter(current_user, db)
    notification = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        base_filter
    ).first()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
        
    db.delete(notification)
    db.commit()
    return None
