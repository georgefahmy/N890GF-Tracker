import sqlite3

from werkzeug.security import generate_password_hash

conn = sqlite3.connect("../maintenance.db")
username = "admin"
password = "admin"
conn.execute(
    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
    (username, generate_password_hash(password)),
)

conn.commit()
conn.close()
