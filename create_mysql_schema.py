import mysql.connector
import os

# Database configuration - UPDATE THESE
DB_HOST = "localhost"
DB_USER = "root"        # Update this
DB_PASSWORD = "gummallajithendra06@"
DB_NAME = "project_db"  # Update this

def create_schema():
    print(f"Connecting to MySQL at {DB_HOST}...")
    try:
        # Connect to MySQL server (no database selected yet)
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cursor = conn.cursor()
        
        # Create database if not exists
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        print(f"Database '{DB_NAME}' created/verified.")
        
        # Connect to the database
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
                work TEXT
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
                work TEXT
            )
        """)
        print("Table 'coordinators' verified.")

        # Applications
        # SQLite used TEXT for dates, MySQL has DATETIME but we'll stick to VARCHAR/TEXT 
        # for compatibility unless we want to migrate data types properly.
        # Keeping consistent with original logic first.
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
                form_data TEXT,
                date_opened VARCHAR(50),
                date_submitted VARCHAR(50),
                last_modified VARCHAR(50)
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
        # Initialize sequence if not exists
        cursor.execute("SELECT COUNT(*) FROM application_sequence")
        if cursor.fetchone()[0] == 0:
            print("Initializing application_sequence...")
            # Default start
            start = 4879
            cursor.execute("INSERT INTO application_sequence (id, last_number) VALUES (1, %s)", (start,))
        print("Table 'application_sequence' verified.")

        # Default admin
        cursor.execute("SELECT * FROM admins WHERE email = %s", ("admin@example.com",))
        if not cursor.fetchone():
            print("Creating default admin...")
            cursor.execute("""
                INSERT INTO admins (first_name, last_name, email, phone, password, work)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, ("Default", "Admin", "admin@example.com", "0000000000", "admin123", ""))
        
        conn.commit()
        print("Schema creation complete.")
        
    except mysql.connector.Error as err:
        print(f"Error: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    create_schema()
