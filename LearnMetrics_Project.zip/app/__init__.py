import os
from datetime import timedelta
from flask import Flask, session, request, abort, redirect, url_for, flash, render_template
from markupsafe import Markup
from dotenv import load_dotenv
from .db import init_pool, query
from . import security as sec

def create_app():
    load_dotenv()
    if not os.getenv('SECRET_KEY'):
        raise RuntimeError('Set SECRET_KEY in the .env file (copy .env.example to .env first).')
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ['SECRET_KEY'], DEBUG=os.getenv('FLASK_DEBUG', '0') == '1',
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0') == '1',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=2), MAX_CONTENT_LENGTH=8 * 1024 * 1024)
    init_pool()
    from .views_auth import bp as auth_bp
    from .views_admin import bp as admin_bp
    from .views_course import bp as course_bp
    from .views_student import bp as student_bp
    for b in (auth_bp, admin_bp, course_bp, student_bp): app.register_blueprint(b)

    app.jinja_env.globals['csrf_token'] = sec.csrf_token
    app.jinja_env.globals['csrf'] = lambda: Markup('<input type="hidden" name="_csrf" value="%s">' % sec.csrf_token())
    app.jinja_env.filters['dt'] = lambda v: str(v)[:16] if v else '-'

    @app.context_processor
    def inject():
        return {'me': session.get('user')}

    @app.before_request
    def guard():
        if request.method == 'POST' and not sec.csrf_ok(): abort(400)     # every form is protected against forged requests
        u = session.get('user')
        if u and request.endpoint not in ('static', 'auth.logout', 'auth.change_password'):
            row = query('SELECT active, must_change_password FROM users WHERE id=%s', (u['id'],), True)
            if not row or not row['active']:
                session.clear(); flash('This account is not available. Contact the administrator.', 'danger')
                return redirect(url_for('auth.login'))
            if row['must_change_password']: return redirect(url_for('auth.change_password'))

    for code, msg in ((400, 'The form expired or was invalid. Go back, refresh the page and try again.'),
                      (403, 'You do not have access to this page.'), (404, 'Page not found.'), (500, 'Something went wrong on the server.')):
        app.register_error_handler(code, lambda e, c=code, m=msg: (render_template('error.html', code=c, msg=m), c))
    return app
