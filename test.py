import os
import sqlite3

from dotmap import DotMap

CWD_PATH = os.getcwd()
DB_PATH = CWD_PATH + "/../maintenance.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = lambda cursor, row: {
        col[0]: row[idx] for idx, col in enumerate(cursor.description)
    }
    return conn


conn = get_db_connection()

cur = conn.execute("SELECT * FROM flight_log ORDER BY date ASC, id ASC")
rows = cur.fetchall()
data = DotMap({i: r for i, r in enumerate(rows)})
