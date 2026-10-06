"""
Regression test suite to verify existing and new routes in AMS
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

def test_routes():
    print("Testing AMS routes for regressions...")
    client = app.app.test_client()

    # 1. Home
    r = client.get('/')
    assert r.status_code == 200, f"Home failed: {r.status_code}"
    print("✓ Home route '/' OK")

    # 2. Admin page
    r = client.get('/admin')
    assert r.status_code == 200, f"Admin page failed: {r.status_code}"
    print("✓ Admin login page '/admin' OK")

    # 3. Coordinator page
    r = client.get('/coordinator')
    assert r.status_code == 200, f"Coordinator page failed: {r.status_code}"
    print("✓ Coordinator login page '/coordinator' OK")

    # 4. Unauthenticated Application form redirects to coordinator login
    r = client.get('/application_form')
    assert r.status_code == 302, f"Application form redirect failed: {r.status_code}"
    print("✓ Unauthenticated '/application_form' redirects to login OK")

    # Set coordinator session
    with client.session_transaction() as sess:
        sess['coordinator_id'] = 10
        sess['coordinator_name'] = 'jithu'
        sess['coordinator_email'] = 'jithu@gmail.com'

    # Authenticated application form
    r = client.get('/application_form')
    assert r.status_code == 200, f"Authenticated Application form failed: {r.status_code}"
    print("✓ Authenticated Application form page '/application_form' OK")

    # 5. Coordinator Dashboard with session
    with client.session_transaction() as sess:
        sess['coordinator_id'] = 10
        sess['coordinator_name'] = 'jithu'
        sess['coordinator_email'] = 'jithu@gmail.com'

    r = client.get('/coordinator_dashboard')
    assert r.status_code == 200, f"Coordinator dashboard failed: {r.status_code}"
    print("✓ Coordinator dashboard '/coordinator_dashboard' OK")

    # 6. Coordinator applications JSON API
    r = client.get('/get_coordinator_applications')
    assert r.status_code == 200, f"get_coordinator_applications failed: {r.status_code}"
    data = r.get_json()
    assert "applications" in data
    print(f"✓ Coordinator applications API OK (returned {len(data['applications'])} applications)")

    # 7. Coordinator follow_ups JSON API
    r = client.get('/api/coordinator/follow_ups')
    assert r.status_code == 200, f"api/coordinator/follow_ups failed: {r.status_code}"
    data = r.get_json()
    assert "follow_ups" in data
    print(f"✓ Coordinator follow-ups API OK (returned {len(data['follow_ups'])} follow-ups)")

    # 8. Admin Dashboard with session
    with client.session_transaction() as sess:
        sess['admin_id'] = 1
        sess['admin_name'] = 'Default Admin'
        sess['admin_email'] = 'admin@example.com'

    r = client.get('/admin_dashboard')
    assert r.status_code == 200, f"Admin dashboard failed: {r.status_code}"
    print("✓ Admin dashboard '/admin_dashboard' OK")

    # 9. Admin Stats API
    r = client.get('/api/admin/stats')
    assert r.status_code == 200, f"Admin stats failed: {r.status_code}"
    print("✓ Admin stats API '/api/admin/stats' OK")

    # 10. Admin Follow-ups API
    r = client.get('/api/admin/follow_ups')
    assert r.status_code == 200, f"Admin follow_ups failed: {r.status_code}"
    print("✓ Admin follow-ups API '/api/admin/follow_ups' OK")

    # 11. Admin test email with invalid email -> should return error safely, not crash
    r = client.post('/api/admin/send_test_email', json={"email": "invalid-email"})
    assert r.status_code == 400
    print("✓ Admin send_test_email validation OK")

    # 12. Scheduler run check API
    r = client.post('/api/scheduler/run_check')
    assert r.status_code == 200
    print("✓ Scheduler manual trigger API '/api/scheduler/run_check' OK")

    print("\nALL REGRESSION CHECKS PASSED PERFECTLY!")

if __name__ == "__main__":
    test_routes()
