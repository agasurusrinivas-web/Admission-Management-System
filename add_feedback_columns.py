
import mysql.connector
import os

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "gummallajithendra06@"
DB_NAME = "project_db"

def migrate():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cursor = conn.cursor()

        print("Checking for 'feedback' column...")
        try:
            cursor.execute("SELECT feedback FROM applications LIMIT 1")
            print("'feedback' column already exists.")
        except mysql.connector.Error:
            print("Adding 'feedback' column...")
            cursor.execute("ALTER TABLE applications ADD COLUMN feedback TEXT")
        
        print("Checking for 'next_visit' column...")
        try:
            cursor.execute("SELECT next_visit FROM applications LIMIT 1")
            print("'next_visit' column already exists.")
        except mysql.connector.Error:
            print("Adding 'next_visit' column...")
            cursor.execute("ALTER TABLE applications ADD COLUMN next_visit VARCHAR(50)")

        conn.commit()
        print("Migration completed successfully.")
        cursor.close()
        conn.close()

    except mysql.connector.Error as err:
        print(f"Error: {err}")

if __name__ == "__main__":
    migrate()
