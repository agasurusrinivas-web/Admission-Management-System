import unittest
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
from app import app, get_db
from services.email_service import is_smtp_configured, send_coordinator_credentials_email

def run_tests():
    print("=" * 65)
    print("VERIFYING COORDINATOR CREATION & LOGO UPDATES")
    print("=" * 65)

    with app.test_client() as client:
        # 1. Verify Logo Files
        res1 = client.get('/static/PEC%20Logo.png')
        assert res1.status_code == 200, f"PEC Logo.png failed with {res1.status_code}"
        print("✓ 1. /static/PEC%20Logo.png loads successfully (HTTP 200)")

        res2 = client.get('/static/pec_logo.png')
        assert res2.status_code == 200, f"pec_logo.png failed with {res2.status_code}"
        print("✓ 2. /static/pec_logo.png loads successfully (HTTP 200)")

        # Verify page templates load properly with new logo
        pages = ['/', '/admin', '/coordinator', '/application_form', '/admin_dashboard']
        with client.session_transaction() as sess:
            sess['admin_id'] = 1
            sess['admin_email'] = 'admin@prathyusha.edu.in'
            sess['coordinator_id'] = 1
            sess['coordinator_name'] = 'Coordinator'

        for p in pages:
            r = client.get(p)
            assert r.status_code in (200, 302), f"Page {p} returned {r.status_code}"
            html = r.get_data(as_text=True)
            # Ensure old logo is not referenced
            assert 'hlogo.jpg' not in html, f"Old logo 'hlogo.jpg' found in {p}!"
            assert 'logo.jpg' not in html, f"Old logo 'logo.jpg' found in {p}!"
            print(f"✓ 3. Verified page '{p}' has NO old logo references.")

        # 4. Verify email service generator directly
        test_email = "dynamic.coordinator@example.com"
        test_user = "Priya Sharma"
        test_pass = "SecurePass#2026"
        login_url = "http://127.0.0.1:5000/coordinator"

        # Check credentials email function
        ok, err = send_coordinator_credentials_email(
            coord_email=test_email,
            username=test_user,
            password=test_pass,
            login_url=login_url
        )
        print(f"✓ 4. send_coordinator_credentials_email execution status: ok={ok}, info='{err}'")

        # 5. Verify Coordinator Creation API
        from app import create_db_connection
        db = create_db_connection()
        cur = db.cursor()
        cur.execute("DELETE FROM coordinators WHERE email=%s", (test_email,))
        db.commit()

        post_res = client.post('/api/admin/coordinators', json={
            'email': test_email,
            'username': test_user,
            'password': test_pass
        })
        assert post_res.status_code == 200, f"Coordinator creation failed: {post_res.status_code} {post_res.get_data(as_text=True)}"
        data = post_res.get_json()
        assert data.get('success') is True, f"Expected success=True, got: {data}"
        print(f"✓ 5. Coordinator creation API response: {data}")

        # 6. Verify Coordinator in Database
        cur.execute("SELECT id, first_name, last_name, email, password FROM coordinators WHERE email=%s", (test_email,))
        saved = cur.fetchone()
        assert saved is not None, "Coordinator record was NOT saved in database!"
        row_dict = dict(saved) if hasattr(saved, 'keys') else {"id": saved[0], "first_name": saved[1], "last_name": saved[2], "email": saved[3], "password": saved[4]}
        print(f"✓ 6. Coordinator successfully retrieved from DB: ID={row_dict['id']}, Name={row_dict['first_name']} {row_dict['last_name']}, Email={row_dict['email']}")
        assert row_dict['email'] == test_email
        assert row_dict['password'] == test_pass

        # 7. Verify Coordinator Login works with newly created credentials
        login_res = client.post('/coordinator_login', data={
            'email': test_email,
            'password': test_pass
        }, follow_redirects=False)
        assert login_res.status_code == 302, f"Login failed with status {login_res.status_code}"
        assert '/coordinator_dashboard' in login_res.headers.get('Location', '')
        print("✓ 7. Coordinator login verified! Redirected to /coordinator_dashboard.")

        # Cleanup test coordinator
        cur.execute("DELETE FROM coordinators WHERE email=%s", (test_email,))
        db.commit()
        print("✓ 8. Test coordinator cleaned up from database.")

    print("\n" + "=" * 65)
    print("ALL TESTS PASSED SUCCESSFULLY (100%)!")
    print("=" * 65)

if __name__ == '__main__':
    run_tests()
