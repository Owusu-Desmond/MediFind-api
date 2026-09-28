from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, Enum, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

class UserRole(str, enum.Enum):
    Patient = "Patient"
    Pharmacist = "Pharmacist"
    Admin = "Admin"

class UserStatus(str, enum.Enum):
    Active = "Active"
    Suspended = "Suspended"

class PharmacyStatus(str, enum.Enum):
    Approved = "Approved"
    Pending_Approval = "Pending Approval"
    Suspended = "Suspended"

class ReservationStatus(str, enum.Enum):
    Pending_Pharmacy_Review = "Pending Pharmacy Review"
    Approved = "Approved"
    Reserved = "Reserved"
    Paid = "Paid"
    Ready_for_Pickup = "Ready for Pickup"
    Preparing = "Preparing"
    Out_for_Delivery = "Out for Delivery"
    Delivered = "Delivered"
    Collected = "Collected"
    Cancelled = "Cancelled"
    Expired = "Expired"
    Rejected = "Rejected"

class PaymentMethod(str, enum.Enum):
    PAYSTACK = "PAYSTACK"
    CASH = "CASH"

class PaymentStatus(str, enum.Enum):
    UNPAID = "UNPAID"
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.Patient, nullable=False)
    phone = Column(String, nullable=True)
    location = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    status = Column(Enum(UserStatus), default=UserStatus.Active)
    date_created = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    reservations = relationship("Reservation", back_populates="patient", foreign_keys="Reservation.patient_id")

class Pharmacy(Base):
    __tablename__ = "pharmacies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    location = Column(String, nullable=False)
    license_number = Column(String, unique=True, nullable=False)
    pharmacist_name = Column(String, nullable=True)
    pharmacist_id = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, unique=True, nullable=True)
    status = Column(Enum(PharmacyStatus), default=PharmacyStatus.Pending_Approval)
    date_submitted = Column(DateTime(timezone=True), server_default=func.now())
    delivery_offered = Column(Boolean, default=False)
    opening_hours = Column(String, nullable=True)
    gps_address = Column(String, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    verified = Column(Boolean, default=False)
    certificate_url = Column(String, nullable=True)

    # Paystack & Payout details
    paystack_subaccount_code = Column(String, nullable=True) # e.g. "ACCT_xxxx"
    paystack_subaccount_id = Column(String, nullable=True)
    paystack_subaccount_status = Column(String, default="PENDING") # "ACTIVE", "PENDING", "FAILED"
    payment_account_type = Column(String, nullable=True) # "bank" or "mobile_money"
    bank_name = Column(String, nullable=True)
    bank_code = Column(String, nullable=True)
    account_name = Column(String, nullable=True)
    account_number = Column(String, nullable=True)
    mobile_money_provider = Column(String, nullable=True)
    mobile_money_number = Column(String, nullable=True)
    payment_account_verified = Column(Boolean, default=False)
    payment_account_verified_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    staff = relationship("PharmacyStaff", back_populates="pharmacy", cascade="all, delete-orphan")
    inventory = relationship("Inventory", back_populates="pharmacy", cascade="all, delete-orphan")
    reservations = relationship("Reservation", back_populates="pharmacy", cascade="all, delete-orphan")
    payments = relationship("PaymentTransaction", back_populates="pharmacy")

class PharmacyStaff(Base):
    __tablename__ = "pharmacy_staff"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"), nullable=False)

    user = relationship("User")
    pharmacy = relationship("Pharmacy", back_populates="staff")

class Medicine(Base):
    __tablename__ = "medicines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False) # Brand / Trade Name
    generic_name = Column(String, index=True, nullable=True) # INN / Generic Name
    strength = Column(String, nullable=True) # e.g. "500mg", "100mg/5ml", "80/480mg"
    dosage_form = Column(String, index=True, nullable=True) # e.g. "Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Inhaler", "Ointment", "Drops"
    route_of_administration = Column(String, nullable=True) # e.g. "Oral", "Intravenous", "Topical", "Inhalation", "Ophthalmic"
    dosage = Column(String, nullable=True) # Kept for backward compatibility
    dosage_instructions = Column(Text, nullable=True)
    category = Column(String, index=True, nullable=True)
    description = Column(Text, nullable=True)
    manufacturer = Column(String, nullable=True)
    precautions = Column(Text, nullable=True)
    side_effects = Column(Text, nullable=True)
    tags = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    requires_prescription = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    inventory = relationship("Inventory", back_populates="medicine", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("name", "strength", "dosage_form", "manufacturer", name="uq_medicine_catalogue_entry"),
    )

class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id", ondelete="CASCADE"), nullable=False, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id"), nullable=False, index=True)
    batch_number = Column(String, nullable=True)
    stock_quantity = Column(Integer, default=0, nullable=False)
    price = Column(Float, nullable=False)
    expiry_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default="In Stock")
    is_available = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    pharmacy = relationship("Pharmacy", back_populates="inventory")
    medicine = relationship("Medicine", back_populates="inventory")

    __table_args__ = (
        UniqueConstraint("pharmacy_id", "medicine_id", name="uq_pharmacy_medicine"),
    )

class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"), nullable=False)
    date = Column(DateTime(timezone=True), server_default=func.now())
    fulfillment_method = Column(String, nullable=True) # "Pickup" or "Delivery"
    fulfillment_address = Column(String, nullable=True)
    fulfillment_time = Column(String, nullable=True)
    payment_preference = Column(String, nullable=True) # Legacy display string: "Pay Online" or "Pay at Pharmacy"
    
    # Separate Status & Payment fields
    status = Column(Enum(ReservationStatus, native_enum=False), default=ReservationStatus.Pending_Pharmacy_Review)
    payment_method = Column(Enum(PaymentMethod, native_enum=False), nullable=True, default=None)
    payment_status = Column(Enum(PaymentStatus, native_enum=False), default=PaymentStatus.UNPAID)
    
    total_price = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    ref_number = Column(String, unique=True, index=True, nullable=True)
    reservation_code = Column(String, unique=True, index=True, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    payment_verified_at = Column(DateTime(timezone=True), nullable=True)
    
    cash_payment_confirmed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    cash_payment_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    is_hidden_by_patient = Column(Boolean, default=False, nullable=False)

    patient = relationship("User", back_populates="reservations", foreign_keys=[patient_id])
    cash_confirmed_by = relationship("User", foreign_keys=[cash_payment_confirmed_by_id])
    pharmacy = relationship("Pharmacy", back_populates="reservations")
    items = relationship("ReservationItem", back_populates="reservation", cascade="all, delete-orphan")
    payments = relationship("PaymentTransaction", back_populates="reservation", cascade="all, delete-orphan")

class ReservationItem(Base):
    __tablename__ = "reservation_items"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False)
    medicine_id = Column(Integer, ForeignKey("medicines.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)

    reservation = relationship("Reservation", back_populates="items")
    medicine = relationship("Medicine")

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    payment_method = Column(Enum(PaymentMethod, native_enum=False), default=PaymentMethod.PAYSTACK, nullable=False)
    payment_status = Column(Enum(PaymentStatus, native_enum=False), default=PaymentStatus.PENDING, nullable=False)
    
    amount = Column(Float, nullable=False)
    currency = Column(String, default="GHS", nullable=False)
    platform_fee = Column(Float, default=0.0, nullable=False)
    pharmacy_amount = Column(Float, nullable=False)
    
    paystack_reference = Column(String, unique=True, index=True, nullable=True)
    paystack_transaction_id = Column(String, nullable=True)
    paystack_status = Column(String, nullable=True) # e.g. "success", "failed", "abandoned"
    
    paid_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    reservation = relationship("Reservation", back_populates="payments")
    pharmacy = relationship("Pharmacy", back_populates="payments")
    patient = relationship("User")

# Keep legacy Payment alias for backwards compatibility
Payment = PaymentTransaction

