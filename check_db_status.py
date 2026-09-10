
import mysql.connector
import sys

# Configure stdout for utf-8
sys.stdout.reconfigure(encoding='utf-8')

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "gummallajithendra06@"
DB_NAME = "project_db"

def check_db():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cur = conn.cursor(dictionary=True)
        
        print("--- APP STATUS COUNTS ---")
        cur.execute("SELECT status, COUNT(*) as c FROM applications GROUP BY status")
        rows = cur.fetchall()
        for row in rows:
            print(f"Status: {row.get('status')} | Count: {row.get('c')}")
            
        print("\n--- LAST 5 APPS ---")
        cur.execute("SELECT application_number, status, date_opened FROM applications ORDER BY id DESC LIMIT 5")
        rows = cur.fetchall()
        for row in rows:
            print(f"{row.get('application_number')} | {row.get('status')} | {row.get('date_opened')}")
            
        conn.close()
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    check_db()
