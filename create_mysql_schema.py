import mysql.connector
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Database configuration from environment or fallback
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "project_db")

def create_schema(password=None):
    pwd = password if password is not None else DB_PASSWORD
    print(f"Connecting to MySQL at {DB_HOST} with user '{DB_USER}'...")
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=pwd,
            connection_timeout=5
        )
        cursor = conn.cursor()
        
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        print(f"Database '{DB_NAME}' created/verified.")
        
        conn.database = DB_NAME
        
        # Admins
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INT AUTO_INCREMENT PRIMARY KEY,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                email VARCHAR(100) UNIQUE,
                phone VARCHAR(20),
                password VARCHAR(255),
                work TEXT,
                photo VARCHAR(255),
                role VARCHAR(50),
                dob VARCHAR(50),
                address TEXT,
                city VARCHAR(100),
                state VARCHAR(100),
                pincode VARCHAR(20),
                country VARCHAR(100)
            )
        """)
        print("Table 'admins' verified.")

        # Coordinators
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS coordinators (
                id INT AUTO_INCREMENT PRIMARY KEY,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                email VARCHAR(100) UNIQUE,
                phone VARCHAR(20),
                password VARCHAR(255),
                work TEXT,
                photo VARCHAR(255),
                role VARCHAR(50),
                dob VARCHAR(50),
                address TEXT,
                city VARCHAR(100),
                state VARCHAR(100),
                pincode VARCHAR(20),
                country VARCHAR(100)
            )
        """)
        print("Table 'coordinators' verified.")

        # Applications
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                application_number VARCHAR(50),
                numeric_part INT,
                coordinator VARCHAR(100),
                status VARCHAR(50),
                student_name VARCHAR(255),
                father_name VARCHAR(255),
                preferred_branch VARCHAR(100),
                mobile VARCHAR(20),
                address TEXT,
                form_data LONGTEXT,
                date_opened VARCHAR(50),
                date_submitted VARCHAR(50),
                last_modified VARCHAR(50),
                feedback TEXT,
                next_visit VARCHAR(50)
            )
        """)
        print("Table 'applications' verified.")

        # Sequence table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS application_sequence (
                id INT PRIMARY KEY,
                last_number INT NOT NULL
            )
        """)
        cursor.execute("SELECT COUNT(*) FROM application_sequence")
        if cursor.fetchone()[0] == 0:
            print("Initializing application_sequence...")
            start = 4879
            cursor.execute("INSERT INTO application_sequence (id, last_number) VALUES (1, %s)", (start,))
        print("Table 'application_sequence' verified.")

        # Follow-ups Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS follow_ups (
                id INT AUTO_INCREMENT PRIMARY KEY,
                application_id INT NULL,
                application_number VARCHAR(50) NOT NULL,
                coordinator_id INT NULL,
                coordinator_name VARCHAR(100) NULL,
                student_name VARCHAR(255) NULL,
                student_email VARCHAR(255) NULL,
                feedback TEXT NULL,
                scheduled_date VARCHAR(50) NULL,
                scheduled_time VARCHAR(50) NULL,
                visit_date VARCHAR(50) NULL,
                visit_time VARCHAR(50) NULL,
                scheduled_at VARCHAR(50) NOT NULL,
                purpose VARCHAR(255) NULL,
                reminder_setting VARCHAR(50) DEFAULT 'at_event',
                status VARCHAR(50) DEFAULT 'scheduled',
                notes TEXT NULL,
                created_at VARCHAR(50) NULL,
                updated_at VARCHAR(50) NULL,
                completed_at VARCHAR(50) NULL
            )
        """)
        print("Table 'follow_ups' verified.")

        # Email Notifications Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                follow_up_id INT,
                application_number VARCHAR(50),
                recipient_type VARCHAR(50),
                recipient_email VARCHAR(255),
                subject VARCHAR(255),
                scheduled_at VARCHAR(50),
                sent_at VARCHAR(50),
                status VARCHAR(50) DEFAULT 'scheduled',
                error_message TEXT,
                created_at VARCHAR(50)
            )
        """)
        print("Table 'email_notifications' verified.")

        conn.commit()
        print("Schema creation complete.")
        return True
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return False
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    create_schema()
