import csv
import io

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    session,
    Response,
)

from .db import query, execute
from . import security as sec, analytics as an
from .forms import F, read_form, insert, update


bp = Blueprint("course", __name__)
staff_admin = sec.roles("admin", "staff")


LESSON_FIELDS = [
    F("title", "Lesson title", r=1),
    F(
        "content_type",
        "Content type",
        "select",
        1,
        [(t, t.title()) for t in ("video", "document", "text", "link")],
    ),
    F("content_url", "Content link (YouTube / document / website)", "url"),
    F("body", "Text content (lesson notes)", "textarea"),
    F("position", "Order number (blank = last)", "number", lo=1),
    F("duration_minutes", "Duration (minutes)", "number", lo=0),
]

QUIZ_FIELDS = [
    F("title", "Quiz title", r=1),
    F("pass_percent", "Pass mark (%)", "number", 1, lo=0, hi=100),
]

QUESTION_FIELDS = [
    F("question_text", "Question", "textarea", 1),
    F("option_a", "Option A", r=1),
    F("option_b", "Option B", r=1),
    F("option_c", "Option C"),
    F("option_d", "Option D"),
    F("correct_option", "Correct option", "select", 1,
      [(x, x) for x in "ABCD"]),
    F("marks", "Marks", "number", 1, lo=1, hi=100),
]


def own_course(cid):
    course = query(
        "SELECT * FROM courses WHERE id=%s",
        (cid,),
        True,
    )

    if not course:
        abort(404)

    user = session["user"]

    if (
        user["role"] == "staff"
        and course["instructor_id"] != user["staff_id"]
    ):
        abort(403)

    return course


@bp.route("/staff")
@sec.roles("staff")
def staff_dashboard():
    cs = an.course_stats(session["user"]["staff_id"])

    data = {
        "titles": [c["course_code"] for c in cs],
        "completion": [c["completion"] for c in cs],
    }

    return render_template(
        "staff_dashboard.html",
        cs=cs,
        data=data,
    )


@bp.route("/course/<int:cid>")
@staff_admin
def manage(cid):
    course = own_course(cid)

    lessons = query(
        """
        SELECT l.*,
               l.sort_order AS position,
               l.lesson_type AS content_type
        FROM lessons l
        WHERE l.course_id = %s
        ORDER BY l.sort_order, l.id
        """,
        (cid,),
    )

    quizzes = query(
        """
        SELECT z.*,
               (
                   SELECT COUNT(*)
                   FROM questions x
                   WHERE x.quiz_id = z.id
               ) AS nq
        FROM quizzes z
        WHERE z.course_id = %s
        ORDER BY z.id
        """,
        (cid,),
    )

    lesson_id = request.args.get("lesson", type=int)

    edit = next(
        (
            lesson for lesson in lessons
            if lesson["id"] == lesson_id
        ),
        None,
    )

    return render_template(
        "course_manage.html",
        c=course,
        lessons=lessons,
        quizzes=quizzes,
        lf=LESSON_FIELDS,
        qf=QUESTION_FIELDS,
        edit=edit,
        vals=edit or {"content_type": "video"},
    )


@bp.route("/course/<int:cid>/lesson", methods=["POST"])
@staff_admin
def lesson_save(cid):
    """Create or update a lesson, including its link and notes."""
    own_course(cid)
    lesson_id = request.form.get("id", type=int)

    if lesson_id and not query(
        "SELECT id FROM lessons WHERE id=%s AND course_id=%s",
        (lesson_id, cid),
        True,
    ):
        abort(404)

    values, errors = read_form(LESSON_FIELDS, request.form)

    if not errors:
        title = (values.get("title") or "").strip()
        lesson_type = (
            values.get("content_type") or "video"
        ).strip().lower()
        content_url = (
            (values.get("content_url") or "").strip() or None
        )
        body = (values.get("body") or "").strip() or None
        duration = values.get("duration_minutes") or 0
        position = values.get("position")

        if lesson_type not in ("video", "document", "text", "link"):
            errors.append("Choose a valid content type.")

        if not errors:
            if position is None:
                row = query(
                    """
                    SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order
                    FROM lessons
                    WHERE course_id = %s
                    """,
                    (cid,),
                    True,
                )
                position = row["next_order"]

            try:
                if lesson_id:
                    execute(
                        """
                        UPDATE lessons
                        SET title=%s,
                            lesson_type=%s,
                            content_url=%s,
                            body=%s,
                            duration_minutes=%s,
                            sort_order=%s
                        WHERE id=%s AND course_id=%s
                        """,
                        (
                            title,
                            lesson_type,
                            content_url,
                            body,
                            duration,
                            position,
                            lesson_id,
                            cid,
                        ),
                    )
                else:
                    execute(
                        """
                        INSERT INTO lessons
                            (course_id, title, lesson_type, content_url,
                             body, duration_minutes, sort_order)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            cid,
                            title,
                            lesson_type,
                            content_url,
                            body,
                            duration,
                            position,
                        ),
                    )

                flash(
                    "Lesson saved, including its content link and notes.",
                    "success",
                )

            except Exception:
                flash(
                    "Could not save the lesson. Check the Flask terminal "
                    "for the database error.",
                    "danger",
                )

    for error in errors:
        flash(error, "danger")

    return redirect(url_for("course.manage", cid=cid))


@bp.route("/lesson/<int:lid>/delete", methods=["POST"])
@staff_admin
def lesson_delete(lid):
    lesson = query(
        "SELECT course_id FROM lessons WHERE id=%s",
        (lid,),
        True,
    )

    if not lesson:
        abort(404)

    own_course(lesson["course_id"])

    try:
        execute("DELETE FROM lessons WHERE id=%s", (lid,))
        flash("Lesson deleted.", "success")
    except Exception:
        flash(
            "Could not delete the lesson. Existing student progress "
            "may reference it.",
            "danger",
        )

    return redirect(
        url_for("course.manage", cid=lesson["course_id"])
    )


@bp.route("/course/<int:cid>/quiz", methods=["POST"])
@staff_admin
def quiz_save(cid):
    own_course(cid)
    values, errors = read_form(QUIZ_FIELDS, request.form)

    if not errors:
        values["course_id"] = cid

        try:
            insert("quizzes", values)
            flash("Quiz created. Open it to add questions.", "success")
        except Exception:
            flash(
                "Could not create the quiz. Check the Flask terminal.",
                "danger",
            )

    for error in errors:
        flash(error, "danger")

    return redirect(url_for("course.manage", cid=cid))


def own_quiz(qid):
    quiz = query(
        "SELECT * FROM quizzes WHERE id=%s",
        (qid,),
        True,
    )

    if not quiz:
        abort(404)

    own_course(quiz["course_id"])
    return quiz


@bp.route("/quiz/<int:qid>/delete", methods=["POST"])
@staff_admin
def quiz_delete(qid):
    quiz = own_quiz(qid)

    try:
        execute("DELETE FROM quizzes WHERE id=%s", (qid,))
        flash("Quiz deleted.", "success")
    except Exception:
        flash(
            "Students may have attempted this quiz, so it could not "
            "be deleted.",
            "danger",
        )

    return redirect(
        url_for("course.manage", cid=quiz["course_id"])
    )


@bp.route("/quiz/<int:qid>")
@staff_admin
def quiz_manage(qid):
    quiz = own_quiz(qid)

    questions = query(
        """
        SELECT q.*,
               COUNT(a.id) AS answered,
               COALESCE(
                   SUM(
                       CASE
                           WHEN a.chosen = q.correct_option THEN 1
                           ELSE 0
                       END
                   ),
                   0
               ) AS correct
        FROM questions q
        LEFT JOIN attempt_answers a ON a.question_id = q.id
        WHERE q.quiz_id = %s
        GROUP BY q.id, q.quiz_id, q.question_text,
                 q.option_a, q.option_b, q.option_c,
                 q.option_d, q.correct_option, q.marks
        ORDER BY q.id
        """,
        (qid,),
    )

    for question in questions:
        question["pct"] = (
            round(
                100 * int(question["correct"])
                / int(question["answered"]),
                1,
            )
            if question["answered"]
            else None
        )

    question_id = request.args.get("question", type=int)

    edit = next(
        (
            question for question in questions
            if question["id"] == question_id
        ),
        None,
    )

    return render_template(
        "quiz_manage.html",
        z=quiz,
        qs=questions,
        qf=QUESTION_FIELDS,
        edit=edit,
        vals=edit or {"correct_option": "A", "marks": 1},
    )


@bp.route("/quiz/<int:qid>/question", methods=["POST"])
@staff_admin
def question_save(qid):
    own_quiz(qid)
    question_id = request.form.get("id", type=int)

    if question_id and not query(
        "SELECT id FROM questions WHERE id=%s AND quiz_id=%s",
        (question_id, qid),
        True,
    ):
        abort(404)

    values, errors = read_form(QUESTION_FIELDS, request.form)

    if not errors:
        values["quiz_id"] = qid

        try:
            if question_id:
                update("questions", question_id, values)
            else:
                insert("questions", values)

            flash("Question saved.", "success")
        except Exception:
            flash(
                "Could not save the question. Check the Flask terminal.",
                "danger",
            )

    for error in errors:
        flash(error, "danger")

    return redirect(url_for("course.quiz_manage", qid=qid))


@bp.route("/question/<int:xid>/delete", methods=["POST"])
@staff_admin
def question_delete(xid):
    question = query(
        "SELECT quiz_id FROM questions WHERE id=%s",
        (xid,),
        True,
    )

    if not question:
        abort(404)

    own_quiz(question["quiz_id"])

    try:
        execute("DELETE FROM questions WHERE id=%s", (xid,))
        flash("Question deleted.", "success")
    except Exception:
        flash(
            "Could not delete the question. Existing quiz attempts "
            "may reference it.",
            "danger",
        )

    return redirect(
        url_for("course.quiz_manage", qid=question["quiz_id"])
    )


@bp.route("/course/<int:cid>/roster")
@staff_admin
def roster(cid):
    course = own_course(cid)
    rows = an.progress_rows(course_id=cid)

    return render_template(
        "roster.html",
        c=course,
        rows=rows[:300],
        total=len(rows),
    )


@bp.route("/course/<int:cid>/roster.csv")
@staff_admin
def roster_csv(cid):
    course = own_course(cid)
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "student_id",
        "name",
        "lessons_done",
        "lessons_total",
        "percent",
        "minutes",
        "avg_quiz_percent",
        "last_activity",
    ])

    for row in an.progress_rows(course_id=cid):
        writer.writerow([
            row["student_code"],
            row["full_name"],
            row["done"],
            row["total"],
            row["percent"],
            row["minutes"],
            (
                row["avg_quiz"]
                if row["avg_quiz"] is not None
                else ""
            ),
            str(row["last_activity"] or "")[:16],
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                f"attachment; filename={course['course_code']}_roster.csv"
        },
    )