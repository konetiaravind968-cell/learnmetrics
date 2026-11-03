"""Command line tools.
  python manage.py init-db            create the database and all tables (run once on a new MySQL)
  python manage.py create-admin       create the first administrator
  python manage.py create-logins      create logins for every imported student/staff member who has none (writes an Excel file of temporary passwords)
  python manage.py reset-password ID  new temporary password for one student/staff ID
  python manage.py seed-demo          fill an EMPTY database with synthetic demo data (demo password: Demo@12345)"""
import getpass, os, random, sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

def init_db():
    import mysql.connector
    from dotenv import load_dotenv; load_dotenv()
    conn = mysql.connector.connect(host=os.getenv('DB_HOST', 'localhost'), port=int(os.getenv('DB_PORT', '3306')),
                                   user=os.getenv('DB_USER', 'root'), password=os.getenv('DB_PASSWORD', ''))
    cur = conn.cursor()
    sql = open(os.path.join(os.path.dirname(__file__), 'schema.sql'), encoding='utf-8').read()
    try:
        for stmt in [s.strip() for s in sql.split(';') if s.strip()]: cur.execute(stmt)
        conn.commit()
    except mysql.connector.Error as e:
        raise SystemExit(f'Could not create the database: {e}\nIf the tables already exist, either keep them or start fresh with:  DROP DATABASE elearning_course_analytics;')
    print('Database and tables created.')

def create_admin():
    from app.db import init_pool, query, execute
    init_pool()
    name = input('Admin full name: ').strip(); email = input('Admin email: ').strip().lower()
    pw = getpass.getpass('Password (10+ chars, letters and digits): ')
    if len(pw) < 10 or pw != getpass.getpass('Confirm: ') or not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        raise SystemExit('Password too weak or not matching.')
    if query('SELECT id FROM users WHERE email=%s', (email,), True): raise SystemExit('That email already exists.')
    execute("INSERT INTO users(full_name,email,password_hash,role,created_at) VALUES(%s,%s,%s,'admin',%s)", (name, email, generate_password_hash(pw), datetime.now()))
    print('Administrator created. Sign in with that email.')

def create_logins():
    from openpyxl import Workbook
    from app.db import init_pool, query, execute
    from app.security import temp_password
    init_pool()
    todo = query("""SELECT 'student' role, s.id rid, s.student_code code, s.full_name, s.email FROM students s LEFT JOIN users u ON u.student_id=s.id WHERE u.id IS NULL
                    UNION ALL SELECT 'staff', t.id, t.staff_code, t.full_name, t.email FROM staff t LEFT JOIN users u ON u.staff_id=t.id WHERE u.id IS NULL""")
    if not todo: raise SystemExit('Everyone already has a login.')
    print(f'Creating {len(todo)} logins (hashing in parallel, about a minute)...')
    pws = [temp_password() for _ in todo]
    with ProcessPoolExecutor() as ex: hashes = list(ex.map(generate_password_hash, pws, chunksize=20))
    wb = Workbook(); ws = wb.active; ws.title = 'Credentials'; ws.append(['role', 'login_id', 'full_name', 'email', 'temporary_password'])
    made, skipped = 0, []
    for r, pw, h in zip(todo, pws, hashes):
        try:
            execute('INSERT INTO users(full_name,email,password_hash,role,student_id,staff_id,must_change_password,created_at) VALUES(%s,%s,%s,%s,%s,%s,1,%s)',
                    (r['full_name'], r['email'].lower(), h, r['role'], r['rid'] if r['role'] == 'student' else None, r['rid'] if r['role'] == 'staff' else None, datetime.now()))
            ws.append([r['role'], r['code'], r['full_name'], r['email'].lower(), pw]); made += 1
        except Exception as e: skipped.append((r['code'], str(e)[:70]))
    name = datetime.now().strftime('credentials_%Y%m%d_%H%M.xlsx'); wb.save(name)
    print(f'Created {made} logins, skipped {len(skipped)}.'); [print('  skipped', s) for s in skipped[:10]]
    print(f'Temporary passwords are in {name}. Hand them out securely, then DELETE the file.')

def reset_password(code):
    from app.db import init_pool, query, execute
    from app.security import temp_password
    init_pool()
    u = query("""SELECT u.id, u.full_name FROM users u LEFT JOIN students s ON s.id=u.student_id LEFT JOIN staff t ON t.id=u.staff_id
                 WHERE s.student_code=%s OR t.staff_code=%s""", (code, code), True)
    if not u: raise SystemExit('No login found for ' + code)
    pw = temp_password(); execute('UPDATE users SET password_hash=%s, must_change_password=1 WHERE id=%s', (generate_password_hash(pw), u['id']))
    print(f"{u['full_name']}: temporary password {pw} (must be changed at next login)")

def seed_demo():
    from app.db import init_pool, query, execute, transaction
    from app.security import make_login
    init_pool()
    if query('SELECT COUNT(*) n FROM courses', one=True)['n']: raise SystemExit('The database already has courses. Seed only an empty database.')
    random.seed(7); now = datetime.now(); PW = 'Demo@12345'
    staff = []
    for i, (n, d) in enumerate([('Dr. Arun Verma', 'CSE'), ('Dr. Sneha Iyer', 'IT')], 1):
        sid = execute('INSERT INTO staff(staff_code,full_name,email,department) VALUES(%s,%s,%s,%s)', (f'DEMOSTF{i}', n, f'staff{i}@demo.example', d))
        make_login('staff', sid, n, f'staff{i}@demo.example', PW, 0); staff.append(sid)
    students = []
    for i, n in enumerate(['Rahul Sharma', 'Priya Nair', 'Karthik Reddy', 'Ananya Das', 'Vikram Singh', 'Meera Pillai', 'Sanjay Gupta', 'Divya Rao'], 1):
        sid = execute('INSERT INTO students(student_code,full_name,email,department,semester) VALUES(%s,%s,%s,%s,%s)',
                      (f'DEMO{i:03d}', n, f'student{i}@demo.example', ['CSE', 'IT', 'ECE'][i % 3], random.randint(1, 8)))
        make_login('student', sid, n, f'student{i}@demo.example', PW, 0); students.append(sid)
    plan, types = {}, ['video', 'document', 'text', 'link', 'video']
    for ci, (code, title, cat, diff) in enumerate([('PY101', 'Python Programming Basics', 'Programming', 'Beginner'),
                                                   ('DB201', 'Database Management with MySQL', 'Databases', 'Intermediate'),
                                                   ('DS301', 'Data Structures and Algorithms', 'Programming', 'Advanced')]):
        cid = execute('INSERT INTO courses(course_code,title,description,category,difficulty,instructor_id,duration_hours,published,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,1,%s)',
                      (code, title, f'Synthetic demo course: {title}.', cat, diff, staff[ci % 2], 8 + ci * 2, now))
        lids = [execute('INSERT INTO lessons(course_id,title,content_type,content_url,body,position,duration_minutes) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                        (cid, f'Lesson {p}: {title} part {p}', types[p - 1], 'https://example.com/learn' if types[p - 1] != 'text' else None,
                         'Demo text lesson content.' if types[p - 1] == 'text' else None, p, random.choice([15, 20, 30, 45]))) for p in range(1, 6)]
        zid = execute('INSERT INTO quizzes(course_id,title,pass_percent) VALUES(%s,%s,40)', (cid, f'{title} Quiz'))
        qids = [execute('INSERT INTO questions(quiz_id,question_text,option_a,option_b,option_c,option_d,correct_option,marks) VALUES(%s,%s,%s,%s,%s,%s,%s,1)',
                        (zid, f'Sample question {q} for {title}?', 'Option A', 'Option B', 'Option C', 'Option D', random.choice('ABCD'))) for q in range(1, 5)]
        plan[cid] = (lids, zid, qids)
    for sid in students:
        for cid in random.sample(list(plan), random.randint(1, 3)):
            lids, zid, qids = plan[cid]; enrolled = now - timedelta(days=random.randint(5, 28))
            execute("INSERT INTO enrollments(student_id,course_id,enrolled_at,status) VALUES(%s,%s,%s,'active')", (sid, cid, enrolled))
            done = random.randint(0, 5)
            for lid in lids[:done]:
                when = min(enrolled + timedelta(days=random.randint(0, max(1, (now - enrolled).days)), hours=random.randint(0, 10)), now)
                execute('INSERT INTO lesson_progress(student_id,lesson_id,completed,completed_at,seconds_spent,last_activity) VALUES(%s,%s,1,%s,%s,%s)', (sid, lid, when, random.randint(300, 2400), when))
            if done >= 3:
                with transaction() as cur:
                    ans = [(q, random.choice('ABCD')) for q in qids]
                    cur.execute('SELECT id,correct_option FROM questions WHERE quiz_id=%s', (zid,)); key = {r['id']: r['correct_option'] for r in cur.fetchall()}
                    score = sum(1 for q, c in ans if key[q] == c)
                    cur.execute('INSERT INTO attempts(quiz_id,student_id,score,max_marks,percentage,attempted_at) VALUES(%s,%s,%s,4,%s,%s)',
                                (zid, sid, score, round(score * 25, 2), now - timedelta(days=random.randint(0, 10))))
                    aid = cur.lastrowid
                    for q, c in ans: cur.execute('INSERT INTO attempt_answers(attempt_id,question_id,chosen) VALUES(%s,%s,%s)', (aid, q, c))
    print(f'Demo data created. Logins (password {PW}): staff1@demo.example, student1@demo.example ... student8@demo.example, or IDs DEMO001..DEMO008')

if __name__ == '__main__':
    c = sys.argv[1] if len(sys.argv) > 1 else ''
    if c == 'init-db': init_db()
    elif c == 'create-admin': create_admin()
    elif c == 'create-logins': create_logins()
    elif c == 'reset-password' and len(sys.argv) == 3: reset_password(sys.argv[2])
    elif c == 'seed-demo': seed_demo()
    else: print(__doc__)
