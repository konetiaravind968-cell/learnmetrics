import hmac, secrets
from datetime import datetime
from functools import wraps
from flask import session, request, abort, redirect, url_for
from werkzeug.security import generate_password_hash
from .db import query, execute

ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
HOME = {'admin': 'admin.dashboard', 'staff': 'course.staff_dashboard', 'student': 'student.dashboard'}

def temp_password(): return ''.join(secrets.choice(ALPHABET) for _ in range(12))

def csrf_token():
    if '_csrf' not in session: session['_csrf'] = secrets.token_hex(16)
    return session['_csrf']

def csrf_ok():
    s = session.get('_csrf'); t = request.form.get('_csrf') or request.headers.get('X-CSRF-Token', '')
    return bool(s) and hmac.compare_digest(t, s)

def home_url(role): return url_for(HOME[role])

def roles(*allowed):
    """Checked on the server for every request: a wrong role gets HTTP 403 even if the URL is typed by hand."""
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = session.get('user')
            if not u: return redirect(url_for('auth.login'))
            if u['role'] not in allowed: abort(403)
            return f(*a, **k)
        return w
    return deco

def find_user(ident):
    ident = (ident or '').strip()
    return query("""SELECT u.* FROM users u LEFT JOIN students s ON s.id=u.student_id LEFT JOIN staff t ON t.id=u.staff_id
                    WHERE u.email=%s OR s.student_code=%s OR t.staff_code=%s LIMIT 1""", (ident.lower(), ident, ident), True)

def start_session(u):
    session.clear(); session.permanent = True
    session['user'] = {'id': u['id'], 'name': u['full_name'], 'role': u['role'],
                       'student_id': u['student_id'], 'staff_id': u['staff_id']}

def log(uid, action, details=''):
    execute('INSERT INTO activity_logs(user_id,action,details,created_at) VALUES(%s,%s,%s,%s)', (uid, action, details, datetime.now()))

def make_login(kind, rid, name, email, pw=None, must_change=1):
    pw = pw or temp_password()
    execute('INSERT INTO users(full_name,email,password_hash,role,student_id,staff_id,must_change_password,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (name, email.lower(), generate_password_hash(pw), kind, rid if kind == 'student' else None,
             rid if kind == 'staff' else None, must_change, datetime.now()))
    return pw
