from app import create_db_connection
import json

conn = create_db_connection()
cur = conn.cursor(dictionary=True, buffered=True)

print("=== 1. Coordinators Photo Column ===")
cur.execute("SELECT id, first_name, last_name, photo FROM coordinators")
for r in cur.fetchall():
    print(f"Coordinator ID {r['id']} ({r['first_name']}): photo = {r['photo']}")

print("\n=== 2. Applications Documents / Photos ===")
cur.execute("SELECT application_number, student_name, form_data FROM applications WHERE form_data IS NOT NULL")
for r in cur.fetchall():
    try:
        fd = json.loads(r['form_data']) if isinstance(r['form_data'], str) else r['form_data']
        files = {k: v for k, v in fd.items() if isinstance(v, str) and ('/static/' in v or v.startswith('data:image'))}
        if files:
            print(f"Application {r['application_number']} ({r['student_name']}):")
            for k, v in files.items():
                print(f"   Key '{k}': {v[:60]}...")
    except Exception as e:
        print(f"Error reading form_data for {r['application_number']}: {e}")
