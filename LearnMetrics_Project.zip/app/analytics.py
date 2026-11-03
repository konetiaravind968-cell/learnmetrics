
"""All numbers on every dashboard and report come from these SQL queries."""

from datetime import datetime, date, timedelta

from .db import query, execute


ACTIVE_ENROLLMENT = "enrolled"


def course_stats(staff_id=None):
    where_clause = (
        "WHERE c.instructor_id=%s" if staff_id else ""
    )
    params = (staff_id,) if staff_id else ()

    rows = query(
        f"""
        SELECT
            c.id,
            c.course_code,
            c.title,

            (
                SELECT COUNT(*)
                FROM enrollments e
                WHERE e.course_id = c.id
                  AND e.status = 'enrolled'
            ) AS enrolled,

            (
                SELECT COUNT(*)
                FROM lessons l
                WHERE l.course_id = c.id
            ) AS lessons,

            (
                SELECT COUNT(*)
                FROM lesson_progress lp
                JOIN lessons l ON l.id = lp.lesson_id
                JOIN enrollments e
                  ON e.student_id = lp.student_id
                 AND e.course_id = l.course_id
                 AND e.status = 'enrolled'
                WHERE l.course_id = c.id
                  AND lp.completed = 1
            ) AS done,

            (
                SELECT AVG(a.percentage)
                FROM attempts a
                JOIN quizzes z ON z.id = a.quiz_id
                WHERE z.course_id = c.id
            ) AS avg_score

        FROM courses c
        {where_clause}
        ORDER BY c.title
        """,
        params,
    )

    for row in rows:
        total = int(row["enrolled"]) * int(row["lessons"])

        row["completion"] = (
            round(100 * int(row["done"]) / total, 1)
            if total else 0.0
        )

        row["avg_score"] = (
            round(float(row["avg_score"]), 1)
            if row["avg_score"] is not None else None
        )

    return rows


def trend(days=14, sid=None):
    days = max(1, int(days))

    start = (
        datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        - timedelta(days=days - 1)
    )

    if sid is not None:
        condition = "AND student_id = %s"
        params = (start, sid)
    else:
        condition = ""
        params = (start,)

    rows = query(
        f"""
        SELECT DATE(completed_at) AS d, COUNT(*) AS n
        FROM lesson_progress
        WHERE completed = 1
          AND completed_at >= %s
          {condition}
        GROUP BY DATE(completed_at)
        """,
        params,
    )

    values = {
        str(row["d"])[:10]: int(row["n"])
        for row in rows
    }

    labels = [
        (start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days)
    ]

    return labels, [values.get(label, 0) for label in labels]


def inactive(days=14):
    cut = datetime.now() - timedelta(days=days)

    return query(
        """
        SELECT
            s.student_code,
            s.full_name,
            MAX(lp.last_activity) AS last_activity

        FROM students s

        JOIN enrollments e
          ON e.student_id = s.id
         AND e.status = 'enrolled'

        LEFT JOIN lesson_progress lp
          ON lp.student_id = s.id

        GROUP BY s.id, s.student_code, s.full_name

        HAVING MAX(lp.last_activity) IS NULL
            OR MAX(lp.last_activity) < %s

        ORDER BY last_activity
        LIMIT 10
        """,
        (cut,),
    )


def streak(sid):
    rows = query(
        """
        SELECT DISTINCT DATE(last_activity) AS d
        FROM lesson_progress
        WHERE student_id = %s
          AND last_activity IS NOT NULL
        """,
        (sid,),
    )

    days = {str(row["d"])[:10] for row in rows}

    current_day = date.today()

    if current_day.isoformat() not in days:
        current_day -= timedelta(days=1)

    count = 0

    while current_day.isoformat() in days:
        count += 1
        current_day -= timedelta(days=1)

    return count


def progress_rows(course_id=None, staff_id=None):
    conditions = ["e.status = 'enrolled'"]
    params = []

    if course_id is not None:
        conditions.append("c.id = %s")
        params.append(course_id)

    if staff_id is not None:
        conditions.append("c.instructor_id = %s")
        params.append(staff_id)

    rows = query(
        f"""
        SELECT
            s.student_code,
            s.full_name,
            c.course_code,
            c.title,

            (
                SELECT COUNT(*)
                FROM lessons l
                WHERE l.course_id = c.id
            ) AS total,

            (
                SELECT COUNT(*)
                FROM lesson_progress lp
                JOIN lessons l ON l.id = lp.lesson_id
                WHERE l.course_id = c.id
                  AND lp.student_id = s.id
                  AND lp.completed = 1
            ) AS done,

            (
                SELECT COALESCE(SUM(lp.seconds_spent), 0)
                FROM lesson_progress lp
                JOIN lessons l ON l.id = lp.lesson_id
                WHERE l.course_id = c.id
                  AND lp.student_id = s.id
            ) AS secs,

            (
                SELECT MAX(lp.last_activity)
                FROM lesson_progress lp
                JOIN lessons l ON l.id = lp.lesson_id
                WHERE l.course_id = c.id
                  AND lp.student_id = s.id
            ) AS last_activity,

            (
                SELECT AVG(a.percentage)
                FROM attempts a
                JOIN quizzes z ON z.id = a.quiz_id
                WHERE z.course_id = c.id
                  AND a.student_id = s.id
            ) AS avg_quiz

        FROM enrollments e
        JOIN students s ON s.id = e.student_id
        JOIN courses c ON c.id = e.course_id

        WHERE {" AND ".join(conditions)}

        ORDER BY c.course_code, s.full_name
        """,
        tuple(params),
    )

    for row in rows:
        total = int(row["total"])
        done = int(row["done"])

        row["percent"] = (
            round(100 * done / total, 1)
            if total else 0.0
        )

        row["minutes"] = round(int(row["secs"]) / 60)

        row["avg_quiz"] = (
            round(float(row["avg_quiz"]), 1)
            if row["avg_quiz"] is not None else None
        )

    return rows


def student_courses(sid):
    rows = query(
        """
        SELECT
            c.id,
            c.course_code,
            c.title,

            (
                SELECT COUNT(*)
                FROM lessons l
                WHERE l.course_id = c.id
            ) AS total,

            (
                SELECT COUNT(*)
                FROM lesson_progress lp
                JOIN lessons l ON l.id = lp.lesson_id
                WHERE l.course_id = c.id
                  AND lp.student_id = e.student_id
                  AND lp.completed = 1
            ) AS done,

            (
                SELECT COALESCE(SUM(lp.seconds_spent), 0)
                FROM lesson_progress lp
                JOIN lessons l ON l.id = lp.lesson_id
                WHERE l.course_id = c.id
                  AND lp.student_id = e.student_id
            ) AS secs

        FROM enrollments e
        JOIN courses c ON c.id = e.course_id

        WHERE e.student_id = %s
          AND e.status = 'enrolled'
          AND c.published = 1

        ORDER BY c.title
        """,
        (sid,),
    )

    for row in rows:
        total = int(row["total"])
        done = int(row["done"])
        seconds = int(row["secs"])

        row["percent"] = (
            round(100 * done / total, 1)
            if total else 0.0
        )

        row["status"] = (
            "Completed"
            if total and done >= total
            else "In progress"
            if done or seconds
            else "Not started"
        )

        row["minutes"] = round(seconds / 60)

    return rows


def enroll(sid, cid):
    existing = query(
        """
        SELECT id, status
        FROM enrollments
        WHERE student_id = %s AND course_id = %s
        """,
        (sid, cid),
        True,
    )

    if existing and existing["status"] == "enrolled":
        return False

    if existing:
        execute(
            """
            UPDATE enrollments
            SET status = 'enrolled'
            WHERE id = %s
            """,
            (existing["id"],),
        )
    else:
        execute(
            """
            INSERT INTO enrollments
                (student_id, course_id, enrolled_on, status)
            VALUES (%s, %s, CURDATE(), 'enrolled')
            """,
            (sid, cid),
        )

    return True
