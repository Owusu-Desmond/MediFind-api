from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from routers import auth, users, pharmacies, medicines, reservations, payments

from sqlalchemy import text

# Create database tables and ensure newly added columns exist on existing databases
try:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS age INTEGER;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS precautions TEXT;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS side_effects TEXT;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS tags VARCHAR;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS image_url VARCHAR;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS dosage_instructions TEXT;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS gps_address VARCHAR;"))
        
        # Pharmacy Payout & Paystack columns
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS paystack_subaccount_code VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS paystack_subaccount_id VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS paystack_subaccount_status VARCHAR DEFAULT 'PENDING';"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS payment_account_type VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS bank_name VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS bank_code VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS account_name VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS account_number VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS mobile_money_provider VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS mobile_money_number VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS payment_account_verified BOOLEAN DEFAULT FALSE;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS payment_account_verified_at TIMESTAMP WITH TIME ZONE;"))
        
        # Reservation Payment & Status columns & type conversions
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS rejection_reason TEXT;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS ref_number VARCHAR;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS payment_preference VARCHAR;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS fulfillment_address VARCHAR;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS fulfillment_time VARCHAR;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS notes TEXT;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS payment_method VARCHAR DEFAULT 'CASH';"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS payment_status VARCHAR DEFAULT 'UNPAID';"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS reservation_code VARCHAR;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP WITH TIME ZONE;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS payment_verified_at TIMESTAMP WITH TIME ZONE;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS cash_payment_confirmed_by_id INTEGER;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS cash_payment_confirmed_at TIMESTAMP WITH TIME ZONE;"))
        conn.execute(text("ALTER TABLE reservations ADD COLUMN IF NOT EXISTS is_hidden_by_patient BOOLEAN DEFAULT FALSE;"))
        
        # Convert enum columns to VARCHAR to support all status additions safely
        conn.execute(text("ALTER TABLE reservations ALTER COLUMN status TYPE VARCHAR USING status::VARCHAR;"))
        conn.execute(text("ALTER TABLE reservations ALTER COLUMN payment_status TYPE VARCHAR USING payment_status::VARCHAR;"))
        conn.execute(text("ALTER TABLE reservations ALTER COLUMN payment_method TYPE VARCHAR USING payment_method::VARCHAR;"))
    print("[startup] Database schema verified and migrations applied successfully.")
except Exception as e:
    print(f"[startup] WARNING: could not run create_all or schema migration — {e}")



app = FastAPI(
    title="MediFind API",
    description="Backend API for the MediFind Application Ecosystem",
    version="1.0.0"
)

# CORS configuration supporting localhost, 127.0.0.1, and all LAN origins (e.g. 172.x, 192.x, 10.x)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import os
from fastapi.staticfiles import StaticFiles

# Create upload directory and mount static files
os.makedirs("uploads/certificates", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(pharmacies.router)
app.include_router(medicines.router)
app.include_router(reservations.router)
app.include_router(payments.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to the MediFind API!"}