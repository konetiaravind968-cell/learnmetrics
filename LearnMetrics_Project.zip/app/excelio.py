import io, re
from openpyxl import Workbook, load_workbook
from .db import transaction, query
from .analytics import progress_rows

ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'VII': 7, 'VIII': 8}
DIFF = ('Beginner', 'Intermediate', 'Advanced')

def clean(v): return re.sub(r'\s+', ' ', str(v if v is not None else '')).strip()

def semester(v):
    s = clean(v).upper()
    if not s: return 1
    n = ROMAN.get(s) or int(float(s))
    if not 1 <= n <= 8: raise ValueError('semester must be 1-8')
    return n

def _rows(wb, name):
    if name not in wb.sheetnames: return []
    it = wb[name].iter_rows(values_only=True)
    keys = [clean(h).lower() for h in next(it, ())]
    return [{k: row[i] if i < len(row) else None for i, k in enumerate(keys) if k}
            for row in it if any(clean(c) for c in row)]

def import_workbook(fileobj):
    """Upsert Students, Staff and Courses sheets. Returns (summary dict, list of problems)."""
    wb = load_workbook(fileobj, read_only=True, data_only=True)
    summary, problems = {}, []
    with transaction() as cur:
        def upsert(table, key, vals):
            cur.execute(f'SELECT id FROM {table} WHERE {key}=%s', (vals[key],)); r = cur.fetchone()
            cols = list(vals)
            if r:
                cur.execute(f"UPDATE {table} SET {','.join(c + '=%s' for c in cols)} WHERE id=%s", tuple(vals[c] for c in cols) + (r['id'],))
            else:
                cur.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join(['%s'] * len(cols))})", tuple(vals[c] for c in cols))
            return 'updated' if r else 'created'
        for sheet, table, key, need in (('Students', 'students', 'student_code', ('student_code', 'full_name', 'email')),
                                        ('Staff', 'staff', 'staff_code', ('staff_code', 'full_name', 'email')),
                                        ('Courses', 'courses', 'course_code', ('course_code', 'title'))):
            c = {'created': 0, 'updated': 0, 'skipped': 0}
            for i, r in enumerate(_rows(wb, sheet), 2):
                try:
                    if not all(clean(r.get(k)) for k in need): raise ValueError('missing ' + '/'.join(need))
                    if table == 'students':
                        v = dict(student_code=clean(r['student_code']), full_name=clean(r['full_name']), email=clean(r['email']).lower(),
                                 department=clean(r.get('department')) or 'CSE', semester=semester(r.get('semester')))
                    elif table == 'staff':
                        v = dict(staff_code=clean(r['staff_code']), full_name=clean(r['full_name']), email=clean(r['email']).lower(),
                                 department=clean(r.get('department')) or None)
                    else:
                        d = clean(r.get('difficulty')).title()
                        v = dict(course_code=clean(r['course_code']), title=clean(r['title']), description=clean(r.get('description')) or None,
                                 category=clean(r.get('category')) or 'General', difficulty=d if d in DIFF else 'Beginner',
                                 duration_hours=float(clean(r.get('duration_hours')) or 0),
                                 published=1 if clean(r.get('published')).lower() in ('1', 'yes', 'true') else 0)
                        ic = clean(r.get('instructor_code'))
                        if ic:
                            cur.execute('SELECT id FROM staff WHERE staff_code=%s', (ic,)); s = cur.fetchone()
                            v['instructor_id'] = s['id'] if s else None
                    c[upsert(table, key, v)] += 1
                except Exception as e:
                    c['skipped'] += 1
                    if len(problems) < 15: problems.append(f'{sheet} row {i}: {str(e)[:90]}')
            summary[sheet] = c
    return summary, problems

def export_workbook(kind):
    sql = {'students': 'SELECT student_code,full_name,email,department,semester FROM students ORDER BY student_code',
           'staff': 'SELECT staff_code,full_name,email,department FROM staff ORDER BY staff_code',
           'courses': """SELECT c.course_code,c.title,c.description,c.category,c.difficulty,c.duration_hours,s.staff_code instructor_code,c.published
                         FROM courses c LEFT JOIN staff s ON s.id=c.instructor_id ORDER BY c.course_code""",
           'enrollments': """SELECT s.student_code,c.course_code,e.enrolled_at,e.status FROM enrollments e
                             JOIN students s ON s.id=e.student_id JOIN courses c ON c.id=e.course_id ORDER BY c.course_code,s.student_code"""}
    if kind == 'progress':
        rows = [dict(student_code=r['student_code'], name=r['full_name'], course=r['course_code'], lessons_done=int(r['done']), lessons_total=int(r['total']),
                     percent=r['percent'], minutes=r['minutes'], avg_quiz=r['avg_quiz'], last_activity=str(r['last_activity'] or '')[:16]) for r in progress_rows()]
    elif kind in sql: rows = query(sql[kind])
    else: return None
    wb = Workbook(); ws = wb.active; ws.title = kind.title()
    if rows:
        ws.append(list(rows[0].keys()))
        for r in rows: ws.append([float(v) if hasattr(v, 'as_tuple') else v for v in r.values()])
    else: ws.append(['No records'])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return buf
