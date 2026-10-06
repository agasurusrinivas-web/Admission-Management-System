import sqlite3
import os

sqlite_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')
conn = sqlite3.connect(sqlite_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

tables = ['admins', 'coordinators', 'applications', 'application_sequence', 'follow_ups', 'email_notifications']

sql_lines = [
    '--',
    '-- Complete MySQL Setup and Data Import Script for AMS Project',
    '--',
    'CREATE DATABASE IF NOT EXISTS project_db;',
    'USE project_db;',
    ''
]

schemas = {
    'admins': """CREATE TABLE IF NOT EXISTS admins (
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
);""",
    'coordinators': """CREATE TABLE IF NOT EXISTS coordinators (
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
);""",
    'applications': """CREATE TABLE IF NOT EXISTS applications (
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
);""",
    'application_sequence': """CREATE TABLE IF NOT EXISTS application_sequence (
    id INT PRIMARY KEY,
    last_number INT NOT NULL
);""",
    'follow_ups': """CREATE TABLE IF NOT EXISTS follow_ups (
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
);""",
    'email_notifications': """CREATE TABLE IF NOT EXISTS email_notifications (
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
);"""
}

def escape_sql(val):
    if val is None:
        return 'NULL'
    if isinstance(val, (int, float)):
        return str(val)
    val_str = str(val).replace('\\', '\\\\').replace("'", "''")
    return f"'{val_str}'"

for tbl in tables:
    sql_lines.append(f'-- ----------------------------')
    sql_lines.append(f'-- Table structure and data for `{tbl}`')
    sql_lines.append(f'-- ----------------------------')
    sql_lines.append(schemas[tbl])
    sql_lines.append('')
    
    cur.execute(f'PRAGMA table_info({tbl})')
    cols = [col['name'] for col in cur.fetchall()]
    
    cur.execute(f'SELECT * FROM {tbl}')
    rows = cur.fetchall()
    if rows:
        col_str = ', '.join([f'`{c}`' for c in cols])
        sql_lines.append(f'REPLACE INTO `{tbl}` ({col_str}) VALUES')
        val_rows = []
        for r in rows:
            vals = [escape_sql(r[c]) for c in cols]
            val_rows.append('  (' + ', '.join(vals) + ')')
        sql_lines.append(',\n'.join(val_rows) + ';')
        sql_lines.append('')

sql_lines.append('-- ----------------------------')
sql_lines.append('-- Verification Queries')
sql_lines.append('-- ----------------------------')
sql_lines.append("SELECT 'admins' AS table_name, COUNT(*) AS total_records FROM admins;")
sql_lines.append("SELECT 'coordinators' AS table_name, COUNT(*) AS total_records FROM coordinators;")
sql_lines.append("SELECT 'applications' AS table_name, COUNT(*) AS total_records FROM applications;")
sql_lines.append("SELECT 'follow_ups' AS table_name, COUNT(*) AS total_records FROM follow_ups;")
sql_lines.append("SELECT 'email_notifications' AS table_name, COUNT(*) AS total_records FROM email_notifications;")
sql_lines.append('')
sql_lines.append('SELECT * FROM applications LIMIT 50;')

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'load_ams_into_workbench.sql')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(sql_lines))

print(f'Successfully generated: {out_path}')
