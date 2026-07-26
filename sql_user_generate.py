import os
import sqlite3

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(BASE_DIR, "instance", "maintenance.db")

conn = sqlite3.connect(db_path)
username = "admin"
password = "admin"
conn.execute(
    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
    (username, generate_password_hash(password)),
)

conn.commit()
conn.close()
