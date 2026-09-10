
import mysql.connector

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "gummallajithendra06@"
DB_NAME = "project_db"

def get_coordinator():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT email, password FROM coordinators LIMIT 1")
        row = cur.fetchone()
        conn.close()
        return row
    except Exception as e:
        print(f"Error fetching coordinator: {e}")
        return None

if __name__ == "__main__":
    c = get_coordinator()
    if c:
        print(f"EMAIL: {c['email']}")
        print(f"PASSWORD: {c['password']}")
    else:
        print("No coordinator found")
