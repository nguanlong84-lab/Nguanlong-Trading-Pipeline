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
    ("cbot_corn_thb_kg","CBOT Corn แปลงเป็น THB/kg","world","corn",    "api",   "daily",   "THB/kg",  2),
    ("brent_oil",    "Brent Crude (BZ)",          "driver","energy", "api",   "daily",   "USD/bbl", 2),
    ("wti_oil",      "WTI Crude (CL)",            "driver","energy", "api",   "daily",   "USD/bbl", 2),
    ("fertilizer_urea","ยูเรีย (World Bank)","driver","fertilizer","scrape","monthly","USD/ton",2),
    ("cassava_chip", "มันเส้น Chips FOB (TTTA)",   "thai",  "cassava", "scrape","daily",   "THB/kg",  2),
    ("cpf_livestock","CPF ราคาสัตว์ (ดีมานด์อาหารสัตว์)","thai",None,   "scrape","daily",   "THB/ตัว", 2),
    ("live_hog",     "สุกรมีชีวิตหน้าฟาร์ม (เฉลี่ยประเทศ)","thai","hog", "scrape","daily",   "THB/kg",  2),
    ("cpf_feed_corn",  "CPF รับซื้อ ข้าวโพดเม็ด",     "thai", "corn",   "scrape","daily",   "THB/kg",  2),
    ("cpf_feed_broken","CPF รับซื้อ ปลายข้าวเจ้า",    "thai", "broken", "scrape","daily",   "THB/kg",  2),
    ("cpf_feed_bran",  "CPF รับซื้อ รำขาว",          "thai", "bran",   "scrape","daily",   "THB/kg",  2),
    ("trm_broken",   "ปลายข้าวเอวันเลิศ (โรงสี รายวัน)","thai","broken","scrape","daily",   "THB/kg",  2),
    ("trm_bran",     "รำข้าวขาว (โรงสี รายวัน)",     "thai",  "bran",   "scrape","daily",   "THB/kg",  2),
    ("tmpa",         "TMPA ราคาประกาศ",            "thai",  None,      "scrape","daily",   "THB/kg",  2),
    ("dam_level",    "ระดับน้ำเขื่อน (RID)",        "driver",None,      "api",   "daily",   "%",       2),
    ("nl_buy_corn",  "ง่วนล้ง รับซื้อ ข้าวโพด",       "nguanlong","corn",  "api",   "daily",   "THB/kg",  3),
    ("nl_sell_corn", "ง่วนล้ง ขาย ข้าวโพด",          "nguanlong","corn",  "api",   "daily",   "THB/kg",  3),
    ("nl_buy_broken","ง่วนล้ง รับซื้อ ปลายข้าว/ท่อน",  "nguanlong","broken","api",   "daily",   "THB/kg",  3),
    ("nl_sell_broken","ง่วนล้ง ขาย ปลายข้าว/ท่อน",     "nguanlong","broken","api",   "daily",   "THB/kg",  3),
    ("nl_buy_bran",  "ง่วนล้ง รับซื้อ รำ",            "nguanlong","bran",  "api",   "daily",   "THB/kg",  3),
    ("nl_sell_bran", "ง่วนล้ง ขาย รำ",               "nguanlong","bran",  "api",   "daily",   "THB/kg",  3),
    ("nl_buy_bounce","ง่วนล้ง รับซื้อ ท่อนดีด",        "nguanlong","bounce","api",   "daily",   "THB/kg",  3),
    ("nl_sell_bounce","ง่วนล้ง ขาย ท่อนดีด",          "nguanlong","bounce","api",   "daily",   "THB/kg",  3),
    ("nl_buy_branmali","ง่วนล้ง รับซื้อ รำมะลิ",       "nguanlong","branmali","api", "daily",   "THB/kg",  3),
    ("nl_sell_branmali","ง่วนล้ง ขาย รำมะลิ",         "nguanlong","branmali","api", "daily",   "THB/kg",  3),
    ("nl_buy_pathum","ง่วนล้ง รับซื้อ ต้นปทุม",        "nguanlong","pathum", "api",   "daily",   "THB/kg",  3),
    ("nl_sell_pathum","ง่วนล้ง ขาย ต้นปทุม",          "nguanlong","pathum", "api",   "daily",   "THB/kg",  3),
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


# คำที่บอกว่าแถวไม่ใช่ผู้รับซื้อ (header/สรุป/สินค้าอื่น)
_TMPA_SKIP = ("ข้าวโพด", "สินค้า", "ราคา", "ถั่ว", "f.o.b", "fob", "หน่วย")


def _parse_tmpa_corn(html: str):
    """parse บทความ TMPA:
      - benchmark = แถวสรุป 'ข้าวโพดเลี้ยงสัตว์' ที่มีทั้ง THB/kg (6-16) และ FOB/ton (150-600)
      - buyers = ตารางผู้รับซื้อรายโรงงาน {ชื่อผู้ซื้อ: ราคา THB/kg} (ราคาอยู่ในช่วง 6-16)
    คืน (obs_date, benchmark_kg, fob_ton_or_None, buyers_dict, raw_row)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    corn_kg = fob = raw = None
    fallback = None
    buyers = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        joined = " ".join(cells)
        nums = [float(x.replace(",", "")) for x in re.findall(r"\d+(?:\.\d+)?", joined)]
        kg = next((n for n in nums if 6 <= n <= 16), None)
        big = next((n for n in nums if 150 <= n <= 600), None)

        if "ข้าวโพด" in joined:                          # แถว benchmark/สรุป ของข้าวโพด
            if kg is not None and fallback is None:
                fallback = (kg, joined)
            if kg is not None and big is not None:
                corn_kg, fob, raw = kg, big, joined
            continue

        # แถวผู้รับซื้อ: ชื่อผู้ซื้อ (cell แรก) + ราคา THB/kg ช่วง 6-16, ไม่ใช่ header/สินค้าอื่น
        name = cells[0].strip()
        low = name.lower()
        if (kg is not None and name and not name.replace(".", "").isdigit()
                and not any(w in low for w in _TMPA_SKIP)):
            buyers[name] = kg

    if corn_kg is None and fallback is not None:         # ไม่เจอแถวสรุป ใช้ราคาข้าวโพดแรก
        corn_kg, raw = fallback
    if corn_kg is None:
        raise ValueError("TMPA: parse ราคาข้าวโพดไม่เจอ — ตรวจ HTML จริง")
    obs = _trea_date(html) or _recent_monday()
    return obs, corn_kg, fob, buyers, raw


def collect_tmpa():
    """ราคาข้าวโพดเลี้ยงสัตว์ จาก TMPA รายวัน, THB/kg.
    value = benchmark ; meta.buyers = ราคารับซื้อรายโรงงาน (แยกตามผู้ซื้อ/ทำเล)."""
    import requests
    rc = requests.get(_TMPA_CAT, timeout=25)
    rc.raise_for_status()
    rc.encoding = rc.apparent_encoding or "utf-8"
    art_url = _tmpa_latest_article_url(rc.text)
    ra = requests.get(art_url, timeout=25)
    ra.raise_for_status()
    ra.encoding = ra.apparent_encoding or "utf-8"
    obs, price, fob, buyers, raw = _parse_tmpa_corn(ra.text)
    if not (6.0 <= price <= 16.0):
        raise ValueError(f"TMPA: ข้าวโพด {price} นอกช่วง 6-16 THB/kg — น่าจะ parse ผิด")
    meta = {"src": "tmpa", "commodity": "corn", "article": art_url, "raw": raw}
    if fob is not None:
        meta["fob_usd_ton"] = fob
    if buyers:
        meta["buyers"] = buyers
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


# corn bushel = 56 lb = 25.4012 kg (เฉพาะข้าวโพด; ถั่ว/ข้าวสาลี = 60 lb ต่างกัน)
_CORN_BUSHEL_KG = 25.4012


def collect_cbot_corn_thb():
    """แปลงราคา CBOT Corn (USd/bu) -> THB/kg ด้วย FX วันนั้น (derived series).
    สูตร: (cents/100)/25.4012 * (THB/USD). obs_date ใช้ของ ZC (วันเทรดล่าสุด)."""
    corn = collect_cbot_corn()          # [(date, cents_per_bu, meta)]
    fx = collect_fx_usdthb()            # [(date, thb_per_usd, meta)]
    obs, cents, _ = corn[0]
    _, rate, _ = fx[0]
    thb_kg = (cents / 100.0) / _CORN_BUSHEL_KG * rate
    if not (2.0 <= thb_kg <= 30.0):
        raise ValueError(f"cbot_corn_thb_kg: {thb_kg:.3f} นอกช่วง 2-30 THB/kg — ตรวจหน่วย/FX")
    return [(obs, round(thb_kg, 4), {
        "src": "derived", "from": "cbot_corn x fx_usdthb",
        "cents_per_bu": cents, "fx_thb_usd": rate, "bushel_kg": _CORN_BUSHEL_KG,
    })]


# ------------------------------------------------------------------
# Crude oil — yfinance (Brent BZ=F, WTI CL=F) : driver (freight/ปุ๋ย/ethanol)
# ------------------------------------------------------------------
def _collect_yf_price(symbol, lo, hi, extra=None):
    import yfinance as yf
    df = yf.Ticker(symbol).history(period="7d", auto_adjust=False)
    obs, val = _parse_yf_history(df)
    if not (lo <= val <= hi):
        raise ValueError(f"{symbol}: {val} นอกช่วง {lo}-{hi}")
    meta = {"src": "yfinance", "symbol": symbol.replace("=F", "")}
    if extra:
        meta.update(extra)
    return [(obs, val, meta)]


def collect_brent_oil():
    """Brent crude front-month (BZ=F), USD/bbl."""
    return _collect_yf_price("BZ=F", 20.0, 200.0)


def collect_wti_oil():
    """WTI crude front-month (CL=F), USD/bbl."""
    return _collect_yf_price("CL=F", 20.0, 200.0)


# ------------------------------------------------------------------
# Fertilizer (urea) — TheGlobalEconomy (ข้อมูล World Bank), รายเดือน + current
# หน้ามีตาราง label/value: 'Latest value | 400' และ 'Reference | July 2026'
# เปลี่ยนจาก IndexMundi (เดิม stale/เพี้ยน $725) มาใช้ตัวนี้ที่ตรงกับ World Bank ปัจจุบัน (~$400)
# ------------------------------------------------------------------
_UREA_URL = "https://www.theglobaleconomy.com/world/urea_prices/"
_MON3 = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
         "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _month_year_to_date(s):
    """'July 2026' / 'Jul 2026' -> date(2026,7,1) (วันที่ 1 ของเดือน)."""
    if not s:
        return None
    m = re.search(r"([A-Za-z]{3,})\s+(\d{4})", s)
    if m:
        mon = _MON3.get(m.group(1)[:3].lower())
        if mon:
            try:
                return date(int(m.group(2)), mon, 1)
            except ValueError:
                pass
    return None


def _parse_tge_urea(html):
    """คืน (obs_date, price, ref) จากตาราง label/value ของ TheGlobalEconomy
    หา row 'Latest value' -> ราคา ; row 'Reference' -> เดือน/ปี."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    value = None
    ref = None
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        label = cells[0].lower()
        if "latest value" in label:
            pm = re.search(r"\d+(?:\.\d+)?", cells[1])
            if pm:
                value = float(pm.group())
        elif "reference" in label:
            ref = cells[1]
    if value is None:
        raise ValueError("urea: หา 'Latest value' ไม่เจอ (TheGlobalEconomy) — layout เปลี่ยน")
    obs = _month_year_to_date(ref) or _recent_monday()
    return obs, value, ref


def collect_fertilizer_urea():
    """ราคายูเรีย รายเดือน (World Bank ผ่าน TheGlobalEconomy), USD/ton."""
    import requests
    r = requests.get(_UREA_URL, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    obs, price, ref = _parse_tge_urea(r.text)
    if not (100.0 <= price <= 900.0):
        raise ValueError(f"urea: {price} นอกช่วง 100-900 USD/ton — น่าจะ parse ผิด")
    return [(obs, price, {"src": "worldbank/theglobaleconomy", "commodity": "urea",
                          "reference": ref})]


# ------------------------------------------------------------------
# Cassava chips FOB (มันเส้น) — ttta-tapioca.org, corn substitute ในอาหารสัตว์
# หน้าแรกมีตารางราคา แถว 'มันเส้น Chips' = ช่วงราคา THB/kg (+ USD/ton) + วันที่ dd/mm/yy
# NOTE: parser best-effort (เห็นค่าแต่ไม่เห็น raw HTML) — ยืนยันครั้งแรกที่รันจริง
# ------------------------------------------------------------------
_TTTA_URL = "https://ttta-tapioca.org/?lang=en"


def _ttta_date(html):
    m = re.search(r"(\d{2})/(\d{2})/(\d{2})", html)
    if m:
        d, mon, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(2000 + yy, mon, d)
        except ValueError:
            return None
    return None


def _parse_ttta_chips(html):
    """คืน (obs_date, thb_per_kg_mid, raw) จากแถว 'มันเส้น/Chips'."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        joined = " ".join(cells)
        if "มันเส้น" in joined or "chip" in joined.lower():
            thb = [float(x) for x in re.findall(r"\d+\.\d+", joined) if 3.0 <= float(x) <= 20.0]
            if thb:
                mid = round(sum(thb) / len(thb), 3)     # กลางของช่วงราคา
                return _ttta_date(html) or _recent_monday(), mid, joined
    raise ValueError("cassava: หาแถว 'มันเส้น/Chips' ไม่เจอ — ตรวจ HTML จริง")


def collect_cassava_chip():
    """ราคามันเส้นส่งออก FOB (กลางของช่วง), THB/kg."""
    import requests
    r = requests.get(_TTTA_URL, timeout=25)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    obs, price, raw = _parse_ttta_chips(r.text)
    if not (3.0 <= price <= 20.0):
        raise ValueError(f"cassava: {price} นอกช่วง 3-20 THB/kg — น่าจะ parse ผิด")
    return [(obs, price, {"src": "ttta", "commodity": "cassava_chip", "raw": raw})]


# ------------------------------------------------------------------
# CPF livestock — cpffeed.com/animal-price/ : สัญญาณดีมานด์อาหารสัตว์
# ตารางเดียวกับ CPF material: [ชนิด | สัปดาห์ | วันที่ | ราคา | เปลี่ยน | หน่วย | หมายเหตุ]
# มีหลายสัตว์ -> เก็บทุกตัวใน meta.items ; value = ราคาลูกไก่เนื้อ (ตัวชี้นำ restock)
# ------------------------------------------------------------------
_CPF_ANIMAL_URL = "https://www.cpffeed.com/animal-price/"


def _parse_cpf_animals(html):
    """คืน dict {ชื่อสัตว์: (obs_date, price, raw)} เอาแถววันที่ล่าสุดของแต่ละตัว."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    latest = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 4:
            continue
        name = cells[0].strip()
        d = p = None
        for c in cells:
            if d is None:
                mm = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", c.strip())
                if mm:
                    d = date(int(mm[1]), int(mm[2]), int(mm[3]))
                    continue
            if d is not None and p is None:
                mm = re.fullmatch(r"\d{1,6}(?:\.\d+)?", c.strip())
                if mm:
                    p = float(c)
        if name and d is not None and p is not None:
            if name not in latest or d > latest[name][0]:
                latest[name] = (d, p, " | ".join(cells))
    if not latest:
        raise ValueError("cpf_livestock: parse ตารางสัตว์ไม่เจอ — layout เปลี่ยน")
    return latest


def collect_cpf_livestock():
    """ราคาสัตว์ CPF (ลูกสุกร/ลูกไก่/ไข่) — สัญญาณดีมานด์อาหารสัตว์.
    value = ราคาลูกไก่เนื้อ (ถ้ามี) ; meta.items = ทุกชนิด."""
    import requests
    r = requests.get(_CPF_ANIMAL_URL, timeout=25)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    animals = _parse_cpf_animals(r.text)
    obs = max(d for d, _, _ in animals.values())
    items = {name: {"price": p, "date": d.isoformat()} for name, (d, p, _) in animals.items()}
    headline = next((p for name, (d, p, _) in animals.items() if "ไก่เนื้อ" in name), None)
    if headline is None:
        headline = sorted(animals.items())[0][1][1]
    return [(obs, headline, {"src": "cpffeed", "board": "animal", "items": items})]


# ------------------------------------------------------------------
# สุกรมีชีวิตหน้าฟาร์ม (live hog) — vetproductsgroup ผ่าน WordPress REST API (wp-json)
# ราคาประกาศรายภาค (text) -> เฉลี่ยเป็นค่าประเทศ. สัญญาณ margin/ดีมานด์อาหารสัตว์
# NOTE: best-effort (แหล่งข่าว/ประกาศ ไม่ใช่ตาราง) — อาจต้องปรับ parser ถ้า layout เปลี่ยน
# หมายเหตุ: ไก่เนื้อมีชีวิตของไทย "ไม่มีแหล่ง auto สะอาด" (ดูที่คุยกับ user) -> ยังไม่ทำ
# ------------------------------------------------------------------
_VPG_API = ("https://www.vetproductsgroup.com/wp-json/wp/v2/posts"
            "?search=swine-poultry-price&per_page=1&orderby=date&order=desc")
_TH_NEXT_COUNTRY = ("จีน", "ลาว", "กัมพูชา", "เวียดนาม", "ฟิลิปปินส์",
                    "เมียนมา", "พม่า", "อินโดนีเซีย", "มาเลเซีย")


def _parse_vpg_hog(content_html, post_date_iso=None):
    """ดึงราคาสุกรมีชีวิตรายภาคใน section 'ประเทศไทย' -> (obs_date, natl_avg, regions)."""
    from bs4 import BeautifulSoup
    text = BeautifulSoup(content_html, "lxml").get_text(" ", strip=True)
    i = text.find("ประเทศไทย")
    if i == -1:
        raise ValueError("live_hog: หา section ประเทศไทย ไม่เจอ — layout เปลี่ยน")
    seg = text[i:]
    cut = len(seg)
    for c in _TH_NEXT_COUNTRY:                       # ตัดก่อนถึงประเทศถัดไป
        j = seg.find(c, 1)
        if j != -1:
            cut = min(cut, j)
    seg = seg[:cut]
    prices = []
    # 'NN.NN – NN.NN ฿ / กก.' หรือ 'NN ฿ / กก.' ; กันลูกสุกร (฿/ตัว) ด้วยหน่วย ก + band
    for m in re.finditer(r"(\d{2,3}(?:\.\d+)?)\s*(?:[–\-]\s*(\d{2,3}(?:\.\d+)?))?\s*฿\s*/\s*ก", seg):
        a = float(m.group(1))
        b = float(m.group(2)) if m.group(2) else a
        mid = (a + b) / 2
        if 40 <= mid <= 100:
            prices.append(round(mid, 2))
    if not prices:
        raise ValueError("live_hog: ไม่เจอราคาสุกร ฿/กก. ใน section ไทย")
    natl = round(sum(prices) / len(prices), 2)
    obs = _trea_date(text) or (date.fromisoformat(post_date_iso[:10])
                               if post_date_iso else _recent_monday())
    return obs, natl, prices


def collect_live_hog():
    """ราคาสุกรมีชีวิตหน้าฟาร์ม เฉลี่ยประเทศ (vetproductsgroup), THB/kg."""
    import requests
    r = requests.get(_VPG_API, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError("live_hog: wp-json ไม่คืนโพสต์")
    post = data[0]
    content = post.get("content", {}).get("rendered", "")
    obs, natl, regions = _parse_vpg_hog(content, post.get("date"))
    if not (30.0 <= natl <= 120.0):
        raise ValueError(f"live_hog: {natl} นอกช่วง 30-120 THB/kg — น่าจะ parse ผิด")
    return [(obs, natl, {"src": "vetproductsgroup", "metric": "live_hog_farmgate",
                         "scope": "national_avg", "regions": regions, "link": post.get("link")})]


# ------------------------------------------------------------------
# ปลายข้าว + รำ รายวัน — สมาคมโรงสีข้าวไทย (thairicemillers.org) PDF รายวัน
# ชื่อไฟล์เดาได้: Pricerice<DDMMYYYY_พ.ศ.>.pdf (เช่น 26 ส.ค. 2026 -> Pricerice26082569.pdf)
# 1 PDF มีทั้งปลายข้าว (บาท/100กก) และ รำ (บาท/กก) -> แชร์ดาวน์โหลดครั้งเดียว
# NOTE: cert self-signed -> deploy ใช้ requests verify=False ; parser ทำจาก screenshot ยังไม่ยืนยันสด
# ------------------------------------------------------------------
_TRM_FOLDER = "http://thairicemillers.org/images/introc_1429264173"
_TRM_CACHE = {}


def _trm_pdf_url(d):
    be = d.year + 543
    return f"{_TRM_FOLDER}/Pricerice{d.day:02d}{d.month:02d}{be}.pdf"


def _trm_fetch_pdf():
    """ลองวันนี้ย้อนหลังไป ~8 วัน (เผื่อวันหยุด) เอา PDF ล่าสุดที่มี -> (obs_date, bytes)."""
    import requests
    import urllib3
    urllib3.disable_warnings()
    today = date.today()
    for back in range(0, 8):
        d = today - timedelta(days=back)
        try:
            r = requests.get(_trm_pdf_url(d), timeout=25, verify=False,
                             allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return d, r.content
        except requests.RequestException:
            continue
    raise ValueError("thairicemillers: หา PDF ราคาย้อนหลัง 8 วันไม่เจอ — ตรวจ URL/folder")


def _trm_norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def _trm_skel(s):
    """โครงพยัญชนะไทย (ก 0E01 - ฮ 0E2E) — ตัดสระ/วรรณยุกต์/ช่องว่าง/\\x00 ทิ้ง
    ทนปัญหา pdfplumber ที่สลับตำแหน่งสระ/วรรณยุกต์ของภาษาไทย."""
    return "".join(c for c in str(s or "") if "ก" <= c <= "ฮ")


def _trm_nums(s):
    return [float(n.replace(",", "")) for n in re.findall(r"[0-9][0-9,]*(?:\.[0-9]+)?", str(s or ""))]


def _trm_lines(pdf_bytes):
    """คืน list ของ 'บรรทัด' (string) จากทั้ง extract_tables (ต่อ cell) และ extract_text
    รวมกันเป็นลำดับเดียว เพื่อให้ match ชื่อ + หาราคาบรรทัดข้างเคียงได้."""
    import io
    import pdfplumber
    lines = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pg in pdf.pages:
            for tbl in (pg.extract_tables() or []):
                for r in tbl:
                    lines.append(" ".join(c or "" for c in r))
            lines.extend((pg.extract_text() or "").splitlines())
    return lines


def _trm_price_from_lines(lines, label):
    """จับบรรทัดด้วยโครงพยัญชนะ -> ราคา บาท/กก
    ถ้าบรรทัดชื่อไม่มีตัวเลข ให้ดูราคาที่บรรทัดก่อน/หลัง (PDF นี้ราคามาก่อนชื่อ)."""
    key = _trm_skel(label)
    if not key:
        return None, None
    n = len(lines)
    for i, ln in enumerate(lines):
        if key in _trm_skel(ln):
            for cand in (ln, lines[i - 1] if i > 0 else "", lines[i + 1] if i + 1 < n else ""):
                vals = [x for x in _trm_nums(cand) if 0 < x < 100000]
                if vals:
                    price = (vals[0] + vals[1]) / 2 if len(vals) >= 2 else vals[0]
                    if price > 100:             # บาท/100กก -> บาท/กก
                        price /= 100.0
                    return round(price, 3), _trm_norm(ln)[:80]
    return None, None


def _trm_hint(lines):
    """แนบข้อความดิบที่ดึงได้จริง (ไว้ debug ตอน parse ไม่เจอ)."""
    sample = _trm_norm(" ".join(lines))
    return f"lines={len(lines)} sample={sample[:150]!r}"


def _trm_data():
    if "x" not in _TRM_CACHE:                   # ดาวน์โหลด+อ่าน PDF ครั้งเดียวต่อ process
        d, pdf = _trm_fetch_pdf()
        _TRM_CACHE["x"] = (d, _trm_lines(pdf))
    return _TRM_CACHE["x"]


def collect_trm_broken():
    """ปลายข้าวขาวเอวันเลิศ รายวัน (สมาคมโรงสีข้าวไทย), THB/kg."""
    d, lines = _trm_data()
    price, raw = _trm_price_from_lines(lines, "ปลายข้าวขาวเอวันเลิศ")
    if price is None:
        raise ValueError(f"trm_broken: หาแถวปลายข้าวไม่เจอ | {_trm_hint(lines)}")
    if not (5.0 <= price <= 25.0):
        raise ValueError(f"trm_broken: {price} นอกช่วง 5-25 บาท/กก | แถว: {raw}")
    return [(d, price, {"src": "thairicemillers", "grade": "ปลายข้าวขาวเอวันเลิศ", "raw": raw})]


def collect_trm_bran():
    """รำข้าวขาว รายวัน (สมาคมโรงสีข้าวไทย), THB/kg."""
    d, lines = _trm_data()
    price, raw = _trm_price_from_lines(lines, "รำข้าวขาว")
    if price is None:
        raise ValueError(f"trm_bran: หาแถวรำไม่เจอ | {_trm_hint(lines)}")
    if not (5.0 <= price <= 25.0):
        raise ValueError(f"trm_bran: {price} นอกช่วง 5-25 บาท/กก | แถว: {raw}")
    return [(d, price, {"src": "thairicemillers", "grade": "รำข้าวขาว", "raw": raw})]


# ------------------------------------------------------------------
# ราคาง่วนล้ง (Phase 3) — Google Sheet ledger รายดีล -> รวมรายวัน (฿/kg ถ่วงน้ำหนักตัน)
# layer='nguanlong' ; แยก buy/sell x commodity ; ราคาอยู่ในคอลัมน์ price_baht_kg แล้ว
# auth: ตั้ง env อย่างใดอย่างหนึ่ง
#   NL_SHEET_CSV_URL                  = ลิงก์ CSV (File > Share > Publish to web) — ง่ายสุด
#   NL_SHEET_ID + GOOGLE_CREDENTIALS  = service account (sheet ยัง private) — ปลอดภัยกว่า
# คอลัมน์ที่ใช้: timestamp, action(buy/sell), commodity(รำ/ข้าวท่อน/ข้าวโพด), qty_ton, price_baht_kg
# ------------------------------------------------------------------
_NL_CACHE = {}


def _nl_commodity_code(s):
    """ระบุชนิดสินค้าจากชื่อ
    override (เช็กก่อนเสมอ — ชื่อมีคำหลักของหมวดอื่นปนอยู่ ถ้าไม่ override จะจัดผิด):
      'ดีด'  -> bounce    (ท่อนดีด — มี 'ท่อน' ปน แต่คนละราคากับปลายข้าว)
      'มะลิ' -> branmali  (รำมะลิ / ร่ามะลิ(พิมพ์เพี้ยน) — มี 'รำ' ปน แต่เป็นเกรด/ราคาแยกจากรำทั่วไป)
      'ปทุม' -> pathum    (ต้นปทุม / ต้นข้าวปทุม — คนละตัวกับปลายข้าว)
    ที่เหลือยึด 'คำแรก (ซ้ายสุด)' เป็นสินค้าหลัก:
      'รำปนปลาย' -> bran (รำเป็นหลัก) · 'ปลายปนรำ' -> broken (ปลายเป็นหลัก)"""
    s = str(s)
    if "ดีด" in s:
        return "bounce"
    if "มะลิ" in s:
        return "branmali"
    if "ปทุม" in s:
        return "pathum"
    hits = [(s.find(kw), code) for kw, code in
            (("โพด", "corn"), ("ปลาย", "broken"), ("ท่อน", "broken"), ("รำ", "bran"))
            if kw in s]
    return min(hits)[1] if hits else None


def _nl_action(s):
    s = str(s).strip().lower()
    if "sell" in s or "ขาย" in s:
        return "sell"
    if "buy" in s or "ซื้อ" in s:
        return "buy"
    return None


def _nl_float(x):
    try:
        v = float(str(x).replace(",", "").strip())
        return None if v != v else v          # กัน NaN (float('nan') ไม่ raise)
    except (ValueError, AttributeError):
        return None


def _nl_date(row):
    for key in ("timestamp", "date"):
        v = row.get(key)
        if v is None or str(v).strip() == "":
            continue
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            continue
    return None


def _parse_nl_ledger(records):
    """records = list[dict] จาก sheet -> {(code, action): [(obs_date, wavg_price, meta)]}
    รวมดีลในวันเดียวกันเป็นราคาเฉลี่ยถ่วงน้ำหนักด้วยตัน (fallback เฉลี่ยธรรมดา)."""
    from collections import defaultdict
    grp = defaultdict(list)
    for r in records:
        code = _nl_commodity_code(r.get("commodity"))
        act = _nl_action(r.get("action"))
        price = _nl_float(r.get("price_baht_kg"))
        d = _nl_date(r)
        if not code or not act or price is None or d is None:
            continue
        ton = _nl_float(r.get("qty_ton")) or 0.0    # ไม่มีตัน -> 0 (กัน NaN ลง JSON)
        grp[(code, act, d)].append((price, ton))
    out = defaultdict(list)
    for (code, act, d), items in grp.items():
        tons = [t for _, t in items]
        tot = sum(tons)
        # ถ่วงน้ำหนักด้วยตันเมื่อ 'ทุกดีล' มีตัน ; ถ้าดีลไหนไม่มีตัน ใช้เฉลี่ยธรรมดา
        if all(t > 0 for t in tons):
            wavg = sum(p * t for p, t in items) / tot
        else:
            wavg = sum(p for p, _ in items) / len(items)
        out[(code, act)].append((d, round(wavg, 3),
                                 {"src": "nguanlong/ledger", "deals": len(items),
                                  "ton": round(tot, 1)}))
    for k in out:
        out[k].sort(key=lambda x: x[0])
    return dict(out)


def _fetch_nl_records():
    import os
    csv_url = os.environ.get("NL_SHEET_CSV_URL")
    if csv_url:
        import io
        import csv as _csv
        import requests
        r = requests.get(csv_url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        raw = r.content
        # รองรับ xlsx (zip 'PK') หรือ URL ที่ publish เป็น xlsx -> อ่านด้วย read_excel
        if raw[:2] == b"PK" or "output=xlsx" in csv_url or "format=xlsx" in csv_url:
            import pandas as pd
            df = pd.read_excel(io.BytesIO(raw))
            cols = [str(c).strip() for c in df.columns]
            if not ("commodity" in cols and "price_baht_kg" in cols):
                raise ValueError(f"xlsx ไม่พบคอลัมน์ commodity/price_baht_kg (เจอ: {cols[:6]}) — "
                                 "ตรวจว่าแท็บ ledger เป็นแท็บแรกของไฟล์")
            return df.to_dict("records")
        if raw[:1] == b"\x89" or b"<html" in raw[:400].lower():
            raise ValueError("NL_SHEET_CSV_URL ไม่ได้คืน CSV/xlsx (ได้ไฟล์ binary/HTML) — "
                             "ต้องใช้ลิงก์ Publish to web แบบ CSV หรือ xlsx ของแท็บ ledger")
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp874", "tis-620", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        reader = _csv.DictReader(io.StringIO(text or ""))
        cols = [c.strip() for c in (reader.fieldnames or [])]
        if not ("commodity" in cols and "price_baht_kg" in cols):
            raise ValueError(f"CSV ไม่พบคอลัมน์ commodity/price_baht_kg (เจอหัวตาราง: {cols[:6]}) — "
                             "ตรวจว่า URL เป็น Publish-to-web CSV ของแท็บ ledger ที่ถูกต้อง")
        return list(reader)
    sid = os.environ.get("NL_SHEET_ID")
    creds = os.environ.get("GOOGLE_CREDENTIALS")
    if sid and creds:
        import json
        import gspread
        from google.oauth2.service_account import Credentials
        info = json.loads(creds)
        cr = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
        ws = gspread.authorize(cr).open_by_key(sid).sheet1
        return ws.get_all_records()
    raise NotImplementedError(
        "ง่วนล้ง sheet: ตั้ง env NL_SHEET_CSV_URL หรือ (NL_SHEET_ID + GOOGLE_CREDENTIALS) ก่อน")


def _nl_data():
    if "d" not in _NL_CACHE:                     # fetch+parse ครั้งเดียวต่อ process (ใช้ร่วม 6 collector)
        _NL_CACHE["d"] = _parse_nl_ledger(_fetch_nl_records())
    return _NL_CACHE["d"]


def _nl_series(code, action):
    rows = _nl_data().get((code, action), [])
    if not rows:
        raise NotImplementedError(f"ง่วนล้ง: ยังไม่มีดีล {action}/{code} ใน sheet")
    return rows


def collect_nl_buy_corn():    return _nl_series("corn", "buy")
def collect_nl_sell_corn():   return _nl_series("corn", "sell")
def collect_nl_buy_broken():  return _nl_series("broken", "buy")
def collect_nl_sell_broken(): return _nl_series("broken", "sell")
def collect_nl_buy_bran():    return _nl_series("bran", "buy")
def collect_nl_sell_bran():   return _nl_series("bran", "sell")
def collect_nl_buy_bounce():  return _nl_series("bounce", "buy")
def collect_nl_sell_bounce(): return _nl_series("bounce", "sell")
def collect_nl_buy_branmali():  return _nl_series("branmali", "buy")
def collect_nl_sell_branmali(): return _nl_series("branmali", "sell")
def collect_nl_buy_pathum():    return _nl_series("pathum", "buy")
def collect_nl_sell_pathum():   return _nl_series("pathum", "sell")


# ------------------------------------------------------------------
# สรุปรายคู่ค้า (supplier mix) — ใช้โดย dashboard หน้า 'สรุปซื้อ-ขาย รายเจ้า'
# อ่าน ledger ดิบ (ไม่ผ่าน observations) เพราะเป็นมุม 'รายดีล/รายเจ้า' ไม่ใช่ time-series รายวัน
# ต้องมีคอลัมน์ชื่อคู่ค้าในชีต — รองรับหลายชื่อ (_NL_PARTY_COLS) หรือกำหนดเองผ่าน env NL_PARTY_COL
# ------------------------------------------------------------------
_NL_PARTY_COLS = ("counterparty", "party", "supplier", "customer", "vendor",
                  "คู่ค้า", "แหล่งรับซื้อ", "แหล่งซื้อ", "ผู้ขาย", "ผู้ซื้อ",
                  "โรงสี", "ลูกค้า", "ร้าน", "ชื่อ", "name")


def _nl_party(row):
    """หาค่าคู่ค้าจากแถว ledger — ลองคอลัมน์ env NL_PARTY_COL ก่อน แล้วค่อยไล่ชื่อที่รู้จัก
    (เทียบแบบ case/space-insensitive เผื่อหัวตารางพิมพ์ต่างกัน)."""
    import os
    prefer = os.environ.get("NL_PARTY_COL")
    keys = ([prefer] if prefer else []) + list(_NL_PARTY_COLS)
    low = {str(k).strip().lower(): k for k in row}
    for cand in keys:
        if not cand:
            continue
        k = low.get(str(cand).strip().lower())
        if k is not None:
            v = str(row[k]).strip()
            if v and v.lower() != "nan":
                return v
    return None


def nl_party_summary(records=None):
    """สรุป ledger รายคู่ค้า -> dict:
      rows: list ต่อ (party, action, commodity) = {party, action, commodity,
            deals, ton, wavg_price, first_date, last_date}  (ราคาเฉลี่ยถ่วงน้ำหนักตัน)
      no_party: จำนวนดีลที่ระบุคู่ค้าไม่ได้ (ถูกข้าม)
      total: จำนวน record ทั้งหมด
      has_party_col: เจอคอลัมน์คู่ค้าอย่างน้อย 1 ดีลไหม"""
    from collections import defaultdict
    if records is None:
        records = _fetch_nl_records()
    grp = defaultdict(list)          # (party, act, code) -> [(price, ton, date)]
    no_party = 0
    has_party = False
    for r in records:
        code = _nl_commodity_code(r.get("commodity"))
        act = _nl_action(r.get("action"))
        price = _nl_float(r.get("price_baht_kg"))
        if not code or not act or price is None:
            continue
        party = _nl_party(r)
        if not party:
            no_party += 1
            continue
        has_party = True
        ton = _nl_float(r.get("qty_ton")) or 0.0
        grp[(party, act, code)].append((price, ton, _nl_date(r)))
    rows = []
    for (party, act, code), items in grp.items():
        tons = [t for _, t, _ in items]
        tot = sum(tons)
        if all(t > 0 for t in tons) and tot > 0:
            wavg = sum(p * t for p, t, _ in items) / tot
        else:
            wavg = sum(p for p, _, _ in items) / len(items)
        dates = sorted(d for _, _, d in items if d is not None)
        rows.append({"party": party, "action": act, "commodity": code,
                     "deals": len(items), "ton": round(tot, 2),
                     "wavg_price": round(wavg, 3),
                     "first_date": dates[0].isoformat() if dates else None,
                     "last_date": dates[-1].isoformat() if dates else None})
    rows.sort(key=lambda x: (x["action"], x["commodity"], -x["ton"]))
    return {"rows": rows, "no_party": no_party, "total": len(records),
            "has_party_col": has_party}


# map source_id -> collector callable
COLLECTORS = {
    "fx_usdthb":       collect_fx_usdthb,
    "enso_oni":        collect_enso_oni,
    "cbot_corn":       collect_cbot_corn,
    "trea_a1_fob":     collect_trea_a1_fob,
    "trea_wr5_fob":    collect_trea_wr5_fob,
    "cbot_soymeal":    collect_cbot_soymeal,
    "cbot_corn_thb_kg":collect_cbot_corn_thb,
    "brent_oil":       collect_brent_oil,
    "wti_oil":         collect_wti_oil,
    "fertilizer_urea": collect_fertilizer_urea,
    "cassava_chip":    collect_cassava_chip,
    "cpf_livestock":   collect_cpf_livestock,
    "live_hog":        collect_live_hog,
    "cpf_feed_corn":   collect_cpf_feed_corn,
    "cpf_feed_broken": collect_cpf_feed_broken,
    "cpf_feed_bran":   collect_cpf_feed_bran,
    "trm_broken":      collect_trm_broken,
    "trm_bran":        collect_trm_bran,
    "tmpa":            collect_tmpa,
    "dam_level":       collect_dam_level,
    "nl_buy_corn":     collect_nl_buy_corn,
    "nl_sell_corn":    collect_nl_sell_corn,
    "nl_buy_broken":   collect_nl_buy_broken,
    "nl_sell_broken":  collect_nl_sell_broken,
    "nl_buy_bran":     collect_nl_buy_bran,
    "nl_sell_bran":    collect_nl_sell_bran,
    "nl_buy_bounce":   collect_nl_buy_bounce,
    "nl_sell_bounce":  collect_nl_sell_bounce,
    "nl_buy_branmali": collect_nl_buy_branmali,
    "nl_sell_branmali":collect_nl_sell_branmali,
    "nl_buy_pathum":   collect_nl_buy_pathum,
    "nl_sell_pathum":  collect_nl_sell_pathum,
    "burma_corn":      _todo("burma_corn"),
}
