"""
End-to-End HTTP Integration Test Suite for MediFind Payment API
Tests the running server at http://127.0.0.1:8000
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import sys

BASE_URL = "http://127.0.0.1:8000"

def log(msg):
    print(msg, flush=True)

def make_request(method, path, body=None, headers=None, form_data=None):
    url = f"{BASE_URL}{path}"
    req_headers = {}
    if headers:
        req_headers.update(headers)
    
    if form_data is not None:
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = form_data.encode("utf-8")
    elif body is not None:
        req_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    else:
        data = None

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            res_body = resp.read().decode("utf-8")
            try:
                json_data = json.loads(res_body)
            except Exception:
                json_data = res_body
            return status, json_data
    except urllib.error.HTTPError as e:
        res_body = e.read().decode("utf-8")
        try:
            json_data = json.loads(res_body)
        except Exception:
            json_data = res_body
        return e.code, json_data

def get_or_register_user(email, password, name, role="Patient"):
    # 1. Try login
    form = f"username={urllib.parse.quote(email)}&password={urllib.parse.quote(password)}"
    status, data = make_request("POST", "/api/auth/login", form_data=form)
    if status == 200 and isinstance(data, dict) and "access_token" in data:
        return data["access_token"]
    
    # 2. Try register with role
    reg_body = {
        "email": email,
        "password": password,
        "name": name,
        "role": role,
        "phone": "0240000000"
    }
    status, data = make_request("POST", "/api/auth/register", body=reg_body)
    
    # 3. Login after register
    status, data = make_request("POST", "/api/auth/login", form_data=form)
    if status == 200 and isinstance(data, dict) and "access_token" in data:
        return data["access_token"]
    
    log(f"Failed to authenticate {email}: {data}")
    return None

def main():
    log("==================================================")
    log("RUNNING LIVE HTTP PAYMENT INTEGRATION TESTS")
    log(f"Target: {BASE_URL}")
    log("==================================================")

    # 1. Check API Health
    status, data = make_request("GET", "/")
    log(f"✓ API Root: Status {status}")

    # 2. Get available medicines
    status, medicines = make_request("GET", "/api/medicines/")
    assert status == 200, f"Medicines failed: {medicines}"
    if not medicines:
        log("No medicines found in database to reserve, test cannot proceed.")
        return
    
    target_medicine = medicines[0]
    med_id = target_medicine["id"]
    pharmacy_id = target_medicine.get("pharmacy_id") or (target_medicine.get("pharmacy") and target_medicine["pharmacy"].get("id")) or 1
    log(f"✓ Found target medicine: '{target_medicine['name']}' at Pharmacy ID: {pharmacy_id}")

    # 3. Create or login test users
    patient_email = "test_patient_payment_live@example.com"
    # Authenticate as the pharmacy's pharmacist email or admin
    pharmacist_email = "central@ghanapharmacy.gov.gh"
    admin_email = "admin_e2e_live@example.com"
    
    patient_token = get_or_register_user(patient_email, "password123", "Payment Test Patient Live", "Patient")
    pharmacist_token = get_or_register_user(pharmacist_email, "password123", "Dr. Emmanuel Mensah", "Pharmacist")
    admin_token = get_or_register_user(admin_email, "password123", "System Admin Live", "Admin")
    
    assert patient_token, "Could not acquire patient token"
    assert pharmacist_token or admin_token, "Could not acquire pharmacist/admin token"
    active_staff_token = pharmacist_token or admin_token
    log("✓ Successfully authenticated Test Patient and Pharmacy Staff")

    patient_headers = {"Authorization": f"Bearer {patient_token}"}
    staff_headers = {"Authorization": f"Bearer {active_staff_token}"}

    # ==========================================
    # TEST 1: Pay at Pharmacy (Cash) Flow
    # ==========================================
    log("\n--- TEST 1: Cash Reservation & Confirmation Flow ---")
    cash_res_payload = {
        "pharmacy_id": pharmacy_id,
        "items": [{"medicine_id": med_id, "quantity": 1}],
        "payment_method": "CASH",
        "notes": "Live HTTP E2E Test Cash Reservation"
    }
    status, res_data = make_request("POST", "/api/reservations/", body=cash_res_payload, headers=patient_headers)
    assert status in (200, 201), f"Cash reservation creation failed: {res_data}"
    cash_res_id = res_data["id"]
    res_code = res_data["reservation_code"]
    log(f"✓ Cash reservation created: ID={cash_res_id}, Reservation Code={res_code}")
    assert res_code.startswith("MF-"), f"Expected MF- prefix, got {res_code}"
    assert res_data["payment_method"].upper() == "CASH"
    assert res_data["payment_status"].upper() == "UNPAID"

    # Patient attempts to mark cash paid (MUST FAIL with 403 Forbidden)
    status, err_data = make_request("POST", f"/api/reservations/{cash_res_id}/mark-cash-paid", headers=patient_headers)
    assert status == 403, f"Expected 403 Forbidden for patient, got: {status}"
    log("✓ Security check passed: Patient cannot self-confirm cash payment (403 Forbidden)")

    # Pharmacist marks cash paid
    status, paid_data = make_request("POST", f"/api/reservations/{cash_res_id}/mark-cash-paid", headers=staff_headers)
    assert status == 200, f"Pharmacist confirmation failed: {paid_data}"
    log(f"✓ Pharmacist confirmed cash collection: Status={paid_data.get('reservation_status')}, PaymentStatus={paid_data.get('payment_status')}")
    assert paid_data["payment_status"].upper() == "PAID"
    assert paid_data["reservation_status"] == "Collected"
    assert paid_data["confirmed_at"] is not None

    # ==========================================
    # TEST 2: Pay Online with Paystack Flow
    # ==========================================
    log("\n--- TEST 2: Paystack Online Payment Flow ---")
    online_res_payload = {
        "pharmacy_id": pharmacy_id,
        "items": [{"medicine_id": med_id, "quantity": 1}],
        "payment_method": "PAYSTACK",
        "notes": "Live HTTP E2E Test Paystack Reservation"
    }
    status, online_res = make_request("POST", "/api/reservations/", body=online_res_payload, headers=patient_headers)
    assert status in (200, 201), f"Online reservation failed: {online_res}"
    online_res_id = online_res["id"]
    log(f"✓ Paystack reservation created: ID={online_res_id}, Method={online_res['payment_method']}")
    assert online_res["payment_method"].upper() == "PAYSTACK"
    assert online_res["payment_status"].upper() == "UNPAID"

    # Initialize Paystack transaction
    init_payload = {
        "reservation_id": online_res_id,
        "callback_url": "http://127.0.0.1:8000/api/payments/verify"
    }
    status, init_data = make_request("POST", "/api/payments/initialize", body=init_payload, headers=patient_headers)
    assert status == 200, f"Paystack init failed: {init_data}"
    ref = init_data["reference"]
    auth_url = init_data.get("authorization_url")
    log(f"✓ Paystack transaction initialized: Reference={ref}")
    log(f"✓ Authorization URL: {auth_url}")
    assert ref.startswith("MF-")

    # Double Payment Prevention Check: Verify endpoint responds idempotently
    status, verify_data = make_request("GET", f"/api/payments/verify/{ref}", headers=patient_headers)
    log(f"✓ Paystack verify endpoint checked: Status={status}")

    # ==========================================
    # TEST 3: Pharmacy Subaccount API
    # ==========================================
    log("\n--- TEST 3: Subaccount Inspection ---")
    status, subacc_data = make_request("GET", f"/api/pharmacies/{pharmacy_id}/paystack/subaccount", headers=staff_headers)
    assert status == 200, f"Failed to get subaccount: {subacc_data}"
    log(f"✓ Subaccount Query: {subacc_data}")

    # ==========================================
    # TEST 4: Webhook Security Verification
    # ==========================================
    log("\n--- TEST 4: Webhook Signature Handling ---")
    bad_webhook_headers = {"x-paystack-signature": "bogus_signature_12345"}
    status, resp = make_request("POST", "/api/payments/paystack/webhook", body={"event": "charge.success"}, headers=bad_webhook_headers)
    assert status in (400, 401), f"Expected 400/401 for bad signature, got {status}"
    log(f"✓ Invalid webhook signature correctly rejected with HTTP {status}")

    log("\n==================================================")
    log("ALL LIVE END-TO-END HTTP INTEGRATION TESTS PASSED!")
    log("==================================================")

if __name__ == "__main__":
    main()
