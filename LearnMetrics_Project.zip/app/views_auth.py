import re
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash, generate_password_hash
from .db import query, execute
from . import security as sec

bp = Blueprint('auth', __name__)

@bp.route('/')
def index():
    u = session.get('user')
    return redirect(sec.home_url(u['role']) if u else url_for('auth.login'))

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = sec.find_user(request.form.get('identifier', ''))
        if not u or not check_password_hash(u['password_hash'], request.form.get('password', '')):
            flash('Invalid ID/email or password.', 'danger')
        elif not u['active']:
            flash('This account is deactivated. Contact the administrator.', 'danger')
        else:
            sec.start_session(u)
            execute('UPDATE users SET last_login=%s WHERE id=%s', (datetime.now(), u['id']))
            sec.log(u['id'], 'login')
            return redirect(url_for('auth.change_password') if u['must_change_password'] else sec.home_url(u['role']))
    return render_template('login.html')

@bp.route('/logout', methods=['POST'])
def logout():
    if session.get('user'): sec.log(session['user']['id'], 'logout')
    session.clear(); flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))

@bp.route('/change-password', methods=['GET', 'POST'])
def change_password():
    u = session.get('user')
    if not u: return redirect(url_for('auth.login'))
    row = query('SELECT password_hash, must_change_password FROM users WHERE id=%s', (u['id'],), True)
    if request.method == 'POST':
        cur, new, conf = request.form.get('current', ''), request.form.get('password', ''), request.form.get('confirm', '')
        errs = []
        if not check_password_hash(row['password_hash'], cur): errs.append('Current password is incorrect.')
        if len(new) < 10 or not re.search(r'[A-Za-z]', new) or not re.search(r'\d', new): errs.append('New password needs 10+ characters with letters and digits.')
        if new != conf: errs.append('Passwords do not match.')
        if not errs and new == cur: errs.append('Choose a password different from the current one.')
        if errs:
            for e in errs: flash(e, 'danger')
        else:
            execute('UPDATE users SET password_hash=%s, must_change_password=0 WHERE id=%s', (generate_password_hash(new), u['id']))
            sec.log(u['id'], 'password_changed'); flash('Password updated.', 'success')
            return redirect(sec.home_url(u['role']))
    return render_template('change_password.html', forced=bool(row['must_change_password']))
