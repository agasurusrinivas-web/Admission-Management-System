
import mysql.connector
import sys

# Configure stdout for utf-8
sys.stdout.reconfigure(encoding='utf-8')

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "gummallajithendra06@"
DB_NAME = "project_db"

def check_recent_applications():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cur = conn.cursor(dictionary=True)
        
        print("\n--- Recent Applications in DB (Last 5) ---")
        cur.execute("""
            SELECT id, application_number, student_name, father_name, preferred_branch, status, date_submitted 
            FROM applications 
            ORDER BY id DESC 
            LIMIT 5
        """)
        rows = cur.fetchall()
        
        if not rows:
            print("No applications found.")
        else:
            print(f"{'App No':<15} | {'Student Name':<20} | {'Status':<10} | {'Date Submitted'}")
            print("-" * 70)
            for row in rows:
                app_no = row['application_number'] if row['application_number'] else "NULL"
                name = row['student_name'] if row['student_name'] else "NULL"
                status = row['status'] if row['status'] else "NULL"
                date = str(row['date_submitted']) if row['date_submitted'] else "NULL"
                
                print(f"{app_no:<15} | {name:<20} | {status:<10} | {date}")
        
        print("\n--- Total Count by Status ---")
        cur.execute("SELECT status, COUNT(*) as count FROM applications GROUP BY status")
        counts = cur.fetchall()
        for c in counts:
            print(f"Status: {c['status']} = {c['count']}")

        conn.close()
    except Exception as e:
        print(f"Error checking DB: {e}")

if __name__ == "__main__":
    check_recent_applications()
