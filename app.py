from flask import Flask, render_template, request, redirect, url_for, session, g, flash, jsonify, send_file
import random, threading
import datetime
import json
from io import BytesIO
from werkzeug.utils import secure_filename

import mysql.connector
import os

# Added libs for downloads
import openpyxl
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import sqlite3

# Try loading .env if dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from services.email_service import is_valid_email, send_test_email, send_coordinator_credentials_email
from services.scheduler_service import (
    start_scheduler, get_now_kolkata, parse_visit_datetime,
    process_single_notification, check_and_process_due_emails
)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your_secret_key")

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root") 
DB_PASSWORD = os.getenv("DB_PASSWORD", "") 
DB_NAME = os.getenv("DB_NAME", "project_db")


# ---------------- SQLite Fallback Wrapper ----------------
class SQLiteCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self.description = None
        self.rowcount = -1

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def execute(self, query, params=None):
        import re
        # Smart replacement for %s parameters (when not part of a string format like %Y-%m-%d)
        sql = re.sub(r"(?<!['\"])(?<!%)(%s)(?!['\"])", '?', query)
        if params is not None:
            if isinstance(params, (list, tuple)):
                self.cursor.execute(sql, params)
            elif isinstance(params, dict):
                self.cursor.execute(sql, params)
            else:
                self.cursor.execute(sql, (params,))
        else:
            self.cursor.execute(sql)
        self.rowcount = self.cursor.rowcount
        self.description = self.cursor.description
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return dict(row)
        return row

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], sqlite3.Row):
            return [dict(r) for r in rows]
        return rows

    def close(self):
        self.cursor.close()

class SQLiteConnWrapper:
    def __init__(self, db_path='users.db'):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        
        self.conn.create_function("STR_TO_DATE", 2, lambda val, fmt=None: val)
        self.conn.create_function("STR_TO_DATE", 1, lambda val: val)
        self.conn.create_function("YEAR", 1, lambda val: int(str(val)[:4]) if val and len(str(val))>=4 and str(val)[:4].isdigit() else None)
        self.conn.create_function("MONTH", 1, lambda val: int(str(val).split('-')[1]) if val and '-' in str(val) and str(val).split('-')[1].isdigit() else None)
        self.conn.create_function("DATE", 1, lambda val: str(val).split(' ')[0] if val else None)

    def cursor(self, dictionary=True, buffered=True):
        return SQLiteCursorWrapper(self.conn.cursor())

    def start_transaction(self):
        pass

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

def ensure_db_schema(conn):
    """
    Ensure follow_ups, email_notifications tables and columns exist in active database.
    Works for both MySQL and SQLite fallback.
    """
    try:
        cur = conn.cursor()
        is_sqlite = isinstance(conn, SQLiteConnWrapper) or hasattr(conn, 'conn')
        if is_sqlite:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS follow_ups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER,
                    application_number TEXT NOT NULL,
                    coordinator_id INTEGER,
                    coordinator_name TEXT,
                    student_name TEXT,
                    student_email TEXT,
                    scheduled_date TEXT,
                    scheduled_time TEXT,
                    visit_date TEXT,
                    visit_time TEXT,
                    scheduled_at TEXT NOT NULL,
                    purpose TEXT,
                    feedback TEXT,
                    reminder_setting TEXT DEFAULT 'at_event',
                    status TEXT DEFAULT 'scheduled',
                    notes TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    completed_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    follow_up_id INTEGER,
                    application_number TEXT,
                    recipient_type TEXT,
                    recipient_email TEXT,
                    subject TEXT,
                    scheduled_at TEXT,
                    sent_at TEXT,
                    status TEXT DEFAULT 'scheduled',
                    error_message TEXT,
                    created_at TEXT
                )
            """)
            cur.execute("PRAGMA table_info(follow_ups)")
            f_cols = [c['name'] if isinstance(c, dict) else c[1] for c in cur.fetchall()]
            for needed in ['application_id', 'student_email', 'scheduled_date', 'scheduled_time']:
                if needed not in f_cols:
                    try:
                        cur.execute(f"ALTER TABLE follow_ups ADD COLUMN {needed} TEXT")
                    except Exception:
                        pass
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS follow_ups (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    application_id INT NULL,
                    application_number VARCHAR(50) NOT NULL,
                    coordinator_id INT NULL,
                    coordinator_name VARCHAR(100) NULL,
                    student_name VARCHAR(255) NULL,
                    student_email VARCHAR(255) NULL,
                    scheduled_date VARCHAR(50) NULL,
                    scheduled_time VARCHAR(50) NULL,
                    visit_date VARCHAR(50) NULL,
                    visit_time VARCHAR(50) NULL,
                    scheduled_at VARCHAR(50) NOT NULL,
                    purpose VARCHAR(255) NULL,
                    feedback TEXT NULL,
                    reminder_setting VARCHAR(50) DEFAULT 'at_event',
                    status VARCHAR(50) DEFAULT 'scheduled',
                    notes TEXT NULL,
                    created_at VARCHAR(50) NULL,
                    updated_at VARCHAR(50) NULL,
                    completed_at VARCHAR(50) NULL
                )
            """)
            cur.execute("""
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
        conn.commit()
    except Exception as e:
        print(f"[Schema Init Info] {e}")

_db_initialized = False

def create_db_connection():
    global _db_initialized
    conn = None
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            connection_timeout=2
        )
        if not _db_initialized:
            print(f"[Database] Successfully connected to MySQL database '{DB_NAME}' on {DB_HOST}.")
    except Exception as e:
        if not _db_initialized:
            print(f"[Database Warning] MySQL connection failed ({e}). Using SQLite fallback (users.db).")
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.db')
        conn = SQLiteConnWrapper(db_path)

    if not _db_initialized and conn:
        ensure_db_schema(conn)
        _db_initialized = True
    return conn

# ---------------- Database Connection ----------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = create_db_connection()
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


# ------------------ Helper functions ------------------

def format_app_number(year, num):
    return f"PEC{year}{num:03d}"

def extract_sequence_number(app_no):
    if not app_no:
        return 0
    clean = str(app_no).strip().upper().replace('PEC', '')
    current_year_str = str(datetime.datetime.now().year)
    while clean.startswith(current_year_str):
        clean = clean[len(current_year_str):]
    try:
        m = re.search(r'(\d+)$', clean)
        if m:
            return int(m.group(1))
        return int(clean) if clean.isdigit() else 0
    except Exception:
        return 0

def get_current_max_sequence(cur, current_year):
    pattern = f"PEC{current_year}%"
    cur.execute("SELECT application_number, numeric_part FROM applications WHERE application_number LIKE %s", (pattern,))
    rows = cur.fetchall()
    max_seq = 0
    for r in rows:
        app_no = r.get('application_number')
        seq1 = extract_sequence_number(app_no)
        num_part = r.get('numeric_part') or 0
        seq = max(seq1, num_part if isinstance(num_part, int) and num_part < 100000 else 0)
        if seq > max_seq:
            max_seq = seq
    return max_seq

# Concurrency lock for safety
sequence_lock = threading.Lock()

def reserve_new_application_number(coordinator_name=None):
    """
    Reserves the next continuous application number for the current year.
    Format: PEC<YYYY><0001> (e.g., PEC20260001)
    """
    conn = create_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        conn.start_transaction()
        current_year = datetime.datetime.now().year
        current_max = get_current_max_sequence(cur, current_year)
        new_num = current_max + 1
        application_number = format_app_number(current_year, new_num)
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        cur.execute("""
            INSERT INTO applications (application_number, numeric_part, coordinator, status, date_opened)
            VALUES (%s, %s, %s, 'reserved', %s)
        """, (application_number, new_num, coordinator_name or '', now))

        conn.commit()
        return application_number, new_num
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_next_application_number_preview():
    """
    Returns the next expected application number WITHOUT altering the database.
    Useful for displaying 'Preview' in the form before saving.
    """
    conn = create_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    try:
        current_year = datetime.datetime.now().year
        current_max = get_current_max_sequence(cur, current_year)
        new_num = current_max + 1
        return format_app_number(current_year, new_num)
    except Exception as e:
        print(f"DEBUG ERROR in preview: {e}")
        return ""
    finally:
        conn.close()


def finalize_save_application(application_number, student_name, father_name, preferred_branch, form_data=None, coordinator_name=None, form_type='normal'):
    """
    Finalize (save) the application: update reserved row to submitted and add fields.
    If reservation doesn't exist, create a new submitted row.
    """
    new_status = 'confirmed' if form_type == 'confirm' else 'visited'
    db = create_db_connection()
    cur = db.cursor(dictionary=True, buffered=True)
    try:
        # Check if application exists
        cur.execute("SELECT id FROM applications WHERE application_number = %s", (application_number,))
        row = cur.fetchone()
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        
        if row:
            # update existing reserved row
            cur.execute("""
                UPDATE applications
                SET student_name=%s, father_name=%s, preferred_branch=%s, status=%s,
                    form_data=%s, date_submitted=%s, coordinator=%s
                WHERE application_number=%s
            """, (
                student_name, father_name, preferred_branch, new_status,
                json.dumps(form_data) if form_data is not None else None,
                now, coordinator_name or '', application_number
            ))
        else:
            # If not found (no reservation), create a new submitted row
            numeric_part = extract_sequence_number(application_number)
            
            cur.execute("""
                INSERT INTO applications (application_number, numeric_part, student_name, father_name, preferred_branch, status, form_data, date_opened, date_submitted, coordinator)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (application_number, numeric_part, student_name, father_name, preferred_branch, new_status,
                  json.dumps(form_data) if form_data is not None else None, now, now, coordinator_name or ''))
        db.commit()
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------- Home ----------------
@app.route('/')
def home():
    return render_template('index.html')


# ---------------- Admin ----------------
@app.route('/admin')
def admin_page():
    return render_template('admin_login.html')


@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        try:
            email = request.form['email'].strip()
            password = request.form['password'].strip()
            db = get_db()
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT id, first_name, last_name, email FROM admins WHERE email=%s AND password=%s",
                           (email, password))
            user = cursor.fetchone()
            if user:
                session['admin_id'] = user['id']
                session['admin_name'] = f"{user['first_name']} {user['last_name']}"
                session['admin_email'] = user['email']
                return redirect(url_for('admin_dashboard'))
            else:
                flash("Invalid Admin credentials", "error")
                return redirect(url_for('admin_page')) # Redirect to GET route
        except Exception as e:
            return f"Login Error: {str(e)}", 500
    return render_template('admin_login.html')


@app.route('/admin_dashboard')
def admin_dashboard():
    if 'admin_id' in session:
        try:
            db = get_db()
            cursor = db.cursor(dictionary=True)
            
            # Fetch Admin Details
            cursor.execute("SELECT * FROM admins WHERE id=%s", (session['admin_id'],))
            admin = cursor.fetchone()
            
            # Fetch all coordinators
            cursor.execute("SELECT first_name, last_name, email, phone, work FROM coordinators")
            coordinators = cursor.fetchall() or []

            return render_template(
                'admin_dashboard.html',
                admin=admin,
                coordinators=coordinators
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"Dashboard Error: {str(e)}", 500
    return redirect(url_for('admin_page'))


@app.route('/api/admin/profile', methods=['GET', 'POST'])
def admin_profile_api():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()

    if request.method == 'GET':
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT first_name, last_name, email, phone, role, dob,
                   address, city, state, pincode, country, photo
            FROM admins WHERE id=%s
        """, (session['admin_id'],))
        row = cur.fetchone()
        if row:
            if row['dob']:
                row['dob'] = str(row['dob'])
            return jsonify(row)
        return jsonify({"error": "Admin not found"}), 404

    if request.method == 'POST':
        try:
            # Handle multipart/form-data (FormData)
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            role = request.form.get('role')
            dob = request.form.get('dob')
            address = request.form.get('address')
            city = request.form.get('city')
            state = request.form.get('state')
            pincode = request.form.get('pincode')
            country = request.form.get('country')

            # Handle photo upload
            photo_path = None
            if 'photo' in request.files:
                file = request.files['photo']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    # Prepend timestamp to avoid caching/collisions
                    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    filename = f"{ts}_{filename}"
                    save_path = os.path.join(app.root_path, 'static', 'uploads', filename)
                    # Ensure directory exists
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    file.save(save_path)
                    photo_path = f"/static/uploads/{filename}"

            cur = db.cursor()

            # Dynamic query construction based on whether photo is updated
            if photo_path:
                query = """
                    UPDATE admins SET
                        first_name=%s, last_name=%s, email=%s, phone=%s,
                        role=%s, dob=%s, address=%s, city=%s, state=%s,
                        pincode=%s, country=%s, photo=%s
                    WHERE id=%s
                """
                params = (
                    first_name, last_name, email, phone, role, dob,
                    address, city, state, pincode, country, photo_path,
                    session['admin_id']
                )
            else:
                 query = """
                    UPDATE admins SET
                        first_name=%s, last_name=%s, email=%s, phone=%s,
                        role=%s, dob=%s, address=%s, city=%s, state=%s,
                        pincode=%s, country=%s
                    WHERE id=%s
                """
                 params = (
                    first_name, last_name, email, phone, role, dob,
                    address, city, state, pincode, country,
                    session['admin_id']
                )

            cur.execute(query, params)
            db.commit()

            # Update session
            session['admin_name'] = f"{first_name} {last_name}"

            return jsonify({"success": True, "message": "Profile updated successfully", "photo": photo_path})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/admin/change_password', methods=['POST'])
def change_admin_password():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    current_pass = data.get('current_password')
    new_pass = data.get('new_password')

    if not current_pass or not new_pass:
        return jsonify({"success": False, "error": "Missing fields"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    
    # Verify current password
    cur.execute("SELECT password FROM admins WHERE id=%s", (session['admin_id'],))
    row = cur.fetchone()
    
    if not row or row['password'] != current_pass:
        return jsonify({"success": False, "error": "Incorrect current password"}), 400

    # Update password
    try:
        cur.execute("UPDATE admins SET password=%s WHERE id=%s", (new_pass, session['admin_id']))
        db.commit()
        return jsonify({"success": True, "message": "Password changed successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/save_admin_work', methods=['POST'])
def save_admin_work():
    if 'admin_id' in session:
        work = request.form['work']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE admins SET work=%s WHERE id=%s", (work, session['admin_id']))
        db.commit()
    return redirect(url_for('admin_dashboard'))


# ---------------- Coordinator ----------------
@app.route('/coordinator')
def coordinator_page():
    return render_template('coordinator_login.html')


@app.route('/coordinator_login', methods=['POST'])
def coordinator_login():
    email = request.form['email']
    password = request.form['password']
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT id, first_name, last_name, email FROM coordinators WHERE email=%s AND password=%s",
                   (email, password))
    user = cursor.fetchone()
    if user:
        session['coordinator_id'] = user['id']
        session['coordinator_name'] = f"{user['first_name']} {user['last_name']}"
        session['coordinator_email'] = user['email']
        return redirect(url_for('coordinator_dashboard'))
    flash("Invalid Coordinator credentials", "error")
    return redirect(url_for('coordinator_page'))





@app.route('/coordinator_dashboard')
def coordinator_dashboard():
    if 'coordinator_id' not in session:
        return redirect(url_for('coordinator_page'))

    db = get_db()
    cursor = db.cursor(dictionary=True, buffered=True)
    # Include photo in query
    cursor.execute("""
        SELECT first_name, last_name, email, phone, work, photo
        FROM coordinators WHERE id=%s
    """, (session['coordinator_id'],))
    row = cursor.fetchone()

    if row:
        coordinator_data = {
            "first_name": row['first_name'],
            "last_name": row['last_name'],
            "email": row['email'],
            "phone": row['phone'],
            "work": row['work'],
            "photo": row['photo']
        }
    else:
        coordinator_data = {
            "first_name": "",
            "last_name": "",
            "email": "",
            "phone": "",
            "work": "",
            "photo": None
        }

    return render_template(
        'coordinator_dashboard.html',
        coordinator_data=coordinator_data
    )
# ---------------- Follow-up and Email Helpers ----------------
def extract_student_email_from_form_data(form_data_raw):
    """
    Safely extract candidate/student email address from application form_data JSON.
    Checks student_email, email, candidate_email, father_email, mother_email.
    """
    if not form_data_raw:
        return ""
    data = {}
    if isinstance(form_data_raw, str):
        try:
            data = json.loads(form_data_raw)
        except Exception:
            data = {}
    elif isinstance(form_data_raw, dict):
        data = form_data_raw

    for key in ("student_email", "email", "candidate_email", "candEmail", "father_email", "mother_email"):
        val = data.get(key)
        if val and isinstance(val, str) and "@" in val:
            cleaned = val.strip()
            if is_valid_email(cleaned):
                return cleaned
    return ""

def resolve_coordinator_for_application(app_row, cur):
    """
    Resolve coordinator details (id, name, email) assigned to the student application.
    Prioritizes the actual coordinator assigned to that application (Section 3).
    """
    app_coord_str = (app_row.get('coordinator') or '').strip() if isinstance(app_row, dict) else ''
    coord_id = None
    coord_name = app_coord_str
    coord_email = None

    if app_coord_str and cur:
        cur.execute("""
            SELECT id, first_name, last_name, email 
            FROM coordinators 
            WHERE TRIM(first_name) = %s 
               OR TRIM(CONCAT(first_name, ' ', last_name)) = %s
               OR TRIM(first_name) LIKE %s
            LIMIT 1
        """, (app_coord_str, app_coord_str, f"{app_coord_str}%"))
        c_row = cur.fetchone()
        if c_row:
            coord_id = c_row.get('id')
            c_fn = (c_row.get('first_name') or '').strip()
            c_ln = (c_row.get('last_name') or '').strip()
            coord_name = f"{c_fn} {c_ln}".strip() or app_coord_str
            coord_email = (c_row.get('email') or '').strip()

    # Fallback to session coordinator if matching or unassigned
    if not coord_email and 'coordinator_id' in session:
        session_name = (session.get('coordinator_name') or '').strip()
        if not app_coord_str or (session_name and app_coord_str.lower() in session_name.lower()):
            coord_id = session.get('coordinator_id')
            coord_name = session_name or coord_name
            coord_email = (session.get('coordinator_email') or '').strip()

    return coord_id, coord_name, coord_email

def normalize_date_to_iso(date_str):
    """
    Standardize date strings to ISO YYYY-MM-DD format regardless of format or time part.
    Handles YYYY-MM-DD, YYYY/MM/DD, DD-MM-YYYY, DD/MM/YYYY, and datetime strings.
    """
    if not date_str:
        return None
    s = str(date_str).strip()
    if not s or s in ['---', '-', 'null', 'None']:
        return None
    import re
    # If starts with YYYY-MM-DD or YYYY/MM/DD
    m_iso = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})', s)
    if m_iso:
        y, m, d = m_iso.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    # If DD-MM-YYYY or DD/MM/YYYY
    m_dmy = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})', s)
    if m_dmy:
        d, m, y = m_dmy.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return None

def is_application_pending(status):
    """
    Return True if application is still pending/remaining in admission process.
    Completed, confirmed, cancelled, rejected, or admitted applications return False.
    """
    if not status:
        return True
    s = str(status).strip().lower()
    finished_statuses = {'confirmed', 'completed', 'cancelled', 'rejected', 'admitted'}
    return s not in finished_statuses

def get_application_action_date(app_dict):
    """
    Determine relevant admission/visit/follow-up action date for an application.
    Prioritizes upcoming next_visit, then initial visit/submitted date, then opened date.
    """
    next_visit = app_dict.get('next_visit')
    if next_visit:
        d = normalize_date_to_iso(next_visit)
        if d:
            return d
    date_sub = app_dict.get('date_submitted')
    if date_sub:
        d = normalize_date_to_iso(date_sub)
        if d:
            return d
    date_op = app_dict.get('date_opened')
    if date_op:
        d = normalize_date_to_iso(date_op)
        if d:
            return d
    return None

def get_application_dates(a):
    """
    Collect all relevant dates associated with an application (submission date, next visit, opened date).
    """
    dates = []
    for k in ('date_submitted', 'next_visit', 'date_opened'):
        d = normalize_date_to_iso(a.get(k))
        if d:
            dates.append(d)
    rel = a.get('relevant_action_date')
    if rel:
        dates.append(rel)
    return list(dict.fromkeys(dates))

def filter_coordinator_applications(apps, start_date=None, end_date=None, search=None, status_filter='all'):
    """
    Filter coordinator applications for a particular time period or single day.
    Shows all application details by default, or filtered by status ('all', 'pending', 'confirmed').
    """
    norm_start = normalize_date_to_iso(start_date) if start_date else None
    norm_end = normalize_date_to_iso(end_date) if end_date else None
    
    # If user selected only From Date (single day), treat as that day
    if norm_start and not norm_end:
        norm_end = norm_start

    has_date_filter = bool(norm_start or norm_end)
    search_q = (search or '').strip().lower()
    st_filter = (status_filter or 'all').strip().lower()

    filtered = []
    for a in apps:
        # Date matching: check if any relevant date falls in the range
        if has_date_filter:
            dates = get_application_dates(a)
            matched = False
            for d in dates:
                if norm_start and norm_end and norm_start <= d <= norm_end:
                    matched = True; break
                elif norm_start and not norm_end and d >= norm_start:
                    matched = True; break
                elif norm_end and not norm_start and d <= norm_end:
                    matched = True; break
            if not matched:
                continue

        # Status filtering (default 'all' shows all applications)
        st = str(a.get('status') or '').strip().lower()
        if st_filter == 'pending' and not is_application_pending(st):
            continue
        elif st_filter == 'confirmed' and st != 'confirmed':
            continue

        # Search query
        if search_q:
            app_no = str(a.get('application_number') or '').lower()
            name = str(a.get('student_name') or '').lower()
            father = str(a.get('father_name') or '').lower()
            dept = str(a.get('preferred_branch') or '').lower()
            mobile = str(a.get('mobile') or '').lower()
            if not (search_q in app_no or search_q in name or search_q in father or search_q in dept or search_q in mobile):
                continue

        filtered.append(a)

    return filtered

def fetch_coordinator_applications_records(cur, coord_name):
    """
    Fetch and format all application records assigned to the given coordinator.
    Handles fallbacks to form_data JSON if fields are stored inside JSON.
    """
    if not coord_name:
        return []
    coord_name = coord_name.strip()
    coord_first = coord_name.split()[0] if coord_name else ''
    cur.execute("""
        SELECT application_number, student_name, father_name, preferred_branch,
               mobile, address, status, date_submitted, date_opened, form_data, feedback, next_visit, coordinator
        FROM applications
        WHERE (TRIM(coordinator) = %s 
           OR coordinator = %s 
           OR TRIM(coordinator) = %s 
           OR TRIM(coordinator) LIKE %s)
    """, (coord_name, coord_name, coord_first, f"{coord_first}%"))
    rows = cur.fetchall()
    
    apps = []
    for r in rows:
        rd = dict(r)
        form_json = None
        if rd.get('form_data'):
            try:
                form_json = json.loads(rd['form_data'])
            except Exception:
                form_json = None
        student_email = extract_student_email_from_form_data(rd.get('form_data'))
        action_date = get_application_action_date(rd)
        apps.append({
            "application_number": rd.get('application_number') or "",
            "student_name": rd.get('student_name') or (form_json.get('student_name') if form_json else "") or (form_json.get('candName') if form_json else ""),
            "father_name": rd.get('father_name') or (form_json.get('father_name') if form_json else "") or (form_json.get('fatherName') if form_json else ""),
            "preferred_branch": rd.get('preferred_branch') or (form_json.get('preferred_branch') if form_json else "") or (form_json.get('branch') if form_json else ""),
            "mobile": rd.get('mobile') or (form_json.get('mobile') if form_json else "") or (form_json.get('studentMobile') if form_json else ""),
            "email": student_email,
            "address": rd.get('address') or (form_json.get('address') if form_json else "") or (form_json.get('permanentAddress') if form_json else ""),
            "status": rd.get('status'),
            "date_submitted": str(rd.get('date_submitted') or '') or (form_json.get('date_submitted') if form_json else ''),
            "date_opened": str(rd.get('date_opened') or ''),
            "feedback": rd.get('feedback'),
            "next_visit": rd.get('next_visit'),
            "relevant_action_date": action_date,
            "is_pending": is_application_pending(rd.get('status')),
            "coordinator": rd.get('coordinator')
        })
    return apps

@app.route('/get_coordinator_applications')
def get_coordinator_applications():
    """
    Return JSON list of applications for the logged-in coordinator.
    Supports optional start_date, end_date, search, and status filtering for that day or time period.
    """
    if 'coordinator_id' not in session:
        return jsonify({"applications": [], "students": []}), 200

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        coord_name = session.get('coordinator_name', '').strip()
        apps = fetch_coordinator_applications_records(cur, coord_name)

        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        search = request.args.get('search') or request.args.get('term')
        status_filter = request.args.get('status') or request.args.get('status_filter') or 'all'

        if start_date or end_date or search or (status_filter and status_filter != 'all'):
            apps = filter_coordinator_applications(apps, start_date=start_date, end_date=end_date, search=search, status_filter=status_filter)

        return jsonify({"applications": apps, "students": apps}), 200
    except Exception as e:
        return jsonify({"error": str(e), "applications": [], "students": []}), 500



@app.route('/save_feedback', methods=['POST'])
def save_feedback():
    """
    Coordinator Follow-up and Feedback endpoint.
    Records feedback, next visit date/time, purpose, and schedules reminder emails
    to both student and the assigned coordinator.
    """
    if 'coordinator_id' not in session and 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    app_no = (data.get('application_number') or '').strip()
    feedback = (data.get('feedback') or '').strip()
    visit_date = (data.get('visit_date') or data.get('next_visit_date') or data.get('next_visit') or '').strip()
    visit_time = (data.get('visit_time') or data.get('next_visit_time') or '10:30 AM').strip()
    purpose = (data.get('purpose') or 'Confirm Admission').strip()
    provided_email = (data.get('student_email') or '').strip()

    if not app_no or not feedback:
        return jsonify({"error": "Please provide both Application Number and Feedback."}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # Check application exists
        cur.execute("""
            SELECT id, application_number, student_name, coordinator, form_data, status
            FROM applications 
            WHERE application_number = %s
        """, (app_no,))
        app_row = cur.fetchone()
        if not app_row:
            return jsonify({"error": f"Application '{app_no}' not found."}), 404

        now_kolkata = get_now_kolkata()
        now_str = now_kolkata.strftime('%Y-%m-%d %H:%M:%S')

        # Student Name resolution
        student_name = (app_row.get('student_name') or '').strip()
        form_data_raw = app_row.get('form_data')
        form_data_dict = {}
        if form_data_raw:
            try:
                form_data_dict = json.loads(form_data_raw) if isinstance(form_data_raw, str) else form_data_raw
            except Exception:
                form_data_dict = {}
        if not student_name:
            student_name = form_data_dict.get('student_name') or form_data_dict.get('candName') or "Student"

        # Student Email resolution
        if provided_email and is_valid_email(provided_email):
            student_email = provided_email
            if not form_data_dict.get('email') and not form_data_dict.get('student_email'):
                form_data_dict['email'] = student_email
                cur.execute("UPDATE applications SET form_data = %s WHERE application_number = %s",
                            (json.dumps(form_data_dict), app_no))
        else:
            student_email = extract_student_email_from_form_data(form_data_raw)

        # Coordinator Email resolution (assigned coordinator from application)
        coord_id, coord_name, coord_email = resolve_coordinator_for_application(app_row, cur)

        follow_up_id = None
        student_warning = None
        student_email_status = "none"
        coord_email_status = "none"

        # If visit_date is provided, create follow_up and schedule emails
        if visit_date:
            scheduled_dt = parse_visit_datetime(visit_date, visit_time)
            if not scheduled_dt:
                return jsonify({"error": "Invalid Next Visit Date or Time format."}), 400

            # Section 1 validation: Check if scheduled date/time is in the past (allow 5-minute buffer)
            if scheduled_dt < (now_kolkata - datetime.timedelta(minutes=5)):
                return jsonify({"error": "Next visit date and time cannot be in the past."}), 400

            scheduled_at_str = scheduled_dt.strftime('%Y-%m-%d %H:%M:%S')

            # Insert into follow_ups table
            cur.execute("""
                INSERT INTO follow_ups (
                    application_id, application_number, coordinator_id, coordinator_name,
                    student_name, student_email, scheduled_date, scheduled_time,
                    visit_date, visit_time, scheduled_at, purpose, feedback, status,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'scheduled', %s, %s)
            """, (
                app_row.get('id'), app_no, coord_id, coord_name,
                student_name, student_email, visit_date, visit_time,
                visit_date, visit_time, scheduled_at_str, purpose, feedback,
                now_str, now_str
            ))
            follow_up_id = cur.lastrowid

            # Create Student Email Notification Record (Section 5)
            student_subj = f"Admission Follow-up Reminder – {app_no}"
            if student_email and is_valid_email(student_email):
                cur.execute("""
                    INSERT INTO email_notifications (
                        follow_up_id, application_number, recipient_type, recipient_email,
                        subject, scheduled_at, status, created_at
                    ) VALUES (%s, %s, 'student', %s, %s, %s, 'scheduled', %s)
                """, (follow_up_id, app_no, student_email, student_subj, scheduled_at_str, now_str))
                student_email_status = "scheduled"
            else:
                # Student email missing: do not crash! Record safely as email_failed
                cur.execute("""
                    INSERT INTO email_notifications (
                        follow_up_id, application_number, recipient_type, recipient_email,
                        subject, scheduled_at, status, error_message, created_at
                    ) VALUES (%s, %s, 'student', %s, %s, %s, 'email_failed', %s, %s)
                """, (follow_up_id, app_no, student_email or '', student_subj, scheduled_at_str,
                      "Student email address missing from application records.", now_str))
                student_email_status = "email_failed"
                student_warning = "Student email address is missing from application records. Coordinator reminder scheduled, but student reminder cannot be delivered until student email is added."

            # Create Coordinator Email Notification Record (Section 5)
            coord_subj = f"Student Follow-up Reminder – {student_name} – {app_no}"
            if coord_email and is_valid_email(coord_email):
                cur.execute("""
                    INSERT INTO email_notifications (
                        follow_up_id, application_number, recipient_type, recipient_email,
                        subject, scheduled_at, status, created_at
                    ) VALUES (%s, %s, 'coordinator', %s, %s, %s, 'scheduled', %s)
                """, (follow_up_id, app_no, coord_email, coord_subj, scheduled_at_str, now_str))
                coord_email_status = "scheduled"
            else:
                cur.execute("""
                    INSERT INTO email_notifications (
                        follow_up_id, application_number, recipient_type, recipient_email,
                        subject, scheduled_at, status, error_message, created_at
                    ) VALUES (%s, %s, 'coordinator', %s, %s, %s, 'email_failed', %s, %s)
                """, (follow_up_id, app_no, coord_email or '', coord_subj, scheduled_at_str,
                      "Coordinator email address missing.", now_str))
                coord_email_status = "email_failed"

        # Backward compatibility: update applications table fields
        nv_text = f"{visit_date} {visit_time}".strip() if visit_date else None
        cur.execute("UPDATE applications SET feedback = %s, next_visit = %s WHERE application_number = %s",
                    (feedback, nv_text, app_no))
        db.commit()

        return jsonify({
            "success": True,
            "message": "Feedback recorded and follow-up scheduled successfully!",
            "warning": student_warning,
            "follow_up_id": follow_up_id,
            "student_email": student_email,
            "coordinator_email": coord_email,
            "student_email_status": student_email_status,
            "coordinator_email_status": coord_email_status
        }), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Failed to save follow-up: {str(e)}"}), 500


@app.route('/complete_follow_up', methods=['POST'])
def complete_follow_up():
    """
    Mark a follow-up as completed (Section 18).
    """
    if 'coordinator_id' not in session and 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    follow_up_id = data.get('follow_up_id')
    if not follow_up_id:
        return jsonify({"error": "Missing follow_up_id"}), 400

    now_kolkata = get_now_kolkata()
    now_str = now_kolkata.strftime('%Y-%m-%d %H:%M:%S')

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            UPDATE follow_ups 
            SET status = 'completed', completed_at = %s, updated_at = %s
            WHERE id = %s
        """, (now_str, now_str, follow_up_id))
        db.commit()
        return jsonify({"success": True, "message": "Follow-up marked as completed."}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@app.route('/retry_email_notification', methods=['POST'])
def retry_email_notification():
    """
    Retry sending a failed email notification safely (Section 15).
    """
    if 'coordinator_id' not in session and 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    notif_id = data.get('notification_id')
    new_email = (data.get('recipient_email') or '').strip()

    if not notif_id:
        return jsonify({"error": "Missing notification_id"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        if new_email and is_valid_email(new_email):
            cur.execute("UPDATE email_notifications SET recipient_email = %s, status = 'scheduled' WHERE id = %s",
                        (new_email, notif_id))
            db.commit()

        success, err = process_single_notification(db, notif_id)
        if success:
            return jsonify({"success": True, "message": "Email sent successfully!"}), 200
        else:
            return jsonify({"success": False, "error": err or "Failed to send email."}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@app.route('/api/coordinator/follow_ups')
def get_coordinator_followups():
    """
    Retrieve follow-ups for the logged-in coordinator (Section 14).
    Supports filters: all, upcoming, today, completed, missed, email_failed.
    """
    if 'coordinator_id' not in session and 'admin_id' not in session:
        return jsonify({"error": "Unauthorized", "follow_ups": []}), 401

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        coord_name = (session.get('coordinator_name') or '').strip()
        coord_id = session.get('coordinator_id')
        filter_status = request.args.get('status', 'all').lower()

        sql = """
            SELECT f.id, f.application_number, f.student_name, f.student_email,
                   f.coordinator_name, f.scheduled_date, f.scheduled_time, f.visit_date, f.visit_time,
                   f.scheduled_at, f.purpose, f.feedback, f.status, f.created_at, f.completed_at,
                   sn.id as student_notif_id, sn.status as student_email_status, sn.error_message as student_email_error,
                   cn.id as coord_notif_id, cn.status as coordinator_email_status, cn.error_message as coord_email_error
            FROM follow_ups f
            LEFT JOIN email_notifications sn ON sn.follow_up_id = f.id AND sn.recipient_type = 'student'
            LEFT JOIN email_notifications cn ON cn.follow_up_id = f.id AND cn.recipient_type = 'coordinator'
        """
        params = []
        if 'coordinator_id' in session and 'admin_id' not in session:
            sql += " WHERE (f.coordinator_id = %s OR TRIM(f.coordinator_name) = %s OR f.coordinator_name = %s OR TRIM(f.coordinator_name) = %s) "
            params.extend([coord_id, coord_name, coord_name, coord_name.split()[0] if coord_name else ''])

        sql += " ORDER BY f.scheduled_at DESC, f.id DESC"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

        now_kolkata = get_now_kolkata()
        today_str = now_kolkata.strftime('%Y-%m-%d')

        items = []
        for r in rows:
            rd = dict(r)
            s_at = rd.get('scheduled_at') or ''
            s_date = rd.get('scheduled_date') or rd.get('visit_date') or (s_at.split()[0] if s_at else '')
            f_status = rd.get('status') or 'scheduled'
            
            # Filter handling
            if filter_status == 'upcoming' and f_status not in ('scheduled', 'email_sent'):
                continue
            elif filter_status == 'today' and s_date != today_str:
                continue
            elif filter_status == 'completed' and f_status != 'completed':
                continue
            elif filter_status == 'missed' and f_status != 'missed':
                continue
            elif filter_status == 'email_failed' and (rd.get('student_email_status') != 'email_failed' and rd.get('coordinator_email_status') != 'email_failed' and f_status != 'email_failed'):
                continue

            items.append(rd)

        return jsonify({"follow_ups": items}), 200
    except Exception as e:
        return jsonify({"error": str(e), "follow_ups": []}), 500


@app.route('/api/follow_up/history/<app_no>')
def get_followup_history(app_no):
    """
    Retrieve all historical follow-ups for a student application (Section 17).
    """
    if 'coordinator_id' not in session and 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT f.*, 
                   sn.id as student_notif_id, sn.status as student_email_status, sn.sent_at as student_email_sent_at, sn.error_message as student_email_error,
                   cn.id as coord_notif_id, cn.status as coordinator_email_status, cn.sent_at as coordinator_email_sent_at, cn.error_message as coordinator_email_error
            FROM follow_ups f
            LEFT JOIN email_notifications sn ON sn.follow_up_id = f.id AND sn.recipient_type = 'student'
            LEFT JOIN email_notifications cn ON cn.follow_up_id = f.id AND cn.recipient_type = 'coordinator'
            WHERE f.application_number = %s
            ORDER BY f.id DESC
        """, (app_no,))
        rows = cur.fetchall()
        return jsonify({"history": [dict(r) for r in rows]}), 200
    except Exception as e:
        return jsonify({"error": str(e), "history": []}), 500


@app.route('/api/admin/follow_ups')
def get_admin_followups():
    """
    Retrieve all follow-ups system-wide for Admin Monitoring (Section 16).
    """
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized", "follow_ups": []}), 401

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        cur.execute("""
            SELECT f.id, f.application_number, f.student_name, f.student_email,
                   f.coordinator_name, f.scheduled_date, f.scheduled_time, f.visit_date, f.visit_time,
                   f.scheduled_at, f.purpose, f.feedback, f.status, f.created_at, f.completed_at,
                   sn.id as student_notif_id, sn.status as student_email_status, sn.error_message as student_email_error,
                   cn.id as coord_notif_id, cn.status as coordinator_email_status, cn.error_message as coord_email_error
            FROM follow_ups f
            LEFT JOIN email_notifications sn ON sn.follow_up_id = f.id AND sn.recipient_type = 'student'
            LEFT JOIN email_notifications cn ON cn.follow_up_id = f.id AND cn.recipient_type = 'coordinator'
            ORDER BY f.scheduled_at DESC, f.id DESC
        """)
        rows = cur.fetchall()
        return jsonify({"follow_ups": [dict(r) for r in rows]}), 200
    except Exception as e:
        return jsonify({"error": str(e), "follow_ups": []}), 500


@app.route('/api/admin/send_test_email', methods=['POST'])
def admin_send_test_email():
    """
    Safe test email mechanism for Admin SMTP verification (Section 24).
    """
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    to_email = (data.get('email') or '').strip()
    if not to_email or not is_valid_email(to_email):
        return jsonify({"error": "Please provide a valid recipient email address."}), 400

    success, err = send_test_email(to_email)
    if success:
        return jsonify({"success": True, "message": f"Test email successfully sent to {to_email}!"}), 200
    else:
        return jsonify({"success": False, "error": err or "Failed to send test email."}), 400


@app.route('/api/scheduler/run_check', methods=['POST'])
def api_trigger_scheduler_check():
    """
    Trigger manual scheduler tick for immediate processing/testing.
    """
    if 'admin_id' not in session and 'coordinator_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        due = check_and_process_due_emails(create_db_connection)
        return jsonify({"success": True, "processed": due}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/delete_feedback', methods=['POST'])
def delete_feedback():
    if 'admin_id' not in session and 'coordinator_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    app_no = data.get('application_number')

    if not app_no:
        return jsonify({"error": "Missing application number"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    try:
        # Also clear feedback from form_data JSON if it exists there
        cur.execute("SELECT form_data FROM applications WHERE application_number=%s", (app_no,))
        row = cur.fetchone()
        
        form_data_str = None
        if row and row.get('form_data'):
            try:
                form_data_dict = json.loads(row['form_data'])
                if isinstance(form_data_dict, dict) and 'feedback' in form_data_dict:
                    form_data_dict['feedback'] = ''
                    form_data_str = json.dumps(form_data_dict)
                else:
                    form_data_str = row['form_data']
            except Exception:
                form_data_str = row['form_data']

        cur = db.cursor()
        cur.execute("UPDATE applications SET feedback = NULL, form_data = %s WHERE application_number=%s", (form_data_str, app_no))
        db.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@app.route('/api/coordinator/profile', methods=['POST'])
def coordinator_profile_api():
    if 'coordinator_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()
    
    try:
        # Handle multipart/form-data
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        # name is usually combined in frontend but we accept split or specific fields
        # If frontend sends 'name', split it
        name = request.form.get('name')
        if name and not first_name:
             parts = name.strip().split(' ', 1)
             first_name = parts[0]
             last_name = parts[1] if len(parts) > 1 else ''

        phone = request.form.get('phone')
        work = request.form.get('work')
        
        # Handle photo upload
        photo_path = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename:
                filename = secure_filename(file.filename)
                ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"coord_{ts}_{filename}"
                save_path = os.path.join(app.root_path, 'static', 'uploads', filename)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                file.save(save_path)
                photo_path = f"/static/uploads/{filename}"

        cur = db.cursor()
        
        if photo_path:
            query = """
                UPDATE coordinators SET 
                    first_name=%s, last_name=%s, phone=%s, work=%s, photo=%s
                WHERE id=%s
            """
            params = (first_name, last_name, phone, work, photo_path, session['coordinator_id'])
        else:
            query = """
                UPDATE coordinators SET 
                    first_name=%s, last_name=%s, phone=%s, work=%s
                WHERE id=%s
            """
            params = (first_name, last_name, phone, work, session['coordinator_id'])
        
        cur.execute(query, params)
        db.commit()
        
        # Update session
        session['coordinator_name'] = f"{first_name} {last_name}"
        
        return jsonify({"success": True, "message": "Profile updated successfully", "photo": photo_path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/save_coordinator_work', methods=['POST'])
def save_coordinator_work():
    if 'coordinator_id' in session:
        work = request.form['work']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE coordinators SET work=%s WHERE id=%s", (work, session['coordinator_id']))
        db.commit()
    return redirect(url_for('coordinator_dashboard'))


# ---------------- Application Form ----------------
@app.route('/upload_temp_photo', methods=['POST'])
def upload_temp_photo():
    """
    Temporary endpoint for the multi-page confirm form to upload images before the final submission.
    Returns the file path.
    """
    if 'coordinator_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    if 'photo' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['photo']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    if file:
        filename = secure_filename(file.filename)
        ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        rand_str = str(random.randint(1000, 9999))
        filename = f"temp_{ts}_{rand_str}_{filename}"
        save_path = os.path.join(app.root_path, 'static', 'uploads', filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        file.save(save_path)
        
        photo_path = f"/static/uploads/{filename}"
        return jsonify({"success": True, "path": photo_path})

    return jsonify({"error": "Failed to handle file"}), 500


@app.route('/conform_application')
@app.route('/conform_application/<page>')
def conform_application(page='first.html'):
    if 'coordinator_id' not in session:
        flash("Please log in as coordinator to access the form", "error")
        return redirect(url_for('coordinator_page'))
    if not page.endswith('.html'):
        page += '.html'
    return render_template(f'application form/{page}')

def process_and_save_form_images(form_data, app_no='temp'):
    if not isinstance(form_data, dict):
        return form_data

    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)

    import base64, uuid, re

    for key, val in list(form_data.items()):
        if isinstance(val, str) and val.startswith('data:'):
            try:
                header, encoded = val.split(',', 1)
                mime = header.split(';')[0].split(':')[1] if ';' in header and ':' in header else 'image/jpeg'
                ext = 'jpg'
                if 'png' in mime: ext = 'png'
                elif 'pdf' in mime: ext = 'pdf'
                elif 'webp' in mime: ext = 'webp'

                data_bytes = base64.b64decode(encoded)
                clean_key = re.sub(r'[^a-zA-Z0-9_]', '_', str(key))
                clean_app = re.sub(r'[^a-zA-Z0-9_]', '_', str(app_no or 'temp'))
                filename = f"{clean_key}_{clean_app}_{uuid.uuid4().hex[:8]}.{ext}"
                abs_path = os.path.join(upload_dir, filename)
                with open(abs_path, 'wb') as f:
                    f.write(data_bytes)

                form_data[key] = f"/static/uploads/{filename}"
            except Exception as e:
                print(f"Error processing base64 image for key '{key}': {e}")

    return form_data

@app.route('/upload_image', methods=['POST'])
def upload_image():
    if 'coordinator_id' not in session and 'admin_id' not in session:
        return jsonify({"error": "Not authorized"}), 401

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    field_name = request.form.get('field_name', 'image')
    app_no = request.form.get('application_number', 'temp')

    if not file or file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    allowed_extensions = {'png', 'jpg', 'jpeg', 'webp', 'pdf'}
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return jsonify({"error": "Invalid file format. Allowed formats: JPG, JPEG, PNG, WEBP, PDF."}), 400

    import uuid, re
    clean_field = re.sub(r'[^a-zA-Z0-9_]', '_', str(field_name))
    clean_app = re.sub(r'[^a-zA-Z0-9_]', '_', str(app_no))
    filename = f"{clean_field}_{clean_app}_{uuid.uuid4().hex[:8]}.{ext}"

    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    abs_path = os.path.join(upload_dir, filename)
    file.save(abs_path)

    rel_path = f"/static/uploads/{filename}"
    return jsonify({
        "success": True,
        "file_path": rel_path,
        "field_name": field_name,
        "message": "File uploaded successfully"
    }), 200

@app.route('/save_draft', methods=['POST'])
def save_draft():
    if 'coordinator_id' not in session:
        return jsonify({"error": "Not authorized"}), 401
        
    data = request.get_json()
    application_number = data.get('application_number')
    form_data = data.get('form_data')
    
    if not application_number:
        return jsonify({"success": False, "error": "No application number provided for draft."}), 400
        
    if isinstance(form_data, dict):
        form_data = process_and_save_form_images(form_data, application_number)

    db = get_db()
    cursor = db.cursor(dictionary=True, buffered=True)
    
    try:
        # Check if exists
        cursor.execute("SELECT id FROM applications WHERE application_number = %s", (application_number,))
        if cursor.fetchone():
            cursor.execute("""
                UPDATE applications 
                SET form_data = %s,
                    last_modified = %s
                WHERE application_number = %s
            """, (
                json.dumps(form_data) if form_data else None,
                datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                application_number
            ))
            db.commit()
            return jsonify({"success": True, "message": "Draft saved successfully."})
        else:
            return jsonify({"success": False, "error": "Application not found."}), 404
            
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()

# Add this route after your existing routes
# ...existing code...
@app.route('/save_application', methods=['POST'])
def save_application():
    if 'coordinator_id' not in session:
        return jsonify({"error": "Not authorized"}), 401

    data = request.get_json()
    db = get_db()
    
    # Server-side validation
    # Server-side validation
    # application_number is NOT required for new applications (it will be generated)
    # Extract top level fields or fallback to form_data
    form_data = data.get('form_data') or {}
    app_no_val = data.get('application_number') or 'temp'
    if isinstance(form_data, dict):
        form_data = process_and_save_form_images(form_data, app_no_val)
        data['form_data'] = form_data

    student_name = data.get('student_name') or form_data.get('student_name')
    father_name = data.get('father_name') or form_data.get('father_name')
    preferred_branch = data.get('preferred_branch') or form_data.get('preferred_branch')
    mobile = data.get('mobile') or form_data.get('mobile') or form_data.get('father_mobile')
    address = data.get('address') or form_data.get('address') or form_data.get('addr_street')
    
    form_type = data.get('form_type', 'normal')
    missing = []
    
    # Check top-level required fields ONLY for normal forms
    if form_type != 'confirm':
        if not student_name: missing.append('student_name')
        if not father_name: missing.append('father_name')
        if not mobile: missing.append('mobile')
        if not address: missing.append('address')
        
        if isinstance(form_data, dict):
            if not form_data.get('gender'):
                # It's okay if gender is missing from form_data if it's not strictly required by backend logic but ideally it should match frontend.
                # Frontend marks it required.
                missing.append('gender')
    
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # Generate Application Number if not provided
    if not data.get('application_number'):
        try:
             # Reserve new number
             app_num, _ = reserve_new_application_number(session.get('coordinator_name'))
             data['application_number'] = app_num
        except Exception as e:
             return jsonify({"error": f"Failed to generate application number: {str(e)}"}), 500

    new_status = 'confirmed' if form_type == 'confirm' else 'visited'

    cursor = db.cursor(dictionary=True, buffered=True)

    try:
        # Check if application exists
        cursor.execute("""
            SELECT id, status FROM applications 
            WHERE application_number = %s
        """, (data['application_number'],))
        exists = cursor.fetchone()

        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if exists:
            # Preserve existing status unless explicitly specified
            effective_status = data.get('status') or exists.get('status') or new_status
            cursor.execute("""
                UPDATE applications 
                SET student_name = %s,
                    father_name = %s,
                    preferred_branch = %s,
                    mobile = %s,
                    address = %s,
                    status = %s,
                    form_data = %s,
                    last_modified = %s,
                    date_submitted = COALESCE(date_submitted, %s)
                WHERE application_number = %s
            """, (
                student_name,
                father_name,
                preferred_branch,
                mobile,
                address,
                effective_status,
                json.dumps(data.get('form_data')) if data.get('form_data') else None,
                now_str, # Update last_modified
                now_str, # Set date_submitted if null
                data['application_number']
            ))
        else:
            # Try insert with full schema
            num_part = extract_sequence_number(data.get('application_number'))
            cursor.execute("""
                INSERT INTO applications (
                    application_number,
                    numeric_part,
                    student_name,
                    father_name,
                    preferred_branch,
                    mobile,
                    address,
                    status,
                    coordinator,
                    form_data,
                    date_submitted,
                    last_modified
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data.get('application_number'),
                num_part,
                student_name,
                father_name,
                preferred_branch,
                mobile,
                address,
                new_status,
                session.get('coordinator_name', ''),
                json.dumps(data.get('form_data')) if data.get('form_data') else None,
                now_str, # date_submitted
                now_str  # last_modified (initially same)
            ))

        db.commit()
        return jsonify({
            "success": True,
            "application_number": data['application_number'],
            "student_name": student_name,
            "status": new_status,
            "date_submitted": now_str
        }), 200

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
# ...existing code...
@app.route('/application_form', methods=['GET', 'POST'])
def application_form():
    if 'coordinator_id' not in session:
        flash("Please log in as coordinator to access the form", "error")
        return redirect(url_for('coordinator_page'))

    db = get_db()
    cursor = db.cursor()

    if request.method == 'POST':
        # On save: finalize the reserved application_number (submitted)
        app_number = request.form.get('application_number')
        student_name = request.form.get('student_name', '').strip()
        father_name = request.form.get('father_name', '').strip()
        preferred_branch = request.form.get('preferred_branch', '').strip()

        if not app_number:
            flash("No application number found. Please reopen the form.", "error")
            return redirect(url_for('application_form'))

        if not student_name or not father_name:
            flash("Please fill all required fields!", "error")
            # Re-render form with values (app_number preserved)
            return render_template('form.html', app_number=app_number, student_name=student_name,
                                   father_name=father_name, preferred_branch=preferred_branch)

        # Optionally gather any additional fields into form_data
        form_data = {
            # add more fields here if your form has them
        }

        try:
            coord_name = session.get('coordinator_name', '')
            finalize_save_application(app_number, student_name, father_name, preferred_branch, form_data=form_data, coordinator_name=coord_name)
        except Exception as e:
            flash(f"Error saving application: {e}", "error")
            return redirect(url_for('application_form'))

        flash(f"Application saved successfully! Application No: {app_number}", "success")
        return render_template('form.html', app_number=app_number, student_name=student_name,
                               father_name=father_name, preferred_branch=preferred_branch)

    # GET: when opening the form
    view_app_number = request.args.get('view')
    if view_app_number:
        # View mode: just render form with this number. Frontend will fetch data.
        return render_template('form.html', app_number=view_app_number, view_mode=True, edit_mode=False)

    edit_app_number = request.args.get('edit')
    if edit_app_number:
        # Edit mode: render form with this number for editing. Frontend will fetch data.
        return render_template('form.html', app_number=edit_app_number, view_mode=False, edit_mode=True)

    try:
        # PReview next number but do not reserve
        preview_num = get_next_application_number_preview()
        return render_template('form.html', app_number=preview_num, view_mode=False)
    except Exception as e:
        flash(f"Error loading form: {e}", "error")
        return render_template('form.html', app_number="", view_mode=False)


@app.route('/delete_reserved_application', methods=['POST'])
def delete_reserved_application():
    data = request.get_json()
    appnum = data.get('application_number')
    if not appnum:
        return jsonify({'success': False, 'error': 'application_number required'}), 400

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("DELETE FROM applications WHERE application_number=%s AND status='reserved'", (appnum,))
        db.commit()
        return jsonify({'success': True, 'message': 'Reserved application deleted'}), 200
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500





@app.route('/view_confirm_application')
def view_confirm_application():
    """
    Render a read-only view of the confirm application form for a given app_no.
    If the application has form_data (i.e., it was submitted via the confirm form),
    it renders an in-line HTML page with all 7 pages of data pre-filled.
    Otherwise, it redirects to the normal form viewer.
    """
    if 'coordinator_id' not in session and 'admin_id' not in session:
        return redirect(url_for('coordinator_page'))

    app_no = request.args.get('app_no', '').strip()
    if not app_no:
        return "No application number specified.", 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT application_number, student_name, father_name, preferred_branch,
               mobile, address, status, form_data, date_submitted
        FROM applications WHERE application_number = %s
    """, (app_no,))
    row = cur.fetchone()

    if not row:
        return f"Application {app_no} not found.", 404

    # If no form_data or not a confirmed application, redirect to normal form viewer
    if row.get('status') != 'confirmed' or not row.get('form_data'):
        return redirect(url_for('application_form', view=app_no))

    try:
        form_data = json.loads(row['form_data']) if isinstance(row['form_data'], str) else row['form_data']
    except Exception:
        form_data = {}

    return render_template('view_confirm_form.html',
                           app_no=app_no,
                           form_data=form_data,
                           student_name=row.get('student_name', ''),
                           status=row.get('status', ''),
                           date_submitted=row.get('date_submitted', ''))






# ---------------- Search, Edit, Delete APIs ----------------

@app.route('/search_application', methods=['GET'])
def search_application():
    """
    Search by application_number (query param: application_number) and return JSON.
    """
    appnum = request.args.get('application_number', '').strip()
    if not appnum:
        return jsonify({"success": False, "error": "application_number query param required"}), 400

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT *
        FROM applications WHERE application_number = %s
    """, (appnum,))
    row = cur.fetchone()
    if not row:
        return jsonify({"success": True, "found": False, "data": None}), 200

    data = dict(row)
    # Parse form_data JSON if present
    if data.get('form_data'):
        try:
            data['form_data'] = json.loads(data['form_data'])
        except Exception:
            pass
    return jsonify({"success": True, "found": True, "data": data}), 200


@app.route('/edit_application', methods=['POST'])
def edit_application():
    """
    Edit an application. Expects JSON or form data including application_number and fields to update.
    Fields supported: student_name, father_name, preferred_branch, form_data
    """
    data = request.get_json() or request.form
    appnum = data.get('application_number')
    if not appnum:
        return jsonify({"success": False, "error": "application_number required"}), 400

    fields = {}
    if 'student_name' in data:
        fields['student_name'] = data.get('student_name')
    if 'father_name' in data:
        fields['father_name'] = data.get('father_name')
    if 'preferred_branch' in data:
        fields['preferred_branch'] = data.get('preferred_branch')
    if 'form_data' in data:
        # ensure JSON string
        try:
            fields['form_data'] = json.dumps(data.get('form_data')) if not isinstance(data.get('form_data'), str) else data.get('form_data')
        except Exception:
            fields['form_data'] = data.get('form_data')

    if not fields:
        return jsonify({"success": False, "error": "No updatable fields provided"}), 400

    # Build SET clause
    set_clause = ", ".join([f"{k} = %s" for k in fields.keys()])
    params = list(fields.values())
    params.append(datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(appnum)

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(f"UPDATE applications SET {set_clause}, last_modified = %s WHERE application_number = %s", params)
        db.commit()
        return jsonify({"success": True, "message": "Updated"}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------- New Admin APIs ----------------

@app.route('/api/admin/stats')
def admin_stats():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        
        # ---- Counters (year-aware, computed after req_year is resolved below) ----
        # Placeholder, will be computed after year parsing
        
        today = datetime.date.today()
        cur_year = today.year

        # ---- Find all years that have data in DB ----
        cur.execute("""
            SELECT DISTINCT SUBSTR(date_submitted, 1, 4) as yr
            FROM applications
            WHERE date_submitted IS NOT NULL AND date_submitted != '' AND LENGTH(date_submitted) >= 4
            ORDER BY yr
        """)
        db_years = []
        for r in cur.fetchall():
            val = r.get('yr')
            if val and str(val).isdigit():
                db_years.append(int(val))
        db_years = sorted(set(db_years))
        # Include 10 previous years + current + next 3 years for a full scrollable list
        fallback_years = list(range(cur_year - 10, cur_year + 4))
        db_years = sorted(set(db_years + fallback_years))

        # ---- Requested year (start year of academic year, default = current year) ----
        # 'all' means show all-time data (no year filter)
        year_param = request.args.get('year', '')
        show_all_years = (year_param == 'all' or year_param == '')
        if show_all_years:
            req_year = cur_year   # used for monthly chart labels
        else:
            try:
                req_year = int(year_param)
            except (ValueError, TypeError):
                req_year = cur_year
        all_year_labels = [str(y) for y in db_years]   # used for yearly bar chart

        month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

        # ---- Last 7 days labels ----
        weekly_labels = []
        for i in range(6, -1, -1):
            d = today - datetime.timedelta(days=i)
            weekly_labels.append(d.strftime("%a %d/%m"))

        # ---- Helper: weekly counts ----
        def get_weekly(where_clause):
            result = []
            for i in range(6, -1, -1):
                d = today - datetime.timedelta(days=i)
                d_str = d.strftime("%Y-%m-%d")
                cur.execute(f"""
                    SELECT COUNT(*) as c FROM applications
                    WHERE {where_clause}
                      AND SUBSTR(date_submitted, 1, 10) = %s
                """, (d_str,))
                row = cur.fetchone()
                result.append(row['c'] if row else 0)
            return result

        # ---- Helper: 12-month counts for a given calendar year ----
        def get_monthly(where_clause, year):
            cur.execute(f"""
                SELECT SUBSTR(date_submitted, 6, 2) as m_str, COUNT(*) as c
                FROM applications
                WHERE {where_clause}
                  AND SUBSTR(date_submitted, 1, 4) = %s
                GROUP BY m_str
            """, (str(year),))
            mm = {}
            for r in cur.fetchall():
                m_val = r.get('m_str')
                if m_val and str(m_val).isdigit():
                    mm[int(m_val)] = r['c']
            return [mm.get(i+1, 0) for i in range(12)]

        # ---- Helper: count per each known year (for yearly bar) ----
        def get_yearly(where_clause):
            totals = []
            for yr in db_years:
                cur.execute(f"""
                    SELECT COUNT(*) as c FROM applications
                    WHERE {where_clause}
                      AND SUBSTR(date_submitted, 1, 4) = %s
                """, (str(yr),))
                row = cur.fetchone()
                totals.append(row['c'] if row else 0)
            return totals

        # ---- Helper: dept breakdown, optionally filtered by year ----
        def get_dept(where_clause, year=None):
            if year:
                cur.execute(f"""
                    SELECT preferred_branch, COUNT(*) as c FROM applications
                    WHERE {where_clause}
                      AND SUBSTR(date_submitted, 1, 4) = %s
                    GROUP BY preferred_branch
                """, (str(year),))
            else:
                cur.execute(f"""
                    SELECT preferred_branch, COUNT(*) as c FROM applications
                    WHERE {where_clause} GROUP BY preferred_branch
                """)
            rows = cur.fetchall()
            return (
                [r['preferred_branch'] for r in rows if r.get('preferred_branch')],
                [r['c'] for r in rows if r.get('preferred_branch')]
            )

        # ====== Admissions (confirmed) ======
        adm_w = "status='confirmed'"
        adm_weekly   = get_weekly(adm_w)
        adm_monthly  = get_monthly(adm_w, req_year)   # 12 months of selected year
        adm_yearly   = get_yearly(adm_w)
        adm_dept_l, adm_dept_d = get_dept(adm_w, req_year if not show_all_years else None)

        # ====== Visited = ALL statuses ======
        vis_w = "status IN ('visited','confirmed','pending')"
        vis_weekly   = get_weekly(vis_w)
        vis_monthly  = get_monthly(vis_w, req_year)   # 12 months of selected year
        vis_yearly   = get_yearly(vis_w)
        vis_dept_l, vis_dept_d = get_dept(vis_w, req_year if not show_all_years else None)

        # ====== Year-filtered counters for the counter cards ======
        if show_all_years:
            cur.execute("SELECT COUNT(*) as c FROM applications WHERE status='confirmed'")
            admissions = cur.fetchone()['c']
            cur.execute("SELECT COUNT(*) as c FROM applications WHERE status IN ('visited', 'confirmed', 'pending')")
            enrollments = cur.fetchone()['c']
        else:
            cur.execute("""
                SELECT COUNT(*) as c FROM applications
                WHERE status='confirmed'
                  AND SUBSTR(date_submitted, 1, 4) = %s
            """, (str(req_year),))
            admissions = cur.fetchone()['c']
            cur.execute("""
                SELECT COUNT(*) as c FROM applications
                WHERE status IN ('visited', 'confirmed', 'pending')
                  AND SUBSTR(date_submitted, 1, 4) = %s
            """, (str(req_year),))
            enrollments = cur.fetchone()['c']

        return jsonify({
            "counters": {"admissions": admissions, "enrollments": enrollments},
            "meta": {
                "cur_year":  cur_year,
                "req_year":  req_year,
                "all_years": db_years       # list of ints e.g. [2024, 2025, 2026]
            },
            "admissions_charts": {
                "weekly":  {"labels": weekly_labels,   "data": adm_weekly},
                "monthly": {"labels": month_names,     "data": adm_monthly, "year": req_year},
                "yearly":  {"labels": all_year_labels, "data": adm_yearly},
                "dept":    {"labels": adm_dept_l,      "data": adm_dept_d}
            },
            "visited_charts": {
                "weekly":  {"labels": weekly_labels,   "data": vis_weekly},
                "monthly": {"labels": month_names,     "data": vis_monthly, "year": req_year},
                "yearly":  {"labels": all_year_labels, "data": vis_yearly},
                "dept":    {"labels": vis_dept_l,      "data": vis_dept_d}
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/admin/coordinators', methods=['GET', 'POST', 'DELETE'])
def admin_coordinators():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    
    if request.method == 'GET':
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id, first_name, last_name, email, phone, work, photo FROM coordinators")
        rows = cur.fetchall()
        result = []

        # Optional year filter from query param: ?year=2025 or ?year=all
        year_param = request.args.get('year', 'all')
        filter_year = None
        if year_param and year_param != 'all':
            try:
                filter_year = int(year_param)
            except (ValueError, TypeError):
                filter_year = None

        for r in rows:
            coord_name = f"{r['first_name']} {r['last_name']}"

            # Admissions count — filtered by year if requested
            if filter_year:
                cur.execute("""
                    SELECT COUNT(*) as c FROM applications
                    WHERE coordinator=%s AND status='confirmed'
                      AND SUBSTR(date_submitted, 1, 4) = %s
                """, (coord_name, str(filter_year)))
            else:
                cur.execute(
                    "SELECT COUNT(*) as c FROM applications WHERE coordinator=%s AND status='confirmed'",
                    (coord_name,)
                )
            count = cur.fetchone()['c']

            # Recent students (last 5) — filtered by year if requested
            if filter_year:
                cur.execute("""
                    SELECT student_name, application_number FROM applications
                    WHERE coordinator=%s AND status IN ('visited','confirmed')
                      AND SUBSTR(date_submitted, 1, 4) = %s
                    LIMIT 5
                """, (coord_name, str(filter_year)))
            else:
                cur.execute(
                    "SELECT student_name, application_number FROM applications WHERE coordinator=%s AND status IN ('visited','confirmed') LIMIT 5",
                    (coord_name,)
                )
            students = [{"name": s['student_name'], "appId": s['application_number']} for s in cur.fetchall()]

            photo_url = r['photo'] if r['photo'] else "https://via.placeholder.com/100"

            result.append({
                "id": r['id'],
                "username": coord_name,
                "email": r['email'],
                "photo": photo_url,
                "admissions": count,
                "students": students,
                "year": year_param   # echo back so frontend can display
            })
        return jsonify(result)

    if request.method == 'POST':
        data = request.get_json() or {}
        coord_email = (data.get('email') or '').strip()
        username = (data.get('username') or '').strip()
        password = str(data.get('password') or '').strip()

        if not coord_email or not username or not password:
            return jsonify({"error": "Email, Username, and Password are required."}), 400

        if not is_valid_email(coord_email):
            return jsonify({"error": f"Invalid email address: '{coord_email}'"}), 400

        try:
            cur = db.cursor(dictionary=True) if hasattr(db, 'cursor') else db.cursor()
            # Check for duplicate email before insert
            cur.execute("SELECT id, first_name, last_name FROM coordinators WHERE email = %s", (coord_email,))
            existing = cur.fetchone()
            if existing:
                return jsonify({
                    "error": f"A coordinator with email '{coord_email}' already exists in the system. Please use a different email or delete/edit the existing coordinator."
                }), 400

            # Split name safely
            parts = username.split(' ', 1)
            fname = parts[0]
            lname = parts[1] if len(parts) > 1 else ''
            
            cur.execute("INSERT INTO coordinators (first_name, last_name, email, phone, password, work) VALUES (%s, %s, %s, %s, %s, %s)",
                       (fname, lname, coord_email, '0000000000', password, ''))
            db.commit()

            # Dynamic welcome credentials email to coordinator
            login_url = request.host_url.rstrip('/') + url_for('coordinator_page')
            mail_ok, mail_err = send_coordinator_credentials_email(
                coord_email=coord_email,
                username=username,
                password=password,
                login_url=login_url
            )

            if mail_ok:
                return jsonify({
                    "success": True,
                    "email_sent": True,
                    "message": f"Coordinator '{username}' created successfully! Credentials emailed to {coord_email}."
                })
            else:
                return jsonify({
                    "success": True,
                    "email_sent": False,
                    "warning": f"Coordinator created successfully, but credentials email could not be delivered: {mail_err}"
                })
        except Exception as e:
            try:
                db.rollback()
            except Exception:
                pass
            err_msg = str(e)
            if 'Duplicate entry' in err_msg or 'UNIQUE' in err_msg.upper():
                return jsonify({
                    "error": f"A coordinator with email '{coord_email}' already exists. Please use a different email."
                }), 400
            return jsonify({"error": err_msg}), 400

    if request.method == 'DELETE':
        cid = request.args.get('id')
        if not cid:
            return jsonify({"error": "Coordinator ID required"}), 400

        cur = db.cursor(dictionary=True, buffered=True)
        try:
            # 1. Fetch coordinator details
            cur.execute("SELECT id, first_name, last_name, email, photo FROM coordinators WHERE id=%s", (cid,))
            coord = cur.fetchone()
            if not coord:
                return jsonify({"error": "Coordinator not found"}), 404

            fname = (coord.get('first_name') or '').strip()
            lname = (coord.get('last_name') or '').strip()
            full_name = f"{fname} {lname}".strip()
            email = (coord.get('email') or '').strip()

            # 2. Find all applications associated with this coordinator
            cur.execute("""
                SELECT id, application_number, form_data, coordinator FROM applications
                WHERE TRIM(coordinator) = %s OR coordinator = %s OR coordinator = %s OR coordinator = %s
            """, (full_name, f"{fname} {lname}", fname, email))
            apps = cur.fetchall()

            # 3. Clean up associated uploaded files on disk for each application
            for app_row in apps:
                form_raw = app_row.get('form_data')
                if form_raw:
                    try:
                        f_data = json.loads(form_raw) if isinstance(form_raw, str) else form_raw
                        if isinstance(f_data, dict):
                            for v in f_data.values():
                                if isinstance(v, str) and ('/static/uploads/' in v or 'static/uploads/' in v):
                                    # Extract relative static path
                                    rel_path = v[v.find('static/uploads/'):]
                                    abs_file_path = os.path.join(app.root_path, rel_path)
                                    if os.path.isfile(abs_file_path):
                                        try:
                                            os.remove(abs_file_path)
                                        except Exception:
                                            pass
                    except Exception:
                        pass

            # 4. Clean up coordinator's custom profile photo if present
            c_photo = coord.get('photo')
            if c_photo and ('/static/uploads/' in c_photo or 'static/uploads/' in c_photo):
                rel_p = c_photo[c_photo.find('static/uploads/'):]
                abs_p = os.path.join(app.root_path, rel_p)
                if os.path.isfile(abs_p):
                    try:
                        os.remove(abs_p)
                    except Exception:
                        pass

            # 5. Delete application records and coordinator in transaction
            try:
                db.start_transaction()
            except Exception:
                pass

            cur.execute("""
                DELETE FROM applications
                WHERE TRIM(coordinator) = %s OR coordinator = %s OR coordinator = %s OR coordinator = %s
            """, (full_name, f"{fname} {lname}", fname, email))

            cur.execute("DELETE FROM coordinators WHERE id=%s", (cid,))
            db.commit()
            return jsonify({"success": True, "message": "Coordinator and all associated applications deleted."})

        except Exception as e:
            db.rollback()
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

@app.route('/api/admin/feedback', methods=['GET', 'POST'])
def admin_feedback():
    if 'admin_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    db = get_db()
    
    if request.method == 'GET':
        cur = db.cursor(dictionary=True)
        # Fetching basic application data + columns for feedback
        cur.execute("SELECT * FROM applications WHERE status IN ('visited', 'confirmed')")
        rows = cur.fetchall()
        data = []
        for r in rows:
            form_json = {}
            if r['form_data']:
                try: form_json = json.loads(r['form_data'])
                except: pass
            
            # Prioritize dedicated columns, fallback to form_data or empty
            fb = r.get('feedback')
            if not fb:
                fb = form_json.get('feedback', '')

            nv = r.get('next_visit')
            if not nv:
                nv = form_json.get('next_visit', '')

            data.append({
                "appNo": r['application_number'],
                "student": r['student_name'],
                "father_name": r.get('father_name') or form_json.get('father_name', ''),
                "coordinator": r['coordinator'],
                "mobile": r['mobile'],
                "address": r['address'],
                "preferred_branch": r['preferred_branch'],
                "feedback": fb, 
                "next_visit": nv,
                "date_submitted": r.get('date_submitted') or '',
                "status": r.get('status') or '',
                "form_data": form_json
            })
        return jsonify(data)
    
    if request.method == 'POST': 
        return jsonify({"error": "Use /edit_application for updates"}), 400

@app.route('/api/admin/work-log')
def admin_work_log():
    # Return simple work log data
    # Real implementation would need a separate 'logs' table.
    # We will return mock data or query recent applications by date.
    if 'admin_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    cur = db.cursor(dictionary=True)
    
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    
    cur.execute("SELECT coordinator, application_number, student_name, preferred_branch, status FROM applications WHERE DATE(date_submitted) = %s", (today,))
    today_rows = [{"coordinator": r['coordinator'], "appId": r['application_number'], "student": r['student_name'], "branch": r['preferred_branch'], "status": r['status']} for r in cur.fetchall()]
    
    cur.execute("SELECT coordinator, application_number, student_name, preferred_branch, status FROM applications WHERE DATE(date_submitted) = %s", (yesterday,))
    yesterday_rows = [{"coordinator": r['coordinator'], "appId": r['application_number'], "student": r['student_name'], "branch": r['preferred_branch'], "status": r['status']} for r in cur.fetchall()]
    
    return jsonify({"today": today_rows, "yesterday": yesterday_rows})






@app.route("/check_data")
def check_data():
    start = request.args.get("start_date")
    end = request.args.get("end_date")
    search = request.args.get("search") or request.args.get("term")
    
    if not start and not end:
        return jsonify({"error": "Start and end dates required"}), 400

    try:
        db = get_db()
        cur = db.cursor(dictionary=True)
        # If coordinator is logged in, count matching applications for coordinator
        if 'coordinator_id' in session:
            coord_name = session.get('coordinator_name', '').strip()
            apps = fetch_coordinator_applications_records(cur, coord_name)
            status_filter = request.args.get('status') or request.args.get('status_filter') or 'all'
            filtered = filter_coordinator_applications(apps, start_date=start, end_date=end, search=search, status_filter=status_filter)
            return jsonify({"count": len(filtered)})
        else:
            # Fallback to existing admin count logic
            query = "SELECT COUNT(*) as count FROM applications WHERE 1=1"
            params = []
            if start:
                query += " AND date_submitted >= %s"
                params.append(start + " 00:00:00")
            if end:
                query += " AND date_submitted <= %s"
                params.append(end + " 23:59:59")
            cur.execute(query, tuple(params))
            row = cur.fetchone()
            count = row['count'] if row else 0
            return jsonify({"count": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/download_excel', methods=['GET'])
def download_excel():
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    chart = request.args.get('chart', '0')
    branch = request.args.get('branch', '')
    status = request.args.get('status', '')
    search = request.args.get('search') or request.args.get('term')

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Coordinator applications export
    if 'coordinator_id' in session:
        coord_name = session.get('coordinator_name', '').strip()
        apps = fetch_coordinator_applications_records(cur, coord_name)
        status_filter = request.args.get('status') or request.args.get('status_filter') or 'all'
        filtered = filter_coordinator_applications(apps, start_date=start, end_date=end, search=search, status_filter=status_filter)

        if not filtered:
            return "No applications found for the selected dates.", 404

        import openpyxl
        from io import BytesIO
        from openpyxl.chart import PieChart, Reference

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Applications Details"

        headers = ["Application No", "Student Name", "Father Name", "Department", "Mobile", "Address", "Date Submitted", "Next College Visit", "Status"]
        ws.append(headers)

        dept_count = {}
        for rdict in filtered:
            ws.append([
                rdict.get('application_number') or '',
                rdict.get('student_name') or '',
                rdict.get('father_name') or '',
                rdict.get('preferred_branch') or '',
                rdict.get('mobile') or '',
                rdict.get('address') or '',
                rdict.get('date_submitted') or '',
                rdict.get('next_visit') or '-',
                rdict.get('status') or 'visited'
            ])
            dept = rdict.get('preferred_branch')
            if dept:
                dept_count[dept] = dept_count.get(dept, 0) + 1

        if chart in ['1', 'true', True] and dept_count:
            ws_chart = wb.create_sheet(title="Department Pie Chart")
            ws_chart.append(["Department", "Count"])
            for dept, count in dept_count.items():
                ws_chart.append([dept, count])
            pie = PieChart()
            data = Reference(ws_chart, min_col=2, min_row=1, max_row=len(dept_count)+1)
            labels = Reference(ws_chart, min_col=1, min_row=2, max_row=len(dept_count)+1)
            pie.add_data(data, titles_from_data=True)
            pie.set_categories(labels)
            pie.title = "Applications by Department"
            ws_chart.add_chart(pie, "E5")

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        from flask import send_file
        filename = f"applications_report_{start or 'all'}_{end or 'all'}.xlsx"
        return send_file(buf, as_attachment=True, download_name=filename,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # Admin export (existing behavior)
    query = "SELECT * FROM applications WHERE 1=1"
    params = []
    if start:
        query += " AND date_submitted >= %s"
        params.append(start + " 00:00:00")
    if end:
        query += " AND date_submitted <= %s"
        params.append(end + " 23:59:59")
    if branch:
        query += " AND preferred_branch = %s"
        params.append(branch)
    if status:
        query += " AND status = %s"
        params.append(status)
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    if not rows:
        return "No data found for the selected dates.", 404

    import openpyxl
    from io import BytesIO
    from openpyxl.chart import PieChart, Reference

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Applications"

    headers = ["Application No", "Student Name", "Father Name", "Mobile", "Address", "Department", "Form Data", "Date Submitted"]
    ws.append(headers)

    dept_count = {}
    for r in rows:
        rdict = dict(r)
        form_json = rdict.get('form_data') or ''
        ws.append([
            rdict.get('application_number'),
            rdict.get('student_name'),
            rdict.get('father_name'),
            rdict.get('mobile'),
            rdict.get('address'),
            rdict.get('preferred_branch'),
            form_json,
            rdict.get('date_submitted')
        ])
        dept = rdict.get('preferred_branch')
        if dept:
            dept_count[dept] = dept_count.get(dept, 0) + 1

    if chart in ['1', 'true', True] and dept_count:
        ws_chart = wb.create_sheet(title="Department Pie Chart")
        ws_chart.append(["Department", "Count"])
        for dept, count in dept_count.items():
            ws_chart.append([dept, count])
        pie = PieChart()
        data = Reference(ws_chart, min_col=2, min_row=1, max_row=len(dept_count)+1)
        labels = Reference(ws_chart, min_col=1, min_row=2, max_row=len(dept_count)+1)
        pie.add_data(data, titles_from_data=True)
        pie.set_categories(labels)
        pie.title = "Students by Department"
        ws_chart.add_chart(pie, "E5")

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    from flask import send_file
    return send_file(buf, as_attachment=True, download_name=f"applications_{start}_{end}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def generate_application_form_pdf(app_no):
    import base64
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM applications WHERE application_number = %s", (app_no,))
    row = cur.fetchone()
    if not row:
        return None, f"Application {app_no} not found"

    f_data = {}
    if row.get('form_data'):
        try:
            f_data = json.loads(row['form_data']) if isinstance(row['form_data'], str) else row['form_data']
        except Exception:
            f_data = {}

    def get_v(keys, fallback='-'):
        if isinstance(keys, str):
            keys = [keys]
        for k in keys:
            val = f_data.get(k) or row.get(k)
            if val:
                return str(val)
        return fallback

    def get_chk(keys):
        if isinstance(keys, str):
            keys = [keys]
        for k in keys:
            v = f_data.get(k)
            if v in ['true', 'on', 'yes', 'YES', True, 1, '1']:
                return '[X]'
        return '[ ]'

    def get_rv(group_key, fallbacks=[], default='-'):
        v = f_data.get(group_key)
        if v and v not in ['false', 'off', False, 0, '0']:
            return str(v).upper()
        for fb in fallbacks:
            val = f_data.get(fb)
            if val in ['true', 'on', 'yes', 'YES', True, 1, '1']:
                return fb.replace(group_key + '_', '').replace('_', ' ').upper()
            elif val and val not in ['false', 'off', False, 0, '0']:
                return str(val).upper()
        return default

    def get_rl_image(keys, width=80, height=80):
        if isinstance(keys, str):
            keys = [keys]
        img_str = ''
        for k in keys:
            if f_data.get(k):
                img_str = f_data.get(k)
                break
        if not img_str or not isinstance(img_str, str):
            return None
        try:
            if img_str.startswith('data:image'):
                header, encoded = img_str.split(',', 1)
                data = base64.b64decode(encoded)
                buf = BytesIO(data)
                return RLImage(buf, width=width, height=height)
            else:
                clean_str = img_str.replace('\\', '/')
                if 'static/' in clean_str:
                    rel_path = clean_str[clean_str.find('static/'):]
                else:
                    rel_path = clean_str
                abs_path = os.path.normpath(os.path.join(app.root_path, rel_path.lstrip('/')))
                if not os.path.isfile(abs_path) and os.path.isfile(img_str):
                    abs_path = img_str
                if os.path.isfile(abs_path):
                    try:
                        with open(abs_path, 'rb') as fp:
                            img_bytes = fp.read()
                        buf = BytesIO(img_bytes)
                        return RLImage(buf, width=width, height=height)
                    except Exception as img_err:
                        print("Invalid image file load:", abs_path, img_err)
                        return None
        except Exception as e:
            print("PDF Image load error:", e)
        return None

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=25, rightMargin=25, topMargin=25, bottomMargin=25)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=13, leading=15, alignment=1, textColor=colors.HexColor('#000000'))
    sub_style = ParagraphStyle('DocSub', parent=styles['Normal'], fontSize=8.5, leading=10.5, alignment=1)
    h2_style = ParagraphStyle('DocH2', parent=styles['Heading2'], fontSize=10, leading=12, alignment=1, textColor=colors.HexColor('#1565c0'), spaceBefore=8, spaceAfter=4)
    h3_style = ParagraphStyle('DocH3', parent=styles['Heading3'], fontSize=9, leading=11, textColor=colors.HexColor('#000000'), spaceBefore=6, spaceAfter=2)
    norm = ParagraphStyle('Norm', parent=styles['Normal'], fontSize=8, leading=10)
    bold = ParagraphStyle('Bld', parent=styles['Normal'], fontSize=8, leading=10, fontName='Helvetica-Bold')

    story = []

    # Page 1 Header
    logo_img = get_rl_image(['logo', 'college_logo'], width=50, height=50)
    if not logo_img:
        for cand in ['PEC Logo.png', 'pec_logo.png', 'logo.png', 'logo.jpg']:
            logo_path = os.path.join(app.root_path, 'static', cand)
            if os.path.isfile(logo_path):
                try:
                    logo_img = RLImage(logo_path, width=50, height=50)
                    break
                except Exception:
                    pass

    header_text = [
        Paragraph("<b>PRATHYUSHA ENGINEERING COLLEGE</b>", title_style),
        Paragraph("<b>AN AUTONOMOUS INSTITUTION</b> | TIRUVALLUR-602 025", sub_style),
        Paragraph("<b>APPLICATION FORM</b> &mdash; FIRST YEAR &amp; LATERAL ENTRY B.E/B.TECH", sub_style)
    ]

    student_photo = get_rl_image(['photoInput', 'student_photo', 'photo', 'photoPreview'], width=75, height=90)
    photo_cell = student_photo if student_photo else Paragraph("<font size=7 color='#777'>[Photo Here]</font>", sub_style)

    hdr_table = Table([
        [logo_img if logo_img else '', header_text, photo_cell]
    ], colWidths=[65, 380, 85])
    hdr_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (0,0), 'CENTER'),
        ('ALIGN', (2,0), (2,0), 'CENTER'),
        ('BOX', (2,0), (2,0), 1, colors.black),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 8))

    # App No & Branch Table
    branch_str = f"{get_chk('prog_CSE')} CSE  {get_chk('prog_ECE')} ECE  {get_chk('prog_AIDS')} AI&DS  {get_chk('prog_CSBS')} CSBS  {get_chk('prog_MECH')} MECH  {get_chk('prog_CIVIL')} CIVIL"
    app_info_table = Table([
        [Paragraph(f"<b>Application No:</b> {app_no}", norm), Paragraph(f"<b>Branch:</b> {branch_str}", norm)]
    ], colWidths=[200, 330])
    app_info_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(app_info_table)
    story.append(Spacer(1, 6))

    # 1. Student Name & Parent Details
    story.append(Paragraph(f"<b>1. Student Name:</b> {get_v(['student_name', 'candName'])}", h3_style))
    story.append(Paragraph("<b>2(a). Parent Details</b>", h3_style))
    parent_table = Table([
        [Paragraph("", bold), Paragraph("<b>Father</b>", bold), Paragraph("<b>Mother</b>", bold)],
        [Paragraph("<b>Name</b>", norm), Paragraph(get_v('father_name'), norm), Paragraph(get_v('mother_name'), norm)],
        [Paragraph("<b>Qualification</b>", norm), Paragraph(get_v('father_qual'), norm), Paragraph(get_v('mother_qual'), norm)],
        [Paragraph("<b>Occupation</b>", norm), Paragraph(get_v('father_occupation'), norm), Paragraph(get_v('mother_occupation'), norm)],
        [Paragraph("<b>Income</b>", norm), Paragraph(get_v('father_income'), norm), Paragraph(get_v('mother_income'), norm)],
        [Paragraph("<b>Mobile</b>", norm), Paragraph(get_v('father_mobile'), norm), Paragraph(get_v('mother_mobile'), norm)],
        [Paragraph("<b>Email</b>", norm), Paragraph(get_v('father_email'), norm), Paragraph(get_v('mother_email'), norm)],
    ], colWidths=[90, 220, 220])
    parent_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(parent_table)
    story.append(Spacer(1, 6))

    # 2(b). Guardian Details
    story.append(Paragraph("<b>2(b). Guardian Details</b>", h3_style))
    guard_table = Table([
        [Paragraph("<b>Name</b>", norm), Paragraph(get_v('guardian_name'), norm), Paragraph("<b>Qualification</b>", norm), Paragraph(get_v('guardian_qual'), norm)],
        [Paragraph("<b>Occupation</b>", norm), Paragraph(get_v('guardian_occ'), norm), Paragraph("<b>Mobile</b>", norm), Paragraph(get_v('guardian_mobile'), norm)],
    ], colWidths=[90, 175, 90, 175])
    guard_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(guard_table)
    story.append(Spacer(1, 6))

    # 3. Address Table
    story.append(Paragraph("<b>3. Address Details</b>", h3_style))
    addr_table = Table([
        [Paragraph("<b>Details</b>", bold), Paragraph("<b>Present</b>", bold), Paragraph("<b>Permanent</b>", bold)],
        [Paragraph("<b>Door No.</b>", norm), Paragraph(get_v('addr_door_p'), norm), Paragraph(get_v('addr_door_perm'), norm)],
        [Paragraph("<b>Street</b>", norm), Paragraph(get_v(['address', 'addr_street']), norm), Paragraph(get_v('addr_street_perm'), norm)],
        [Paragraph("<b>Place</b>", norm), Paragraph(get_v('addr_place_p'), norm), Paragraph(get_v('addr_place_perm'), norm)],
        [Paragraph("<b>Taluk</b>", norm), Paragraph(get_v('addr_taluk_p'), norm), Paragraph(get_v('addr_taluk_perm'), norm)],
        [Paragraph("<b>District</b>", norm), Paragraph(get_v('addr_dist_p'), norm), Paragraph(get_v('addr_dist_perm'), norm)],
        [Paragraph("<b>Pin Code</b>", norm), Paragraph(get_v('addr_pin_p'), norm), Paragraph(get_v('addr_pin_perm'), norm)],
        [Paragraph("<b>State</b>", norm), Paragraph(get_v('addr_state_p'), norm), Paragraph(get_v('addr_state_perm'), norm)],
        [Paragraph("<b>Phone</b>", norm), Paragraph(get_v('addr_mob_p'), norm), Paragraph(get_v('addr_mob_perm'), norm)],
    ], colWidths=[90, 220, 220])
    addr_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(addr_table)
    story.append(Spacer(1, 6))

    # Student Details Items 4-19
    pass_validity = f"{get_v('passport_no')} (Valid: {get_v('passport_from')} to {get_v('passport_to')})" if get_v('passport_from') != '-' else get_v('passport_no')
    story.append(Paragraph("<b>Student Personal Details (Items 4-19)</b>", h3_style))
    stud_det = Table([
        [Paragraph("<b>Gender:</b>", norm), Paragraph(get_rv('gender', ['gender_male', 'gender_female', 'gender_other']), norm), Paragraph("<b>DOB:</b>", norm), Paragraph(get_v(['dob_input', 'dob', 'candDob']), norm)],
        [Paragraph("<b>Email:</b>", norm), Paragraph(get_v(['email', 'father_email']), norm), Paragraph("<b>Mobile:</b>", norm), Paragraph(get_v(['mobile', 'father_mobile', 'mobileNo']), norm)],
        [Paragraph("<b>Place of Birth:</b>", norm), Paragraph(get_v('place_of_birth'), norm), Paragraph("<b>Blood Group:</b>", norm), Paragraph(get_v('blood_group'), norm)],
        [Paragraph("<b>Mother Tongue:</b>", norm), Paragraph(get_v('mother_tongue'), norm), Paragraph("<b>Civic Status:</b>", norm), Paragraph(get_rv('civic', ['civic_corporation', 'civic_municipality', 'civic_township', 'civic_panchayat']), norm)],
        [Paragraph("<b>Aadhar No:</b>", norm), Paragraph(get_v('aadhar_no'), norm), Paragraph("<b>Citizenship:</b>", norm), Paragraph(get_rv('citizenship', ['citizenship_indian', 'citizenship_other']), norm)],
        [Paragraph("<b>Passport Details:</b>", norm), Paragraph(pass_validity, norm), Paragraph("<b>Religion:</b>", norm), Paragraph(get_v('religion'), norm)],
        [Paragraph("<b>Caste:</b>", norm), Paragraph(get_v('caste_name'), norm), Paragraph("<b>Appearances:</b>", norm), Paragraph(get_rv('appearances', ['appearances_one', 'appearances_two']), norm)],
        [Paragraph("<b>TNEA Rank:</b>", norm), Paragraph(get_v('tnea_ranking'), norm), Paragraph("<b>Consortium Rank:</b>", norm), Paragraph(get_v('consortium_ranking'), norm)],
        [Paragraph("<b>Hosteller/Day:</b>", norm), Paragraph(get_rv('hosteller', ['hosteller_hosteller', 'hosteller_dayscholar']), norm), Paragraph("<b>Food:</b>", norm), Paragraph(get_rv('food', ['food_veg', 'food_nonveg']), norm)],
        [Paragraph("<b>Boarding Point:</b>", norm), Paragraph(get_v('boarding_point'), norm), Paragraph("<b>Admission Quota:</b>", norm), Paragraph(get_rv('admission', ['admission_govt', 'admission_management']), norm)],
    ], colWidths=[90, 175, 90, 175])
    stud_det.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(stud_det)
    story.append(Spacer(1, 6))

    extra_str = f"<b>Extra Curricular:</b> {get_chk('activity_sports')} Sports  {get_chk('activity_irc')} IRC  {get_chk('activity_ncc')} NCC  {get_chk('activity_nss')} NSS  {get_chk('activity_dance')} Dance  {get_chk('activity_finearts')} Fine Arts"
    story.append(Paragraph(extra_str, norm))
    govt_str = f"<b>Govt Category:</b> {get_chk('govt_category_sports')} Sports  {get_chk('govt_category_exservicemen')} Ex-Servicemen  {get_chk('govt_category_freedomfighter')} Freedom Fighter  {get_chk('govt_category_physicallychallenged')} Physically Challenged  {get_chk('govt_category_community')} Community  {get_chk('govt_category_opencategory')} Open  {get_chk('govt_category_7_5_quota')} 7.5% Quota"
    story.append(Paragraph(govt_str, norm))
    story.append(PageBreak())

    # PAGE 2: Academic Details
    story.append(Paragraph("<b>PAGE 2: ACADEMIC DETAILS & MARKS</b>", h2_style))
    story.append(Paragraph("<b>20(a). School of Study</b>", h3_style))
    school_table = Table([
        [Paragraph("<b>Class</b>", bold), Paragraph("<b>Reg No</b>", bold), Paragraph("<b>Year</b>", bold), Paragraph("<b>Medium</b>", bold), Paragraph("<b>School</b>", bold), Paragraph("<b>City</b>", bold), Paragraph("<b>State</b>", bold), Paragraph("<b>App</b>", bold), Paragraph("<b>Marks%</b>", bold)],
        [Paragraph("X Std", norm), Paragraph(get_v('p2_x_regno'), norm), Paragraph(get_v('p2_x_year'), norm), Paragraph(get_v('p2_x_medium'), norm), Paragraph(get_v('p2_x_school'), norm), Paragraph(get_v('p2_x_city'), norm), Paragraph(get_v('p2_x_state'), norm), Paragraph(get_v('p2_x_appear'), norm), Paragraph(get_v('p2_x_marks'), norm)],
        [Paragraph("HSC", norm), Paragraph(get_v('p2_hsc_regno'), norm), Paragraph(get_v('p2_hsc_year'), norm), Paragraph(get_v('p2_hsc_medium'), norm), Paragraph(get_v('p2_hsc_school'), norm), Paragraph(get_v('p2_hsc_city'), norm), Paragraph(get_v('p2_hsc_state'), norm), Paragraph(get_v('p2_hsc_appear'), norm), Paragraph(get_v('p2_hsc_marks'), norm)],
        [Paragraph("Diploma", norm), Paragraph(get_v('p2_dip_regno'), norm), Paragraph(get_v('p2_dip_year'), norm), Paragraph(get_v('p2_dip_medium'), norm), Paragraph(get_v('p2_dip_school'), norm), Paragraph(get_v('p2_dip_city'), norm), Paragraph(get_v('p2_dip_state'), norm), Paragraph(get_v('p2_dip_appear'), norm), Paragraph(get_v('p2_dip_marks'), norm)],
    ], colWidths=[55, 60, 45, 55, 120, 60, 55, 35, 45])
    school_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(school_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>20(b). HSC Academic Marks</b>", h3_style))
    hsc_table = Table([
        [Paragraph("<b>Subject</b>", bold), Paragraph("<b>Month &amp; Year</b>", bold), Paragraph("<b>Max Marks</b>", bold), Paragraph("<b>Obtained</b>", bold)],
        [Paragraph("Physics", norm), Paragraph(get_v('p2_phy_month'), norm), Paragraph(get_v('p2_phy_max'), norm), Paragraph(get_v('p2_phy_obt'), norm)],
        [Paragraph("Chemistry", norm), Paragraph(get_v('p2_chem_month'), norm), Paragraph(get_v('p2_chem_max'), norm), Paragraph(get_v('p2_chem_obt'), norm)],
        [Paragraph("Mathematics", norm), Paragraph(get_v('p2_math_month'), norm), Paragraph(get_v('p2_math_max'), norm), Paragraph(get_v('p2_math_obt'), norm)],
        [Paragraph("<b>Total Cutoff</b>", bold), Paragraph("", norm), Paragraph("", norm), Paragraph(f"<b>{get_v(['p2_acad_total_cutoff', 'p2_acad_cutoff'])}</b>", bold)],
    ], colWidths=[150, 130, 120, 130])
    hsc_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(hsc_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>20(c). HSC Vocational Marks</b>", h3_style))
    voc_table = Table([
        [Paragraph("<b>Subject</b>", bold), Paragraph("<b>Month &amp; Year</b>", bold), Paragraph("<b>Max Marks</b>", bold), Paragraph("<b>Obtained</b>", bold)],
        [Paragraph("Related Subjects I", norm), Paragraph(get_v('p2_voc_rs1_month'), norm), Paragraph(get_v('p2_voc_rs1_max'), norm), Paragraph(get_v('p2_voc_rs1_obt'), norm)],
        [Paragraph("Related Subjects II", norm), Paragraph(get_v('p2_voc_rs2_month'), norm), Paragraph(get_v('p2_voc_rs2_max'), norm), Paragraph(get_v('p2_voc_rs2_obt'), norm)],
        [Paragraph("Vocational Theory", norm), Paragraph(get_v('p2_voc_theory_month'), norm), Paragraph(get_v('p2_voc_theory_max'), norm), Paragraph(get_v('p2_voc_theory_obt'), norm)],
        [Paragraph("Practical I", norm), Paragraph(get_v('p2_voc_p1_month'), norm), Paragraph(get_v('p2_voc_p1_max'), norm), Paragraph(get_v('p2_voc_p1_obt'), norm)],
        [Paragraph("Practical II", norm), Paragraph(get_v('p2_voc_p2_month'), norm), Paragraph(get_v('p2_voc_p2_max'), norm), Paragraph(get_v('p2_voc_p2_obt'), norm)],
        [Paragraph("<b>Total Cutoff</b>", bold), Paragraph("", norm), Paragraph("", norm), Paragraph(f"<b>{get_v(['p2_voc_total_cutoff', 'p2_voc_cutoff'])}</b>", bold)],
    ], colWidths=[150, 130, 120, 130])
    voc_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(voc_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>20(d). Diploma Lateral Entry Marks</b>", h3_style))
    le_rows = [[Paragraph("<b>Sem</b>", bold), Paragraph("<b>Month &amp; Year</b>", bold), Paragraph("<b>Max</b>", bold), Paragraph("<b>Obtained</b>", bold), Paragraph("<b>%</b>", bold)]]
    for s in ['1','2','3','4','5','6']:
        le_rows.append([Paragraph(f"Sem {s}", norm), Paragraph(get_v(f'p2_le_s{s}_month'), norm), Paragraph(get_v(f'p2_le_s{s}_max'), norm), Paragraph(get_v(f'p2_le_s{s}_obt'), norm), Paragraph(get_v(f'p2_le_s{s}_pct'), norm)])
    le_rows.append([Paragraph("<b>Total %</b>", bold), Paragraph("", norm), Paragraph("", norm), Paragraph("", norm), Paragraph(f"<b>{get_v('p2_le_total_pct')}</b>", bold)])
    le_table = Table(le_rows, colWidths=[70, 140, 110, 110, 100])
    le_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(le_table)
    story.append(PageBreak())

    # PAGE 3: Scholarship, Contact Photos & Office Use
    story.append(Paragraph("<b>PAGE 3: SCHOLARSHIP & OFFICE USE</b>", h2_style))
    story.append(Paragraph("<b>21. Scholarship Details</b>", h3_style))
    sch_table = Table([
        [Paragraph("<b>Scholarship Name</b>", bold), Paragraph("<b>Yes/No</b>", bold), Paragraph("<b>Eligibility</b>", bold), Paragraph("<b>Income Limit</b>", bold)],
        [Paragraph("First Generation Graduate", norm), Paragraph(get_rv('first_graduate', ['first_graduate_yes', 'first_graduate_no']), norm), Paragraph(get_v('first_graduate_eligibility', 'e-Certificate only'), norm), Paragraph("Not Applicable", norm)],
        [Paragraph("General Scholarship", norm), Paragraph(get_rv('general_scholarship', ['general_sch_yes', 'general_sch_no']), norm), Paragraph("BC/MBC/SC/ST", norm), Paragraph("2.5 Lakh/PA", norm)],
        [Paragraph("Post Matric Scholarship", norm), Paragraph(get_rv('scholarship', ['scholarship_yes', 'scholarship_no']), norm), Paragraph("SC/ST/SCA/SCC", norm), Paragraph("2.5 Lakh/PA", norm)],
    ], colWidths=[180, 80, 140, 130])
    sch_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(sch_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>22. Local Guardian Name:</b> {get_v('local_guardian_name')}", h3_style))
    story.append(Spacer(1, 4))

    # Photos Section
    f_photo = get_rl_image(['father_photo', 'fatherPreview'], width=60, height=60)
    m_photo = get_rl_image(['mother_photo', 'motherPreview'], width=60, height=60)
    g_photo = get_rl_image(['guardian_photo', 'guardianPreview'], width=60, height=60)

    photos_table = Table([
        [Paragraph("<b>Father Phone &amp; Photo</b>", bold), Paragraph("<b>Mother Phone &amp; Photo</b>", bold), Paragraph("<b>Guardian Phone &amp; Photo</b>", bold)],
        [Paragraph(get_v('father_photo_phone'), norm), Paragraph(get_v('mother_photo_phone'), norm), Paragraph(get_v('guardian_photo_phone'), norm)],
        [f_photo if f_photo else Paragraph("(No Photo)", norm), m_photo if m_photo else Paragraph("(No Photo)", norm), g_photo if g_photo else Paragraph("(No Photo)", norm)]
    ], colWidths=[175, 175, 180])
    photos_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('ALIGN', (0,2), (-1,2), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(photos_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>FOR OFFICE USE ONLY</b>", h3_style))
    off_table = Table([
        [Paragraph("<b>Admission No:</b>", norm), Paragraph(get_v('office_admission_no'), norm), Paragraph("<b>Course Allotted:</b>", norm), Paragraph(get_v('office_course_allotted'), norm)],
        [Paragraph("<b>Stay:</b>", norm), Paragraph(get_rv('stay', ['stay_hostel', 'stay_dayscholar']), norm), Paragraph("<b>Confirmation:</b>", norm), Paragraph(get_rv('office_confirm', ['office_confirm_admitted', 'office_confirm_not_admitted']), norm)],
    ], colWidths=[100, 165, 100, 165])
    off_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(off_table)
    story.append(Spacer(1, 6))

    off_sch_table = Table([
        [Paragraph("<b>Scholarship Name</b>", bold), Paragraph("<b>Caste</b>", bold), Paragraph("<b>Income</b>", bold), Paragraph("<b>Eligible Status</b>", bold)],
        [Paragraph("First Generation Graduate", norm), Paragraph(get_v('office_sch1_caste'), norm), Paragraph(get_v('office_sch1_income'), norm), Paragraph(get_v('office_sch1_eligible'), norm)],
        [Paragraph("Post Matric Scholarship", norm), Paragraph(get_v('office_sch2_caste'), norm), Paragraph(get_v('office_sch2_income'), norm), Paragraph(get_v('office_sch2_eligible'), norm)],
        [Paragraph("General Scholarship", norm), Paragraph(get_v('office_sch3_caste'), norm), Paragraph(get_v('office_sch3_income'), norm), Paragraph(get_v('office_sch3_eligible'), norm)],
    ], colWidths=[150, 120, 120, 140])
    off_sch_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f2f2f2')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(off_sch_table)
    story.append(Spacer(1, 10))

    off_sig = get_rl_image(['office_verified_sign', 'accountsSign', 'admissionSign'], width=100, height=45)
    prin_sig = get_rl_image(['principal_sign', 'signPreview'], width=100, height=45)
    app_sig = get_rl_image(['signFileApplicant', 'signaturePreviewApplicant', 'applicant-sign'], width=100, height=45)
    par_sig = get_rl_image(['signFileParent', 'signaturePreviewParent', 'parent-sign'], width=100, height=45)

    off_sig_table = Table([
        [Paragraph("<b>Verified By</b>", norm), Paragraph("<b>Office Signature</b>", norm), Paragraph("<b>Principal Signature</b>", norm)],
        [Paragraph(get_v('office_verified_by'), norm), off_sig if off_sig else Paragraph("(No Signature)", norm), prin_sig if prin_sig else Paragraph("(No Signature)", norm)]
    ], colWidths=[175, 175, 180])
    off_sig_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(off_sig_table)
    story.append(PageBreak())

    # PAGE 4 & 5: Certificates, Declarations & Signatures
    story.append(Paragraph("<b>PAGE 4 &amp; 5: CERTIFICATES &amp; DECLARATION</b>", h2_style))
    story.append(Paragraph(f"<b>Achievements / Awards:</b> {get_v('achievements_awards')}", norm))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>Extra-curricular Details:</b> {get_v('curricular_details')}", norm))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>First Graduate &amp; PMSS Declarations</b>", h3_style))
    fg_str = f"(a) First Graduate in Family: {get_rv('first_graduate', ['first_graduate_yes', 'first_graduate_no'])}  |  (b) Sibling availed concession: {get_rv('brother_sister', ['brother_sister_yes', 'brother_sister_no'])}  |  (c) PMSS Willingness: {get_rv('scholarship', ['scholarship_yes', 'scholarship_no'])}"
    story.append(Paragraph(fg_str, norm))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Joint Declaration by Applicant and Parent</b>", h3_style))
    dec_text = "We hereby solemnly and sincerely affirm that the statements made and the information furnished by me in the application are true. Should it be found that any information is untrue, I am liable for criminal prosecution and agree to forfeit the seat. We agree to abide by all rules, attendance requirements (75%), dress code, and fee structures of Prathyusha Engineering College."
    story.append(Paragraph(dec_text, norm))
    story.append(Spacer(1, 10))

    date_loc_table = Table([
        [Paragraph("<b>Place:</b> Aranvoyalkuppam, Thiruvallur", norm), Paragraph(f"<b>Date:</b> {get_v('date')}", norm)]
    ], colWidths=[265, 265])
    date_loc_table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('PADDING', (0,0), (-1,-1), 4)]))
    story.append(date_loc_table)
    story.append(Spacer(1, 15))

    signatures_table = Table([
        [Paragraph("<b>Signature of Applicant</b>", bold), Paragraph("<b>Signature of Parent / Guardian</b>", bold), Paragraph("<b>Signature of Principal</b>", bold)],
        [Paragraph(get_v(['applicant-sign', 'student_name']), norm), Paragraph(get_v(['parent-sign', 'father_name']), norm), Paragraph("Principal", norm)],
        [app_sig if app_sig else Paragraph("(Signature Attached)", norm), par_sig if par_sig else Paragraph("(Signature Attached)", norm), prin_sig if prin_sig else Paragraph("(Signature Attached)", norm)]
    ], colWidths=[175, 175, 180])
    signatures_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(signatures_table)
    story.append(Spacer(1, 20))

    # Vision & Mission
    story.append(Paragraph("<b>OUR VISION &amp; MISSION</b>", h3_style))
    story.append(Paragraph("<b>VISION:</b> To emerge as a premier Technical, Engineering and Management Institution in the country by imparting Quality Education and thus facilitate our students to blossom into dynamic professionals.", norm))
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>MISSION:</b> Providing state-of-the-art infrastructure, imparting quality education, empowering youth, and promoting Industry-Institute partnership.", norm))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes, None

@app.route('/download_application_pdf/<app_no>')
def download_application_pdf_route(app_no):
    pdf_data, err = generate_application_form_pdf(app_no)
    if err or not pdf_data:
        return err or "Failed to generate PDF", 404
    from io import BytesIO
    from flask import send_file
    buf = BytesIO(pdf_data)
    return send_file(buf, as_attachment=True, download_name=f"Application_Form_{app_no}.pdf", mimetype="application/pdf")

@app.route('/download_pdf', methods=['GET'])
def download_pdf():
    app_no = request.args.get('app_no') or request.args.get('application_number')
    if app_no:
        pdf_data, err = generate_application_form_pdf(app_no)
        if err or not pdf_data:
            return err or "Application PDF not found", 404
        from io import BytesIO
        from flask import send_file
        buf = BytesIO(pdf_data)
        return send_file(buf, as_attachment=True, download_name=f"Application_Form_{app_no}.pdf", mimetype="application/pdf")

    start = request.args.get('start_date')
    end = request.args.get('end_date')
    branch = request.args.get('branch', '')
    status = request.args.get('status', '')
    search = request.args.get('search') or request.args.get('term')

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Coordinator applications PDF export
    if 'coordinator_id' in session:
        coord_name = session.get('coordinator_name', '').strip()
        apps = fetch_coordinator_applications_records(cur, coord_name)
        status_filter = request.args.get('status') or request.args.get('status_filter') or 'all'
        rows = filter_coordinator_applications(apps, start_date=start, end_date=end, search=search, status_filter=status_filter)

        if not rows:
            return "No applications found for the selected dates.", 404

        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        x_margin = 30
        y = height - 50
        line_height = 14

        p.setFont("Helvetica-Bold", 14)
        p.drawString(x_margin, y, "Prathyusha Engineering College")
        y -= 16
        p.setFont("Helvetica", 10)
        p.drawString(x_margin, y, f"Applications Details Report ({start or 'All'} to {end or 'All'})")
        y -= 22

        headers = ["App No", "Student Name", "Father Name", "Dept", "Mobile", "Date Submitted", "Next Visit", "Status"]
        p.setFont("Helvetica-Bold", 8.5)
        col_widths = [65, 80, 80, 50, 65, 75, 65, 55]
        x_positions = []
        cur_x = x_margin
        for w in col_widths:
            x_positions.append(cur_x)
            cur_x += w

        for i, h in enumerate(headers):
            p.drawString(x_positions[i], y, h)
        y -= line_height
        p.setLineWidth(0.5)
        p.line(x_margin, y + 10, cur_x - 5, y + 10)
        p.setFont("Helvetica", 8)

        for r in rows:
            rdict = dict(r)
            rowvals = [
                str(rdict.get('application_number') or '')[:12],
                str(rdict.get('student_name') or '')[:15],
                str(rdict.get('father_name') or '')[:15],
                str(rdict.get('preferred_branch') or '')[:10],
                str(rdict.get('mobile') or '-')[:11],
                str(rdict.get('date_submitted') or '')[:11],
                str(rdict.get('next_visit') or '-')[:12],
                str(rdict.get('status') or 'visited')[:10]
            ]
            for i, val in enumerate(rowvals):
                p.drawString(x_positions[i], y, val)
            y -= line_height
            if y < 50:
                p.showPage()
                y = height - 50
                p.setFont("Helvetica-Bold", 8.5)
                for i, h in enumerate(headers):
                    p.drawString(x_positions[i], y, h)
                y -= line_height
                p.setFont("Helvetica", 8)

        p.save()
        buffer.seek(0)
        from flask import send_file
        filename = f"applications_report_{start or 'all'}_{end or 'all'}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

    # Admin PDF export (existing behavior)
    query = "SELECT * FROM applications WHERE 1=1"
    params = []
    if start:
        query += " AND date_submitted >= %s"
        params.append(start + " 00:00:00")
    if end:
        query += " AND date_submitted <= %s"
        params.append(end + " 23:59:59")
    if branch:
        query += " AND preferred_branch = %s"
        params.append(branch)
    if status:
        query += " AND status = %s"
        params.append(status)
    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    if not rows:
        return "No data found for the selected dates.", 404

    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    x_margin = 40
    y = height - 50
    line_height = 14

    headers = ["App No", "Student", "Father", "Mobile", "Address", "Dept", "Date Submitted"]
    p.setFont("Helvetica-Bold", 9)
    x_positions = [x_margin + i*70 for i in range(len(headers))]
    for i, h in enumerate(headers):
        p.drawString(x_positions[i], y, h)
    y -= line_height
    p.setFont("Helvetica", 9)

    for r in rows:
        rdict = dict(r)
        rowvals = [
            rdict.get('application_number') or '',
            rdict.get('student_name') or '',
            rdict.get('father_name') or '',
            rdict.get('mobile') or '',
            rdict.get('address') or '',
            rdict.get('preferred_branch') or '',
            rdict.get('date_submitted') or ''
        ]
        for i, val in enumerate(rowvals):
            p.drawString(x_positions[i], y, str(val)[:12])
        y -= line_height
        if y < 60:
            p.showPage()
            y = height - 50
            p.setFont("Helvetica-Bold", 9)
            for i, h in enumerate(headers):
                p.drawString(x_positions[i], y, h)
            y -= line_height
            p.setFont("Helvetica", 9)

    p.save()
    buffer.seek(0)
    from flask import send_file
    return send_file(buffer, as_attachment=True, download_name=f"applications_{start}_{end}.pdf", mimetype="application/pdf")

@app.route('/search_students')
def search_students():
    """
    Search route alias for coordinator applications to ensure compatibility with both
    term query and date range filtering.
    """
    return get_coordinator_applications()


# ---------------- Logout ----------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))



# ---------------- Database Setup & Services ----------------
def init_db():
    """
    Initialize or upgrade the database schema safely.
    """
    try:
        conn = create_db_connection()
        ensure_db_schema(conn)
        is_mysql = not (isinstance(conn, SQLiteConnWrapper) or hasattr(conn, 'conn'))
        conn.close()
        if is_mysql:
            try:
                import create_mysql_schema
                create_mysql_schema.create_schema()
            except Exception:
                pass
    except Exception as e:
        print(f"Database schema check failed: {e}")

@app.errorhandler(Exception)
def handle_500(e):
    import traceback
    return f"<pre>{traceback.format_exc()}</pre>", 500

if __name__ == "__main__":
    init_db()
    # Avoid duplicate scheduler instances with Werkzeug reloader
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('FLASK_DEBUG') != '1':
        start_scheduler(create_db_connection)
    app.run(debug=True, port=5000)

