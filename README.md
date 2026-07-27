# MediFind API

Backend API for **MediFind**, a mobile-based Medicine Availability and Pharmacy Locator System.

MediFind aims to solve the challenge of finding available medicines by allowing users to search for medicines, locate nearby pharmacies, check medicine availability, reserve medicines, and manage pharmacy operations through a centralized platform.

This repository contains the backend REST API built with **FastAPI**.

---

## Features

### Authentication & Authorization

* User registration and login
* JWT-based authentication
* Password hashing using bcrypt
* Protected API routes

### Users

* User profile management
* Access to medicine search and reservation features

### Pharmacies

* Pharmacy management
* Pharmacy location information
* Medicine inventory management

### Medicines

* Search available medicines
* View medicine details
* Check stock availability

### Reservations

* Reserve available medicines from pharmacies
* Manage reservation status

### Payments

* Payment-related functionality and transaction management

---

## Tech Stack

### Backend

* **FastAPI** - Python web framework
* **SQLAlchemy** - ORM for database interaction
* **PostgreSQL** - Database
* **Pydantic** - Data validation
* **JWT** - Authentication
* **Passlib + Bcrypt** - Password security

### Development Tools

* Python 3.14
* Uvicorn
* Git
* Virtual Environment (`venv`)

---

## Project Structure

```
MediFind-api/
│
├── main.py                 # Application entry point
├── database.py             # Database configuration
├── models.py               # SQLAlchemy database models
├── schemas.py              # Pydantic schemas
├── auth.py                 # Authentication logic
├── deps.py                 # Dependency functions
├── seed.py                 # Database seed script
├── ensure_admin.py         # Admin creation utility
│
├── routers/
│   ├── auth.py             # Authentication routes
│   ├── users.py            # User routes
│   ├── pharmacies.py       # Pharmacy routes
│   ├── medicines.py        # Medicine routes
│   ├── reservations.py     # Reservation routes
│   └── payments.py         # Payment routes
│
├── requirements.txt        # Project dependencies
├── venv/                  # Virtual environment (not committed)
└── README.md
```

---

## Installation and Setup

### 1. Clone the repository

```bash
git clone <repository-url>

cd MediFind-api
```

---

### 2. Create a virtual environment

```bash
python3 -m venv venv
```

---

### 3. Activate virtual environment

#### macOS/Linux

```bash
source venv/bin/activate
```

#### Windows

```bash
venv\Scripts\activate
```

---

### 4. Install dependencies

```bash
python -m pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
DATABASE_URL=your_database_connection_string

SECRET_KEY=your_secret_key

ALGORITHM=HS256

ACCESS_TOKEN_EXPIRE_MINUTES=30
```

---

## Database Setup

Make sure PostgreSQL is installed and running.

Update your database connection in the `.env` file.

Run the application. Tables will be created automatically:

```bash
fastapi dev main.py
```

---

## Running the Application

Start the development server:

```bash
fastapi dev main.py
```

or:

```bash
uvicorn main:app --reload
```

The API will be available at:

```
http://127.0.0.1:8000
```

---

## API Documentation

FastAPI automatically provides interactive documentation.

Swagger UI:

```
http://127.0.0.1:8000/docs
```

ReDoc:

```
http://127.0.0.1:8000/redoc
```

---

## Authentication Flow

1. User registers an account.
2. User logs in with credentials.
3. Server generates a JWT access token.
4. Client includes the token in protected requests.

Example:

```
Authorization: Bearer <access_token>
```

---

## Database Models

Current core entities include:

* User
* Administrator
* Pharmacy
* Medicine
* Reservation
* Payment

Relationships are managed using SQLAlchemy ORM.

---

## Development

Install a new dependency:

```bash
python -m pip install package-name
```

Update requirements:

```bash
python -m pip freeze > requirements.txt
```

---

## Git Guidelines

The following files should not be committed:

```
venv/
__pycache__/
.env
```

Example `.gitignore`:

```
venv/
__pycache__/
*.pyc
.env
```

---

## Future Improvements

* Pharmacy dashboard
* Real-time medicine availability updates
* Map integration for pharmacy locations
* Mobile application integration
* Payment gateway integration
* Notification system

---

## Author

Desmond Owusu Ansah

Computer Science Student
University of Ghana

---

## License

This project is developed for academic and research purposes.
