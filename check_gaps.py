
import mysql.connector

DB_HOST = "localhost"
DB_USER = "root" 
DB_PASSWORD = "gummallajithendra06@" 
DB_NAME = "project_db"

def check_sequence():
    conn = mysql.connector.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )
    cur = conn.cursor(dictionary=True)
    
    print("--- Applications Ordered by Number ---")
    cur.execute("SELECT application_number, numeric_part, status, date_submitted FROM applications ORDER BY numeric_part")
    rows = cur.fetchall()
    
    for row in rows:
        print(f"{row['application_number']} | Part: {row['numeric_part']} | Status: {row['status']} | Date: {row['date_submitted']}")

    print("\n--- Gaps Check ---")
    if rows:
        nums = [r['numeric_part'] for r in rows if r['numeric_part'] is not None]
        if nums:
            sorted_nums = sorted(nums)
            start = sorted_nums[0]
            end = sorted_nums[-1]
            full_set = set(range(start, end + 1))
            actual_set = set(sorted_nums)
            missing = sorted(list(full_set - actual_set))
            if missing:
                print(f"Missing Numbers: {missing}")
            else:
                print("No gaps found in numeric_part sequence.")
        else:
            print("No numeric parts found.")
    else:
        print("No applications found.")

    conn.close()

if __name__ == "__main__":
    check_sequence()
