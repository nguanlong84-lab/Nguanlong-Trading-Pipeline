"""
migrate.py — สร้างตารางในฐานข้อมูลจาก schema.sql (idempotent, รันซ้ำได้)
ใช้แทนการเปิด Data tab ของ Railway — เรียกก่อน run.py ตอน start
"""
import os
import psycopg2

with open("schema.sql", "r", encoding="utf-8") as f:
    ddl = f.read()

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = True
conn.cursor().execute(ddl)
conn.close()
print("schema applied (tables ready)")
