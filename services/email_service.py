import os
import smtplib
import re
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

# Try loading .env if dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def is_valid_email(email):
    """Validate an email address string."""
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_REGEX.match(email.strip()))

def get_smtp_config():
    """Retrieve SMTP settings from environment variables."""
    server = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
    port = int(os.getenv("MAIL_PORT", "587").strip())
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_PASSWORD", "").strip()
    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
    use_ssl = os.getenv("MAIL_USE_SSL", "false").lower() in ("true", "1", "yes")
    default_sender = os.getenv("MAIL_DEFAULT_SENDER", "").strip() or username or "admission@prathyusha.edu.in"
    
    return {
        "server": server,
        "port": port,
        "username": username,
        "password": password,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
        "default_sender": default_sender
    }

def is_smtp_configured():
    """Return True if credentials are provided."""
    cfg = get_smtp_config()
    return bool(cfg["username"] and cfg["password"])

def format_human_date(date_str):
    """Format dates like '2026-10-05' into '05 October 2026'."""
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            dt = datetime.datetime.strptime(date_str, fmt)
            return dt.strftime("%d %B %Y")
        except ValueError:
            continue
    return date_str

def format_human_time(time_str):
    """Format times like '10:30' into '10:30 AM'."""
    if not time_str:
        return ""
    time_str = str(time_str).strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            dt = datetime.datetime.strptime(time_str, fmt)
            return dt.strftime("%I:%M %p")
        except ValueError:
            continue
    return time_str

def send_email(to_email, subject, body_text, body_html=None):
    """
    Send an email via SMTP.
    Returns: (success: bool, error_message: str or None)
    """
    if not is_valid_email(to_email):
        return False, f"Invalid recipient email address: '{to_email}'"

    cfg = get_smtp_config()
    if not cfg["username"] or not cfg["password"]:
        return False, "SMTP configuration missing: MAIL_USERNAME or MAIL_PASSWORD not set in environment."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg["default_sender"]
        msg["To"] = to_email
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()

        # Attach text part
        part1 = MIMEText(body_text, "plain", "utf-8")
        msg.attach(part1)

        # Attach HTML part if provided
        if body_html:
            part2 = MIMEText(body_html, "html", "utf-8")
            msg.attach(part2)

        # Connect and send
        if cfg["use_ssl"]:
            server = smtplib.SMTP_SSL(cfg["server"], cfg["port"], timeout=20)
        else:
            server = smtplib.SMTP(cfg["server"], cfg["port"], timeout=20)
            if cfg["use_tls"]:
                server.starttls()

        server.login(cfg["username"], cfg["password"])
        server.sendmail(cfg["default_sender"], [to_email], msg.as_string())
        server.quit()
        return True, None

    except smtplib.SMTPAuthenticationError:
        return False, "SMTP Authentication Failed: Check MAIL_USERNAME and MAIL_PASSWORD (use Gmail App Password)."
    except smtplib.SMTPConnectError:
        return False, f"Failed to connect to SMTP server at {cfg['server']}:{cfg['port']}."
    except Exception as e:
        # Sanitized error message (never expose password)
        err_msg = str(e)
        if cfg["password"] and cfg["password"] in err_msg:
            err_msg = err_msg.replace(cfg["password"], "********")
        return False, f"SMTP Error: {err_msg}"

def send_student_followup_email(student_email, student_name, app_no, visit_date, visit_time, purpose):
    """
    Send follow-up reminder email to student according to section 6.
    """
    formatted_date = format_human_date(visit_date)
    formatted_time = format_human_time(visit_time)
    display_student = (student_name or "Applicant").strip()
    display_purpose = (purpose or "Confirm Admission").strip()
    display_app_no = (app_no or "").strip()

    subject = f"Admission Follow-up Reminder – {display_app_no}"

    # Plain text version
    body_text = f"""Dear {display_student},

This is a reminder regarding your admission application.

Application Number:
{display_app_no}

Your next visit to the college is scheduled for:

Date: {formatted_date}
Time: {formatted_time}

Purpose:
{display_purpose}

Please visit the college on the scheduled date and time.

If you need to make any changes to your visit, please contact the admission coordinator.

Regards,
Admission Management System
Prathyusha Engineering College
"""

    # Rich HTML version
    body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-top: 5px solid #a60000; }}
    .header {{ background: #a60000; color: #ffffff; padding: 24px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 20px; letter-spacing: 0.5px; }}
    .header p {{ margin: 4px 0 0; font-size: 13px; opacity: 0.9; }}
    .content {{ padding: 28px 24px; color: #333333; line-height: 1.6; }}
    .card {{ background: #fdf8f8; border-left: 4px solid #a60000; border-radius: 4px; padding: 16px; margin: 20px 0; }}
    .detail-row {{ margin-bottom: 8px; font-size: 14px; }}
    .detail-label {{ font-weight: bold; color: #555555; display: inline-block; width: 150px; }}
    .detail-value {{ color: #111111; font-weight: 600; }}
    .footer {{ background: #f8f9fa; padding: 18px 24px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #eeeeee; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Prathyusha Engineering College</h1>
      <p>Admission Management System</p>
    </div>
    <div class="content">
      <p>Dear <strong>{display_student}</strong>,</p>
      <p>This is a reminder regarding your admission application at Prathyusha Engineering College.</p>
      
      <div class="card">
        <div class="detail-row"><span class="detail-label">Application Number:</span> <span class="detail-value">{display_app_no}</span></div>
        <div class="detail-row"><span class="detail-label">Scheduled Date:</span> <span class="detail-value">{formatted_date}</span></div>
        <div class="detail-row"><span class="detail-label">Scheduled Time:</span> <span class="detail-value">{formatted_time}</span></div>
        <div class="detail-row"><span class="detail-label">Purpose / Reason:</span> <span class="detail-value">{display_purpose}</span></div>
      </div>

      <p>Please visit the college on the scheduled date and time.</p>
      <p>If you need to make any changes to your visit, please contact your admission coordinator.</p>
    </div>
    <div class="footer">
      <p>Regards,<br><strong>Admission Management System</strong><br>Prathyusha Engineering College</p>
      <p style="margin-top: 8px; font-size: 11px; color: #999;">This is an automated reminder. Please do not reply directly to this email.</p>
    </div>
  </div>
</body>
</html>
"""

    return send_email(student_email, subject, body_text, body_html)

def send_coordinator_followup_email(coord_email, coord_name, student_name, app_no, visit_date, visit_time, purpose, feedback):
    """
    Send follow-up reminder email to coordinator according to section 7.
    """
    formatted_date = format_human_date(visit_date)
    formatted_time = format_human_time(visit_time)
    display_student = (student_name or "Student").strip()
    display_purpose = (purpose or "Confirm Admission").strip()
    display_feedback = (feedback or "Visit discussed with coordinator.").strip()
    display_app_no = (app_no or "").strip()

    subject = f"Student Follow-up Reminder – {display_student} – {display_app_no}"

    # Plain text version
    body_text = f"""Dear Coordinator,

This is a reminder about an upcoming student follow-up.

Student:
{display_student}

Application Number:
{display_app_no}

Scheduled Date:
{formatted_date}

Scheduled Time:
{formatted_time}

Purpose:
{display_purpose}

Previous Feedback:
{display_feedback}

Please follow up with the student as required.

Regards,
Admission Management System
"""

    # Rich HTML version
    body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-top: 5px solid #1e3a8a; }}
    .header {{ background: #1e3a8a; color: #ffffff; padding: 24px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 20px; }}
    .header p {{ margin: 4px 0 0; font-size: 13px; opacity: 0.9; }}
    .content {{ padding: 28px 24px; color: #333333; line-height: 1.6; }}
    .card {{ background: #f0f4ff; border-left: 4px solid #1e3a8a; border-radius: 4px; padding: 16px; margin: 20px 0; }}
    .detail-row {{ margin-bottom: 8px; font-size: 14px; }}
    .detail-label {{ font-weight: bold; color: #555555; display: inline-block; width: 160px; }}
    .detail-value {{ color: #111111; font-weight: 600; }}
    .footer {{ background: #f8f9fa; padding: 18px 24px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #eeeeee; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Admission Management System</h1>
      <p>Coordinator Follow-up Alert</p>
    </div>
    <div class="content">
      <p>Dear Coordinator,</p>
      <p>This is a reminder about an upcoming student follow-up scheduled in the Admission Management System.</p>
      
      <div class="card">
        <div class="detail-row"><span class="detail-label">Student Name:</span> <span class="detail-value">{display_student}</span></div>
        <div class="detail-row"><span class="detail-label">Application Number:</span> <span class="detail-value">{display_app_no}</span></div>
        <div class="detail-row"><span class="detail-label">Scheduled Date:</span> <span class="detail-value">{formatted_date}</span></div>
        <div class="detail-row"><span class="detail-label">Scheduled Time:</span> <span class="detail-value">{formatted_time}</span></div>
        <div class="detail-row"><span class="detail-label">Purpose / Reason:</span> <span class="detail-value">{display_purpose}</span></div>
        <div class="detail-row" style="margin-top: 10px;"><span class="detail-label">Previous Feedback:</span> <br><span style="color:#444; font-style: italic;">{display_feedback}</span></div>
      </div>

      <p>Please follow up with the student as required.</p>
    </div>
    <div class="footer">
      <p>Regards,<br><strong>Admission Management System</strong><br>Prathyusha Engineering College</p>
    </div>
  </div>
</body>
</html>
"""

    return send_email(coord_email, subject, body_text, body_html)

def send_test_email(to_email):
    """
    Test email sender for admin configuration validation (section 24).
    """
    subject = "AMS Test Email - SMTP Configuration Successful"
    body_text = f"""Dear Administrator,

This is a test email sent from the Admission Management System (AMS) to verify that your SMTP email settings are working correctly.

Sent At: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Recipient: {to_email}

Your follow-up email notification system is configured properly.

Regards,
Admission Management System
Prathyusha Engineering College
"""
    body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; }}
    .container {{ max-width: 500px; margin: 0 auto; background: #ffffff; border-radius: 8px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-top: 5px solid #16a34a; }}
    h2 {{ color: #16a34a; margin-top: 0; }}
  </style>
</head>
<body>
  <div class="container">
    <h2>✓ SMTP Test Successful</h2>
    <p>This is a test email from the <strong>Admission Management System (AMS)</strong> confirming that your SMTP email configuration is active and working properly.</p>
    <p><strong>Sent At:</strong> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
       <strong>Recipient:</strong> {to_email}</p>
    <p style="color: #666; font-size: 13px;">You can now use automatic email reminders for student follow-up visits.</p>
  </div>
</body>
</html>
"""
    return send_email(to_email, subject, body_text, body_html)


def send_coordinator_credentials_email(coord_email, username, password, login_url=None):
    """
    Send an account creation welcome email to a new Coordinator with their login credentials.
    Dynamically sent to the email provided by the Admin.
    """
    display_name = (username or "Admission Coordinator").strip()
    clean_email = (coord_email or "").strip()
    display_url = login_url or "http://127.0.0.1:5000/coordinator"

    subject = "Your Admission Coordinator Account Credentials – Prathyusha Engineering College"

    # Plain text version
    body_text = f"""Dear {display_name},

An Admission Coordinator account has been successfully created for you by the Administrator in the Admission Management System (AMS) at Prathyusha Engineering College.

Your Login Credentials:
------------------------------------------
Portal URL : {display_url}
Email / ID : {clean_email}
User Name  : {display_name}
Password   : {password}
------------------------------------------

Instructions:
1. Open the portal URL in your web browser: {display_url}
2. Enter your Email Address and Password to sign in.
3. Access your Coordinator Dashboard to review candidate applications, schedule follow-ups, and manage admissions.

Security Notice:
Please keep your credentials confidential. For security reasons, we recommend updating your password after your initial login.

Regards,
Admission Management System
Prathyusha Engineering College
"""

    # Rich HTML version
    body_html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f4f6f9; margin: 0; padding: 20px; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); border-top: 5px solid #a60000; }}
    .header {{ background: #a60000; color: #ffffff; padding: 24px; text-align: center; }}
    .header h1 {{ margin: 0; font-size: 20px; letter-spacing: 0.5px; }}
    .header p {{ margin: 6px 0 0; font-size: 13px; opacity: 0.9; }}
    .content {{ padding: 28px 24px; color: #333333; line-height: 1.6; }}
    .welcome-text {{ font-size: 15px; margin-bottom: 20px; }}
    .card {{ background: #fdf8f8; border: 1px solid #f2dede; border-left: 4px solid #a60000; border-radius: 6px; padding: 18px; margin: 22px 0; }}
    .detail-row {{ margin-bottom: 10px; font-size: 14px; display: flex; }}
    .detail-label {{ font-weight: bold; color: #555555; width: 140px; flex-shrink: 0; }}
    .detail-value {{ color: #111111; font-weight: 600; word-break: break-all; }}
    .btn-container {{ text-align: center; margin: 26px 0 16px 0; }}
    .btn {{ display: inline-block; background: #a60000; color: #ffffff !important; padding: 12px 28px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; box-shadow: 0 2px 6px rgba(166,0,0,0.3); }}
    .notice {{ background: #fffbeb; border: 1px solid #fef3c7; border-radius: 6px; padding: 12px 16px; font-size: 12px; color: #92400e; margin-top: 20px; }}
    .footer {{ background: #f8f9fa; padding: 18px 24px; text-align: center; font-size: 12px; color: #777777; border-top: 1px solid #eeeeee; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Prathyusha Engineering College</h1>
      <p>Admission Management System (AMS)</p>
    </div>
    <div class="content">
      <p class="welcome-text">Dear <strong>{display_name}</strong>,</p>
      <p>Your Admission Coordinator account has been successfully created by the Administrator. You can now log in to the Admission Portal to manage candidate forms, track visits, and schedule student follow-ups.</p>
      
      <div class="card">
        <div class="detail-row"><span class="detail-label">Portal URL:</span> <span class="detail-value"><a href="{display_url}" style="color:#a60000;">{display_url}</a></span></div>
        <div class="detail-row"><span class="detail-label">Login Email:</span> <span class="detail-value">{clean_email}</span></div>
        <div class="detail-row"><span class="detail-label">Coordinator Name:</span> <span class="detail-value">{display_name}</span></div>
        <div class="detail-row"><span class="detail-label">Password:</span> <span class="detail-value"><code style="background:#eee;padding:2px 6px;border-radius:4px;color:#c00;">{password}</code></span></div>
      </div>

      <div class="btn-container">
        <a href="{display_url}" class="btn" target="_blank">Log In to Coordinator Portal &rarr;</a>
      </div>

      <div class="notice">
        <strong>🔒 Security Notice:</strong> Please keep your login details safe and do not share them. We recommend changing your password after your initial login for account security.
      </div>
    </div>
    <div class="footer">
      <p>Regards,<br><strong>Admission Management Office</strong><br>Prathyusha Engineering College</p>
      <p style="margin-top: 8px; font-size: 11px; color: #999;">This is an automated system notification. If you did not expect this account, please contact the college administration.</p>
    </div>
  </div>
</body>
</html>
"""

    return send_email(clean_email, subject, body_text, body_html)

