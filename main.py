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
except Exception as e:
    print(f"[startup] WARNING: could not run create_all or schema migration — {e}")

app = FastAPI(
    title="MediFind API",
    description="Backend API for the MediFind Application Ecosystem",
    version="1.0.0"
)

# CORS configuration
# NOTE: "*" (wildcard) CANNOT be used together with allow_credentials=True.
# Browsers reject responses that combine credentials mode with a wildcard origin.
# All allowed origins must be listed explicitly.
origins = [
    "http://localhost",
    "http://localhost:3000",   # Next.js admin dashboard
    "http://localhost:3001",   # Next.js pharmacy portal (if on 3001)
    "http://localhost:8080",
    "http://localhost:8081",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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