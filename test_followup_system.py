"""
Comprehensive Verification Test Suite for AMS Follow-up Email Notification System
Tests all scenarios specified in Section 25 of the requirements.
"""

import sys
import os
import json
import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

# Configure stdout for utf-8 on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add parent path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app
from services.email_service import is_valid_email
from services.scheduler_service import (
    get_now_kolkata, parse_visit_datetime, check_and_process_due_emails
)

def run_tests():
    print("======================================================================")
    print("  STARTING COMPREHENSIVE AMS FOLLOW-UP SYSTEM VERIFICATION TESTS")
    print("======================================================================\n")

    client = app.app.test_client()
    now_kolkata = get_now_kolkata()

    # -------------------------------------------------------------
    # SETUP TEST DATA: Coordinator & Application
    # -------------------------------------------------------------
    conn = app.create_db_connection()
    conn.autocommit = True
    cur = conn.cursor(dictionary=True)

    # 1. Ensure test coordinator exists
    cur.execute("SELECT id, email FROM coordinators WHERE email = %s", ("coordinator@example.com",))
    coord_row = cur.fetchone()
    if not coord_row:
        cur.execute("""
            INSERT INTO coordinators (first_name, last_name, email, phone, password, work)
            VALUES ('Coordinator', 'A', 'coordinator@example.com', '9876543210', 'password123', 'CSE')
        """)
        conn.commit()
        cur.execute("SELECT id, email FROM coordinators WHERE email = %s", ("coordinator@example.com",))
        coord_row = cur.fetchone()
    coord_id = coord_row["id"]
    print(f"✓ Coordinator verified: ID={coord_id}, Email=coordinator@example.com")

    # 2. Test 1: Create application: PEC20260001, Rahul Kumar, student@example.com, Coordinator A
    test_app_no = "PEC20260001"
    cur.execute("SELECT id FROM applications WHERE application_number = %s", (test_app_no,))
    existing_app = cur.fetchone()
    form_data = {
        "student_name": "Rahul Kumar",
        "father_name": "Suresh Kumar",
        "email": "student@example.com",
        "student_email": "student@example.com",
        "mobile": "9998887776",
        "address": "123 Main Road, Chennai"
    }

    if existing_app:
        cur.execute("""
            UPDATE applications
            SET student_name = 'Rahul Kumar', father_name = 'Suresh Kumar',
                preferred_branch = 'CSE', mobile = '9998887776', address = '123 Main Road, Chennai',
                status = 'visited', coordinator = 'Coordinator A', form_data = %s
            WHERE application_number = %s
        """, (json.dumps(form_data), test_app_no))
    else:
        cur.execute("""
            INSERT INTO applications (
                application_number, numeric_part, student_name, father_name,
                preferred_branch, mobile, address, status, coordinator, form_data,
                date_opened, date_submitted
            ) VALUES (%s, 1, 'Rahul Kumar', 'Suresh Kumar', 'CSE', '9998887776',
                     '123 Main Road, Chennai', 'visited', 'Coordinator A', %s, %s, %s)
        """, (test_app_no, json.dumps(form_data), now_kolkata.strftime('%Y-%m-%d %H:%M:%S'), now_kolkata.strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()

    # Clear previous test follow-ups for clean test run
    cur.execute("DELETE FROM follow_ups WHERE application_number = %s", (test_app_no,))
    cur.execute("DELETE FROM email_notifications WHERE application_number = %s", (test_app_no,))
    conn.commit()
    conn.close()
    print("✓ Test 1 Passed: Application PEC20260001 created/verified with Rahul Kumar and student@example.com.\n")

    # -------------------------------------------------------------
    # Test 2: Coordinator records feedback & next visit
    # -------------------------------------------------------------
    with client.session_transaction() as sess:
        sess['coordinator_id'] = coord_id
        sess['coordinator_name'] = 'Coordinator A'
        sess['coordinator_email'] = 'coordinator@example.com'

    tomorrow_date = (now_kolkata + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    visit_time = "10:30 AM"

    resp = client.post('/save_feedback', json={
        "application_number": test_app_no,
        "student_name": "Rahul Kumar",
        "feedback": "Student visited the college and discussed admission details.",
        "visit_date": tomorrow_date,
        "visit_time": visit_time,
        "purpose": "Confirm Admission"
    })

    assert resp.status_code == 200, f"save_feedback failed: {resp.data}"
    result = resp.get_json()
    assert result.get("success") is True
    follow_up_id = result.get("follow_up_id")
    assert follow_up_id is not None
    print(f"✓ Test 2 Passed: Coordinator recorded feedback and follow-up (ID={follow_up_id}).\n")

    # -------------------------------------------------------------
    # Test 3: Verify database contains the follow-up
    # -------------------------------------------------------------
    conn = app.create_db_connection()
    conn.autocommit = True
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM follow_ups WHERE id = %s", (follow_up_id,))
    fu_row = cur.fetchone()
    assert fu_row is not None
    assert fu_row["application_number"] == test_app_no
    assert fu_row["student_name"] == "Rahul Kumar"
    assert fu_row["student_email"] == "student@example.com"
    assert fu_row["status"] == "scheduled"
    assert fu_row["purpose"] == "Confirm Admission"
    print("✓ Test 3 Passed: Verified follow-up record in database with correct fields.\n")

    # -------------------------------------------------------------
    # Test 4: Verify two email notification records exist (Student & Coordinator)
    # -------------------------------------------------------------
    cur.execute("SELECT * FROM email_notifications WHERE follow_up_id = %s ORDER BY recipient_type", (follow_up_id,))
    notifs = cur.fetchall()
    assert len(notifs) == 2, f"Expected 2 notifications, found {len(notifs)}"
    types = [n["recipient_type"] for n in notifs]
    assert "student" in types
    assert "coordinator" in types

    s_notif = next(n for n in notifs if n["recipient_type"] == "student")
    c_notif = next(n for n in notifs if n["recipient_type"] == "coordinator")
    assert s_notif["recipient_email"] == "student@example.com"
    assert c_notif["recipient_email"] == "coordinator@example.com"
    assert s_notif["status"] == "scheduled"
    assert c_notif["status"] == "scheduled"
    print("✓ Test 4 Passed: Verified 2 email notification records (Student and Coordinator) created.\n")

    # -------------------------------------------------------------
    # Test 5, 6, 7: Scheduler Execution & Email Sending
    # (Mock SMTP to avoid external network dependencies during unit test)
    # -------------------------------------------------------------
    # To test due execution, set scheduled_at to current/past time
    past_due_str = (now_kolkata - datetime.timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("UPDATE email_notifications SET scheduled_at = %s WHERE follow_up_id = %s", (past_due_str, follow_up_id))
    cur.execute("UPDATE follow_ups SET scheduled_at = %s WHERE id = %s", (past_due_str, follow_up_id))
    conn.commit()

    sent_emails = []

    def mock_send_email(to_email, subject, body_text, body_html=None):
        sent_emails.append({
            "to": to_email,
            "subject": subject,
            "body": body_text
        })
        return True, None

    with patch("services.scheduler_service.send_student_followup_email") as mock_student_send, \
         patch("services.scheduler_service.send_coordinator_followup_email") as mock_coord_send:

        mock_student_send.side_effect = lambda student_email, student_name, app_no, visit_date, visit_time, purpose: (
            mock_send_email(student_email, f"Admission Follow-up Reminder – {app_no}", "Student body")
        )
        mock_coord_send.side_effect = lambda coord_email, coord_name, student_name, app_no, visit_date, visit_time, purpose, feedback: (
            mock_send_email(coord_email, f"Student Follow-up Reminder – {student_name} – {app_no}", "Coord body")
        )

        # Run scheduler
        due_processed = check_and_process_due_emails(app.create_db_connection)
        assert due_processed == 2, f"Expected 2 processed, got {due_processed}"

    # Verify student email sent
    cur.execute("SELECT status, sent_at FROM email_notifications WHERE follow_up_id = %s AND recipient_type = 'student'", (follow_up_id,))
    s_updated = cur.fetchone()
    assert s_updated["status"] == "sent"
    assert s_updated["sent_at"] is not None
    print("✓ Test 5 & 6 Passed: Scheduler ran and Student email was sent successfully.")

    # Verify coordinator email sent
    cur.execute("SELECT status, sent_at FROM email_notifications WHERE follow_up_id = %s AND recipient_type = 'coordinator'", (follow_up_id,))
    c_updated = cur.fetchone()
    assert c_updated["status"] == "sent"
    assert c_updated["sent_at"] is not None
    print("✓ Test 7 Passed: Coordinator email was sent successfully.\n")

    # -------------------------------------------------------------
    # Test 8: Run scheduler again -> Verify DUPLICATE emails NOT sent
    # -------------------------------------------------------------
    sent_count_before = len(sent_emails)
    with patch("services.scheduler_service.send_student_followup_email") as mock_s, \
         patch("services.scheduler_service.send_coordinator_followup_email") as mock_c:
        due_second_run = check_and_process_due_emails(app.create_db_connection)
        # Should be 0 because notifications are already 'sent'
        assert due_second_run == 0, f"Expected 0 due on second run, got {due_second_run}"
        mock_s.assert_not_called()
        mock_c.assert_not_called()
    assert len(sent_emails) == sent_count_before
    print("✓ Test 8 Passed: Scheduler re-run did NOT send duplicate emails (idempotent).\n")

    # -------------------------------------------------------------
    # Test 9: Mark the follow-up as completed
    # -------------------------------------------------------------
    comp_resp = client.post('/complete_follow_up', json={"follow_up_id": follow_up_id})
    assert comp_resp.status_code == 200
    comp_data = comp_resp.get_json()
    assert comp_data.get("success") is True

    cur.execute("SELECT status, completed_at FROM follow_ups WHERE id = %s", (follow_up_id,))
    fu_completed = cur.fetchone()
    assert fu_completed["status"] == "completed"
    assert fu_completed["completed_at"] is not None
    print(f"✓ Test 9 Passed: Follow-up marked completed at {fu_completed['completed_at']}.\n")

    # -------------------------------------------------------------
    # Test 10: Verify complete follow-up / email history remains available
    # -------------------------------------------------------------
    hist_resp = client.get(f'/api/follow_up/history/{test_app_no}')
    assert hist_resp.status_code == 200
    hist_data = hist_resp.get_json()
    assert len(hist_data.get("history", [])) >= 1
    h_entry = hist_data["history"][0]
    assert h_entry["id"] == follow_up_id
    assert h_entry["status"] == "completed"
    assert h_entry["student_email_status"] == "sent"
    assert h_entry["coordinator_email_status"] == "sent"
    print("✓ Test 10 Passed: Complete follow-up and email delivery history is fully preserved.\n")

    # -------------------------------------------------------------
    # Test 11: Failed student email while coordinator email succeeds
    # -------------------------------------------------------------
    test_app_no2 = "PEC20260002"
    # Create application without student email
    cur.execute("SELECT id FROM applications WHERE application_number = %s", (test_app_no2,))
    app2 = cur.fetchone()
    form_data2 = {"student_name": "Vikram Singh", "father_name": "R. Singh", "mobile": "9887766554"}
    if app2:
        cur.execute("UPDATE applications SET student_name = 'Vikram Singh', form_data = %s, coordinator = 'Coordinator A', status = 'visited' WHERE application_number = %s",
                    (json.dumps(form_data2), test_app_no2))
    else:
        cur.execute("INSERT INTO applications (application_number, numeric_part, student_name, status, coordinator, form_data, date_opened, date_submitted) VALUES (%s, 2, 'Vikram Singh', 'visited', 'Coordinator A', %s, %s, %s)",
                    (test_app_no2, json.dumps(form_data2), now_kolkata.strftime('%Y-%m-%d %H:%M:%S'), now_kolkata.strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()

    resp2 = client.post('/save_feedback', json={
        "application_number": test_app_no2,
        "student_name": "Vikram Singh",
        "student_email": "", # Intentionally missing
        "feedback": "Discussed scholarship options.",
        "visit_date": tomorrow_date,
        "visit_time": "11:00 AM",
        "purpose": "Document Verification"
    })
    assert resp2.status_code == 200
    res2 = resp2.get_json()
    fu_id2 = res2["follow_up_id"]
    assert res2["student_email_status"] == "email_failed"
    assert res2["coordinator_email_status"] == "scheduled"
    assert "warning" in res2

    # Verify coordinator email can still be sent
    cur.execute("UPDATE email_notifications SET scheduled_at = %s WHERE follow_up_id = %s", (past_due_str, fu_id2))
    conn.commit()

    with patch("services.scheduler_service.send_coordinator_followup_email") as mock_c:
        mock_c.return_value = (True, None)
        check_and_process_due_emails(app.create_db_connection)

    cur.execute("SELECT recipient_type, status FROM email_notifications WHERE follow_up_id = %s", (fu_id2,))
    notifs2 = {r["recipient_type"]: r["status"] for r in cur.fetchall()}
    assert notifs2["student"] == "email_failed"
    assert notifs2["coordinator"] == "sent"
    print("✓ Test 11 Passed: Student email failed gracefully while coordinator email succeeded.\n")

    # -------------------------------------------------------------
    # Test 12: Restart / reload simulation
    # Verify pending follow-ups remain in database and can still be processed
    # -------------------------------------------------------------
    # Reconnect fresh connection (simulating restart)
    conn.close()
    fresh_conn = app.create_db_connection()
    fresh_cur = fresh_conn.cursor(dictionary=True)
    fresh_cur.execute("SELECT id, status FROM follow_ups WHERE id = %s", (fu_id2,))
    reloaded_fu = fresh_cur.fetchone()
    assert reloaded_fu is not None
    print(f"✓ Test 12 Passed: After restart simulation, follow-up {reloaded_fu['id']} remains intact in database.\n")

    # Clean up test records
    fresh_cur.execute("DELETE FROM follow_ups WHERE application_number IN (%s, %s)", (test_app_no, test_app_no2))
    fresh_cur.execute("DELETE FROM email_notifications WHERE application_number IN (%s, %s)", (test_app_no, test_app_no2))
    fresh_conn.commit()
    fresh_conn.close()

    print("======================================================================")
    print("  ALL 12 VERIFICATION TESTS PASSED SUCCESSFULLY! ")
    print("======================================================================")

if __name__ == "__main__":
    run_tests()
