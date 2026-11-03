
import re
import time
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    session,
    jsonify,
)

from .db import query, execute, transaction
from . import security as sec, analytics as an


bp = Blueprint("student", __name__)
student = sec.roles("student")

YT = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([\w-]{11})"
)


def sid():
    return session["user"]["student_id"]


def enrolled(cid):
    result = query(
        """
        SELECT e.id
        FROM enrollments e
        JOIN courses c ON c.id = e.course_id
        WHERE e.student_id = %s
          AND e.course_id = %s
          AND e.status = 'enrolled'
          AND c.published = 1
        """,
        (sid(), cid),
        True,
    )
    return result or abort(403)


def touch(lid, seconds=0, complete=False):
    now = datetime.now()

    r = query(
        """
        SELECT id, completed
        FROM lesson_progress
        WHERE student_id = %s AND lesson_id = %s
        """,
        (sid(), lid),
        True,
    )

    if not r:
        execute(
            """
            INSERT INTO lesson_progress
                (student_id, lesson_id, completed, completed_at,
                 seconds_spent, last_activity)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                sid(),
                lid,
                1 if complete else 0,
                now if complete else None,
                seconds,
                now,
            ),
        )
        return

    if complete and not r["completed"]:
        execute(
            """
            UPDATE lesson_progress
            SET completed = 1,
                completed_at = %s,
                seconds_spent = seconds_spent + %s,
                last_activity = %s
            WHERE id = %s
            """,
            (now, seconds, now, r["id"]),
        )
    else:
        execute(
            """
            UPDATE lesson_progress
            SET seconds_spent = seconds_spent + %s,
                last_activity = %s
            WHERE id = %s
            """,
            (seconds, now, r["id"]),
        )


@bp.route("/dashboard")
@student
def dashboard():
    profile = query(
        """
        SELECT student_code, full_name, department, semester
        FROM students
        WHERE id = %s
        """,
        (sid(),),
        True,
    )

    cs = an.student_courses(sid())
    labels, counts = an.trend(14, sid())

    att = query(
        """
        SELECT z.title, a.percentage, a.attempted_at, a.id
        FROM attempts a
        JOIN quizzes z ON z.id = a.quiz_id
        WHERE a.student_id = %s
        ORDER BY a.attempted_at DESC
        LIMIT 5
        """,
        (sid(),),
    )

    nxt = query(
        """
        SELECT l.id AS lid, l.title, c.id AS cid, c.title AS course
        FROM lessons l
        JOIN courses c ON c.id = l.course_id
        JOIN enrollments e
          ON e.course_id = c.id
         AND e.student_id = %s
         AND e.status = 'enrolled'
        LEFT JOIN lesson_progress p
          ON p.lesson_id = l.id
         AND p.student_id = e.student_id
         AND p.completed = 1
        WHERE p.id IS NULL
          AND c.published = 1
        ORDER BY e.enrolled_on DESC, c.id, l.id
        LIMIT 1
        """,
        (sid(),),
        True,
    )

    avg_row = query(
        """
        SELECT AVG(percentage) AS a
        FROM attempts
        WHERE student_id = %s
        """,
        (sid(),),
        True,
    )
    avg = avg_row["a"] if avg_row else None

    stats = {
        "courses": len(cs),
        "done": sum(
            1 for c in cs
            if str(c.get("status", "")).lower() in ("completed",)
        ),
        "minutes": sum(c.get("minutes", 0) or 0 for c in cs),
        "streak": an.streak(sid()),
        "avg": round(float(avg), 1) if avg is not None else None,
    }

    return render_template(
        "student_dashboard.html",
        profile=profile,
        cs=cs,
        att=att,
        nxt=nxt,
        stats=stats,
        data={
            "days": [label[5:] for label in labels],
            "daily": counts,
        },
    )


@bp.route("/courses")
@student
def courses():
    rows = query(
        """
        SELECT c.id, c.course_code, c.title, c.description,
               c.category, c.difficulty,
               s.full_name AS instructor,
               (SELECT COUNT(*)
                FROM lessons l
                WHERE l.course_id = c.id) AS lessons,
               (SELECT COUNT(*)
                FROM enrollments e
                WHERE e.course_id = c.id
                  AND e.student_id = %s
                  AND e.status = 'enrolled') AS mine
        FROM courses c
        LEFT JOIN staff s ON s.id = c.instructor_id
        WHERE c.published = 1
        ORDER BY c.title
        """,
        (sid(),),
    )

    return render_template("student_courses.html", rows=rows)


@bp.route("/courses/<int:cid>/enroll", methods=["POST"])
@student
def enroll(cid):
    course_row = query(
        """
        SELECT id
        FROM courses
        WHERE id = %s AND published = 1
        """,
        (cid,),
        True,
    )

    if not course_row:
        abort(404)

    success = an.enroll(sid(), cid)

    flash(
        "Enrolled. Happy learning!"
        if success
        else "You are already enrolled.",
        "success",
    )

    return redirect(url_for("student.course", cid=cid))


@bp.route("/courses/<int:cid>/unenroll", methods=["POST"])
@student
def unenroll(cid):
    enrolled(cid)

    execute(
        """
        UPDATE enrollments
        SET status = 'dropped'
        WHERE student_id = %s AND course_id = %s
        """,
        (sid(), cid),
    )

    flash(
        "You left the course. Your progress is kept if you rejoin.",
        "success",
    )
    return redirect(url_for("student.courses"))


@bp.route("/learn/<int:cid>")
@student
def course(cid):
    enrolled(cid)

    c = query(
        "SELECT * FROM courses WHERE id = %s",
        (cid,),
        True,
    )

    lessons = query(
        """
        SELECT l.*, COALESCE(p.completed, 0) AS done
        FROM lessons l
        LEFT JOIN lesson_progress p
          ON p.lesson_id = l.id
         AND p.student_id = %s
        WHERE l.course_id = %s
        ORDER BY l.id
        """,
        (sid(), cid),
    )

    quizzes = query(
        """
        SELECT z.id, z.title, z.pass_percent,
               (SELECT COUNT(*)
                FROM questions q
                WHERE q.quiz_id = z.id) AS nq,
               (SELECT MAX(a.percentage)
                FROM attempts a
                WHERE a.quiz_id = z.id
                  AND a.student_id = %s) AS best
        FROM quizzes z
        WHERE z.course_id = %s
        """,
        (sid(), cid),
    )

    done = sum(1 for lesson_row in lessons if lesson_row["done"])
    pct = round(100 * done / len(lessons), 1) if lessons else 0.0

    return render_template(
        "student_course.html",
        c=c,
        lessons=lessons,
        quizzes=quizzes,
        pct=pct,
    )


def lesson_ctx(lid):
    lesson_row = query(
        "SELECT * FROM lessons WHERE id = %s",
        (lid,),
        True,
    ) or abort(404)

    enrolled(lesson_row["course_id"])
    return lesson_row


@bp.route("/learn/lesson/<int:lid>")
@student
def lesson(lid):
    lesson_row = lesson_ctx(lid)
    touch(lid)

    ids = [
        row["id"]
        for row in query(
            """
            SELECT id
            FROM lessons
            WHERE course_id = %s
            ORDER BY id
            """,
            (lesson_row["course_id"],),
        )
    ]

    i = ids.index(lid)
    match = YT.search(lesson_row["content_url"] or "")

    progress = query(
        """
        SELECT completed
        FROM lesson_progress
        WHERE student_id = %s AND lesson_id = %s
        """,
        (sid(), lid),
        True,
    )

    return render_template(
        "lesson.html",
        l=lesson_row,
        embed=match.group(1) if match else None,
        done=bool(progress and progress["completed"]),
        prev=ids[i - 1] if i else None,
        nxt=ids[i + 1] if i + 1 < len(ids) else None,
    )


@bp.route("/learn/lesson/<int:lid>/complete", methods=["POST"])
@student
def complete(lid):
    lesson_row = lesson_ctx(lid)
    touch(lid, complete=True)

    flash("Lesson marked complete.", "success")

    ids = [
        row["id"]
        for row in query(
            """
            SELECT id
            FROM lessons
            WHERE course_id = %s
            ORDER BY id
            """,
            (lesson_row["course_id"],),
        )
    ]

    i = ids.index(lid)

    if i + 1 < len(ids):
        return redirect(url_for("student.lesson", lid=ids[i + 1]))

    return redirect(
        url_for("student.course", cid=lesson_row["course_id"])
    )


@bp.route("/learn/lesson/<int:lid>/ping", methods=["POST"])
@student
def ping(lid):
    """Measure active page time, not actual attention."""
    lesson_ctx(lid)

    key = f"ping{lid}"
    now = time.time()
    last = session.get(key, 0)
    session[key] = now

    seconds = 30 if not last or now - last > 40 else int(now - last)
    touch(lid, seconds=seconds)

    return jsonify(ok=True)


@bp.route("/learn/quiz/<int:qid>", methods=["GET", "POST"])
@student
def quiz(qid):
    z = query(
        "SELECT * FROM quizzes WHERE id = %s",
        (qid,),
        True,
    ) or abort(404)

    enrolled(z["course_id"])

    qs = query(
        """
        SELECT id, question_text, option_a, option_b,
               option_c, option_d, marks
        FROM questions
        WHERE quiz_id = %s
        ORDER BY id
        """,
        (qid,),
    )

    if request.method == "POST":
        if not qs:
            flash("This quiz has no questions yet.", "warning")
            return redirect(
                url_for("student.course", cid=z["course_id"])
            )

        key = {
            q["id"]: q
            for q in query(
                """
                SELECT id, correct_option, marks
                FROM questions
                WHERE quiz_id = %s
                """,
                (qid,),
            )
        }

        score = 0
        answers = []

        for question_id, question in key.items():
            choice = request.form.get(f"q{question_id}", "")
            choice = choice if choice in ("A", "B", "C", "D") else None

            if choice == question["correct_option"]:
                score += question["marks"]

            answers.append((question_id, choice))

        max_marks = sum(q["marks"] for q in key.values())
        percentage = (
            round(100 * score / max_marks, 2)
            if max_marks else 0
        )

        with transaction() as cur:
            cur.execute(
                """
                INSERT INTO attempts
                    (quiz_id, student_id, score, max_marks,
                     percentage, attempted_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    qid,
                    sid(),
                    score,
                    max_marks,
                    percentage,
                    datetime.now(),
                ),
            )

            aid = cur.lastrowid

            for question_id, choice in answers:
                cur.execute(
                    """
                    INSERT INTO attempt_answers
                        (attempt_id, question_id, chosen)
                    VALUES (%s, %s, %s)
                    """,
                    (aid, question_id, choice),
                )

        return redirect(url_for("student.attempt", aid=aid))

    return render_template("quiz_take.html", z=z, qs=qs)


@bp.route("/learn/attempt/<int:aid>")
@student
def attempt(aid):
    a = query(
        """
        SELECT a.*, z.title, z.pass_percent, z.course_id
        FROM attempts a
        JOIN quizzes z ON z.id = a.quiz_id
        WHERE a.id = %s AND a.student_id = %s
        """,
        (aid, sid()),
        True,
    ) or abort(404)

    rows = query(
        """
        SELECT q.question_text, q.option_a, q.option_b,
               q.option_c, q.option_d, q.correct_option, x.chosen
        FROM attempt_answers x
        JOIN questions q ON q.id = x.question_id
        WHERE x.attempt_id = %s
        ORDER BY q.id
        """,
        (aid,),
    )

    return render_template(
        "attempt.html",
        a=a,
        rows=rows,
        passed=float(a["percentage"]) >= float(a["pass_percent"]),
    )
