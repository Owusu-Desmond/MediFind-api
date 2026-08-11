import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
import httpx
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
MAIL_FROM = os.getenv("MAIL_FROM", "")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")


def render_approval_html_email(pharmacy_name: str, email: str, password: str, login_url: str) -> str:
    """Renders a responsive HTML email template for pharmacy approval with spam optimization."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pharmacy Account Approved - MediFind Ghana</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f4f7f6; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #334155;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f4f7f6; padding: 40px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" max-width="600" cellspacing="0" cellpadding="0" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
          
          <!-- Header -->
          <tr>
            <td style="background-color: #005c55; padding: 32px; text-align: center;">
              <h1 style="color: #ffffff; margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">MediFind Ghana</h1>
              <p style="color: #99f6e4; margin: 6px 0 0 0; font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Official Pharmacy Partner Network</p>
            </td>
          </tr>

          <!-- Content -->
          <tr>
            <td style="padding: 32px 32px 24px 32px;">
              <div style="display: inline-block; background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 20px; padding: 4px 12px; font-size: 12px; font-weight: 700; color: #166534; margin-bottom: 16px;">
                APPLICATION APPROVED
              </div>
              
              <h2 style="margin: 0 0 12px 0; color: #0f172a; font-size: 20px; font-weight: 800;">Congratulations, {pharmacy_name}!</h2>
              
              <p style="margin: 0 0 20px 0; font-size: 14px; line-height: 1.6; color: #475569;">
                Your pharmacy application has been verified and approved by the MediFind Compliance Committee. Your pharmacy branch is now activated on the national digital healthcare network.
              </p>

              <!-- Credentials Box -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; margin-bottom: 20px;">
                <tr>
                  <td style="padding: 20px;">
                    <p style="margin: 0 0 12px 0; font-size: 11px; font-weight: 800; text-transform: uppercase; color: #64748b; letter-spacing: 0.5px;">YOUR PHARMACY PORTAL CREDENTIALS</p>
                    <p style="margin: 4px 0; font-size: 13px; color: #334155;"><strong>Login Email:</strong> <span style="color: #005c55; font-weight: 700;">{email}</span></p>
                    <p style="margin: 4px 0; font-size: 13px; color: #334155;"><strong>Generated Password:</strong> <code style="background-color: #e2e8f0; padding: 3px 8px; border-radius: 4px; font-family: monospace; font-size: 15px; font-weight: 700; color: #0f172a;">{password}</code></p>
                  </td>
                </tr>
              </table>

              <!-- Security Awareness Callout -->
              <div style="background-color: #f0f9ff; border-left: 4px solid #0284c7; padding: 14px; border-radius: 0 6px 6px 0; margin-bottom: 24px;">
                <p style="margin: 0; font-size: 12px; color: #0369a1; line-height: 1.5; font-weight: 600;">
                  🔒 <strong>Password Security Notice:</strong> This is a securely generated initial password. You can easily change this password at any time after logging in by visiting <strong>Pharmacy Profile & Settings</strong>.
                </p>
              </div>

              <!-- Call to Action Button -->
              <div style="text-align: center; margin: 28px 0;">
                <a href="{login_url}" target="_blank" style="display: inline-block; background-color: #005c55; color: #ffffff; text-decoration: none; font-size: 14px; font-weight: 700; padding: 14px 28px; border-radius: 6px; box-shadow: 0 2px 4px rgba(0, 92, 85, 0.2);">
                  Sign In to Pharmacy Portal &rarr;
                </a>
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 20px 32px; text-align: center;">
              <p style="margin: 0; font-size: 11px; color: #94a3b8;">
                MediFind Ghana Healthcare Technologies • Accra, Ghana<br>
                If you did not request this registration, please contact support@medifindghana.com
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


async def send_approval_email_async(email: str, pharmacy_name: str, password: str, login_url: str = "http://localhost:3001/"):
    """
    Sends pharmacy approval notification email using:
    1. Resend API (if RESEND_API_KEY is configured)
    2. SMTP Server (if SMTP_HOST is configured)
    3. Console Logger (development fallback)
    """
    # Clean professional subject (no emojis) for high inbox deliverability
    subject = f"MediFind Ghana: Pharmacy Application Approved ({pharmacy_name})"
    html_content = render_approval_html_email(pharmacy_name, email, password, login_url)
    plain_text = (
        f"Dear {pharmacy_name} Team,\n\n"
        f"Your pharmacy application has been APPROVED!\n\n"
        f"LOGIN DETAILS:\n"
        f"Portal URL: {login_url}\n"
        f"Email: {email}\n"
        f"Generated Password: {password}\n\n"
        f"Security Notice: You can change this password at any time after logging in under Pharmacy Profile & Settings.\n"
    )

    # 1. Try Resend API (Best Delivery Platform)
    if RESEND_API_KEY and not RESEND_API_KEY.startswith("re_123456789"):
        try:
            from_hdr = MAIL_FROM or "MediFind Ghana <onboarding@resend.dev>"
            print(f"[EmailService] Sending via Resend API to {email}...")
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": from_hdr,
                        "to": [email],
                        "subject": subject,
                        "html": html_content,
                        "text": plain_text,
                    },
                )
            if res.status_code in (200, 201):
                print(f"[EmailService] Resend email delivered successfully to {email}! Message ID: {res.json().get('id')}")
                return True
            else:
                print(f"[EmailService] Resend API error (HTTP {res.status_code}): {res.text}")
        except Exception as e:
            print(f"[EmailService] Resend API exception: {e}")

    # 2. Try SMTP if configured
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        try:
            smtp_pass = SMTP_PASSWORD.strip().replace(" ", "")
            sender_header = MAIL_FROM or f"MediFind Support <{SMTP_USER}>"

            print(f"[EmailService] Sending via SMTP ({SMTP_HOST}:{SMTP_PORT}) to {email} from '{sender_header}'...")
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = sender_header
            msg["To"] = email
            msg["Reply-To"] = SMTP_USER
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid(domain="medifindghana.com")

            msg.attach(MIMEText(plain_text, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15.0) as server:
                server.starttls()
                server.login(SMTP_USER, smtp_pass)
                server.sendmail(SMTP_USER, [email], msg.as_string())

            print(f"[EmailService] SMTP email delivered successfully to {email}!")
            return True
        except Exception as e:
            print(f"[EmailService] SMTP exception: {e}")

    # 3. Development Fallback (Console Print)
    print("\n" + "=" * 65)
    print(f"[EMAIL SERVICE - DEV NOTIFICATION LOG]")
    print(f"TO: {email}")
    print(f"SUBJECT: {subject}")
    print(f"PORTAL LINK: {login_url}")
    print(f"PASSWORD: {password}")
    print("=" * 65 + "\n")
    return True


def send_approval_email(email: str, pharmacy_name: str, password: str, login_url: str = "http://localhost:3001/"):
    """Synchronous wrapper for FastAPI endpoint handlers."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(send_approval_email_async(email, pharmacy_name, password, login_url))
    except RuntimeError:
        asyncio.run(send_approval_email_async(email, pharmacy_name, password, login_url))
    return True
