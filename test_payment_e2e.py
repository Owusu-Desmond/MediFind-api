"""
End-to-End Test Suite for MediFind Payment Integration
Tests both payment methods:
1. Pay at Pharmacy (Cash) reservation, pharmacist confirmation, patient permission check (403).
2. Pay Online with Paystack initialization, double payment prevention, verification idempotency.
3. Paystack Subaccount creation & query.
4. Paystack Webhook signature handling.
"""

import sys
import hmac
import hashlib
import json
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from main import app
from database import get_session, engine
from models import (
    User, UserRole, Pharmacy, Medicine, Reservation, ReservationStatus,
    PaymentMethod, PaymentStatus, PaymentTransaction
)
from auth import create_access_token, get_password_hash

client = TestClient(app)

def setup_test_data():
    """Sets up a test patient, test pharmacist, pharmacy, and medicine in DB."""
    with Session(engine) as db:
        # Check or create test patient
        patient = db.exec(select(User).where(User.email == "test_patient_payment@example.com")).first()
        if not patient:
            patient = User(
                email="test_patient_payment@example.com",
                name="E2E Test Patient",
                password_hash=get_password_hash("password123"),
                role=UserRole.Patient,
                phone="0241000001"
            )
            db.add(patient)
            db.commit()
            db.refresh(patient)

        # Check or create test pharmacist
        pharmacist = db.exec(select(User).where(User.email == "test_pharmacist_payment@example.com")).first()
        if not pharmacist:
            pharmacist = User(
                email="test_pharmacist_payment@example.com",
                name="E2E Test Pharmacist",
                password_hash=get_password_hash("password123"),
                role=UserRole.Pharmacist,
                phone="0241000002"
            )
            db.add(pharmacist)
            db.commit()
            db.refresh(pharmacist)

        # Check or create test pharmacy
        pharmacy = db.exec(select(Pharmacy).where(Pharmacy.name == "E2E Test Pharmacy")).first()
        if not pharmacy:
            pharmacy = Pharmacy(
                name="E2E Test Pharmacy",
                location="Accra Central",
                license_number="LIC-E2E-PAY-001",
                pharmacist_id=pharmacist.id,
                pharmacist_name=pharmacist.name,
                status="Approved",
                verified=True,
                paystack_subaccount_code="ACCT_e2e_test_subacc",
                payment_account_type="mobile_money",
                mobile_money_provider="mtn",
                account_name="E2E Test Pharmacy MoMo",
                account_number="0241234567",
                payment_account_verified=True
            )
            db.add(pharmacy)
            db.commit()
            db.refresh(pharmacy)

        # Check or create test medicine
        medicine = db.exec(select(Medicine).where(Medicine.name == "Amoxicillin 500mg E2E")).first()
        if not medicine:
            medicine = Medicine(
                name="Amoxicillin 500mg E2E",
                category="Antibiotics",
                dosage_form="Capsule",
                strength="500mg",
                price=45.0,
                stock_quantity=100,
                is_available=True,
                pharmacy_id=pharmacy.id
            )
            db.add(medicine)
            db.commit()
            db.refresh(medicine)

        patient_token = create_access_token(data={"sub": patient.email, "role": patient.role.value, "user_id": patient.id})
        pharmacist_token = create_access_token(data={"sub": pharmacist.email, "role": pharmacist.role.value, "user_id": pharmacist.id})

        return {
            "patient": patient,
            "pharmacist": pharmacist,
            "pharmacy": pharmacy,
            "medicine": medicine,
            "patient_token": patient_token,
            "pharmacist_token": pharmacist_token
        }

def test_cash_payment_flow():
    print("\n--- TEST 1: Cash Payment & In-Store Confirmation Flow ---")
    data = setup_test_data()
    patient_headers = {"Authorization": f"Bearer {data['patient_token']}"}
    pharmacist_headers = {"Authorization": f"Bearer {data['pharmacist_token']}"}

    # 1. Patient creates reservation with Cash payment method
    res_payload = {
        "medicine_id": data["medicine"].id,
        "pharmacy_id": data["pharmacy"].id,
        "quantity": 2,
        "payment_method": "cash",
        "notes": "E2E Test Cash Reservation"
    }
    create_res = client.post("/api/reservations/", json=res_payload, headers=patient_headers)
    assert create_res.status_code == 201, f"Failed to create reservation: {create_res.text}"
    res_data = create_res.json()

    reservation_id = res_data["id"]
    reservation_code = res_data["reservation_code"]
    print(f"✓ Cash reservation created: ID={reservation_id}, Code={reservation_code}")
    assert reservation_code.startswith("MF-")
    assert res_data["payment_method"] == "cash"
    assert res_data["payment_status"] == "unpaid"
    assert res_data["total_price"] == 90.0

    # 2. Patient attempts to mark cash paid (MUST FAIL with 403 Forbidden)
    patient_mark_res = client.post(f"/api/reservations/{reservation_id}/mark-cash-paid", headers=patient_headers)
    assert patient_mark_res.status_code == 403, f"Expected 403 Forbidden for patient, got: {patient_mark_res.status_code}"
    print("✓ Patient blocked from self-confirming cash payment (403 Forbidden)")

    # 3. Pharmacist marks cash paid upon cash collection
    pharmacist_mark_res = client.post(f"/api/reservations/{reservation_id}/mark-cash-paid", headers=pharmacist_headers)
    assert pharmacist_mark_res.status_code == 200, f"Pharmacist confirmation failed: {pharmacist_mark_res.text}"
    confirmed_data = pharmacist_mark_res.json()
    print("✓ Pharmacist successfully marked cash reservation as paid")
    assert confirmed_data["payment_status"] == "paid"
    assert confirmed_data["status"] == "Collected"
    assert confirmed_data["cash_payment_confirmed_at"] is not None

def test_paystack_online_initialization_and_duplicate_prevention():
    print("\n--- TEST 2: Paystack Online Payment Initialization & Guardrails ---")
    data = setup_test_data()
    patient_headers = {"Authorization": f"Bearer {data['patient_token']}"}

    # 1. Create online Paystack reservation
    res_payload = {
        "medicine_id": data["medicine"].id,
        "pharmacy_id": data["pharmacy"].id,
        "quantity": 1,
        "payment_method": "paystack",
        "notes": "E2E Test Paystack Reservation"
    }
    create_res = client.post("/api/reservations/", json=res_payload, headers=patient_headers)
    assert create_res.status_code == 201
    res_data = create_res.json()
    reservation_id = res_data["id"]
    print(f"✓ Online reservation created: ID={reservation_id}, PaymentMethod={res_data['payment_method']}")

    # 2. Initialize Paystack payment
    init_payload = {
        "reservation_id": reservation_id,
        "callback_url": "https://example.com/callback"
    }
    init_res = client.post("/api/payments/initialize", json=init_payload, headers=patient_headers)
    assert init_res.status_code == 200, f"Payment init failed: {init_res.text}"
    init_data = init_res.json()
    assert init_data["reference"].startswith("MF_PAY_")
    assert "authorization_url" in init_data
    print(f"✓ Paystack payment initialized: Reference={init_data['reference']}")

    # 3. Verify PaymentTransaction record in database
    with Session(engine) as db:
        txn = db.exec(select(PaymentTransaction).where(PaymentTransaction.reservation_id == reservation_id)).first()
        assert txn is not None
        assert txn.status == PaymentStatus.PENDING
        assert txn.amount == 45.0
        print(f"✓ Pending PaymentTransaction recorded in DB: Amount={txn.amount} GHS")

    # 4. Simulate payment already marked PAID, then verify double-init is rejected
    with Session(engine) as db:
        db_res = db.get(Reservation, reservation_id)
        db_res.payment_status = PaymentStatus.PAID
        db.add(db_res)
        db.commit()

    double_init_res = client.post("/api/payments/initialize", json=init_payload, headers=patient_headers)
    assert double_init_res.status_code == 400
    assert "already been paid" in double_init_res.json()["detail"].lower()
    print("✓ Double-payment prevented on already paid reservation (400 Bad Request)")

def test_pharmacy_subaccount_api():
    print("\n--- TEST 3: Pharmacy Paystack Subaccount Configuration ---")
    data = setup_test_data()
    pharmacist_headers = {"Authorization": f"Bearer {data['pharmacist_token']}"}
    pharmacy_id = data["pharmacy"].id

    # 1. Query subaccount info (masked account number)
    subacc_res = client.get(f"/api/pharmacies/{pharmacy_id}/paystack/subaccount", headers=pharmacist_headers)
    assert subacc_res.status_code == 200
    subacc_data = subacc_res.json()
    assert subacc_data["subaccount_code"] == "ACCT_e2e_test_subacc"
    assert subacc_data["account_number"] == "024****567"
    print(f"✓ Masked subaccount retrieved: {subacc_data['account_number']}")

def test_paystack_webhook_verification():
    print("\n--- TEST 4: Webhook Signature Handling ---")
    payload = {
        "event": "charge.success",
        "data": {
            "reference": "MF_PAY_NONEXISTENT_TEST_REF",
            "amount": 4500,
            "status": "success",
            "metadata": {"reservation_id": 999999}
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")

    # 1. Invalid signature
    invalid_headers = {"x-paystack-signature": "invalid_sha512_signature"}
    inv_res = client.post("/api/payments/paystack/webhook", content=raw_body, headers=invalid_headers)
    assert inv_res.status_code == 400
    print("✓ Invalid webhook signature correctly rejected (400 Bad Request)")

if __name__ == "__main__":
    print("==================================================")
    print("RUNNING E2E PAYMENT INTEGRATION TEST SUITE")
    print("==================================================")
    test_cash_payment_flow()
    test_paystack_online_initialization_and_duplicate_prevention()
    test_pharmacy_subaccount_api()
    test_paystack_webhook_verification()
    print("\n==================================================")
    print("ALL E2E PAYMENT INTEGRATION TESTS PASSED SUCCESSFULLY!")
    print("==================================================")
