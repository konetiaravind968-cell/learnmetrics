
import csv
import io
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    send_file,
)

from .db import query, execute, transaction
from . import security as sec, analytics as an
from .forms import F, read_form, insert, update, links, PAGE
from .excelio import import_workbook, export_workbook, DIFF


bp = Blueprint('admin', __name__, url_prefix='/admin')
admin = sec.roles('admin')


PEOPLE = {
    'student': dict(
        table='students',
        code='student_code',
        fk='student_id',
        title='Students',
        fields=[
            F('student_code', 'Student ID', r=1),
            F('full_name', 'Full name', r=1),
            F('email', 'Email', 'email', 1),
            F('department', 'Department', r=1),
            F('semester', 'Semester (1-8)', 'number', 1, lo=1, hi=8),
        ],
    ),
    'staff': dict(
        table='staff',
        code='staff_code',
        fk='staff_id',
        title='Staff',
        fields=[
            F('staff_code', 'Staff ID', r=1),
            F('full_name', 'Full name', r=1),
            F('email', 'Email', 'email', 1),
            F('department', 'Department'),
        ],
    ),
}


def person(kind):
    return PEOPLE.get(kind) or abort(404)


# --------------------------------------------------
# ADMIN DASHBOARD
# --------------------------------------------------

@bp.route('/')
@admin
def dashboard():
    t = query("""
        SELECT
            (SELECT COUNT(*) FROM students) students,
            (SELECT COUNT(*) FROM staff) staff,
            (SELECT COUNT(*) FROM courses) courses,
            (SELECT COUNT(*) FROM enrollments
                WHERE status = 'enrolled') enrollments,
            (SELECT COUNT(*) FROM lesson_progress
                WHERE completed = 1) lessons_done,
            (SELECT COALESCE(ROUND(AVG(percentage), 1), 0)
                FROM attempts) avg_score
    """, one=True)

    cs = an.course_stats()
    labels, counts = an.trend(14)

    data = dict(
        titles=[c['course_code'] for c in cs],
        enrolled=[int(c['enrolled']) for c in cs],
        completion=[c['completion'] for c in cs],
        scores=[c['avg_score'] or 0 for c in cs],
        days=[label[5:] for label in labels],
        daily=counts,
    )

    return render_template(
        'admin_dashboard.html',
        t=t,
        cs=cs,
        data=data,
        idle=an.inactive(14),
    )


# --------------------------------------------------
# STUDENTS AND STAFF
# --------------------------------------------------

@bp.route('/people/<kind>')
@admin
def people(kind):
    P = person(kind)

    q = request.args.get('q', '').strip()
    page = max(request.args.get('page', 1, type=int), 1)

    like = (f'%{q}%',) * 3

    where = (
        f"(p.{P['code']} LIKE %s "
        "OR p.full_name LIKE %s "
        "OR p.email LIKE %s)"
    )

    total_row = query(
        f"SELECT COUNT(*) n FROM {P['table']} p WHERE {where}",
        like,
        True,
    )
    total = total_row['n']

    extra = ', p.semester' if kind == 'student' else ''

    rows = query(
        f"""
        SELECT
            p.id,
            p.{P['code']} code,
            p.full_name,
            p.email,
            p.department
            {extra},
            u.id uid,
            u.active
        FROM {P['table']} p
        LEFT JOIN users u ON u.{P['fk']} = p.id
        WHERE {where}
        ORDER BY p.full_name
        LIMIT %s OFFSET %s
        """,
        like + (PAGE, (page - 1) * PAGE),
    )

    pages = max(-(-total // PAGE), 1)
    prev, nxt = links(page, pages)

    return render_template(
        'people.html',
        kind=kind,
        P=P,
        rows=rows,
        q=q,
        page=page,
        pages=pages,
        total=total,
        prev=prev,
        nxt=nxt,
    )


@bp.route('/people/<kind>/new', methods=['GET', 'POST'])
@admin
def person_new(kind):
    P = person(kind)
    vals = {}

    if request.method == 'POST':
        vals, errs = read_form(P['fields'], request.form)

        if not errs:
            try:
                rid = insert(P['table'], vals)
            except Exception:
                errs.append('That ID or email already exists.')
            else:
                try:
                    pw = sec.make_login(
                        kind,
                        rid,
                        vals['full_name'],
                        vals['email'],
                    )
                except Exception:
                    flash(
                        'Record saved, but a login could not be created.',
                        'warning',
                    )
                else:
                    flash(
                        f"Created. Login ID: {vals[P['code']]} | "
                        f"Temporary password: {pw} "
                        "(shown once; change it at first login)",
                        'warning',
                    )

                return redirect(url_for('admin.people', kind=kind))

        for error in errs:
            flash(error, 'danger')

    return render_template(
        'form.html',
        title=f'Add {kind}',
        fields=P['fields'],
        vals=vals,
        back=url_for('admin.people', kind=kind),
    )


@bp.route('/people/<kind>/<int:rid>/edit', methods=['GET', 'POST'])
@admin
def person_edit(kind, rid):
    P = person(kind)

    row = query(
        f"SELECT * FROM {P['table']} WHERE id=%s",
        (rid,),
        True,
    ) or abort(404)

    vals = row

    if request.method == 'POST':
        vals, errs = read_form(P['fields'], request.form)

        if not errs:
            try:
                with transaction() as cur:
                    cols = list(vals)

                    cur.execute(
                        f"""
                        UPDATE {P['table']}
                        SET {','.join(c + '=%s' for c in cols)}
                        WHERE id=%s
                        """,
                        tuple(vals[c] for c in cols) + (rid,),
                    )

                    cur.execute(
                        f"""
                        UPDATE users
                        SET full_name=%s, email=%s
                        WHERE {P['fk']}=%s
                        """,
                        (
                            vals['full_name'],
                            vals['email'],
                            rid,
                        ),
                    )

            except Exception:
                errs.append(
                    'That ID or email is already used by someone else.'
                )
            else:
                flash('Changes saved.', 'success')
                return redirect(url_for('admin.people', kind=kind))

        for error in errs:
            flash(error, 'danger')

    return render_template(
        'form.html',
        title=f'Edit {kind}',
        fields=P['fields'],
        vals=vals,
        back=url_for('admin.people', kind=kind),
    )


@bp.route('/people/<kind>/<int:rid>/delete', methods=['POST'])
@admin
def person_delete(kind, rid):
    P = person(kind)

    try:
        execute(
            f"DELETE FROM {P['table']} WHERE id=%s",
            (rid,),
        )
        flash('Deleted.', 'success')
    except Exception:
        flash(
            'This record has linked data and cannot be deleted. '
            'Deactivate the login instead.',
            'danger',
        )

    return redirect(url_for('admin.people', kind=kind))


@bp.route('/people/<kind>/<int:rid>/reset', methods=['POST'])
@admin
def person_reset(kind, rid):
    P = person(kind)

    row = query(
        f"SELECT * FROM {P['table']} WHERE id=%s",
        (rid,),
        True,
    ) or abort(404)

    user = query(
        f"SELECT id FROM users WHERE {P['fk']}=%s",
        (rid,),
        True,
    )

    if user:
        pw = sec.temp_password()

        from werkzeug.security import generate_password_hash

        execute(
            """
            UPDATE users
            SET password_hash=%s, must_change_password=1
            WHERE id=%s
            """,
            (generate_password_hash(pw), user['id']),
        )
    else:
        pw = sec.make_login(
            kind,
            rid,
            row['full_name'],
            row['email'],
        )

    flash(
        f"Login ID: {row[P['code']]} | "
        f"New temporary password: {pw} (shown once)",
        'warning',
    )

    return redirect(
        request.referrer or url_for('admin.people', kind=kind)
    )


@bp.route('/people/<kind>/<int:rid>/toggle', methods=['POST'])
@admin
def person_toggle(kind, rid):
    P = person(kind)

    execute(
        f"UPDATE users SET active=1-active WHERE {P['fk']}=%s",
        (rid,),
    )

    flash('Login status changed.', 'success')

    return redirect(
        request.referrer or url_for('admin.people', kind=kind)
    )


# --------------------------------------------------
# COURSE MANAGEMENT
# --------------------------------------------------

def course_fields():
    staff = [
        ('', '- none -')
    ] + [
        (
            str(s['id']),
            f"{s['full_name']} ({s['staff_code']})",
        )
        for s in query(
            'SELECT id, staff_code, full_name FROM staff ORDER BY full_name'
        )
    ]

    return [
        F('course_code', 'Course code', r=1),
        F('title', 'Title', r=1),
        F('description', 'Description', 'textarea'),
        F('category', 'Category'),
        F(
            'difficulty',
            'Difficulty',
            'select',
            1,
            [(d, d) for d in DIFF],
        ),
        F('duration_hours', 'Duration (hours)', 'number', lo=0),
        F('instructor_id', 'Instructor', 'select', o=staff),
        F('published', 'Published (visible to students)', 'checkbox'),
    ]


@bp.route('/courses')
@admin
def courses():
    rows = query("""
        SELECT
            c.id,
            c.course_code,
            c.title,
            c.category,
            c.difficulty,
            c.published,
            s.full_name instructor,
            (
                SELECT COUNT(*)
                FROM lessons l
                WHERE l.course_id = c.id
            ) lessons
        FROM courses c
        LEFT JOIN staff s ON s.id = c.instructor_id
        ORDER BY c.course_code
    """)

    return render_template('courses_admin.html', rows=rows)


@bp.route('/courses/new', methods=['GET', 'POST'])
@admin
def course_new():
    fields = course_fields()
    vals = {'difficulty': 'Beginner'}

    if request.method == 'POST':
        vals, errs = read_form(fields, request.form)

        if not errs:
            vals['category'] = vals['category'] or 'General'
            vals['duration_hours'] = vals['duration_hours'] or 0

            try:
                insert('courses', vals)
                flash(
                    'Course created. Use Content to add lessons and quizzes.',
                    'success',
                )
                return redirect(url_for('admin.courses'))
            except Exception:
                errs.append('That course code already exists.')

        for error in errs:
            flash(error, 'danger')

    return render_template(
        'form.html',
        title='Add course',
        fields=fields,
        vals=vals,
        back=url_for('admin.courses'),
    )


@bp.route('/courses/<int:cid>/edit', methods=['GET', 'POST'])
@admin
def course_edit(cid):
    fields = course_fields()

    vals = query(
        'SELECT * FROM courses WHERE id=%s',
        (cid,),
        True,
    ) or abort(404)

    if request.method == 'POST':
        vals, errs = read_form(fields, request.form)

        if not errs:
            vals['category'] = vals['category'] or 'General'
            vals['duration_hours'] = vals['duration_hours'] or 0

            try:
                update('courses', cid, vals)
                flash('Course updated.', 'success')
                return redirect(url_for('admin.courses'))
            except Exception:
                errs.append('That course code already exists.')

        for error in errs:
            flash(error, 'danger')

    return render_template(
        'form.html',
        title='Edit course',
        fields=fields,
        vals=vals,
        back=url_for('admin.courses'),
    )


@bp.route('/courses/<int:cid>/publish', methods=['POST'])
@admin
def course_publish(cid):
    execute(
        'UPDATE courses SET published=1-published WHERE id=%s',
        (cid,),
    )

    flash('Publication status changed.', 'success')
    return redirect(url_for('admin.courses'))


@bp.route('/courses/<int:cid>/delete', methods=['POST'])
@admin
def course_delete(cid):
    try:
        execute('DELETE FROM courses WHERE id=%s', (cid,))
        flash('Course deleted.', 'success')
    except Exception:
        flash(
            'This course has linked enrollments or quiz attempts. '
            'Unpublish it instead.',
            'danger',
        )

    return redirect(url_for('admin.courses'))


# --------------------------------------------------
# ENROLLMENTS
# --------------------------------------------------

@bp.route('/enrollments', methods=['GET', 'POST'])
@admin
def enrollments():
    if request.method == 'POST':
        cid = request.form.get('course_id', type=int)

        if not cid or not query(
            'SELECT id FROM courses WHERE id=%s',
            (cid,),
            True,
        ):
            abort(404)

        if request.form.get('mode') == 'one':
            student_code = request.form.get(
                'student_code', ''
            ).strip()

            student = query(
                'SELECT id FROM students WHERE student_code=%s',
                (student_code,),
                True,
            )

            if not student:
                flash('No student with that ID.', 'danger')
            else:
                already = query(
                    """
                    SELECT id FROM enrollments
                    WHERE student_id=%s
                      AND course_id=%s
                      AND status='enrolled'
                    """,
                    (student['id'], cid),
                    True,
                )

                if already:
                    flash('Student is already enrolled.', 'warning')
                else:
                    try:
                        with transaction() as cur:
                            cur.execute(
                                """
                                INSERT INTO enrollments
                                    (student_id, course_id, enrolled_on, status)
                                VALUES (%s, %s, CURRENT_DATE, 'enrolled')
                                """,
                                (student['id'], cid),
                            )
                        flash('Student enrolled.', 'success')
                    except Exception:
                        flash(
                            'Enrollment failed. Check the database schema.',
                            'danger',
                        )

        else:
            dept = request.form.get('department', '').strip()
            sem = request.form.get('semester', '').strip()

            conditions = [
                """
                NOT EXISTS (
                    SELECT 1
                    FROM enrollments e
                    WHERE e.student_id=s.id
                      AND e.course_id=%s
                      AND e.status='enrolled'
                )
                """
            ]
            params = [cid]

            if dept:
                conditions.append('s.department=%s')
                params.append(dept)

            if sem.isdigit() and 1 <= int(sem) <= 8:
                conditions.append('s.semester=%s')
                params.append(int(sem))

            try:
                with transaction() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO enrollments
                            (student_id, course_id, enrolled_on, status)
                        SELECT s.id, %s, CURRENT_DATE, 'enrolled'
                        FROM students s
                        WHERE {' AND '.join(conditions)}
                        """,
                        tuple([cid] + params),
                    )
                    count = cur.rowcount

                flash(f'{count} students enrolled.', 'success')

            except Exception:
                flash(
                    'Bulk enrollment failed. Check the enrollments table columns.',
                    'danger',
                )

        return redirect(url_for('admin.enrollments'))

    courses = query("""
        SELECT id, course_code, title
        FROM courses
        ORDER BY title
    """)

    depts = query("""
        SELECT DISTINCT department
        FROM students
        WHERE department IS NOT NULL
          AND department <> ''
        ORDER BY department
    """)

    rows = query("""
        SELECT
            e.id,
            s.student_code,
            s.full_name,
            c.course_code,
            c.title,
            e.enrolled_on,
            e.status
        FROM enrollments e
        JOIN students s ON s.id=e.student_id
        JOIN courses c ON c.id=e.course_id
        ORDER BY e.enrolled_on DESC, e.id DESC
    """)

    return render_template(
        'enrollments.html',
        courses=courses,
        depts=depts,
        rows=rows,
    )


@bp.route('/enrollments/<int:eid>/drop', methods=['POST'])
@admin
def enrollment_drop(eid):
    execute(
        "UPDATE enrollments SET status='dropped' WHERE id=%s",
        (eid,),
    )

    flash('Enrollment ended (history kept).', 'success')
    return redirect(url_for('admin.enrollments'))


# --------------------------------------------------
# EXCEL IMPORT AND EXPORT
# --------------------------------------------------

@bp.route('/excel', methods=['GET', 'POST'])
@admin
def excel():
    if request.method == 'POST':
        file = request.files.get('file')

        if not file or not file.filename.lower().endswith('.xlsx'):
            flash('Upload an .xlsx workbook.', 'danger')
        else:
            try:
                summary, problems = import_workbook(file)

                flash(
                    'Import finished: ' + '; '.join(
                        f"{key}: {value['created']} new, "
                        f"{value['updated']} updated, "
                        f"{value['skipped']} skipped"
                        for key, value in summary.items()
                    ),
                    'success',
                )

                for problem in problems:
                    flash(problem, 'warning')

            except Exception as error:
                flash(
                    f'Import failed: {str(error)[:150]}',
                    'danger',
                )

        return redirect(url_for('admin.excel'))

    return render_template('import_export.html')


@bp.route('/export/<kind>.xlsx')
@admin
def export(kind):
    buffer = export_workbook(kind) or abort(404)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'{kind}.xlsx',
        mimetype=(
            'application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.sheet'
        ),
    )
