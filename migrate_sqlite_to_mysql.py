import sqlite3
import mysql.connector

# Connect to SQLite
sqlite_conn = sqlite3.connect('users.db')
sqlite_conn.row_factory = sqlite3.Row
sqlite_cursor = sqlite_conn.cursor()

# Connect to MySQL
mysql_conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="gummallajithendra06@",
    database="project_db"
)
mysql_cursor = mysql_conn.cursor()

def migrate_table(table_name, unique_key=None):
    print(f"Migrating table: {table_name}")
    
    # Get columns from SQLite
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    columns_info = sqlite_cursor.fetchall()
    columns = [col['name'] for col in columns_info]
    
    # Get all rows from SQLite
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cursor.fetchall()
    
    if not rows:
        print(f"No data to migrate for {table_name}")
        return

    placeholders = ", ".join(["%s"] * len(columns))
    col_str = ", ".join(columns)
    
    # Decide whether to use REPLACE INTO or INSERT IGNORE
    # MySQL `INSERT IGNORE` uses `IGNORE` keyword. `REPLACE INTO` replaces existing rows.
    # Let's use INSERT IGNORE to keep what's currently in MySQL if it exists, or REPLACE if we want to overwrite.
    # For safe migration, I'll use INSERT IGNORE
    
    query = f"INSERT IGNORE INTO {table_name} ({col_str}) VALUES ({placeholders})"
    
    data = []
    for row in rows:
        data.append(tuple(row[col] for col in columns))
        
    try:
        mysql_cursor.executemany(query, data)
        mysql_conn.commit()
        print(f"Successfully migrated {mysql_cursor.rowcount} rows into {table_name}.")
    except Exception as e:
        print(f"Error migrating {table_name}: {e}")
        mysql_conn.rollback()

# List of tables to migrate
tables_to_migrate = ['admins', 'coordinators', 'applications', 'application_sequence']

for table in tables_to_migrate:
    migrate_table(table)

print("Migration completed!")

# Close connections
mysql_cursor.close()
mysql_conn.close()
sqlite_cursor.close()
sqlite_conn.close()
