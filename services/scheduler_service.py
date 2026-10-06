import os
import threading
import time
import datetime
from zoneinfo import ZoneInfo
import logging

from services.email_service import (
    send_student_followup_email,
    send_coordinator_followup_email,
    is_valid_email
)

logger = logging.getLogger(__name__)

KOLKATA_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Kolkata"))

_scheduler_instance = None
_scheduler_lock = threading.RLock()

def get_now_kolkata():
    """Return current timezone-aware datetime in Asia/Kolkata."""
    return datetime.datetime.now(KOLKATA_TZ)

def parse_iso_datetime(dt_str):
    """
    Parse a date/time string into a timezone-aware datetime in Asia/Kolkata.
    Handles 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DD HH:MM', 'YYYY-MM-DD'
    """
    if not dt_str:
        return None
    dt_str = str(dt_str).strip()
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y"
    ]
    for fmt in formats:
        try:
            naive = datetime.datetime.strptime(dt_str, fmt)
            return naive.replace(tzinfo=KOLKATA_TZ)
        except ValueError:
            continue
    return None

def parse_visit_datetime(visit_date, visit_time):
    """
    Combine visit_date (e.g. '2026-10-05') and visit_time (e.g. '10:30' or '10:30 AM')
    into a timezone-aware datetime in Asia/Kolkata.
    """
    if not visit_date:
        return None
        
    date_part = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            date_part = datetime.datetime.strptime(str(visit_date).strip(), fmt).date()
            break
        except ValueError:
            continue
            
    if not date_part:
        return None

    time_part = datetime.time(10, 0) # Default 10:00 AM
    if visit_time:
        vt_clean = str(visit_time).strip().upper()
        for tfmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
            try:
                time_part = datetime.datetime.strptime(vt_clean, tfmt).time()
                break
            except ValueError:
                continue

    combined = datetime.datetime.combine(date_part, time_part, tzinfo=KOLKATA_TZ)
    return combined

def process_single_notification(db_conn, notif_id):
    """
    Process and send a single email notification idempotently.
    Returns (success: bool, error_message: str or None)
    """
    cur = db_conn.cursor(dictionary=True)
    
    # 1. Atomic status check to avoid duplicate sending
    cur.execute("""
        SELECT n.id, n.follow_up_id, n.application_number, n.recipient_type,
               n.recipient_email, n.subject, n.scheduled_at, n.status,
               f.student_name, f.coordinator_name, f.coordinator_id,
               f.visit_date, f.scheduled_date, f.visit_time, f.scheduled_time,
               f.purpose, f.feedback
        FROM email_notifications n
        LEFT JOIN follow_ups f ON n.follow_up_id = f.id
        WHERE n.id = %s
    """, (notif_id,))
    notif = cur.fetchone()
    
    if not notif:
        return False, "Notification record not found."
        
    if notif.get("status") == "sent":
        # Already sent, ignore (idempotent)
        return True, "Notification already sent."

    recipient_type = notif.get("recipient_type")
    recipient_email = (notif.get("recipient_email") or "").strip()
    app_no = notif.get("application_number") or ""
    student_name = notif.get("student_name") or "Student"
    coord_name = notif.get("coordinator_name") or "Coordinator"
    visit_date = notif.get("scheduled_date") or notif.get("visit_date") or ""
    visit_time = notif.get("scheduled_time") or notif.get("visit_time") or ""
    purpose = notif.get("purpose") or "Confirm Admission"
    feedback = notif.get("feedback") or ""
    follow_up_id = notif.get("follow_up_id")

    if not recipient_email or not is_valid_email(recipient_email):
        err = f"Missing or invalid {recipient_type} email address: '{recipient_email}'"
        cur.execute("""
            UPDATE email_notifications 
            SET status = 'email_failed', error_message = %s
            WHERE id = %s
        """, (err, notif_id))
        db_conn.commit()
        _update_followup_status_after_email(db_conn, follow_up_id)
        return False, err

    now_str = get_now_kolkata().strftime("%Y-%m-%d %H:%M:%S")

    # Send email based on recipient type
    if recipient_type == "student":
        success, error_msg = send_student_followup_email(
            student_email=recipient_email,
            student_name=student_name,
            app_no=app_no,
            visit_date=visit_date,
            visit_time=visit_time,
            purpose=purpose
        )
    elif recipient_type == "coordinator":
        success, error_msg = send_coordinator_followup_email(
            coord_email=recipient_email,
            coord_name=coord_name,
            student_name=student_name,
            app_no=app_no,
            visit_date=visit_date,
            visit_time=visit_time,
            purpose=purpose,
            feedback=feedback
        )
    else:
        success = False
        error_msg = f"Unknown recipient type: {recipient_type}"

    # Update notification record
    if success:
        cur.execute("""
            UPDATE email_notifications
            SET status = 'sent', sent_at = %s, error_message = NULL
            WHERE id = %s
        """, (now_str, notif_id))
    else:
        cur.execute("""
            UPDATE email_notifications
            SET status = 'email_failed', error_message = %s
            WHERE id = %s
        """, (error_msg or "Failed to send email", notif_id))

    db_conn.commit()
    _update_followup_status_after_email(db_conn, follow_up_id)
    return success, error_msg

def _update_followup_status_after_email(db_conn, follow_up_id):
    """
    Check all notifications for a follow_up_id and sync follow_up status.
    """
    if not follow_up_id:
        return
    cur = db_conn.cursor(dictionary=True)
    cur.execute("SELECT status FROM follow_ups WHERE id = %s", (follow_up_id,))
    f_row = cur.fetchone()
    if not f_row:
        return
        
    current_status = f_row.get("status")
    if current_status in ("completed", "cancelled"):
        # Completed / cancelled follow-ups keep their overall status
        return

    cur.execute("SELECT status, recipient_type FROM email_notifications WHERE follow_up_id = %s", (follow_up_id,))
    rows = cur.fetchall()
    if not rows:
        return

    statuses = [r.get("status") for r in rows]
    
    if all(s == "sent" for s in statuses):
        new_status = "email_sent"
    elif any(s == "sent" for s in statuses) and any(s == "email_failed" for s in statuses):
        new_status = "partially_sent"
    elif all(s == "email_failed" for s in statuses):
        new_status = "email_failed"
    elif any(s == "scheduled" for s in statuses):
        new_status = "scheduled"
    else:
        new_status = current_status

    cur.execute("UPDATE follow_ups SET status = %s WHERE id = %s", (new_status, follow_up_id))
    db_conn.commit()

def check_and_process_due_emails(create_conn_fn):
    """
    Core scheduler worker:
    1. Finds notifications with status 'scheduled'
    2. Identifies those whose scheduled_at <= current time in Asia/Kolkata
    3. Sends them and updates statuses
    4. Updates missed follow-ups
    """
    conn = create_conn_fn()
    try:
        now_kolkata = get_now_kolkata()
        cur = conn.cursor(dictionary=True)

        # Fetch pending notifications
        cur.execute("""
            SELECT id, scheduled_at 
            FROM email_notifications 
            WHERE status = 'scheduled'
        """)
        pending = cur.fetchall()

        due_count = 0
        for p in pending:
            scheduled_at_str = p.get("scheduled_at")
            dt_sched = parse_iso_datetime(scheduled_at_str)
            if dt_sched and now_kolkata >= dt_sched:
                due_count += 1
                try:
                    process_single_notification(conn, p["id"])
                except Exception as ex:
                    logger.error(f"Error processing notification {p['id']}: {ex}")

        # Update missed follow-ups
        update_missed_followups(conn, now_kolkata)
        return due_count
    finally:
        conn.close()

def update_missed_followups(conn, now_kolkata):
    """
    Mark follow-ups as 'missed' if scheduled_at has passed and status is still scheduled or email_sent.
    """
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, scheduled_at, status 
        FROM follow_ups 
        WHERE status IN ('scheduled', 'email_sent')
    """)
    rows = cur.fetchall()

    for r in rows:
        sched_str = r.get("scheduled_at")
        dt_sched = parse_iso_datetime(sched_str)
        # If scheduled time + grace period (e.g. scheduled time has passed)
        if dt_sched and now_kolkata > dt_sched:
            # Check if emails were already sent or attempted
            cur.execute("""
                SELECT status FROM email_notifications 
                WHERE follow_up_id = %s AND status = 'scheduled'
            """, (r["id"],))
            remaining_scheduled_emails = cur.fetchall()
            
            # If all emails have been processed (sent or failed), and time is passed, mark missed
            if not remaining_scheduled_emails and r.get("status") != "missed":
                cur.execute("UPDATE follow_ups SET status = 'missed' WHERE id = %s", (r["id"],))
                conn.commit()

class BackgroundSchedulerRunner:
    """
    Runs background check periodically.
    Supports APScheduler with clean fallback to threading.Thread.
    """
    def __init__(self, create_conn_fn, interval_seconds=60):
        self.create_conn_fn = create_conn_fn
        self.interval = interval_seconds
        self.running = False
        self.thread = None
        self.apscheduler = None

    def start(self):
        with _scheduler_lock:
            if self.running:
                return

            # Try APScheduler first
            try:
                from apscheduler.schedulers.background import BackgroundScheduler
                self.apscheduler = BackgroundScheduler(daemon=True, timezone=KOLKATA_TZ)
                self.apscheduler.add_job(
                    func=self.run_once,
                    trigger="interval",
                    seconds=self.interval,
                    id="followup_email_job",
                    name="Follow-up Email Dispatcher",
                    replace_existing=True
                )
                self.apscheduler.start()
                self.running = True
                logger.info(f"APScheduler started successfully (Interval: {self.interval}s)")
                return
            except Exception as e:
                logger.warning(f"APScheduler start failed: {e}. Falling back to background thread.")

            # Fallback to threading loop
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            logger.info(f"Thread scheduler started (Interval: {self.interval}s)")

    def _run_loop(self):
        while self.running:
            self.run_once()
            time.sleep(self.interval)

    def run_once(self):
        try:
            check_and_process_due_emails(self.create_conn_fn)
        except Exception as e:
            logger.error(f"Error in scheduler tick: {e}")

    def stop(self):
        with _scheduler_lock:
            self.running = False
            if self.apscheduler and self.apscheduler.running:
                self.apscheduler.shutdown(wait=False)

def start_scheduler(create_conn_fn):
    """Global helper to start the scheduler once."""
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is None:
            interval = int(os.getenv("SCHEDULER_INTERVAL", "60").strip())
            _scheduler_instance = BackgroundSchedulerRunner(create_conn_fn, interval)
            _scheduler_instance.start()
            import atexit
            atexit.register(lambda: _scheduler_instance.stop() if _scheduler_instance else None)
    return _scheduler_instance
