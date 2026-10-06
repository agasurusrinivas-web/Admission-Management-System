import sqlite3
import mysql.connector
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "project_db")

def run_migration(password=None):
    pwd = password if password is not None else DB_PASSWORD
    print(f"Starting migration to MySQL ({DB_HOST}:{DB_NAME})...")

    # Connect to SQLite
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')
    sqlite_conn = sqlite3.connect(db_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()

    # Connect to MySQL
    try:
        mysql_conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=pwd,
            database=DB_NAME
        )
        mysql_cursor = mysql_conn.cursor()
    except Exception as e:
        print(f"Failed to connect to MySQL: {e}")
        return False

    tables_to_migrate = ['admins', 'coordinators', 'applications', 'application_sequence', 'follow_ups', 'email_notifications']

    for table_name in tables_to_migrate:
        print(f"\nMigrating table: {table_name}")
        
        # Check if table exists in SQLite
        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        if not sqlite_cursor.fetchone():
            print(f"Table {table_name} does not exist in SQLite, skipping.")
            continue

        # Get columns from SQLite
        sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
        columns_info = sqlite_cursor.fetchall()
        sqlite_cols = [col['name'] for col in columns_info]

        # Get columns in MySQL
        mysql_cursor.execute(f"SHOW COLUMNS FROM {table_name}")
        mysql_cols = [row[0] for row in mysql_cursor.fetchall()]

        # Common columns
        common_cols = [c for c in sqlite_cols if c in mysql_cols]

        # Fetch rows from SQLite
        sqlite_cursor.execute(f"SELECT {', '.join(common_cols)} FROM {table_name}")
        rows = sqlite_cursor.fetchall()

        if not rows:
            print(f"No rows to migrate for {table_name}.")
            continue

        placeholders = ", ".join(["%s"] * len(common_cols))
        col_str = ", ".join(common_cols)
        query = f"REPLACE INTO {table_name} ({col_str}) VALUES ({placeholders})"

        data = [tuple(row[c] for c in common_cols) for row in rows]

        try:
            mysql_cursor.executemany(query, data)
            mysql_conn.commit()
            print(f"Successfully migrated {len(data)} rows into MySQL `{table_name}`.")
        except Exception as e:
            print(f"Error migrating {table_name}: {e}")
            mysql_conn.rollback()

    print("\nMigration process completed successfully!")
    mysql_cursor.close()
    mysql_conn.close()
    sqlite_cursor.close()
    sqlite_conn.close()
    return True

if __name__ == "__main__":
    run_migration()
