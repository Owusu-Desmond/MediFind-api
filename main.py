from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from routers import auth, users, pharmacies, medicines, reservations, payments

# Create the database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="MediFind API",
    description="Backend API for the MediFind Application Ecosystem",
    version="1.0.0"
)

# CORS configuration
origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:8080",
    "http://localhost:8081",
    "*" # For mobile apps testing
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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