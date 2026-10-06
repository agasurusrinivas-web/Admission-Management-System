import urllib.request
import urllib.parse
import http.cookiejar
import json
import datetime
from zoneinfo import ZoneInfo

BASE_URL = "http://127.0.0.1:5000"

def test_live():
    print("=" * 60)
    print("LIVE RUNNING SERVER NOTIFICATION TEST")
    print("=" * 60)

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    # 1. Login
    print("\n1. Logging in as Coordinator 'jithu@gmail.com'...")
    login_data = urllib.parse.urlencode({"email": "jithu@gmail.com", "password": "12345"}).encode()
    res = opener.open(f"{BASE_URL}/coordinator_login", data=login_data)
    print(f"   Login Status: {res.status}")

    # 2. Schedule follow-up
    now = datetime.datetime.now(ZoneInfo("Asia/Kolkata"))
    visit_date = now.strftime("%Y-%m-%d")
    visit_time = now.strftime("%H:%M")
    print(f"\n2. Scheduling Follow-up for Rahul Kumar on {visit_date} at {visit_time}...")
    payload = urllib.parse.urlencode({
        "application_number": "PEC20260001",
        "student_name": "Rahul Kumar",
        "student_email": "rahul.student@example.com",
        "feedback": "Student visited campus and discussed admission.",
        "next_visit_date": visit_date,
        "next_visit_time": visit_time,
        "purpose": "Confirm Admission",
        "reminder_setting": "at_event"
    }).encode()
    res = opener.open(f"{BASE_URL}/save_feedback", data=payload)
    data = json.loads(res.read().decode())
    print("   Save feedback API response:")
    print("  ", json.dumps(data, indent=4))

    # 3. View coordinator follow-ups
    print("\n3. Querying Coordinator Follow-ups API...")
    res = opener.open(f"{BASE_URL}/api/coordinator/follow_ups")
    f_data = json.loads(res.read().decode())
    follow_ups = f_data.get("follow_ups", [])
    print(f"   Total follow-ups: {len(follow_ups)}")
    if follow_ups:
        f = follow_ups[0]
        print(f"   Latest Follow-up: ID={f['id']}, App={f['application_number']}, StudentEmail={f['student_email']}")
        print(f"   Student Email Status    : {f.get('student_email_status')}")
        print(f"   Coordinator Email Status: {f.get('coordinator_email_status')}")

    # 4. Trigger scheduler check
    print("\n4. Triggering Scheduler run check...")
    req = urllib.request.Request(f"{BASE_URL}/api/scheduler/run_check", data=b"{}")
    req.add_header('Content-Type', 'application/json')
    res = opener.open(req)
    sched_data = json.loads(res.read().decode())
    print("   Scheduler response:")
    print("  ", json.dumps(sched_data, indent=4))

    # 5. Check notification status again
    print("\n5. Checking notification delivery logs...")
    res = opener.open(f"{BASE_URL}/api/coordinator/follow_ups")
    f_data = json.loads(res.read().decode())
    if f_data.get("follow_ups"):
        f = f_data["follow_ups"][0]
        print(f"   Student Email Status    : {f.get('student_email_status')}")
        print(f"   Coordinator Email Status: {f.get('coordinator_email_status')}")
        print(f"   Follow-up Status        : {f.get('status')}")

    print("\n" + "=" * 60)
    print("LIVE RUNNING SERVER NOTIFICATION TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    test_live()
