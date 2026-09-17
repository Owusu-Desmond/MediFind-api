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

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str
    reset_token: Optional[str] = None


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
    gps_address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    certificate_url: Optional[str] = None
    # Payout details
    payment_account_type: Optional[str] = None # "bank" or "mobile_money"
    bank_name: Optional[str] = None
    bank_code: Optional[str] = None
    account_name: Optional[str] = None
    account_number: Optional[str] = None
    mobile_money_provider: Optional[str] = None
    mobile_money_number: Optional[str] = None

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
    gps_address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    certificate_url: Optional[str] = None
    status: Optional[str] = None
    payment_account_type: Optional[str] = None
    bank_name: Optional[str] = None
    bank_code: Optional[str] = None
    account_name: Optional[str] = None
    account_number: Optional[str] = None
    mobile_money_provider: Optional[str] = None
    mobile_money_number: Optional[str] = None

class PharmacyPayoutSetupRequest(BaseModel):
    payment_account_type: str # "bank" or "mobile_money"
    bank_name: Optional[str] = None
    bank_code: Optional[str] = None
    account_name: str
    account_number: str # Bank account number or mobile money number
    mobile_money_provider: Optional[str] = None # e.g. "MTN", "VOD", "ATL"
    mobile_money_number: Optional[str] = None

class PharmacyPayoutResponse(BaseModel):
    pharmacy_id: int
    paystack_subaccount_code: Optional[str] = None
    paystack_subaccount_status: str = "PENDING"
    payment_account_type: Optional[str] = None
    bank_name: Optional[str] = None
    account_name: Optional[str] = None
    account_number_masked: Optional[str] = None
    mobile_money_provider: Optional[str] = None
    payment_account_verified: bool = False
    message: Optional[str] = None

class PharmacyResponse(PharmacyBase):
    id: int
    status: str
    verified: bool
    date_submitted: datetime
    is_open: bool = True
    open_status_text: Optional[str] = None
    paystack_subaccount_code: Optional[str] = None
    paystack_subaccount_status: Optional[str] = "PENDING"
    payment_account_verified: Optional[bool] = False

    class Config:
        from_attributes = True

class MedicineBase(BaseModel):
    name: str
    generic_name: Optional[str] = None
    dosage: Optional[str] = None
    dosage_instructions: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    precautions: Optional[str] = None
    side_effects: Optional[str] = None
    tags: Optional[str] = None
    image_url: Optional[str] = None

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
    dosage_instructions: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    precautions: Optional[str] = None
    side_effects: Optional[str] = None
    tags: Optional[str] = None
    image_url: Optional[str] = None
    batch_number: Optional[str] = None
    stock_quantity: int = 0
    price: float = 0.0
    expiry_date: Optional[str] = None

class InventoryMedicineUpdate(BaseModel):
    name: Optional[str] = None
    dosage: Optional[str] = None
    dosage_instructions: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    precautions: Optional[str] = None
    side_effects: Optional[str] = None
    tags: Optional[str] = None
    image_url: Optional[str] = None
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
    fulfillment_method: Optional[str] = None # "Pickup" or "Delivery"
    fulfillment_address: Optional[str] = None
    fulfillment_time: Optional[str] = None
    notes: Optional[str] = None
    payment_method: Optional[str] = None # "PAYSTACK" or "CASH"
    payment_preference: Optional[str] = None # "Pay Online" or "Pay at Pharmacy"

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
    payment_method: Optional[str] = None
    payment_status: Optional[str] = "UNPAID"
    total_price: float
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    ref_number: Optional[str] = None
    reservation_code: Optional[str] = None
    expires_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    payment_verified_at: Optional[datetime] = None
    cash_payment_confirmed_at: Optional[datetime] = None
    is_hidden_by_patient: Optional[bool] = False
    pharmacy: Optional[PharmacyResponse] = None
    patient: Optional[UserResponse] = None
    items: List[ReservationItemResponse] = []

    class Config:
        from_attributes = True

class PaymentInitializeRequest(BaseModel):
    reservation_id: int
    callback_url: Optional[str] = None

class PaymentInitializeResponse(BaseModel):
    status: bool
    authorization_url: str
    access_code: Optional[str] = None
    reference: str
    amount: float
    currency: str = "GHS"
    platform_fee: float = 0.0
    pharmacy_amount: float
    is_mock: bool = False

class PaymentVerifyResponse(BaseModel):
    status: str # "Success" or "Failed"
    message: str
    reservation_id: int
    reservation_status: str
    payment_status: str
    payment_method: str
    amount: float
    currency: str = "GHS"
    reference: str
    paid_at: Optional[datetime] = None

class CashPaymentConfirmResponse(BaseModel):
    success: bool
    message: str
    reservation_id: int
    reservation_status: str
    payment_status: str
    payment_method: str
    amount: float
    confirmed_by_user_id: int
    confirmed_at: datetime

class PaymentTransactionResponse(BaseModel):
    id: int
    reservation_id: int
    pharmacy_id: int
    patient_id: int
    payment_method: str
    payment_status: str
    amount: float
    currency: str
    platform_fee: float
    pharmacy_amount: float
    paystack_reference: Optional[str] = None
    paystack_status: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class AddStaffRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None

class StaffResponse(BaseModel):
    id: int
    user_id: int
    name: str
    email: str
    phone: Optional[str] = None
    role: str

    class Config:
        from_attributes = True

