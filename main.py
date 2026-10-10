from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from routers import auth, users, pharmacies, medicines, reservations, payments, notifications

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
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS image_url VARCHAR;"))
        conn.execute(text("ALTER TABLE pharmacies ADD COLUMN IF NOT EXISTS logo_url VARCHAR;"))
        
        # Central Medicine Catalogue columns & backfills
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS strength VARCHAR;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS dosage_form VARCHAR;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS route_of_administration VARCHAR;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS requires_prescription BOOLEAN DEFAULT FALSE;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();"))
        conn.execute(text("ALTER TABLE medicines ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;"))
        conn.execute(text("UPDATE medicines SET strength = dosage WHERE strength IS NULL AND dosage IS NOT NULL;"))
        conn.execute(text("UPDATE medicines SET is_active = TRUE WHERE is_active IS NULL;"))
        conn.execute(text("UPDATE medicines SET requires_prescription = FALSE WHERE requires_prescription IS NULL;"))
        conn.execute(text("UPDATE medicines SET dosage_form = 'Tablet' WHERE dosage_form IS NULL;"))
        conn.execute(text("UPDATE medicines SET route_of_administration = 'Oral' WHERE route_of_administration IS NULL;"))
        
        # Pharmacy Inventory columns & unique constraint
        conn.execute(text("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS is_available BOOLEAN DEFAULT TRUE;"))
        conn.execute(text("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();"))
        conn.execute(text("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;"))
        conn.execute(text("UPDATE inventory SET is_available = TRUE WHERE is_available IS NULL;"))
        
        # Remove duplicate inventory entries if any exist, keeping highest stock/latest
        conn.execute(text("""
            DELETE FROM inventory a USING inventory b
            WHERE a.id < b.id
              AND a.pharmacy_id = b.pharmacy_id
              AND a.medicine_id = b.medicine_id;
        """))
        
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_pharmacy_medicine') THEN
                    ALTER TABLE inventory ADD CONSTRAINT uq_pharmacy_medicine UNIQUE (pharmacy_id, medicine_id);
                END IF;
            END $$;
        """))
        
        # Ensure PostgreSQL pg_trgm extension is active for typo-tolerant fuzzy searching
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        except Exception as ext_err:
            print(f"[startup] Notice: pg_trgm extension could not be initialized directly ({ext_err})")

        # Medicine Aliases table & indexes
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS medicine_aliases (
                id SERIAL PRIMARY KEY,
                medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE CASCADE,
                alias VARCHAR(255) NOT NULL,
                alias_type VARCHAR(50) DEFAULT 'BRAND',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_medicine_aliases_medicine_id ON medicine_aliases(medicine_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_medicine_aliases_alias ON medicine_aliases(alias);"))
        
        # Ensure unique constraint on (medicine_id, lower(alias))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_medicine_alias') THEN
                    ALTER TABLE medicine_aliases ADD CONSTRAINT uq_medicine_alias UNIQUE (medicine_id, alias);
                END IF;
            END $$;
        """))

        # GIN Trigram Indexes for high-performance sub-string and fuzzy matching
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS trgm_idx_medicines_name ON medicines USING gin (name gin_trgm_ops);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS trgm_idx_medicines_generic_name ON medicines USING gin (generic_name gin_trgm_ops);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS trgm_idx_medicine_aliases_alias ON medicine_aliases USING gin (alias gin_trgm_ops);"))
        except Exception as trgm_idx_err:
            print(f"[startup] Notice: GIN trigram index creation skipped ({trgm_idx_err})")

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

# Create upload directory and mount static files (safely handled for serverless environments)
try:
    os.makedirs("uploads/certificates", exist_ok=True)
    if os.path.exists("uploads"):
        app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
except Exception as static_err:
    print(f"[startup] Notice: Static uploads mount skipped ({static_err})")

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(pharmacies.router)
app.include_router(medicines.router)
app.include_router(reservations.router)
app.include_router(payments.router)
app.include_router(notifications.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to the MediFind API!"}