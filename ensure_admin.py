import sys
import os

# Add directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
import models
import auth

def ensure_admin():
    db = SessionLocal()
    try:
        admins_to_ensure = [
            {
                "email": "justice.admin@medifind.com",
                "name": "Justice Boateng",
                "password": "admin123",
                "phone": "+233 24 000 0001",
                "location": "Accra, Ghana"
            },
            {
                "email": "admin@medifind.com",
                "name": "MediFind Admin",
                "password": "admin1234",
                "phone": "+233 24 000 0000",
                "location": "Accra, Ghana"
            }
        ]

        for admin_info in admins_to_ensure:
            user = db.query(models.User).filter(models.User.email == admin_info["email"]).first()
            if user:
                print(f"Updating existing user {admin_info['email']} to Admin role...")
                user.role = models.UserRole.Admin
                user.status = models.UserStatus.Active
                user.hashed_password = auth.get_password_hash(admin_info["password"])
                db.commit()
                db.refresh(user)
                print(f"User {user.email} updated: Role={user.role}, Status={user.status}")
            else:
                print(f"Creating new Admin user {admin_info['email']}...")
                new_admin = models.User(
                    email=admin_info["email"],
                    name=admin_info["name"],
                    hashed_password=auth.get_password_hash(admin_info["password"]),
                    role=models.UserRole.Admin,
                    phone=admin_info["phone"],
                    location=admin_info["location"],
                    status=models.UserStatus.Active
                )
                db.add(new_admin)
                db.commit()
                db.refresh(new_admin)
                print(f"Created Admin user {new_admin.email} with ID {new_admin.id}")
    finally:
        db.close()

if __name__ == "__main__":
    ensure_admin()
