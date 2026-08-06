from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, Enum
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
    Paid = "Paid"
    Ready_for_Pickup = "Ready for Pickup"
    Preparing = "Preparing"
    Out_for_Delivery = "Out for Delivery"
    Delivered = "Delivered"
    Collected = "Collected"
    Cancelled = "Cancelled"
    Rejected = "Rejected"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.Patient, nullable=False)
    phone = Column(String, nullable=True)
    location = Column(String, nullable=True)
    status = Column(Enum(UserStatus), default=UserStatus.Active)
    date_created = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    reservations = relationship("Reservation", back_populates="patient")

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
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    verified = Column(Boolean, default=False)
    certificate_url = Column(String, nullable=True)

    # Relationships
    staff = relationship("PharmacyStaff", back_populates="pharmacy", cascade="all, delete-orphan")
    inventory = relationship("Inventory", back_populates="pharmacy", cascade="all, delete-orphan")
    reservations = relationship("Reservation", back_populates="pharmacy", cascade="all, delete-orphan")

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
    name = Column(String, index=True, nullable=False)
    generic_name = Column(String, nullable=True)
    dosage = Column(String, nullable=True)
    category = Column(String, index=True, nullable=True)
    description = Column(Text, nullable=True)
    manufacturer = Column(String, nullable=True)

    inventory = relationship("Inventory", back_populates="medicine")

class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"), nullable=False)
    medicine_id = Column(Integer, ForeignKey("medicines.id"), nullable=False)
    batch_number = Column(String, nullable=True)
    stock_quantity = Column(Integer, default=0, nullable=False)
    price = Column(Float, nullable=False)
    expiry_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, default="In Stock")  # Can be computed

    pharmacy = relationship("Pharmacy", back_populates="inventory")
    medicine = relationship("Medicine", back_populates="inventory")

class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pharmacy_id = Column(Integer, ForeignKey("pharmacies.id"), nullable=False)
    date = Column(DateTime(timezone=True), server_default=func.now())
    fulfillment_method = Column(String, nullable=True) # "Pickup" or "Delivery"
    fulfillment_address = Column(String, nullable=True)
    fulfillment_time = Column(String, nullable=True)
    payment_preference = Column(String, nullable=True)
    status = Column(Enum(ReservationStatus), default=ReservationStatus.Pending_Pharmacy_Review)
    total_price = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    ref_number = Column(String, unique=True, index=True, nullable=True)

    patient = relationship("User", back_populates="reservations")
    pharmacy = relationship("Pharmacy", back_populates="reservations")
    items = relationship("ReservationItem", back_populates="reservation")
    payment = relationship("Payment", back_populates="reservation", uselist=False)

class ReservationItem(Base):
    __tablename__ = "reservation_items"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False)
    medicine_id = Column(Integer, ForeignKey("medicines.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)

    reservation = relationship("Reservation", back_populates="items")
    medicine = relationship("Medicine")

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String, nullable=False) # e.g., "Paystack"
    status = Column(String, nullable=False, default="Pending") # "Pending", "Success", "Failed"
    reference = Column(String, nullable=True, unique=True)
    date_created = Column(DateTime(timezone=True), server_default=func.now())

    reservation = relationship("Reservation", back_populates="payment")
