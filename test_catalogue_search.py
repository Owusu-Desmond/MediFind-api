"""
Automated Test Suite for MediFind Central Medicine Catalogue and Intelligent Search Architecture.
Run with: python -m unittest test_catalogue_search.py -v
"""

import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import models
import schemas
import deps
from database import Base, engine, SessionLocal
from main import app
import auth

# Set up an isolated in-memory test database with StaticPool to share memory across threads
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[deps.get_db] = override_get_db


class TestCatalogueAndSearch(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)

    def setUp(self):
        # Clean data between test runs
        db = TestingSessionLocal()
        db.query(models.ReservationItem).delete()
        db.query(models.Reservation).delete()
        db.query(models.Inventory).delete()
        db.query(models.MedicineAlias).delete()
        db.query(models.Medicine).delete()
        db.query(models.PharmacyStaff).delete()
        db.query(models.Pharmacy).delete()
        db.query(models.User).delete()
        db.commit()

        # 1. Create Admin user
        admin_user = models.User(
            email="admin.test@medifind.com",
            name="Admin Test",
            hashed_password=auth.get_password_hash("adminpass123"),
            role=models.UserRole.Admin,
            status=models.UserStatus.Active
        )
        db.add(admin_user)

        # 2. Create Pharmacist user
        pharmacist_user = models.User(
            email="pharm.test@medifind.com",
            name="Pharmacist Test",
            hashed_password=auth.get_password_hash("pharmpass123"),
            role=models.UserRole.Pharmacist,
            status=models.UserStatus.Active
        )
        db.add(pharmacist_user)

        # 3. Create Patient user
        patient_user = models.User(
            email="patient.test@medifind.com",
            name="Patient Test",
            hashed_password=auth.get_password_hash("patientpass123"),
            role=models.UserRole.Patient,
            status=models.UserStatus.Active
        )
        db.add(patient_user)
        db.commit()

        # Generate tokens
        self.admin_token = auth.create_access_token({"sub": admin_user.email, "role": admin_user.role.value})
        self.pharm_token = auth.create_access_token({"sub": pharmacist_user.email, "role": pharmacist_user.role.value})
        self.patient_token = auth.create_access_token({"sub": patient_user.email, "role": patient_user.role.value})

        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        self.pharm_headers = {"Authorization": f"Bearer {self.pharm_token}"}
        self.patient_headers = {"Authorization": f"Bearer {self.patient_token}"}

        # 4. Create Approved Pharmacies
        p1 = models.Pharmacy(
            name="Alpha Pharmacy Accra",
            location="Ring Road Central",
            license_number="PHA-GH-001",
            status=models.PharmacyStatus.Approved,
            delivery_offered=True,
            verified=True,
            lat=5.5601,
            lng=-0.2057
        )
        p2 = models.Pharmacy(
            name="Beta Pharmacy East Legon",
            location="Boundary Road",
            license_number="PHA-GH-002",
            status=models.PharmacyStatus.Approved,
            delivery_offered=False,
            verified=True,
            lat=5.6108,
            lng=-0.1639
        )
        db.add_all([p1, p2])
        db.commit()
        db.refresh(p1)
        db.refresh(p2)
        self.pharmacy_1_id = p1.id
        self.pharmacy_2_id = p2.id
        db.close()

    def test_1_create_and_distinguish_medicines(self):
        """Verify that medicines with same name but different strength/form remain distinct."""
        # 1. Create Paracetamol 500mg Tablet
        res1 = self.client.post("/api/medicines/", json={
            "name": "Paracetamol",
            "generic_name": "Acetaminophen",
            "strength": "500mg",
            "dosage_form": "Tablet",
            "route_of_administration": "Oral",
            "category": "Analgesic",
            "description": "Adult pain reliever",
            "manufacturer": "Ghana Pharma Ltd",
            "requires_prescription": False,
            "aliases": ["Panadol", "PCM", "APAP", "Paracet"]
        }, headers=self.admin_headers)
        self.assertIn(res1.status_code, [200, 201])
        med1 = res1.json()
        self.assertEqual(med1["name"], "Paracetamol")
        self.assertEqual(med1["strength"], "500mg")
        self.assertEqual(med1["dosage_form"], "Tablet")

        # 2. Create Paracetamol 120mg/5ml Syrup
        res2 = self.client.post("/api/medicines/", json={
            "name": "Paracetamol",
            "generic_name": "Acetaminophen",
            "strength": "120mg/5ml",
            "dosage_form": "Syrup",
            "route_of_administration": "Oral",
            "category": "Analgesic",
            "description": "Pediatric pain reliever",
            "manufacturer": "Ghana Pharma Ltd",
            "requires_prescription": False,
            "aliases": ["Calpol Infant", "Panadol Baby"]
        }, headers=self.admin_headers)
        self.assertIn(res2.status_code, [200, 201])
        med2 = res2.json()
        self.assertNotEqual(med1["id"], med2["id"])
        self.assertEqual(med2["strength"], "120mg/5ml")
        self.assertEqual(med2["dosage_form"], "Syrup")

    def test_2_alias_management_crud(self):
        """Test adding, retrieving, updating, and deleting aliases on a canonical medicine."""
        # Create Ciprofloxacin
        create_res = self.client.post("/api/medicines/", json={
            "name": "Ciprofloxacin",
            "generic_name": "Ciprofloxacin Hydrochloride",
            "strength": "500mg",
            "dosage_form": "Tablet",
            "category": "Antibacterial",
            "manufacturer": "Ghana National Pharma"
        }, headers=self.admin_headers)
        med_id = create_res.json()["id"]

        # 1. Add Alias "Cipro"
        alias_res = self.client.post(f"/api/medicines/{med_id}/aliases", json={
            "alias": "Cipro",
            "alias_type": "BRAND"
        }, headers=self.admin_headers)
        self.assertEqual(alias_res.status_code, 201)
        alias_id = alias_res.json()["id"]
        self.assertEqual(alias_res.json()["alias"], "Cipro")

        # 2. Add second alias "Ciproxin"
        alias_res2 = self.client.post(f"/api/medicines/{med_id}/aliases", json={
            "alias": "Ciproxin",
            "alias_type": "BRAND"
        }, headers=self.admin_headers)
        self.assertEqual(alias_res2.status_code, 201)

        # 3. Retrieve aliases list
        list_res = self.client.get(f"/api/medicines/{med_id}/aliases")
        self.assertEqual(list_res.status_code, 200)
        aliases = [a["alias"] for a in list_res.json()]
        self.assertIn("Cipro", aliases)
        self.assertIn("Ciproxin", aliases)

        # 4. Duplicate alias prevention
        dup_res = self.client.post(f"/api/medicines/{med_id}/aliases", json={
            "alias": "Cipro",
            "alias_type": "BRAND"
        }, headers=self.admin_headers)
        self.assertEqual(dup_res.status_code, 409)

        # 5. Delete Alias
        del_res = self.client.delete(f"/api/medicines/aliases/{alias_id}", headers=self.admin_headers)
        self.assertEqual(del_res.status_code, 200)

        # Verify deletion
        list_res_after = self.client.get(f"/api/medicines/{med_id}/aliases")
        remaining = [a["alias"] for a in list_res_after.json()]
        self.assertNotIn("Cipro", remaining)
        self.assertIn("Ciproxin", remaining)

    def test_3_search_resolution_tiers(self):
        """Test search resolving across Exact Name, Alias, Abbreviation, Generic INN, Partial, and Typos."""
        # Seed test medicines
        self.client.post("/api/medicines/", json={
            "name": "Paracetamol",
            "generic_name": "Acetaminophen",
            "strength": "500mg",
            "dosage_form": "Tablet",
            "category": "Analgesic",
            "manufacturer": "Pharma Ltd",
            "aliases": ["Panadol", "PCM", "APAP", "Paracet"]
        }, headers=self.admin_headers)

        self.client.post("/api/medicines/", json={
            "name": "Amoxicillin",
            "generic_name": "Amoxicillin Trihydrate",
            "strength": "500mg",
            "dosage_form": "Capsule",
            "category": "Antibacterial",
            "manufacturer": "Medlab",
            "aliases": ["Amoxil", "Moxatag"]
        }, headers=self.admin_headers)

        # A. Exact Canonical Name Search
        r1 = self.client.get("/api/medicines/?q=Paracetamol")
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(len(r1.json()) > 0)
        self.assertEqual(r1.json()[0]["name"], "Paracetamol")
        self.assertEqual(r1.json()[0]["matched_by"], "exact_name")

        # B. Exact Alias Search (Panadol)
        r2 = self.client.get("/api/medicines/?q=Panadol")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(len(r2.json()) > 0)
        self.assertEqual(r2.json()[0]["name"], "Paracetamol")
        self.assertEqual(r2.json()[0]["matched_by"], "alias")

        # C. Abbreviation Search (PCM, APAP)
        r3 = self.client.get("/api/medicines/?q=PCM")
        self.assertEqual(r3.status_code, 200)
        self.assertTrue(len(r3.json()) > 0)
        self.assertEqual(r3.json()[0]["name"], "Paracetamol")
        self.assertEqual(r3.json()[0]["matched_by"], "alias")

        # D. Generic INN Search (Acetaminophen)
        r4 = self.client.get("/api/medicines/?q=Acetaminophen")
        self.assertEqual(r4.status_code, 200)
        self.assertTrue(len(r4.json()) > 0)
        self.assertEqual(r4.json()[0]["name"], "Paracetamol")
        self.assertEqual(r4.json()[0]["matched_by"], "generic_name")

        # E. Partial Search (parac, amox)
        r5 = self.client.get("/api/medicines/?q=parac")
        self.assertEqual(r5.status_code, 200)
        self.assertTrue(len(r5.json()) > 0)
        self.assertEqual(r5.json()[0]["name"], "Paracetamol")

        # F. Typo / Misspelling Search (paracetmol)
        r6 = self.client.get("/api/medicines/?q=paracetmol")
        self.assertEqual(r6.status_code, 200)
        self.assertTrue(len(r6.json()) > 0)
        self.assertEqual(r6.json()[0]["name"], "Paracetamol")
        self.assertEqual(r6.json()[0]["matched_by"], "fuzzy")

    def test_4_pharmacy_inventory_linking_and_deduplication(self):
        """Verify pharmacy stocks canonical medicine and duplicate inventory records are rejected."""
        # Create medicine
        med_res = self.client.post("/api/medicines/", json={
            "name": "Ibuprofen",
            "generic_name": "Ibuprofen",
            "strength": "400mg",
            "dosage_form": "Tablet",
            "category": "NSAID",
            "manufacturer": "Ghana Pharma Ltd",
            "aliases": ["Advil", "Motrin"]
        }, headers=self.admin_headers)
        med_id = med_res.json()["id"]

        # Pharmacy 1 adds to inventory
        inv1 = self.client.post(f"/api/pharmacies/{self.pharmacy_1_id}/inventory/add-from-catalogue", json={
            "medicine_id": med_id,
            "price": 20.00,
            "stock_quantity": 40,
            "is_available": True
        }, headers=self.admin_headers)
        self.assertEqual(inv1.status_code, 200)
        self.assertEqual(inv1.json()["price"], 20.00)

        # Pharmacy 2 adds same medicine with different price & quantity
        inv2 = self.client.post(f"/api/pharmacies/{self.pharmacy_2_id}/inventory/add-from-catalogue", json={
            "medicine_id": med_id,
            "price": 25.50,
            "stock_quantity": 85,
            "is_available": True
        }, headers=self.admin_headers)
        self.assertEqual(inv2.status_code, 200)
        self.assertEqual(inv2.json()["price"], 25.50)

        # Duplicate addition on Pharmacy 1 is rejected with 409 Conflict
        inv1_dup = self.client.post(f"/api/pharmacies/{self.pharmacy_1_id}/inventory/add-from-catalogue", json={
            "medicine_id": med_id,
            "price": 22.00,
            "stock_quantity": 60,
            "is_available": True
        }, headers=self.admin_headers)
        self.assertEqual(inv1_dup.status_code, 409)

        # Update existing inventory item via PUT
        inv1_id = inv1.json()["id"]
        update_res = self.client.put(f"/api/pharmacies/{self.pharmacy_1_id}/inventory/{inv1_id}", json={
            "price": 22.00,
            "stock_quantity": 60
        }, headers=self.admin_headers)
        self.assertEqual(update_res.status_code, 200)

        # Verify Pharmacy 1 has only 1 inventory item with updated price
        pharm1_inv = self.client.get(f"/api/pharmacies/{self.pharmacy_1_id}/inventory", headers=self.admin_headers)
        self.assertEqual(pharm1_inv.status_code, 200)
        matching = [i for i in pharm1_inv.json() if i["medicine_id"] == med_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["price"], 22.00)
        self.assertEqual(matching[0]["stock_quantity"], 60)

    def test_5_patient_search_flow_with_multi_pharmacy_pricing(self):
        """End-to-end patient search: searching an alias returns all approved pharmacies stocking the medicine."""
        # 1. Create Artemether/Lumefantrine with alias Coartem and Lonart
        med_res = self.client.post("/api/medicines/", json={
            "name": "Artemether / Lumefantrine",
            "generic_name": "Artemether + Lumefantrine",
            "strength": "80/480mg",
            "dosage_form": "Tablet",
            "category": "Antimalarial",
            "manufacturer": "Novartis",
            "aliases": ["Coartem", "Lonart"]
        }, headers=self.admin_headers)
        med_id = med_res.json()["id"]

        # 2. Stock at Pharmacy 1 (GH₵ 45.00)
        self.client.post(f"/api/pharmacies/{self.pharmacy_1_id}/inventory/add-from-catalogue", json={
            "medicine_id": med_id,
            "price": 45.00,
            "stock_quantity": 30,
            "is_available": True
        }, headers=self.admin_headers)

        # 3. Stock at Pharmacy 2 (GH₵ 40.00)
        self.client.post(f"/api/pharmacies/{self.pharmacy_2_id}/inventory/add-from-catalogue", json={
            "medicine_id": med_id,
            "price": 40.00,
            "stock_quantity": 50,
            "is_available": True
        }, headers=self.admin_headers)

        # 4. Patient searches by brand alias "Coartem"
        search_res = self.client.get("/api/medicines/search?q=Coartem")
        self.assertEqual(search_res.status_code, 200)
        results = search_res.json()

        # Both pharmacies stocking the canonical medicine should be returned
        self.assertEqual(len(results), 2)
        pharmacy_names = [r["pharmacy"]["name"] for r in results]
        prices = [r["inventory"]["price"] for r in results]
        matched_tags = [r["medicine"]["matched_by"] for r in results]

        self.assertIn("Alpha Pharmacy Accra", pharmacy_names)
        self.assertIn("Beta Pharmacy East Legon", pharmacy_names)
        self.assertIn(45.00, prices)
        self.assertIn(40.00, prices)
        self.assertTrue(all(m == "alias" for m in matched_tags))


if __name__ == "__main__":
    unittest.main()
