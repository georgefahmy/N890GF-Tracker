import sqlite3

from werkzeug.security import generate_password_hash

conn = sqlite3.connect("src/maintenance.db")
username = "admin"
password = "admin"
conn.execute(
    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
    (username, generate_password_hash(password)),
)

conn.commit()

conn.close()
