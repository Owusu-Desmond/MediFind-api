import os
import hmac
import hashlib
import httpx
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "sk_test_mock_secret_key_medifind")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "pk_test_mock_public_key_medifind")
PAYSTACK_BASE_URL = "https://api.paystack.co"

# Platform fee configuration
# Default: 0% or configurable percentage (e.g. 5.0 for 5%) / fixed fee (e.g. 0.0 GHS)
PLATFORM_FEE_PERCENT = float(os.getenv("PAYSTACK_PLATFORM_FEE_PERCENT", "0.0"))
PLATFORM_FIXED_FEE = float(os.getenv("PAYSTACK_FIXED_FEE", "0.0"))

# Standard Ghana Banks & Mobile Money Providers (Paystack Ghana bank codes)
GHANA_PROVIDERS = [
    {"name": "MTN Mobile Money", "code": "MTN", "type": "mobile_money"},
    {"name": "Telecel Cash (Vodafone)", "code": "VOD", "type": "mobile_money"},
    {"name": "AT Money (AirtelTigo)", "code": "ATL", "type": "mobile_money"},
    {"name": "GCB Bank Limited", "code": "040100", "type": "bank"},
    {"name": "Ecobank Ghana", "code": "130100", "type": "bank"},
    {"name": "Absa Bank Ghana", "code": "030100", "type": "bank"},
    {"name": "Stanbic Bank Ghana", "code": "190100", "type": "bank"},
    {"name": "Standard Chartered Bank", "code": "020100", "type": "bank"},
    {"name": "Fidelity Bank Ghana", "code": "240100", "type": "bank"},
    {"name": "CalBank", "code": "140100", "type": "bank"},
    {"name": "Zenith Bank Ghana", "code": "120100", "type": "bank"},
    {"name": "Access Bank Ghana", "code": "280100", "type": "bank"},
]

def get_paystack_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

def calculate_fees(total_amount: float) -> Dict[str, float]:
    """
    Authoritative platform fee calculation.
    Supports percentage-based, fixed fee, or 0 platform fee.
    """
    platform_fee = (total_amount * (PLATFORM_FEE_PERCENT / 100.0)) + PLATFORM_FIXED_FEE
    platform_fee = round(max(0.0, min(platform_fee, total_amount)), 2)
    pharmacy_amount = round(total_amount - platform_fee, 2)
    return {
        "total_amount": round(total_amount, 2),
        "platform_fee": platform_fee,
        "pharmacy_amount": pharmacy_amount,
        "percentage_fee": PLATFORM_FEE_PERCENT,
        "fixed_fee": PLATFORM_FIXED_FEE,
    }

async def fetch_paystack_banks(country: str = "ghana") -> List[Dict[str, Any]]:
    """
    Fetch supported banks & mobile money providers from Paystack API,
    with static Ghana fallback if offline/mock.
    """
    if PAYSTACK_SECRET_KEY.startswith("sk_test_mock"):
        return GHANA_PROVIDERS

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                f"{PAYSTACK_BASE_URL}/bank?country={country}&currency=GHS",
                headers=get_paystack_headers(),
            )
            if res.status_code == 200:
                data = res.json()
                if data.get("status") and data.get("data"):
                    return [
                        {
                            "name": b.get("name"),
                            "code": b.get("code"),
                            "type": b.get("type", "bank"),
                            "slug": b.get("slug"),
                        }
                        for b in data.get("data", [])
                    ]
    except Exception as e:
        print(f"[Paystack] Failed to fetch live banks ({e}), using default Ghana bank list")
    
    return GHANA_PROVIDERS

async def create_paystack_subaccount(
    business_name: str,
    settlement_bank: str,
    account_number: str,
    percentage_charge: float = PLATFORM_FEE_PERCENT,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a subaccount on Paystack for split payment routing.
    If using mock test key, gracefully return a mock subaccount code.
    """
    if PAYSTACK_SECRET_KEY.startswith("sk_test_mock"):
        import uuid
        mock_code = f"ACCT_MOCK_{uuid.uuid4().hex[:8].upper()}"
        return {
            "status": True,
            "subaccount_code": mock_code,
            "subaccount_id": f"ID_{mock_code}",
            "message": "Mock subaccount created successfully",
            "is_mock": True,
        }

    payload = {
        "business_name": business_name,
        "settlement_bank": settlement_bank,
        "account_number": account_number,
        "percentage_charge": percentage_charge,
        "description": description or f"MediFind Payout Subaccount for {business_name}",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            f"{PAYSTACK_BASE_URL}/subaccount",
            headers=get_paystack_headers(),
            json=payload,
        )
        data = res.json()
        if res.status_code in (200, 201) and data.get("status"):
            sub_data = data.get("data", {})
            return {
                "status": True,
                "subaccount_code": sub_data.get("subaccount_code"),
                "subaccount_id": str(sub_data.get("id")),
                "message": data.get("message", "Subaccount created"),
                "is_mock": False,
            }
        else:
            error_msg = data.get("message", f"Paystack error: {res.status_code}")
            return {
                "status": False,
                "subaccount_code": None,
                "subaccount_id": None,
                "message": error_msg,
                "is_mock": False,
            }

async def initialize_paystack_transaction(
    email: str,
    amount_in_ghs: float,
    reference: str,
    callback_url: Optional[str] = None,
    subaccount_code: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Initialize a Paystack transaction with split payment to pharmacy subaccount.
    Amount sent to Paystack is in Pesewas (1 GHS = 100 Pesewas).
    """
    amount_in_pesewas = int(round(amount_in_ghs * 100))

    if PAYSTACK_SECRET_KEY.startswith("sk_test_mock"):
        return {
            "status": True,
            "authorization_url": f"https://checkout.paystack.com/{reference}",
            "access_code": f"access_{reference}",
            "reference": reference,
            "is_mock": True,
        }

    payload: Dict[str, Any] = {
        "email": email,
        "amount": amount_in_pesewas,
        "currency": "GHS",
        "reference": reference,
        "metadata": metadata or {},
    }

    if callback_url:
        payload["callback_url"] = callback_url

    if subaccount_code and not subaccount_code.startswith("ACCT_MOCK"):
        payload["subaccount"] = subaccount_code
        # 'subaccount' bearer means transaction fees are borne by the subaccount
        payload["bearer"] = "subaccount"

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            headers=get_paystack_headers(),
            json=payload,
        )
        data = res.json()
        if res.status_code in (200, 201) and data.get("status"):
            tx_data = data.get("data", {})
            return {
                "status": True,
                "authorization_url": tx_data.get("authorization_url"),
                "access_code": tx_data.get("access_code"),
                "reference": tx_data.get("reference", reference),
                "is_mock": False,
            }
        else:
            return {
                "status": False,
                "message": data.get("message", f"Initialization failed: {res.status_code}"),
                "is_mock": False,
            }

async def verify_paystack_transaction(reference: str) -> Dict[str, Any]:
    """
    Direct server-side verification of transaction with Paystack API.
    """
    if PAYSTACK_SECRET_KEY.startswith("sk_test_mock") or reference.startswith("PS-MOCK"):
        return {
            "status": True,
            "transaction_status": "success",
            "amount": None, # verified caller can keep DB amount
            "gateway_response": "Successful (Mock Verified)",
            "paid_at": None,
            "reference": reference,
            "is_mock": True,
        }

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=get_paystack_headers(),
        )
        data = res.json()
        if res.status_code == 200 and data.get("status"):
            tx_data = data.get("data", {})
            return {
                "status": True,
                "transaction_status": tx_data.get("status"), # "success", "failed", "abandoned"
                "amount": (tx_data.get("amount", 0) / 100.0) if tx_data.get("amount") else None,
                "currency": tx_data.get("currency"),
                "gateway_response": tx_data.get("gateway_response"),
                "paid_at": tx_data.get("paid_at"),
                "transaction_id": str(tx_data.get("id")),
                "reference": tx_data.get("reference", reference),
                "is_mock": False,
            }
        else:
            return {
                "status": False,
                "transaction_status": "failed",
                "message": data.get("message", "Verification failed"),
                "is_mock": False,
            }

def verify_paystack_webhook_signature(payload_bytes: bytes, signature_header: Optional[str]) -> bool:
    """
    Verify Paystack HMAC SHA512 webhook signature.
    """
    if not signature_header:
        return False
    
    if PAYSTACK_SECRET_KEY.startswith("sk_test_mock"):
        return True

    expected_signature = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        payload_bytes,
        hashlib.sha512
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)
