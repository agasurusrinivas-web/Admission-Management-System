
import mysql.connector
import datetime

DB_HOST = "localhost"
DB_USER = "root" 
DB_PASSWORD = "gummallajithendra06@" 
DB_NAME = "project_db"

def verify_schema_and_query():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cur = conn.cursor(dictionary=True)
        
        print("--- Table 'applications' Columns ---")
        cur.execute("DESCRIBE applications")
        columns = cur.fetchall()
        numeric_part_exists = False
        for col in columns:
            print(f"{col['Field']} - {col['Type']}")
            if col['Field'] == 'numeric_part':
                numeric_part_exists = True

        if not numeric_part_exists:
            print("\nCRITICAL: 'numeric_part' column is missing!")
        else:
            print("\n'numeric_part' column exists.")

        print("\n--- Testing get_next_application_number_preview Logic ---")
        current_year = datetime.datetime.now().year
        pattern = f"PEC{current_year}%"
        print(f"Pattern: {pattern}")
        
        try:
            cur.execute("SELECT MAX(numeric_part) as mx FROM applications WHERE application_number LIKE %s", (pattern,))
            row = cur.fetchone()
            print(f"Query Result: {row}")
            
            current_max = 0
            if row and row['mx']:
                current_max = row['mx']
            
            new_num = current_max + 1
            print(f"Next Number: {new_num}")
            
            preview_app_no = f"PEC{current_year}{new_num:04d}"
            print(f"Preview App No: {preview_app_no}")
            
        except Exception as e:
            print(f"Query execution failed: {e}")

        conn.close()

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    verify_schema_and_query()
