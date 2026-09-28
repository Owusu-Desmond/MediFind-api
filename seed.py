"""
Seed script to populate the MediFind database with test data.
Run with: python seed.py
"""

import requests

BASE = "http://127.0.0.1:8000"

print("=== MediFind API Seed Script ===\n")

# 1. Register an Admin user
print("1. Creating Admin user...")
res = requests.post(f"{BASE}/api/auth/register", json={
    "email": "admin@medifind.com",
    "name": "Justice Boateng",
    "password": "admin1234",
    "phone": "+233 24 000 0001",
    "location": "Accra, Ghana"
})
print(f"   -> {res.status_code}: {res.json()}")
admin_id = res.json().get("id")

# 2. Register a Patient user
print("\n2. Creating Patient user...")
res = requests.post(f"{BASE}/api/auth/register", json={
    "email": "kwame.mensah@gmail.com",
    "name": "Kwame Mensah",
    "password": "patient1234",
    "phone": "+233 55 456 7890",
    "location": "East Legon, Accra"
})
print(f"   -> {res.status_code}: {res.json()}")

# 3. Login as Admin to get token
print("\n3. Logging in as Admin...")
res = requests.post(f"{BASE}/api/auth/login", data={
    "username": "admin@medifind.com",
    "password": "admin1234"
})
print(f"   -> {res.status_code}: {res.json()}")
admin_token = res.json().get("access_token")
admin_headers = {"Authorization": f"Bearer {admin_token}"}

# 4. Manually promote admin user to Admin role (update via DB or add admin endpoint)
print("\n   (Note: to promote admin user to Admin role, update DB directly or add an admin-setup endpoint)")

# 5. Create pharmacies
print("\n4. Creating pharmacies...")
pharmacies_data = [
    {
        "name": "Ghana National Pharmacy",
        "location": "Ring Road Central, Near Kwame Nkrumah Interchange, Accra",
        "license_number": "PHA-GH-2026-8830",
        "pharmacist_name": "Dr. Emmanuel Mensah",
        "pharmacist_id": "RPH-GH-8830",
        "phone": "+233 30 223 4455",
        "email": "central@ghanapharmacy.gov.gh",
        "delivery_offered": True,
        "opening_hours": "08:00 AM - 10:00 PM",
        "lat": 5.5601,
        "lng": -0.2057
    },
    {
        "name": "East Legon Pharmacy Ltd",
        "location": "14 Boundary Road, East Legon, Accra",
        "license_number": "PHA-GH-2026-9040",
        "pharmacist_name": "Dr. Jane Osei",
        "pharmacist_id": "RPH-GH-9022",
        "phone": "+233 24 123 4567",
        "email": "eastlegon@ghanapharmacy.com",
        "delivery_offered": True,
        "opening_hours": "Mon-Sun: 8am - 10pm",
        "lat": 5.6108,
        "lng": -0.1639
    },
]

pharmacy_ids = []
for p in pharmacies_data:
    res = requests.post(f"{BASE}/api/pharmacies/", json=p, headers=admin_headers)
    data = res.json()
    print(f"   -> {res.status_code}: {data.get('name', data)}")
    if res.status_code == 200:
        pharmacy_ids.append(data["id"])

# 6. Create medicines
print("\n5. Creating central catalogue medicines with aliases...")
medicines_data = [
    {
        "name": "Paracetamol",
        "generic_name": "Acetaminophen",
        "strength": "500mg",
        "dosage_form": "Tablet",
        "route_of_administration": "Oral",
        "category": "Analgesic & Antipyretic",
        "description": "First-line pain reliever and fever reducer.",
        "manufacturer": "Pharma Ghana Ltd",
        "requires_prescription": False,
        "aliases": ["Panadol", "PCM", "APAP", "Paracet", "Tylenol"]
    },
    {
        "name": "Paracetamol",
        "generic_name": "Acetaminophen",
        "strength": "120mg/5ml",
        "dosage_form": "Syrup",
        "route_of_administration": "Oral",
        "category": "Analgesic & Antipyretic",
        "description": "Pediatric fever and pain relief liquid suspension.",
        "manufacturer": "Pharma Ghana Ltd",
        "requires_prescription": False,
        "aliases": ["Calpol Infant", "Panadol Baby", "PCM Syrup"]
    },
    {
        "name": "Amoxicillin",
        "generic_name": "Amoxicillin Trihydrate",
        "strength": "500mg",
        "dosage_form": "Capsule",
        "route_of_administration": "Oral",
        "category": "Antibacterial",
        "description": "Broad-spectrum beta-lactam penicillin antibiotic.",
        "manufacturer": "Medlab West Africa",
        "requires_prescription": True,
        "aliases": ["Amoxil", "Moxatag", "Amox"]
    },
    {
        "name": "Ciprofloxacin",
        "generic_name": "Ciprofloxacin Hydrochloride",
        "strength": "500mg",
        "dosage_form": "Tablet",
        "route_of_administration": "Oral",
        "category": "Antibacterial",
        "description": "Fluoroquinolone antibiotic for bacterial infections.",
        "manufacturer": "Ghana National Pharma",
        "requires_prescription": True,
        "aliases": ["Cipro", "Ciproxin", "Ciprolet"]
    },
    {
        "name": "Artemether / Lumefantrine",
        "generic_name": "Artemether + Lumefantrine",
        "strength": "80/480mg",
        "dosage_form": "Tablet",
        "route_of_administration": "Oral",
        "category": "Antimalarial",
        "description": "Artemisinin-based combination therapy (ACT) for acute uncomplicated malaria.",
        "manufacturer": "Novartis GH",
        "requires_prescription": True,
        "aliases": ["Coartem", "Lonart", "Riamet", "Artefan"]
    },
    {
        "name": "Ibuprofen",
        "generic_name": "Ibuprofen",
        "strength": "400mg",
        "dosage_form": "Tablet",
        "route_of_administration": "Oral",
        "category": "NSAID",
        "description": "Non-steroidal anti-inflammatory drug for pain, fever, and inflammation.",
        "manufacturer": "Pharma Ghana Ltd",
        "requires_prescription": False,
        "aliases": ["Advil", "Motrin", "Nurofen"]
    }
]

medicine_ids = []
for m in medicines_data:
    res = requests.post(f"{BASE}/api/medicines/", json=m, headers=admin_headers)
    data = res.json()
    print(f"   -> {res.status_code}: {data.get('name', data)}")
    if res.status_code in (200, 201):
        medicine_ids.append(data["id"])

print("\n=== Seed complete! ===")
print(f"Pharmacy IDs: {pharmacy_ids}")
print(f"Medicine IDs: {medicine_ids}")
