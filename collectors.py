"""
collectors.py — ทะเบียนแหล่งข้อมูล + วิธีดึงแต่ละแหล่ง
เริ่ม external-first: Phase 1 = API ที่ไม่ต้อง auth, Phase 2 = scrape ไทย (เติมทีหลัง)

collector หนึ่งตัว = ฟังก์ชันที่คืน list ของ (obs_date: date, value: float, meta: dict)
เพิ่มแหล่งใหม่ = เพิ่ม entry ใน SOURCES + เขียนฟังก์ชัน collect_<id>
"""
from __future__ import annotations
import re
from datetime import date, timedelta

# ------------------------------------------------------------------
# ทะเบียนแหล่ง — ตรงกับ workbook (ชีต "สเปกตัวแปร") เฉพาะ external
# phase: 1 = ทำเลยได้ (API), 2 = ต้อง inspect หน้าเว็บก่อน (scrape)
# ------------------------------------------------------------------
SOURCES = [
    # id,            label,                       layer,   commodity, method,  frequency, unit,     phase
    ("fx_usdthb",    "USD/THB",                   "world", None,      "api",   "daily",   "THB/USD", 1),
    ("enso_oni",     "ENSO / ONI index",          "driver",None,      "api",   "monthly", "index",   1),
    ("cbot_corn",    "CBOT Corn (ZC)",            "world", "corn",    "api",   "daily",   "USd/bu",  2),
    ("trea_a1_fob",  "TREA A1 Super (ปลายข้าว)",   "world", "broken",  "scrape","weekly",  "USD/ton", 2),
    ("trea_wr5_fob", "TREA ข้าวขาว 5% FOB",        "world", "broken",  "scrape","weekly",  "USD/ton", 2),
    ("cbot_soymeal", "CBOT Soybean Meal (ZM)",    "world", "bran",    "api",   "daily",   "USD/ton", 2),
    ("cpf_feed_corn",  "CPF รับซื้อ ข้าวโพดเม็ด",     "thai", "corn",   "scrape","daily",   "THB/kg",  2),
    ("cpf_feed_broken","CPF รับซื้อ ปลายข้าวเจ้า",    "thai", "broken", "scrape","daily",   "THB/kg",  2),
    ("cpf_feed_bran",  "CPF รับซื้อ รำขาว",          "thai", "bran",   "scrape","daily",   "THB/kg",  2),
    ("tmpa",         "TMPA ราคาประกาศ",            "thai",  None,      "scrape","daily",   "THB/kg",  2),
    ("dam_level",    "ระดับน้ำเขื่อน (RID)",        "driver",None,      "api",   "daily",   "%",       2),
    ("burma_corn",   "ข้าวโพดพม่า/ชายแดน",          "driver","corn",    "manual","weekly",  "THB/kg",  2),
]

def sources_as_dicts():
    keys = ("source_id","label","layer","commodity","method","frequency","unit","phase")
    return [dict(zip(keys, s)) for s in SOURCES]


# ------------------------------------------------------------------
# Collectors — Phase 1 (พร้อมใช้)
# ------------------------------------------------------------------
# Frankfurter = ECB reference rates, ฟรี ไม่ต้อง key
# NOTE: api.frankfurter.app เดี๋ยวนี้ 302 -> api.frankfurter.dev/v1 ; ใช้ canonical host ตรงๆ
_FRANKFURTER = "https://api.frankfurter.dev/v1"


def _parse_fx_latest(d: dict):
    """แปลง payload ของ /latest -> [(obs_date, value, meta)]"""
    return [(date.fromisoformat(d["date"]), float(d["rates"]["THB"]),
             {"src": "frankfurter/ecb", "endpoint": "latest"})]


def _parse_fx_range(d: dict):
    """แปลง payload ของ /{start}..{end} -> list เรียงตามวันที่
    รูปแบบ rates = {"YYYY-MM-DD": {"THB": <float>}, ...} (ECB ข้ามเสาร์-อาทิตย์/วันหยุด)"""
    out = []
    for ds, r in sorted(d.get("rates", {}).items()):
        if "THB" in r:
            out.append((date.fromisoformat(ds), float(r["THB"]),
                        {"src": "frankfurter/ecb", "endpoint": "range"}))
    return out


def collect_fx_usdthb():
    """USD/THB ล่าสุด จาก Frankfurter (ECB reference)."""
    import requests
    r = requests.get(f"{_FRANKFURTER}/latest",
                     params={"from": "USD", "to": "THB"}, timeout=20)
    r.raise_for_status()
    return _parse_fx_latest(r.json())


def backfill_fx_usdthb(start: date | None = None, end: date | None = None):
    """Backfill USD/THB ย้อนหลัง (default ~2 ปี ถึงวันนี้).
    คืน list ของทุกวันทำการในช่วง ไว้ยิงเข้า DB ครั้งเดียวตอนเริ่ม (upsert กันซ้ำอยู่แล้ว)
    ใช้ครั้งเดียว เช่น: from collectors import backfill_fx_usdthb; rows = backfill_fx_usdthb()"""
    import requests
    from datetime import timedelta
    end = end or date.today()
    start = start or (end - timedelta(days=730))
    r = requests.get(f"{_FRANKFURTER}/{start.isoformat()}..{end.isoformat()}",
                     params={"from": "USD", "to": "THB"}, timeout=30)
    r.raise_for_status()
    return _parse_fx_range(r.json())


# ONI (Oceanic Niño Index) — NOAA CPC ascii file, format คงที่:  SEAS  YR  TOTAL  ANOM
# ANOM = ค่า ONI ; SEAS = 3-month label (ตัวอักษรแรกของ 3 เดือน)
_ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

# 3-month label -> เดือนกลาง (YR ในไฟล์ = ปีของเดือนกลาง เช่น DJF -> ม.ค.)
_ONI_MID_MONTH = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}


def _parse_oni_text(text: str):
    """แปลงไฟล์ ascii ONI -> (obs_date, oni_value, label) ของแถวล่าสุด
    แถวข้อมูล = 'SEAS YR TOTAL ANOM' ; ข้าม header ('SEAS...') และบรรทัดว่าง"""
    last = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        seas, yr, total, anom = parts
        if seas not in _ONI_MID_MONTH:      # ข้าม header 'SEAS YR TOTAL ANOM'
            continue
        try:
            last = (seas, int(yr), float(anom))
        except ValueError:
            continue
    if last is None:
        raise ValueError("parse ONI ไม่เจอแถวข้อมูล — format ไฟล์อาจเปลี่ยน")
    seas, yr, anom = last
    obs_date = date(yr, _ONI_MID_MONTH[seas], 1)
    return obs_date, anom, seas


def collect_enso_oni():
    """ONI ล่าสุด จาก NOAA CPC (ascii table, ไม่ต้อง key)."""
    import requests
    r = requests.get(_ONI_URL, timeout=20)
    r.raise_for_status()
    obs_date, oni, label = _parse_oni_text(r.text)
    if not (-3.0 <= oni <= 3.0):
        raise ValueError(f"ONI={oni} นอกช่วง -3..3 — น่าจะ parse ผิด")
    return [(obs_date, oni, {"src": "noaa/cpc", "period": label})]


# ------------------------------------------------------------------
# Collectors — Phase 2 (stub: ต้อง inspect หน้าเว็บก่อน)
# แต่ละตัวเขียนแยกได้ทีละแหล่งใน Cowork โดยไม่กระทบตัวอื่น
# ------------------------------------------------------------------
def _todo(source_id):
    def _f():
        raise NotImplementedError(f"Phase 2: ยังไม่ทำ scraper ของ {source_id}")
    return _f


def collect_dam_level():
    """ระดับน้ำเขื่อนไทย (% ความจุอ่างรวม ระดับประเทศ).
    สถานะ: ยังไม่ทำ — thaiwater.net / HII เป็น dashboard ที่ render ด้วย JS
    เรียก XHR endpoint ที่ไม่ประกาศเป็นเอกสารสาธารณะ (ลอง REST หลายตัวแล้ว 404)
    ต้องตัดสินใจก่อน (ดู note ที่คุยกับ user):
      ทางเลือก A: เปิด thaiwater.net ในเบราว์เซอร์จริง (Railway/เครื่อง user ที่เน็ตเปิด)
                  ดู DevTools > Network จับ XHR JSON ของ 'อ่างใหญ่' แล้วเอา URL มาใส่ที่นี่
      ทางเลือก B: สมัคร token ที่ standard.thaiwater.net (API มาตรฐาน มีเอกสาร)
      ทางเลือก C: Playwright render หน้า dashboard แล้วดึงตาราง (ช้า/เปราะ)
    เมื่อได้ endpoint แล้ว คืน [(obs_date, pct, {"src": "...", "scope": "national|<เขื่อน>"})]
    """
    raise NotImplementedError("dam_level: รอเลือก endpoint (A/B/C) — ยังไม่ยืนยันแหล่งสาธารณะที่ดึงสะอาดได้")

# ------------------------------------------------------------------
# TREA — ราคาส่งออกข้าว FOB รายสัปดาห์ (thairiceexporters.or.th)
# NOTE (สำคัญ): โดเมน TREA เป็น HTTP + ใบรับรอง SSL ผิด (hostname mismatch)
#   เครื่องมือ fetch ในแซนด์บ็อกซ์นี้เข้าไม่ได้ ตรวจ HTML สดไม่ได้
#   -> logic parser ทดสอบกับ fixture ตัวแทนแล้ว แต่ "ยังไม่ยืนยันกับ HTML จริง"
#   ตอน deploy: requests เข้า http:// ได้ตรงๆ (มี fallback verify=False เผื่อ redirect https)
#   ครั้งแรกที่รันจริง ให้ตรวจ label แถว + คอลัมน์ราคาให้ตรง แล้วปรับ pattern ถ้าจำเป็น
# ------------------------------------------------------------------
_TREA_URL = "http://www.thairiceexporters.or.th/price.htm"

_TH_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}


def _recent_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def _fetch_trea_html() -> str:
    """ดึง HTML หน้า TREA — http ตรงก่อน, fallback https verify=False (ใบรับรองเสีย)."""
    import requests
    try:
        r = requests.get(_TREA_URL, timeout=25)
        r.raise_for_status()
    except requests.exceptions.SSLError:
        import urllib3
        urllib3.disable_warnings()
        r = requests.get(_TREA_URL.replace("http://", "https://"), timeout=25, verify=False)
        r.raise_for_status()
    r.encoding = r.apparent_encoding or "tis-620"
    return r.text


def _trea_rows(html: str):
    """คืน list ของแถว (แต่ละแถว = list ของ cell text) จากทุก <table> ในหน้า."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if any(cells):
            rows.append(cells)
    return rows


def _first_price(cells, lo=100.0, hi=2000.0):
    """ราคาแรกในแถวที่อยู่ในช่วง USD/ton สมเหตุผล (กันจับเลข % หรือปีออกมา)."""
    for c in cells:
        for m in re.findall(r"[0-9][0-9,]*(?:\.[0-9]+)?", c):
            v = float(m.replace(",", ""))
            if lo <= v <= hi:
                return v
    return None


def _pick_grade_re(rows, pattern: str, exclude=()):
    """เลือกแถวที่ข้อความ match regex `pattern` (ignorecase) และไม่มีคำใน exclude
    คืน (price, raw_row_text)."""
    rx = re.compile(pattern, re.IGNORECASE)
    exc = [e.lower() for e in exclude]
    for cells in rows:
        joined = " ".join(cells)
        low = joined.lower()
        if rx.search(joined) and not any(e in low for e in exc):
            price = _first_price(cells)
            if price is not None:
                return price, joined
    return None, None


def _trea_date(html: str) -> date | None:
    """best-effort: หา 'วันที่ dd <เดือนไทย> พ.ศ.' (แปลง BE->CE) หรือ dd/mm/yyyy."""
    m = re.search(r"(\d{1,2})\s+(" + "|".join(_TH_MONTHS) + r")\s+(\d{4})", html)
    if m:
        d, mon, y = int(m.group(1)), _TH_MONTHS[m.group(2)], int(m.group(3))
        if y > 2400:  # ปี พ.ศ.
            y -= 543
        try:
            return date(y, mon, d)
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", html)
    if m:
        d, mon, y = map(int, m.groups())
        if y > 2400:
            y -= 543
        try:
            return date(y, mon, d)
        except ValueError:
            pass
    return None


def _collect_trea(pattern, grade_label, exclude=()):
    html = _fetch_trea_html()
    rows = _trea_rows(html)
    price, raw = _pick_grade_re(rows, pattern, exclude=exclude)
    if price is None:
        raise ValueError(f"TREA: หาแถว grade ({grade_label}) ไม่เจอ — ตรวจ label/คอลัมน์จาก HTML จริง")
    obs = _trea_date(html) or _recent_monday()
    return [(obs, price, {"src": "trea", "grade": grade_label, "raw": raw})]


def collect_trea_a1_fob():
    """Thai White Rice A1 Super (ปลายข้าว 100% broken) FOB, USD/ton."""
    return _collect_trea(r"a1\s*super|a\.?1", "A1 super")


def collect_trea_wr5_fob():
    """Thai White Rice 5% FOB, USD/ton (กัน 15%/25% ด้วย regex, กัน parboiled ด้วย exclude)."""
    return _collect_trea(r"white\s*rice\s*5\s*%|(?<!\d)5\s*%\s*broken",
                         "White Rice 5%", exclude=("parboiled", "hom mali", "glutinous"))


# ------------------------------------------------------------------
# CPF Feed — ราคารับซื้อวัตถุดิบ (www.cpffeed.com) — static HTML, สะอาด
# ตารางคอลัมน์: [ชนิด | สัปดาห์ | วันที่ YYYY-MM-DD | ราคา | เปลี่ยนแปลง | หน่วย | หมายเหตุ]
# หนึ่งสินค้า = หนึ่งหน้า -> เหมาะกับการแยก source_id ต่อสินค้า (รอ user อนุมัติแก้ SOURCES)
# ------------------------------------------------------------------
_CPF_PAGES = {
    "corn":   "https://www.cpffeed.com/material4/",   # ข้าวโพดเม็ด
    "broken": "https://www.cpffeed.com/material1/",   # ปลายข้าวเจ้า
    "bran":   "https://www.cpffeed.com/material3/",   # รำขาว
    "soymeal":"https://www.cpffeed.com/material6/",   # กากถั่วเหลือง
}


def _parse_cpf_table(html: str):
    """หาแถวราคาล่าสุด (วันที่มากสุด) -> (obs_date, price_thb_per_kg, raw_row)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    best = None  # (date, price, raw)
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        d = p = None
        for c in cells:
            if d is None:
                m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", c.strip())
                if m:
                    d = date(int(m[1]), int(m[2]), int(m[3]))
                    continue
            if d is not None and p is None:
                m = re.fullmatch(r"\d{1,3}(?:\.\d+)?", c.strip())
                if m:
                    p = float(c)
        if d is not None and p is not None:
            if best is None or d > best[0]:
                best = (d, p, " | ".join(cells))
    if best is None:
        raise ValueError("CPF: parse ตารางไม่เจอแถว (วันที่+ราคา) — layout อาจเปลี่ยน")
    return best


def _collect_cpf(commodity: str):
    import requests
    url = _CPF_PAGES[commodity]
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    obs, price, raw = _parse_cpf_table(r.text)
    if not (5.0 <= price <= 25.0):
        raise ValueError(f"CPF {commodity}: ราคา {price} นอกช่วง 5-25 THB/kg — น่าจะ parse ผิด")
    return [(obs, price, {"src": "cpffeed", "commodity": commodity, "raw": raw})]


def collect_cpf_feed_corn():
    return _collect_cpf("corn")


def collect_cpf_feed_broken():
    return _collect_cpf("broken")


def collect_cpf_feed_bran():
    return _collect_cpf("bran")


def collect_cpf_feed_soymeal():
    return _collect_cpf("soymeal")


# ------------------------------------------------------------------
# TMPA — สมาคมพ่อค้าข้าวโพดและพืชพันธุ์ไทย (thaimaizeandproduce.org)
# Joomla, server-rendered, ไม่ต้อง login. หน้า category ลิสต์บทความราคารายวัน
# แต่ละบทความ = ราคารับซื้อข้าวโพดเลี้ยงสัตว์แยกตามโรงงาน + แถวสรุป (THB/kg + FOB/ton)
# collector = 2 ขั้น: หา URL บทความล่าสุด -> parse ราคาข้าวโพด (benchmark)
# NOTE: parser ทดสอบกับ fixture ตัวแทน ยังไม่ยืนยันกับ HTML จริง (WebFetch เห็นแต่ค่า ไม่เห็น raw)
# ต่อยอด: จะเก็บ per-mill / benchmark แถวสรุป -> รอ user เลือก (ดู note)
# ------------------------------------------------------------------
_TMPA_CAT = ("https://thaimaizeandproduce.org/index.php"
             "?option=com_content&view=category&id=14&Itemid=284")
_TMPA_BASE = "https://thaimaizeandproduce.org/index.php?option=com_content&view=article&id="


def _tmpa_latest_article_url(cat_html: str) -> str:
    """หา id บทความมากสุดในหน้า category (=ล่าสุด) -> URL บทความ.
    ลิงก์บทความ Joomla = id=NNNN:slug (มี ':' ตามด้วย title) — รูปแบบนี้กัน id=14
    (ตัว category เอง) อัตโนมัติ และทน &amp; (HTML-encoded) เพราะไม่พึ่งตัวอักษรหน้า id="""
    html = cat_html.replace("&amp;", "&")
    ids = [int(m) for m in re.findall(r"id=(\d{2,6}):", html)]        # article = id:slug
    if not ids:                                                       # fallback: id ใดๆ > 100
        ids = [int(m) for m in re.findall(r"[?&]id=(\d{2,6})", html) if int(m) > 100]
    if not ids:
        raise ValueError("TMPA: หา id บทความล่าสุดไม่เจอ — layout category เปลี่ยน")
    return _TMPA_BASE + str(max(ids))


def _parse_tmpa_corn(html: str):
    """หาแถว 'ข้าวโพดเลี้ยงสัตว์' ที่เป็นสรุป (มีทั้งราคา THB/kg 8-16 และ FOB/ton 200-500).
    คืน (obs_date, price_thb_per_kg, fob_ton_or_None, raw_row)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    corn_kg = None
    fob = None
    raw = None
    fallback = None
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        joined = " ".join(cells)
        if "ข้าวโพด" not in joined:
            continue
        nums = [float(x.replace(",", "")) for x in re.findall(r"\d+(?:\.\d+)?", joined)]
        kg = next((n for n in nums if 6 <= n <= 16), None)
        big = next((n for n in nums if 150 <= n <= 600), None)
        if kg is not None and fallback is None:
            fallback = (kg, joined)
        if kg is not None and big is not None:      # แถวสรุป
            corn_kg, fob, raw = kg, big, joined
            break
    if corn_kg is None and fallback is not None:     # ไม่เจอแถวสรุป ใช้ราคาข้าวโพดแรก
        corn_kg, raw = fallback
    if corn_kg is None:
        raise ValueError("TMPA: parse ราคาข้าวโพดไม่เจอ — ตรวจ HTML จริง")
    obs = _trea_date(html) or _recent_monday()
    return obs, corn_kg, fob, raw


def collect_tmpa():
    """ราคาข้าวโพดเลี้ยงสัตว์ (benchmark) จาก TMPA รายวัน, THB/kg."""
    import requests
    rc = requests.get(_TMPA_CAT, timeout=25)
    rc.raise_for_status()
    rc.encoding = rc.apparent_encoding or "utf-8"
    art_url = _tmpa_latest_article_url(rc.text)
    ra = requests.get(art_url, timeout=25)
    ra.raise_for_status()
    ra.encoding = ra.apparent_encoding or "utf-8"
    obs, price, fob, raw = _parse_tmpa_corn(ra.text)
    if not (6.0 <= price <= 16.0):
        raise ValueError(f"TMPA: ข้าวโพด {price} นอกช่วง 6-16 THB/kg — น่าจะ parse ผิด")
    meta = {"src": "tmpa", "commodity": "corn", "article": art_url, "raw": raw}
    if fob is not None:
        meta["fob_usd_ton"] = fob
    return [(obs, price, meta)]


# ------------------------------------------------------------------
# CBOT futures — via yfinance (ผู้ใช้เลือก) : ZC=F Corn, ZM=F Soybean Meal
# ฟรี ไม่ต้อง key, ราคา ~delay 10-15 นาที (Yahoo). เป็น unofficial scrape ของ Yahoo
# อาจล่มเงียบๆ ได้ -> ครอบ error ให้ run.py log เป็น 'error' ไม่ทำ pipeline ล่ม
# หน่วย: ZC = USd/bu (เซนต์ต่อบุชเชล ~350-550), ZM = USD/short ton (~250-450)
# ต้องมี yfinance ใน requirements (pip install yfinance) และเน็ตออก Yahoo ได้ (Railway ได้)
# ------------------------------------------------------------------
_CBOT_SYMBOLS = {"cbot_corn": "ZC=F", "cbot_soymeal": "ZM=F"}


def _parse_yf_history(df):
    """รับ DataFrame จาก yfinance (index=Timestamp, มีคอลัมน์ 'Close')
    คืน (obs_date, close) ของแถวล่าสุดที่ Close ไม่ใช่ NaN."""
    import math
    if df is None or len(df) == 0:
        raise ValueError("yfinance คืน DataFrame ว่าง (Yahoo อาจล่ม/สัญลักษณ์ผิด)")
    for i in range(len(df) - 1, -1, -1):
        close = df["Close"].iloc[i]
        if close is not None and not (isinstance(close, float) and math.isnan(close)):
            ts = df.index[i]
            obs = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
            return obs, float(close)
    raise ValueError("yfinance: ไม่มีแถว Close ที่ใช้ได้")


def _collect_cbot(source_id):
    import yfinance as yf
    symbol = _CBOT_SYMBOLS[source_id]
    df = yf.Ticker(symbol).history(period="7d", auto_adjust=False)
    obs, settle = _parse_yf_history(df)
    lo, hi = (150.0, 900.0) if source_id == "cbot_corn" else (150.0, 700.0)
    if not (lo <= settle <= hi):
        raise ValueError(f"{source_id}: {settle} นอกช่วงสมเหตุผล {lo}-{hi} — ตรวจหน่วย/สัญลักษณ์")
    return [(obs, settle, {"src": "yfinance", "symbol": symbol.replace("=F", "")})]


def collect_cbot_corn():
    """CBOT Corn front-month (ZC=F), USd/bu."""
    return _collect_cbot("cbot_corn")


def collect_cbot_soymeal():
    """CBOT Soybean Meal front-month (ZM=F), USD/short ton."""
    return _collect_cbot("cbot_soymeal")


# map source_id -> collector callable
COLLECTORS = {
    "fx_usdthb":       collect_fx_usdthb,
    "enso_oni":        collect_enso_oni,
    "cbot_corn":       collect_cbot_corn,
    "trea_a1_fob":     collect_trea_a1_fob,
    "trea_wr5_fob":    collect_trea_wr5_fob,
    "cbot_soymeal":    collect_cbot_soymeal,
    "cpf_feed_corn":   collect_cpf_feed_corn,
    "cpf_feed_broken": collect_cpf_feed_broken,
    "cpf_feed_bran":   collect_cpf_feed_bran,
    "tmpa":            collect_tmpa,
    "dam_level":       collect_dam_level,
    "burma_corn":      _todo("burma_corn"),
}
