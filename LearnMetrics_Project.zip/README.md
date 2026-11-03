# LearnMetrics - E-Learning Course Analytics System

A full-stack web application (Flask + MySQL + HTML/CSS/JavaScript + Chart.js) for managing courses, tracking learner
progress and analysing engagement. Three roles: **Admin**, **Staff (instructor)** and **Student**.

## Features
- **Secure login** with student ID, staff ID or email. Passwords are stored only as hashes; new accounts get a random
  temporary password and must choose their own at first login. Sessions expire, accounts can be deactivated, and every
  form is protected against forged requests (CSRF). Access is checked on the server for every page.
- **Admin:** manage students and staff (add, edit, search, deactivate, reset password, delete when safe), courses
  (CRUD, publish/unpublish, assign instructor), enrollments (single or by department/semester), Excel import/export,
  progress reports, and a dashboard with four Chart.js charts and an "inactive students" list.
- **Staff:** see only their own courses; add/edit lessons (video, document, text, link), build quizzes and questions,
  see each student's progress, time and quiz average, per-question statistics, and download a CSV roster.
- **Student:** browse published courses, enroll/leave, open lessons (YouTube videos are embedded), mark lessons complete,
  take quizzes (graded on the server), see results, progress bars, learning time, a day streak and a
  "continue learning" suggestion.
- **Analytics:** every number and chart comes from SQL queries on the database (see `app/analytics.py`).

## Run it (Windows)
1. Install **Python 3.10+** (tick "Add to PATH") and **MySQL Server 8** (remember the root password).
2. In a terminal, inside this folder:
   ```
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env
   ```
3. Open `.env` and set `SECRET_KEY` (any long random text) and the MySQL user/password. To get a random key:
   `python -c "import secrets; print(secrets.token_hex(32))"`
4. Create the database user (MySQL Workbench or `mysql -u root -p`), using your own password:
   ```sql
   CREATE USER 'elearning_user'@'localhost' IDENTIFIED BY 'YourPasswordHere';
   GRANT ALL PRIVILEGES ON elearning_course_analytics.* TO 'elearning_user'@'localhost';
   GRANT CREATE ON *.* TO 'elearning_user'@'localhost';
   FLUSH PRIVILEGES;
   ```
   (Or put `DB_USER=root` and the root password in `.env` for a quick start.)
5. Create the tables and the first admin:
   ```
   python manage.py init-db
   python manage.py create-admin
   ```
6. Optional demo data (staff1@demo.example / student1@demo.example ..., password `Demo@12345`):
   `python manage.py seed-demo`
7. Start the app: `python run.py` (or double-click `run.bat`) and open http://127.0.0.1:5000

## Load real students from Excel
1. Admin menu: **Excel & reports**, upload a workbook shaped like `data/sample_import.xlsx`
   (sheets `Students`, `Staff`, `Courses`; extra columns are optional; roman semesters like `II` are accepted).
2. Run `python manage.py create-logins`. It creates a login for everyone without one and saves the temporary passwords
   in `credentials_<date>.xlsx`. Hand each person only their own password, then **delete that file**.
3. One forgotten password: Admin > Students/Staff > *Reset password*, or `python manage.py reset-password <ID>`.

## Test it
- Automatic, no MySQL needed: `python tests/test_smoke.py` (40 checks: login, roles, CSRF, CRUD, enrollment, progress,
  quizzes, Excel import, reports, lock-outs).
- Manual walkthrough: log in as admin > add a staff member and a course (assign the staff, tick Published) > log in as
  that staff member and add 2 lessons and a quiz with questions > add a student, enroll them > log in as the student,
  open a lesson, complete it, take the quiz > check the dashboards and roster.

## Project layout
```
app/__init__.py      app factory, CSRF + account checks on every request
app/security.py      roles, passwords, sessions        app/analytics.py  all dashboard/report SQL
app/views_*.py       auth, admin, course (staff), student pages
app/forms.py         validation helpers                 app/excelio.py    Excel import/export
app/templates/       Jinja2 + Bootstrap pages           schema.sql        MySQL tables
manage.py            init-db, create-admin, create-logins, reset-password, seed-demo
tests/test_smoke.py  end-to-end test                    data/sample_import.xlsx  example workbook
```

## Database (MySQL, `elearning_course_analytics`)
`students`, `staff`, `users` (login, linked to a student or staff row), `courses`, `lessons`, `enrollments`,
`lesson_progress`, `quizzes`, `questions`, `attempts`, `attempt_answers`, `activity_logs`. Foreign keys protect records:
a student or course with enrollments/attempts cannot be deleted (deactivate/unpublish instead). Progress is calculated
(completed lessons / total lessons), never typed in.

## Honest limitations
- "Minutes learned" is the time lesson pages were open and visible (a heartbeat every 30 s). It cannot prove a video was
  actually watched or that the student paid attention.
- No email sending: temporary passwords are handed over from the credentials file. There is no "forgot password" email.
- No brute-force lockout on the login page, and no HTTPS by itself: before real deployment use a production server
  (e.g. gunicorn/waitress behind HTTPS), set `SESSION_COOKIE_SECURE=1` and `FLASK_DEBUG=0`.
- Not included: attendance, assignments with file upload, certificates, automatic emails, AI helper, toll-free helpdesk.
  They are good next steps (the schema and `analytics.py` are built to extend).
- Never share `.env` or `credentials_*.xlsx`, and never commit real student data.
