# Admission Management System (AMS)
### Prathyusha Engineering College

A web-based Admission Management System built with Python (Flask) and MySQL to digitize and manage college admissions, student applications, coordinator workflows, and automated follow-ups.

---

## About the Project

In many colleges, the admission process still relies heavily on manual paperwork, physical registers, and scattered Excel sheets. This project was built to solve that problem for **Prathyusha Engineering College**.

It provides a centralized portal where:
- **Counselors / Admission Coordinators** can register applicants through an interactive multi-step form, track student visits, update status, and schedule follow-ups.
- **Administrators** can track total admissions and visits, analyze branch-wise distribution, manage coordinators, and export reports in Excel and PDF formats.
- **Automated Email Reminders** notify students and coordinators before scheduled campus visits.

---

## Key Features

### 1. 7-Step Admission Wizard & Advance Booking
- Multi-step application wizard covering personal details, parents' info, marks/cutoffs, quota/scholarship, branch choice, document uploads, and final verification.
- Auto-generates unique institutional application numbers (e.g., `PEC20260001`).
- Auto-calculates academic aggregates and cut-off scores.
- Clean digital signature staging and document preview.

### 2. Coordinator Dashboard
- **Student Management:** View applicant details in a clean, locked view-only mode or edit application data with dedicated edit access.
- **Date & Range Filters:** Filter student visits by specific date or date range with real-time count badges.
- **Follow-up Reminders:** Schedule visits and track completed vs pending follow-ups.
- **Department Analytics:** Interactive pie chart showing branch choices (CSE, AI&DS, ECE, IT, etc.).

### 3. Automated Email Reminder System
- Background scheduler that checks for scheduled student visits every 15 minutes.
- Sends automated HTML reminder emails to students and admission coordinators before their scheduled visit date.
- Dedicated retry mechanism for failed deliveries and manual "Run Check Now" button for testing.

### 4. Admin Portal & Reporting
- High-level overview of total admissions, visits, and department allocations.
- Coordinator account management.
- One-click **Excel export** (`.xlsx`) with embedded charts and formatted data.
- Print-ready **PDF generation** for official admission forms.

### 5. Robust Database Design
- Built for **MySQL** (`project_db`) with relational integrity and indexed search queries.
- Automatic fallback support for local SQLite development if MySQL is not configured.
- Environment variables (`.env`) for secure credential storage.

---

## Tech Stack

- **Backend:** Python 3.10+, Flask
- **Frontend:** HTML5, CSS3, JavaScript (ES6+), FontAwesome
- **Database:** MySQL (Primary) / SQLite (Fallback)
- **Email & Automation:** Python `smtplib` + background threading scheduler
- **Reports & Exports:** ReportLab (PDF), OpenPyXL (Excel)

---

## Project Structure

```text
AMS--main/
├── app.py                         # Main Flask application and API routes
├── .env.example                   # Template for environment configuration
├── requirements.txt               # Python package dependencies
│
├── services/                      # Background services
│   ├── email_service.py           # SMTP mailer and email template engine
│   └── scheduler_service.py       # Automated visit check and follow-up runner
│
├── templates/                     # HTML templates (Jinja2)
│   ├── index.html                 # College portal landing page
│   ├── admin_login.html           # Admin login
│   ├── admin_dashboard.html       # Administrator dashboard
│   ├── coordinator_login.html     # Coordinator login
│   ├── coordinator_dashboard.html # Coordinator workstation & student list
│   ├── form.html                  # Admission & Advance booking form
│   ├── view_confirm_form.html     # Read-only 7-page print preview
│   └── application form/          # 7-step wizard pages (first.html to seventh.html)
│
├── static/                        # CSS, client-side JS, logos & uploads
│   ├── PEC Logo.png               # College seal logo
│   └── form_wizard.js             # Client-side form wizard validation
│
├── create_mysql_schema.py         # MySQL database table creator
├── run_query.py                   # CLI tool to inspect application photos & docs
├── test_regression.py             # Route and API regression test suite
└── test_coordinator_date_filter.py# Date filtering test suite
```

---

## Getting Started

### 1. Prerequisites
- Python 3.10 or higher installed
- MySQL Server (MySQL 8.0, XAMPP, or MariaDB)
- Git

### 2. Clone the Repository
```bash
git clone https://github.com/agasurusrinivas-web/Admission-Management-System.git
cd Admission-Management-System
```

### 3. Create a Virtual Environment
```bash
# On Windows
python -m venv venv
venv\Scripts\activate

# On Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your database credentials:
```bash
cp .env.example .env
```

Edit `.env`:
```ini
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=project_db

# Email settings (Optional - for reminders)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_app_password
```

### 6. Initialize Database
Create the MySQL database and tables:
```bash
python create_mysql_schema.py
```

### 7. Run the Application
```bash
python app.py
```

Once running, open your browser and go to:
```text
http://127.0.0.1:5000/
```

---

## Default Access & Portals

| Portal | URL Path | Description |
| :--- | :--- | :--- |
| **Home Page** | `/` | Role selection page |
| **Admin Login** | `/admin` | Administrator login portal |
| **Admin Dashboard** | `/admin_dashboard` | College admission statistics and exports |
| **Coordinator Login** | `/coordinator` | Admission counselor login |
| **Coordinator Dashboard** | `/coordinator_dashboard` | Student application list, follow-ups & filters |
| **Admission Form** | `/application_form` | Interactive candidate enrollment form |

---

## Testing

To verify that all routes and database connections are working:
```bash
# Run route regression tests
python test_regression.py

# Run coordinator date filter tests
python test_coordinator_date_filter.py
```

---

## Author & Credits

- **Developed by:** Srinivas ([@agasurusrinivas-web](https://github.com/agasurusrinivas-web))
- **Institution:** Prathyusha Engineering College (PEC)
- Developed as a final-year academic capstone project.

---

## License

This project is created for educational and institutional use.
