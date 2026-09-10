import sqlite3

conn = sqlite3.connect('users.db')
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables:", tables)

for table_name in tables:
    table = table_name[0]
    print(f"\n--- Schema for table {table} ---")
    cursor.execute(f"PRAGMA table_info({table});")
    print(cursor.fetchall())
    
    print(f"\n--- Data for table {table} ---")
    cursor.execute(f"SELECT * FROM {table} LIMIT 5;")
    print(cursor.fetchall())

conn.close()
