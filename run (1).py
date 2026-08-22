"""
run.py — รันหนึ่งรอบ (cron-friendly). ตั้ง Railway cron ให้เรียกไฟล์นี้ตามความถี่

  python run.py --plan     ดูว่ารอบนี้จะรันแหล่งไหน (ไม่ต้องต่อ DB/เน็ต)
  python run.py --phase 1  รันเฉพาะ collectors Phase 1
  python run.py            รันทั้งหมดที่ active + ถึงกำหนด แล้ว upsert เข้า DB

ตั้งค่า DB ผ่าน env: DATABASE_URL (Railway ให้มาอยู่แล้ว)
"""
import os, sys, argparse
from datetime import date
from collectors import sources_as_dicts, COLLECTORS


def is_due(freq: str, today: date) -> bool:
    """กติกาง่ายๆ: daily=ทุกวัน, weekly=จันทร์, monthly=วันที่ 1, event=ข้าม (ดึงมือ)"""
    if freq == "daily":   return True
    if freq == "weekly":  return today.weekday() == 0
    if freq == "monthly": return today.day == 1
    return False


def plan(today, phase=None):
    rows = []
    for s in sources_as_dicts():
        if phase and s["phase"] != phase:
            continue
        due = s["method"] != "manual" and is_due(s["frequency"], today)
        rows.append((s["source_id"], s["layer"], s["frequency"], s["phase"],
                     "DUE" if due else "skip"))
    w = max(len(r[0]) for r in rows)
    print(f"{'source':<{w}}  layer    freq     ph  status")
    print("-" * (w + 32))
    for sid, layer, freq, ph, st in rows:
        print(f"{sid:<{w}}  {layer:<7}  {freq:<7}  {ph}   {st}")


def upsert_sources(cur):
    for s in sources_as_dicts():
        cur.execute("""
            INSERT INTO sources (source_id,label,layer,commodity,method,frequency,unit)
            VALUES (%(source_id)s,%(label)s,%(layer)s,%(commodity)s,%(method)s,%(frequency)s,%(unit)s)
            ON CONFLICT (source_id) DO UPDATE SET
              label=EXCLUDED.label, layer=EXCLUDED.layer, commodity=EXCLUDED.commodity,
              method=EXCLUDED.method, frequency=EXCLUDED.frequency, unit=EXCLUDED.unit
        """, s)


def run(today, phase=None):
    import psycopg2
    from psycopg2.extras import Json
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    cur = conn.cursor()
    upsert_sources(cur)

    for s in sources_as_dicts():
        sid, freq, method = s["source_id"], s["frequency"], s["method"]
        if phase and s["phase"] != phase:               continue
        if method == "manual" or not is_due(freq, today): continue
        try:
            rows = COLLECTORS[sid]()
            for obs_date, value, meta in rows:
                cur.execute("""
                    INSERT INTO observations (source_id,obs_date,value,meta)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (source_id,obs_date) DO UPDATE
                      SET value=EXCLUDED.value, meta=EXCLUDED.meta, ingested_at=now()
                """, (sid, obs_date, value, Json(meta)))
            cur.execute("INSERT INTO ingest_runs (source_id,status,rows) VALUES (%s,'ok',%s)",
                        (sid, len(rows)))
            print(f"  ok   {sid}: {len(rows)} row(s)")
        except NotImplementedError as e:
            cur.execute("INSERT INTO ingest_runs (source_id,status,message) VALUES (%s,'skipped',%s)",
                        (sid, str(e)))
            print(f"  --   {sid}: {e}")
        except Exception as e:
            cur.execute("INSERT INTO ingest_runs (source_id,status,message) VALUES (%s,'error',%s)",
                        (sid, str(e)))
            print(f"  ERR  {sid}: {e}")
    cur.close(); conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--phase", type=int, default=None)
    a = ap.parse_args()
    today = date.today()
    if a.plan:
        plan(today, a.phase)
    else:
        run(today, a.phase)
