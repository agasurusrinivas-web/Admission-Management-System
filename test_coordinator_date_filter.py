"""
Unit & Integration Test Suite for Coordinator Dashboard Date Filter, Single Day ("That Day"),
Time Period, and All Application Details
"""
import sys
import os

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app

def run_tests():
    print("======================================================================")
    print("  TESTING COORDINATOR DASHBOARD: TIME PERIOD & THAT DAY FILTERING     ")
    print("======================================================================")

    client = app.app.test_client()

    # 1. Establish coordinator session (jithu@gmail.com, ID 10)
    with client.session_transaction() as sess:
        sess['coordinator_id'] = 10
        sess['coordinator_name'] = 'jithu'
        sess['coordinator_email'] = 'jithu@gmail.com'

    # Test 1: Calling /get_coordinator_applications without dates returns all applications
    r = client.get('/get_coordinator_applications')
    assert r.status_code == 200
    data = r.get_json()
    all_apps = data.get("applications", [])
    assert len(all_apps) >= 4, f"Expected at least 4 applications, found {len(all_apps)}"
    print(f"✓ Test 1 Passed: Unfiltered returns all coordinator applications ({len(all_apps)} found).")

    # Test 2: Verify all application details exist on each record (App No, Name, Father Name, Dept, Mobile, Address, Date Submitted, Next Visit, Status)
    required_fields = ["application_number", "student_name", "father_name", "preferred_branch", "mobile", "address", "date_submitted", "status", "next_visit"]
    for a in all_apps:
        for f in required_fields:
            assert f in a, f"Required field '{f}' missing from application {a.get('application_number')}"
    print("✓ Test 2 Passed: Every application contains all application details (Father Name, Address, Mobile, Date Submitted, etc.).")

    # Test 3: Filter for 'that day' (single date: start_date=2026-08-24)
    # Coordinator Jithu has 4 applications all submitted on 2026-08-24:
    # 3 confirmed (PEC2026001, PEC2026002, PEC2026003) and 1 visited (PEC2026004).
    # All 4 must be returned for 'that day'!
    r = client.get('/get_coordinator_applications?start_date=2026-08-24')
    assert r.status_code == 200
    day_data = r.get_json()
    day_apps = day_data.get("applications", [])
    assert len(day_apps) == 4, f"Expected 4 applications for 2026-08-24, found {len(day_apps)}"
    app_numbers = [a["application_number"] for a in day_apps]
    for expected in ["PEC2026001", "PEC2026002", "PEC2026003", "PEC2026004"]:
        assert expected in app_numbers, f"Expected application {expected} missing from that day filter!"
    print(f"✓ Test 3 Passed: Selecting that day (2026-08-24) correctly shows all {len(day_apps)} application details.")

    # Test 4: Filter for a particular time period (2026-08-01 to 2026-08-31)
    r = client.get('/get_coordinator_applications?start_date=2026-08-01&end_date=2026-08-31')
    assert r.status_code == 200
    period_data = r.get_json()
    period_apps = period_data.get("applications", [])
    assert len(period_apps) == 4, f"Expected 4 applications for August 2026 period, found {len(period_apps)}"
    print(f"✓ Test 4 Passed: Selecting time period (2026-08-01 to 2026-08-31) shows all {len(period_apps)} application details.")

    # Test 5: Status filtering on that day - Pending / Visited Only
    r = client.get('/get_coordinator_applications?start_date=2026-08-24&status=pending')
    assert r.status_code == 200
    pending_apps = r.get_json().get("applications", [])
    assert len(pending_apps) == 1
    assert pending_apps[0]["application_number"] == "PEC2026004"
    assert pending_apps[0]["status"] == "visited"
    print("✓ Test 5 Passed: Status=pending filter for that day returns only pending/visited application.")

    # Test 6: Status filtering on that day - Confirmed Only
    r = client.get('/get_coordinator_applications?start_date=2026-08-24&status=confirmed')
    assert r.status_code == 200
    confirmed_apps = r.get_json().get("applications", [])
    assert len(confirmed_apps) == 3
    for a in confirmed_apps:
        assert a["status"] == "confirmed"
    print(f"✓ Test 6 Passed: Status=confirmed filter for that day returns all {len(confirmed_apps)} confirmed applications.")

    # Test 7: Search filter combined with date filter
    r = client.get('/get_coordinator_applications?start_date=2026-08-24&search=seenu')
    assert r.status_code == 200
    search_apps = r.get_json().get("applications", [])
    assert len(search_apps) == 1
    assert search_apps[0]["student_name"] == "seenu"
    print("✓ Test 7 Passed: Search combined with date filter works accurately.")

    # Test 8: Empty date range correctly returns 0 records
    r = client.get('/get_coordinator_applications?start_date=2026-01-01&end_date=2026-01-31')
    assert r.status_code == 200
    assert len(r.get_json().get("applications", [])) == 0
    print("✓ Test 8 Passed: Non-matching date range returns 0 applications.")

    # Test 9: Check /check_data for that day (2026-08-24)
    r = client.get('/check_data?start_date=2026-08-24')
    assert r.status_code == 200
    assert r.get_json().get("count") == 4
    print("✓ Test 9 Passed: /check_data for that day returns count=4.")

    # Test 10: Download Excel for that day (2026-08-24) with chart
    r = client.get('/download_excel?start_date=2026-08-24&chart=1')
    assert r.status_code == 200
    assert r.headers.get("Content-Type") == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(r.data) > 1000
    print("✓ Test 10 Passed: /download_excel successfully generated Excel workbook with all applications and chart.")

    # Test 11: Download PDF for that day (2026-08-24)
    r = client.get('/download_pdf?start_date=2026-08-24')
    assert r.status_code == 200
    assert r.headers.get("Content-Type") == "application/pdf"
    assert r.data.startswith(b'%PDF')
    print("✓ Test 11 Passed: /download_pdf successfully generated PDF report with all application details.")

    print("\n======================================================================")
    print("  ALL 11 COORDINATOR DATE & DETAILS VERIFICATION TESTS PASSED!        ")
    print("======================================================================")

if __name__ == "__main__":
    run_tests()
