
import mysql.connector
import datetime
import threading

# Mocking app.py context
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "gummallajithendra06@"
DB_NAME = "project_db"

def format_app_number(year, num):
    return f"PEC{year}{num:03d}"

def get_next_application_number_preview():
    print("Connecting to DB...")
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        print("Connected.")
        cur = conn.cursor(dictionary=True)
        
        current_year = datetime.datetime.now().year
        pattern = f"PEC{current_year}%"
        print(f"Searching pattern: {pattern}")
        
        cur.execute("SELECT MAX(numeric_part) as mx FROM applications WHERE application_number LIKE %s", (pattern,))
        row = cur.fetchone()
        print(f"Row: {row}")
        
        current_max = 0
        if row and row['mx']:
            current_max = row['mx']
        
        print(f"Current Max: {current_max}")
        new_num = current_max + 1
        res = format_app_number(current_year, new_num)
        print(f"Result: {res}")
        return res
    except Exception as e:
        print(f"Error: {e}")
        return ""
    finally:
        try:
            conn.close()
        except:
            pass

if __name__ == "__main__":
    print(f"Final Output: {get_next_application_number_preview()}")
