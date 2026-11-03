import os
from contextlib import contextmanager
from dotenv import load_dotenv
from mysql.connector import pooling
load_dotenv()
_pool = None

def init_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(pool_name='lm_pool', pool_size=5,
            host=os.getenv('DB_HOST', 'localhost'), port=int(os.getenv('DB_PORT', '3306')),
            user=os.getenv('DB_USER', 'root'), password=os.getenv('DB_PASSWORD', ''),
            database=os.getenv('DB_NAME', 'elearning_course_analytics'), charset='utf8mb4')

def query(sql, params=(), one=False):
    """Parameterized SELECT. Values always travel in params, never inside the SQL text."""
    conn = _pool.get_connection(); cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        cur.close(); conn.close()

def execute(sql, params=()):
    conn = _pool.get_connection(); cur = conn.cursor()
    try:
        cur.execute(sql, params); conn.commit(); return cur.lastrowid
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()

@contextmanager
def transaction():
    """Several statements succeed together or not at all."""
    conn = _pool.get_connection(); cur = conn.cursor(dictionary=True)
    try:
        yield cur; conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()
