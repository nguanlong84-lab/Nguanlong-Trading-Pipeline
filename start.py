"""
start.py — ตัวเลือกว่าจะรันอะไร ตาม env var SERVICE_ROLE
  SERVICE_ROLE=pipeline (ค่าเริ่มต้น) -> migrate + run.py   (ตั้ง cron ให้ service นี้)
  SERVICE_ROLE=dashboard              -> streamlit dashboard (web, always-on, มี public domain)

ทั้งสอง Railway service ใช้ repo เดียวกัน + railpack startCommand เดียวกัน (python start.py)
ต่างกันแค่ตั้ง SERVICE_ROLE ของ dashboard service = dashboard
"""
import os
import sys
import subprocess

role = os.environ.get("SERVICE_ROLE", "pipeline")

if role == "dashboard":
    port = os.environ.get("PORT", "8501")
    sys.exit(subprocess.call([
        "streamlit", "run", "dashboard.py",
        "--server.port", port,
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
    ]))
else:
    subprocess.check_call(["python", "migrate.py"])
    sys.exit(subprocess.call(["python", "run.py"]))
