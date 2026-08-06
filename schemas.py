from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    name: str
    phone: Optional[str] = None
    location: Optional[str] = None
    age: Optional[int] = None

class UserCreate(UserBase):
    password: str
    role: Optional[str] = "Patient"

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    age: Optional[int] = None
    role: Optional[str] = None
    status: Optional[str] = None

class UserResponse(UserBase):
    id: int
    role: str
    status: str
    date_created: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None

class PharmacyBase(BaseModel):
    name: str
    location: str
    license_number: str
    pharmacist_name: Optional[str] = None
    pharmacist_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    delivery_offered: bool = False
    opening_hours: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    certificate_url: Optional[str] = None

class PharmacyCreate(PharmacyBase):
    pass

class PharmacyUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    license_number: Optional[str] = None
    pharmacist_name: Optional[str] = None
    pharmacist_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    delivery_offered: Optional[bool] = None
    opening_hours: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    certificate_url: Optional[str] = None
    status: Optional[str] = None

class PharmacyResponse(PharmacyBase):
    id: int
    status: str
    verified: bool
    date_submitted: datetime

    class Config:
        from_attributes = True

class MedicineBase(BaseModel):
    name: str
    generic_name: Optional[str] = None
    dosage: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None

class MedicineCreate(MedicineBase):
    pass

class MedicineResponse(MedicineBase):
    id: int

    class Config:
        from_attributes = True

class InventoryBase(BaseModel):
    pharmacy_id: int
    medicine_id: int
    batch_number: Optional[str] = None
    stock_quantity: int
    price: float
    expiry_date: Optional[datetime] = None

class InventoryCreate(InventoryBase):
    pass

class InventoryResponse(InventoryBase):
    id: int
    status: str
    medicine: MedicineResponse
    pharmacy: PharmacyResponse

    class Config:
        from_attributes = True

class InventoryMedicineCreate(BaseModel):
    name: str
    dosage: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    batch_number: Optional[str] = None
    stock_quantity: int = 0
    price: float = 0.0
    expiry_date: Optional[str] = None

class InventoryMedicineUpdate(BaseModel):
    name: Optional[str] = None
    dosage: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    batch_number: Optional[str] = None
    stock_quantity: Optional[int] = None
    price: Optional[float] = None
    expiry_date: Optional[str] = None


class ReservationItemBase(BaseModel):
    medicine_id: int
    quantity: int

class ReservationItemResponse(ReservationItemBase):
    id: int
    price: float
    medicine: MedicineResponse

    class Config:
        from_attributes = True

class ReservationCreate(BaseModel):
    pharmacy_id: int
    items: List[ReservationItemBase]
    fulfillment_method: Optional[str] = None
    fulfillment_address: Optional[str] = None
    fulfillment_time: Optional[str] = None
    notes: Optional[str] = None

class ReservationResponse(BaseModel):
    id: int
    patient_id: int
    pharmacy_id: int
    date: datetime
    fulfillment_method: Optional[str] = None
    fulfillment_address: Optional[str] = None
    fulfillment_time: Optional[str] = None
    payment_preference: Optional[str] = None
    status: str
    total_price: float
    notes: Optional[str] = None
    ref_number: Optional[str] = None
    items: List[ReservationItemResponse]

    class Config:
        from_attributes = True
