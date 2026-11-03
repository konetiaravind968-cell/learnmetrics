"""End-to-end smoke test that runs WITHOUT MySQL (it swaps in an in-memory SQLite database).
Usage:  pip install -r requirements.txt   then   python tests/test_smoke.py"""
import io, os, re, sqlite3, sys, types
from datetime import datetime
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
os.environ['SECRET_KEY'] = 'test-secret'

# ---- fake MySQL pool backed by SQLite (the real db.py code still runs) ----
try: import dotenv
except ImportError:
    m = types.ModuleType('dotenv'); m.load_dotenv = lambda *a, **k: None; sys.modules['dotenv'] = m
try: from mysql.connector import pooling
except ImportError:
    mysql = types.ModuleType('mysql'); mc = types.ModuleType('mysql.connector'); pooling = types.ModuleType('mysql.connector.pooling')
    mysql.connector = mc; mc.pooling = pooling; sys.modules.update({'mysql': mysql, 'mysql.connector': mc, 'mysql.connector.pooling': pooling})
sqlite3.register_adapter(datetime, lambda d: d.isoformat(' '))
DB = sqlite3.connect(':memory:', check_same_thread=False); DB.row_factory = sqlite3.Row
sql = open(os.path.join(ROOT, 'schema.sql'), encoding='utf-8').read()
sql = re.sub(r'CREATE DATABASE[^;]*;|USE [^;]*;', '', sql)
sql = sql.replace('INT AUTO_INCREMENT PRIMARY KEY', 'INTEGER PRIMARY KEY AUTOINCREMENT').replace(') ENGINE=InnoDB', ')')
sql = re.sub(r'ENUM\([^)]*\)', 'TEXT', sql); sql = re.sub(r'UNIQUE KEY \w+ \(', 'UNIQUE (', sql)
DB.execute('PRAGMA foreign_keys=ON'); DB.executescript(sql)
class Cur:
    def __init__(s, d): s.c = DB.cursor(); s.d = d; s.lastrowid = None; s.rowcount = -1
    def execute(s, q, p=()): s.c.execute(q.replace('%s', '?'), tuple(p)); s.lastrowid = s.c.lastrowid; s.rowcount = s.c.rowcount
    def fetchone(s): r = s.c.fetchone(); return None if r is None else (dict(r) if s.d else tuple(r))
    def fetchall(s): return [dict(r) if s.d else tuple(r) for r in s.c.fetchall()]
    def close(s): pass
class Conn:
    def cursor(s, dictionary=False): return Cur(dictionary)
    def commit(s): DB.commit()
    def rollback(s): DB.rollback()
    def close(s): pass
pooling.MySQLConnectionPool = lambda **k: types.SimpleNamespace(get_connection=lambda: Conn())

from app import create_app
from app.db import execute, query
from werkzeug.security import generate_password_hash as H
app = create_app(); app.testing = True
results = []
def ok(name, cond): results.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)
def tok(c, url='/login'): return re.search(r'name="_csrf" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
def login(c, ident, pw): return c.post('/login', data={'_csrf': tok(c), 'identifier': ident, 'password': pw}, follow_redirects=True)

execute("INSERT INTO users(full_name,email,password_hash,role,created_at) VALUES('Admin','admin@x.test',%s,'admin',%s)", (H('AdminPass123'), datetime.now()))
adm = app.test_client()
r = login(adm, 'admin@x.test', 'AdminPass123'); ok('admin login', b'Platform overview' in r.data)
ok('missing CSRF rejected', app.test_client().post('/login', data={'identifier': 'admin@x.test', 'password': 'AdminPass123'}).status_code == 400)
ok('wrong password rejected', b'Invalid' in login(app.test_client(), 'admin@x.test', 'nope').data)

def apost(c, url, data, page):
    d = dict(data); d['_csrf'] = tok(c, page); return c.post(url, data=d, follow_redirects=True)
# staff + courses
r = apost(adm, '/admin/people/staff/new', dict(staff_code='STF1', full_name='Staff One', email='staff1@x.test', department='CSE'), '/admin/people/staff/new')
ok('admin creates staff + temp password shown', b'temporary password' in r.data)
spw = re.search(r'temporary password: (\S+)', r.get_data(as_text=True)).group(1)
sid = query("SELECT id FROM staff WHERE staff_code='STF1'", one=True)['id']
apost(adm, '/admin/courses/new', dict(course_code='PY101', title='Python Basics', category='Programming', difficulty='Beginner', duration_hours='8', instructor_id=str(sid), published='1'), '/admin/courses/new')
apost(adm, '/admin/courses/new', dict(course_code='XX999', title='Other course', difficulty='Beginner'), '/admin/courses/new')
cid = query("SELECT id FROM courses WHERE course_code='PY101'", one=True)['id']; oid = query("SELECT id FROM courses WHERE course_code='XX999'", one=True)['id']
ok('courses created and published', query('SELECT published p FROM courses WHERE id=%s', (cid,), one=True)['p'] == 1)
ok('duplicate course code rejected', b'already exists' in apost(adm, '/admin/courses/new', dict(course_code='PY101', title='Dup', difficulty='Beginner'), '/admin/courses/new').data)

stf = app.test_client(); r = login(stf, 'STF1', spw)
ok('staff first login forces password change', b'Set your own password' in r.data)
r = apost(stf, '/change-password', dict(current=spw, password='StaffNewPass9', confirm='StaffNewPass9'), '/change-password')
ok('staff lands on own courses', b'Courses assigned to me' in r.data and b'PY101' in r.data)
for n, t in ((1, 'Intro'), (2, 'Variables')):
    apost(stf, f'/course/{cid}/lesson', dict(title=t, content_type='video', content_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ', position=str(n), duration_minutes='10'), f'/course/{cid}')
ok('lessons added', query('SELECT COUNT(*) n FROM lessons WHERE course_id=%s', (cid,), one=True)['n'] == 2)
ok('javascript: link rejected', b'must start with http' in apost(stf, f'/course/{cid}/lesson', dict(title='Bad', content_type='link', content_url='javascript:alert(1)'), f'/course/{cid}').data)
apost(stf, f'/course/{cid}/quiz', dict(title='Quiz 1', pass_percent='50'), f'/course/{cid}')
zid = query('SELECT id FROM quizzes WHERE course_id=%s', (cid,), one=True)['id']
apost(stf, f'/quiz/{zid}/question', dict(question_text='2+2?', option_a='3', option_b='4', option_c='5', option_d='6', correct_option='B', marks='1'), f'/quiz/{zid}')
apost(stf, f'/quiz/{zid}/question', dict(question_text='Capital of France?', option_a='Rome', option_b='Paris', correct_option='B', marks='1'), f'/quiz/{zid}')
ok('staff blocked from another instructor course', stf.get(f'/course/{oid}').status_code == 403)
ok('staff blocked from admin pages', stf.get('/admin/').status_code == 403 and stf.get('/admin/people/student').status_code == 403)

# students + Excel import
r = apost(adm, '/admin/people/student/new', dict(student_code='S001', full_name='Stu One', email='s1@x.test', department='CSE', semester='2'), '/admin/people/student/new')
pw1 = re.search(r'temporary password: (\S+)', r.get_data(as_text=True)).group(1)
ok('semester out of range rejected', b'out of the allowed range' in apost(adm, '/admin/people/student/new', dict(student_code='S9', full_name='X Y', email='x@y.test', department='CSE', semester='12'), '/admin/people/student/new').data)
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.title = 'Students'; ws.append(['student_code', 'full_name', 'email', 'department', 'semester'])
ws.append(['S002', '  STU   TWO  ', 'S2@X.TEST', 'IT', 'II']); ws.append(['S003', 'Stu Three', 'dup@x.test', 'IT', 3]); ws.append(['S004', 'Stu Four', 'dup@x.test', 'IT', 3])
buf = io.BytesIO(); wb.save(buf); buf.seek(0)
r = adm.post('/admin/excel', data={'_csrf': tok(adm, '/admin/excel'), 'file': (buf, 'students.xlsx')}, content_type='multipart/form-data', follow_redirects=True)
row = query("SELECT full_name,email,semester FROM students WHERE student_code='S002'", one=True)
ok('Excel import cleans names, emails and roman semester', row and row['full_name'] == 'STU TWO' and row['email'] == 's2@x.test' and row['semester'] == 2)
ok('Excel import reports a duplicate-email row instead of crashing', b'skipped' in r.data and query("SELECT COUNT(*) n FROM students WHERE student_code IN ('S003','S004')", one=True)['n'] == 1)
ok('bulk enroll by department', b'students enrolled' in apost(adm, '/admin/enrollments', dict(mode='bulk', course_id=str(cid), department='IT', semester=''), '/admin/enrollments').data)

stu = app.test_client(); r = login(stu, 'S001', pw1)
ok('student ID login forces password change', b'Set your own password' in r.data)
apost(stu, '/change-password', dict(current=pw1, password='StudentNew99x', confirm='StudentNew99x'), '/change-password')
ok('student blocked from admin and staff pages', stu.get('/admin/').status_code == 403 and stu.get('/staff').status_code == 403 and stu.get(f'/course/{cid}').status_code == 403)
ok('student cannot open lesson before enrolling', stu.get(f"/learn/lesson/{query('SELECT id FROM lessons LIMIT 1', one=True)['id']}").status_code == 403)
ok('student sees published course only', b'Python Basics' in stu.get('/courses').data and b'Other course' not in stu.get('/courses').data)
apost(stu, f'/courses/{cid}/enroll', {}, '/courses'); apost(stu, f'/courses/{cid}/enroll', {}, '/courses')
ok('duplicate enrollment prevented', query('SELECT COUNT(*) n FROM enrollments WHERE course_id=%s AND student_id=(SELECT id FROM students WHERE student_code=%s)', (cid, 'S001'), one=True)['n'] == 1)
l1, l2 = [r['id'] for r in query('SELECT id FROM lessons WHERE course_id=%s ORDER BY position', (cid,))]
ok('lesson page embeds the video', b'youtube.com/embed/dQw4w9WgXcQ' in stu.get(f'/learn/lesson/{l1}').data)
stu.post(f'/learn/lesson/{l1}/ping', headers={'X-CSRF-Token': tok(stu, f'/learn/lesson/{l1}')})
ok('time on page recorded', query('SELECT seconds_spent s FROM lesson_progress WHERE lesson_id=%s', (l1,), one=True)['s'] == 30)
apost(stu, f'/learn/lesson/{l1}/complete', {}, f'/learn/lesson/{l1}'); apost(stu, f'/learn/lesson/{l1}/complete', {}, f'/learn/lesson/{l1}')
ok('lesson counted once even if completed twice', query('SELECT COUNT(*) n FROM lesson_progress WHERE completed=1 AND lesson_id=%s', (l1,), one=True)['n'] == 1)
h = stu.get('/dashboard').get_data(as_text=True)
ok('student dashboard shows 50% progress and 1-day streak', '50%' in h and 'Day streak' in h and re.search(r'stat">1<', h))
qs = query('SELECT id,correct_option FROM questions WHERE quiz_id=%s ORDER BY id', (zid,))
r = apost(stu, f'/learn/quiz/{zid}', {f"q{qs[0]['id']}": qs[0]['correct_option'], f"q{qs[1]['id']}": 'A'}, f'/learn/quiz/{zid}')
ok('quiz graded server-side (1 of 2 = 50%)', b'1 / 2 (50' in r.data and b'Passed' in r.data)
aid = query('SELECT id FROM attempts', one=True)['id']
r = apost(adm, '/admin/people/student/new', dict(student_code='S005', full_name='Stu Five', email='s5@x.test', department='CSE', semester='1'), '/admin/people/student/new')
pw5 = re.search(r'temporary password: (\S+)', r.get_data(as_text=True)).group(1)
other = app.test_client(); login(other, 'S005', pw5); apost(other, '/change-password', dict(current=pw5, password='OtherStudent99', confirm='OtherStudent99'), '/change-password')
ok('owner can open own quiz result', stu.get(f'/learn/attempt/{aid}').status_code == 200)
ok('another student cannot open it', other.get(f'/learn/attempt/{aid}').status_code == 404)
r = stf.get(f'/quiz/{zid}'); ok('staff sees per-question statistics', b'50.0% correct' in r.data or b'100.0% correct' in r.data)
r = stf.get(f'/course/{cid}/roster'); ok('staff roster shows progress', b'S001' in r.data and b'50%' in r.data)
ok('roster CSV export', b'S001,Stu One' in stf.get(f'/course/{cid}/roster.csv').data)
h = adm.get('/admin/').get_data(as_text=True); ok('admin dashboard renders real numbers and chart data', '"completion"' in h and 'Lessons completed' in h)
ok('admin Excel progress report', adm.get('/admin/export/progress.xlsx').status_code == 200 and adm.get('/admin/export/nope.xlsx').status_code == 404)
ok('delete with enrollments is blocked safely', b'cannot be deleted' in apost(adm, f"/admin/people/student/{query('SELECT id FROM students WHERE student_code=%s', ('S001',), one=True)['id']}/delete", {}, '/admin/people/student').data)
apost(adm, f"/admin/people/student/{query('SELECT id FROM students WHERE student_code=%s', ('S001',), one=True)['id']}/toggle", {}, '/admin/people/student')
ok('deactivated student is locked out mid-session', stu.get('/dashboard').status_code == 302)
ok('logout needs a valid token', adm.post('/logout').status_code == 400)
print('ALL PASSED' if all(results) else f'FAILED {results.count(False)} of {len(results)}'); sys.exit(0 if all(results) else 1)
