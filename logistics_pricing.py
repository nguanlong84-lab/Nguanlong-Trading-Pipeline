"""
logistics_pricing.py — หน้า "โลจิสติกส์ / คิดราคาส่ง" (interactive landed-cost + margin + แผนที่)
แนวคิด: ราคาซื้อจากโรงสี + ค่าขนส่งตามระยะทาง = ราคาส่งถึงโรงงาน
        เลือกต้นทาง (ซื้อ) + ปลายทาง (ขาย) -> เห็นระยะทาง ค่าขนส่ง ราคาสุทธิ margin บนแผนที่

ออกแบบให้ "เสียบเข้า dashboard เดิม" ได้ด้วยบรรทัดเดียว:
    from logistics_pricing import page_logistics
    st.Page(page_logistics, title="โลจิสติกส์ / ราคาส่ง", icon="🚚")

แหล่งข้อมูล (อยู่ข้างไฟล์นี้ในโปรเจกต์):
  - nl_locations.csv    : counterparty -> พิกัด GPS (จับคู่จาก Station.xls, มี needs_review)
  - nl_deals_seed.csv   : ดีลจาก Trading Log (ใช้เป็นราคาเริ่มต้น)
  ถ้ามี env ledger (NL_SHEET_CSV_URL / NL_SHEET_ID) จะดึงดีลสดผ่าน collectors อัตโนมัติ

หมายเหตุค่าขนส่ง: เรตจากตาราง "อัตราค่าบรรทุก" (ฐานน้ำมัน 37.50 บาท/ลิตร ณ 1 ก.ค. 2569)
"""
from __future__ import annotations
import os
import math
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

_HERE = os.path.dirname(os.path.abspath(__file__))
OKABE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9"]
BUY_C, SELL_C = "#0072B2", "#D55E00"
GOOD, BAD, MUTED = "#059669", "#dc2626", "#6b7280"

# ------------------------------------------------------------------
# ตารางอัตราค่าบรรทุก (บาท/กก.) — (ระยะทางไม่เกิน กม., รถพ่วง, รถเดี่ยว)
# ที่มา: รูป "อัตราค่าบรรทุก" ฐานน้ำมัน 37.50 บาท/ลิตร (1 ก.ค. 2569) · ปรับลด 3% แล้ว
# ------------------------------------------------------------------
TRANSPORT_RATES = [
    (50,  0.16, 0.24), (100, 0.24, 0.26), (200, 0.25, 0.36), (250, 0.32, 0.40),
    (300, 0.40, 0.46), (350, 0.44, 0.52), (400, 0.51, 0.57), (450, 0.56, 0.62),
    (500, 0.61, 0.69), (550, 0.69, 0.75), (600, 0.72, 0.80), (650, 0.74, 0.85),
    (700, 0.82, 0.92),
]
TRUCKS = {"รถพ่วง": 1, "รถเดี่ยว": 2}           # index ในตาราง
TON_PER_TRUCK = {"รถพ่วง": 30.0, "รถเดี่ยว": 16.0}   # ปริมาณเริ่มต้นต่อคัน (ปรับได้)


def transport_rate(km: float, truck: str) -> tuple[float, bool]:
    """คืน (อัตรา บาท/กก., เกินตาราง?) ตามระยะทาง + ชนิดรถ.
    เกิน 700 กม. = ประมาณการต่อจาก step สุดท้าย (คืน flag=True)."""
    col = TRUCKS[truck]
    for maxkm, phuang, diao in TRANSPORT_RATES:
        if km <= maxkm:
            return (phuang if col == 1 else diao), False
    # เกิน 700 กม.: ต่อ step สุดท้าย (700 - 650)
    last, prev = TRANSPORT_RATES[-1], TRANSPORT_RATES[-2]
    base = last[col]
    step = last[col] - prev[col]                 # เพิ่มต่อ 50 กม.
    extra_steps = math.ceil((km - last[0]) / 50.0)
    return round(base + step * extra_steps, 3), True


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ------------------------------------------------------------------
# Commodity — จัดกลุ่มกว้าง (ใช้ 'กรอง' dropdown เท่านั้น ไม่บังคับจับคู่)
# ตรงกับ 3 หน้าหลักของ dashboard: ข้าวโพด / ปลายข้าว-ท่อน / รำ
# ------------------------------------------------------------------
CLASS_LABEL = {"corn": "ข้าวโพด", "broken": "ปลายข้าว / ท่อน", "bran": "รำ",
               "soy": "กากถั่ว", "other": "อื่นๆ"}


def broad_class(commodity: str) -> str:
    s = str(commodity)
    if "โพด" in s:
        return "corn"
    if "ท่อน" in s or "ปลาย" in s or "ปทุม" in s:
        return "broken"
    if "รำ" in s:
        return "bran"
    if "ถั่ว" in s:
        return "soy"
    return "other"


# ------------------------------------------------------------------
# Data load
# ------------------------------------------------------------------
@st.cache_data(ttl=1800)
def load_locations() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(_HERE, "nl_locations.csv"))
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    return df.dropna(subset=["lat", "lon"])


@st.cache_data(ttl=600)
def load_deals() -> pd.DataFrame:
    """ดีลระดับรายการ: ดึง ledger สดก่อน (collectors._fetch_nl_records), ไม่ได้ค่อย fallback seed.
    df.attrs['source'] = 'live' | 'seed' (ยังไม่ตั้ง env) | 'seed-fallback' (ตั้งแล้วแต่ดึงไม่ได้)."""
    records, src = None, "seed"
    try:
        from collectors import _fetch_nl_records
    except Exception:
        _fetch_nl_records = None                   # ไม่มี collectors ในบริบทนี้ -> seed
    if _fetch_nl_records is not None:
        try:
            records = _fetch_nl_records()
            src = "live"
        except NotImplementedError:
            records, src = None, "seed"            # ยังไม่ได้ตั้ง env ledger
        except Exception:
            records, src = None, "seed-fallback"   # ตั้งแล้วแต่ดึงไม่สำเร็จ (เน็ต/URL/สิทธิ์)
    if records:
        df = pd.DataFrame(records)
    else:
        df = pd.read_csv(os.path.join(_HERE, "nl_deals_seed.csv"))
    # normalize
    for c in ("action", "commodity", "counterparty"):
        if c not in df.columns:
            df[c] = None
    df["price_baht_kg"] = pd.to_numeric(df.get("price_baht_kg"), errors="coerce")
    df["qty_ton"] = pd.to_numeric(df.get("qty_ton"), errors="coerce")
    # recency: timestamp (เวลาบันทึก, มักครบ) ก่อน แล้วค่อย date (วันรับของ, ว่างบ่อย)
    ts = (pd.to_datetime(df["timestamp"], errors="coerce")
          if "timestamp" in df.columns else pd.Series(pd.NaT, index=df.index))
    dt = (pd.to_datetime(df["date"], errors="coerce")
          if "date" in df.columns else pd.Series(pd.NaT, index=df.index))
    df["recency"] = ts.fillna(dt)
    df = df[df["counterparty"].notna() & df["price_baht_kg"].notna()].copy()
    df["action"] = df["action"].astype(str).str.strip().str.lower()
    df["cls"] = df["commodity"].map(broad_class)
    df.attrs["source"] = src
    return df


def priced_points(deals: pd.DataFrame, locs: pd.DataFrame, action: str) -> pd.DataFrame:
    """ราคาล่าสุด ต่อ (คู่ค้า, สินค้า) ของฝั่ง buy/sell + พิกัด.
    เรียงตาม recency (timestamp>date) แล้ว order_id แล้วเลือกแถวล่าสุดของแต่ละกลุ่ม."""
    d = deals[deals["action"] == action].copy()
    if d.empty:
        return pd.DataFrame(columns=["counterparty", "commodity", "cls", "price", "date"])
    sort_cols = [c for c in ("recency", "order_id") if c in d.columns]
    d = d.sort_values(sort_cols, na_position="first")
    latest = (d.groupby(["counterparty", "commodity"], as_index=False)
              .agg(price=("price_baht_kg", "last"), date=("recency", "last"),
                   cls=("cls", "last"), deals=("price_baht_kg", "size")))
    m = latest.merge(locs[["counterparty", "matched_station", "province", "amphur",
                           "lat", "lon", "needs_review"]],
                     on="counterparty", how="left")
    return m


def _fmt_opt(r) -> str:
    warn = " ⚠️" if bool(r.get("needs_review")) else ""
    prov = f" · {r['province']}" if pd.notna(r.get("province")) else ""
    return f"{r['counterparty']} — {r['commodity']} — {r['price']:.2f}฿{prov}{warn}"


# ------------------------------------------------------------------
# Map
# ------------------------------------------------------------------
def route_map(src, dst, margin):
    """แผนที่เส้นทางต้นทาง->ปลายทาง — รองรับ plotly ทั้งรุ่นเก่า (Scattermapbox/mapbox)
    และรุ่นใหม่ (Scattermap/map) โดยไม่ต้องใช้ token."""
    new_api = hasattr(go, "Scattermap")
    Trace = go.Scattermap if new_api else go.Scattermapbox
    line_c = GOOD if margin is not None and margin >= 0 else BAD
    fig = go.Figure()
    fig.add_trace(Trace(
        lat=[src["lat"], dst["lat"]], lon=[src["lon"], dst["lon"]],
        mode="lines", line=dict(width=3, color=line_c), hoverinfo="skip", showlegend=False))
    fig.add_trace(Trace(
        lat=[src["lat"]], lon=[src["lon"]], mode="markers+text",
        marker=dict(size=16, color=BUY_C), text=["ซื้อ"], textposition="top right",
        name="ต้นทาง (ซื้อ)",
        hovertext=[f"{src['counterparty']}<br>{src['commodity']} {src['price']:.2f}฿"],
        hoverinfo="text"))
    fig.add_trace(Trace(
        lat=[dst["lat"]], lon=[dst["lon"]], mode="markers+text",
        marker=dict(size=16, color=SELL_C), text=["ขาย"], textposition="top right",
        name="ปลายทาง (ขาย)",
        hovertext=[f"{dst['counterparty']}<br>{dst['commodity']} {dst['price']:.2f}฿"],
        hoverinfo="text"))
    clat, clon = (src["lat"] + dst["lat"]) / 2, (src["lon"] + dst["lon"]) / 2
    span = max(abs(src["lat"] - dst["lat"]), abs(src["lon"] - dst["lon"]), 0.4)
    zoom = max(5, min(9 - math.log2(span / 0.4 + 1), 11))
    map_cfg = dict(style="open-street-map", center=dict(lat=clat, lon=clon), zoom=zoom)
    fig.update_layout(height=420, margin=dict(l=0, r=0, t=0, b=0),
                      legend=dict(orientation="h", y=-0.05),
                      **({"map": map_cfg} if new_api else {"mapbox": map_cfg}))
    return fig


# ------------------------------------------------------------------
# Ranking (anchored)
# ------------------------------------------------------------------
def rank_lanes(anchor, others, buy_price, truck, road_factor, anchor_is_buy):
    rows = []
    for _, o in others.iterrows():
        if pd.isna(o["lat"]) or pd.isna(o["lon"]):
            continue
        km = haversine_km(anchor["lat"], anchor["lon"], o["lat"], o["lon"]) * road_factor
        rate, over = transport_rate(km, truck)
        if anchor_is_buy:
            landed = buy_price + rate
            margin = o["price"] - landed
            name, price = o["counterparty"], o["price"]
        else:
            landed = o["price"] + rate
            margin = anchor["price"] - landed
            name, price = o["counterparty"], o["price"]
        rows.append({"คู่ค้า": name, "สินค้า": o["commodity"], "จังหวัด": o.get("province"),
                     "ราคา (฿)": round(price, 2), "ระยะ (กม.)": round(km),
                     "ค่าขนส่ง (฿)": rate, "ราคาสุทธิ (฿)": round(landed, 2),
                     "margin (฿/กก.)": round(margin, 2),
                     "เกินตาราง": "⚠️" if over else ""})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("margin (฿/กก.)", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------
# PAGE
# ------------------------------------------------------------------
def page_logistics():
    st.title("🚚 โลจิสติกส์ / คิดราคาส่ง")
    st.markdown("เลือก **ต้นทาง (โรงสีที่ซื้อ)** และ **ปลายทาง (โรงงานที่ขาย)** "
                "แล้วดูระยะทาง ค่าขนส่ง ราคาสุทธิถึงปลายทาง และ margin บนแผนที่ · "
                "ราคาเริ่มต้นดึงจากดีลจริงใน Trading Log (แก้ตัวเลขเองได้)")

    locs = load_locations()
    deals = load_deals()
    buys = priced_points(deals, locs, "buy")
    sells = priced_points(deals, locs, "sell")
    if buys.empty or sells.empty:
        st.warning("ยังไม่มีดีลซื้อหรือขายพอจะคำนวณ — ตรวจ Trading Log / ledger")
        st.stop()

    # ---- สถานะแหล่งราคา + รีเฟรช ----
    src = deals.attrs.get("source", "seed")
    last = pd.to_datetime(deals["recency"], errors="coerce").max()
    last_txt = f" · ดีลล่าสุด {last:%Y-%m-%d %H:%M}" if pd.notna(last) else ""
    sc1, sc2 = st.columns([5, 1])
    with sc1:
        if src == "live":
            st.caption(f"🟢 ราคาจาก **ledger สด** (Google Sheet){last_txt} · แคช 10 นาที")
        elif src == "seed-fallback":
            st.caption(f"🟠 ดึง ledger สดไม่สำเร็จ — ใช้ **Trading Log (seed)** ชั่วคราว{last_txt} · "
                       "ตรวจ NL_SHEET_CSV_URL / สิทธิ์ชีต")
        else:
            st.caption(f"⚪ ราคาจาก **Trading Log (seed)**{last_txt} · "
                       "ตั้ง env `NL_SHEET_CSV_URL` ที่ service dashboard เพื่อดึงสด")
    with sc2:
        if st.button("🔄 รีเฟรช", use_container_width=True):
            load_deals.clear()
            st.rerun()

    # ---- ตัวกรองกลุ่มสินค้า ----
    classes = [c for c in ["corn", "broken", "bran", "soy", "other"]
               if c in set(buys["cls"]) | set(sells["cls"])]
    csel = st.radio("กลุ่มสินค้า (กรองรายการ)", ["ทั้งหมด"] + classes,
                    format_func=lambda c: "ทั้งหมด" if c == "ทั้งหมด" else CLASS_LABEL[c],
                    horizontal=True)
    fbuys = buys if csel == "ทั้งหมด" else buys[buys["cls"] == csel]
    fsells = sells if csel == "ทั้งหมด" else sells[sells["cls"] == csel]
    if fbuys.empty or fsells.empty:
        st.info("กลุ่มนี้มีเฉพาะฝั่งซื้อหรือฝั่งขาย — เลือก 'ทั้งหมด' เพื่อจับคู่ข้ามกลุ่ม")
        fbuys, fsells = buys, sells

    fbuys = fbuys.sort_values("counterparty").reset_index(drop=True)
    fsells = fsells.sort_values("counterparty").reset_index(drop=True)

    # ---- เลือกต้นทาง/ปลายทาง ----
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 🟦 ต้นทาง — ซื้อจากโรงสี")
        bi = st.selectbox("โรงสี (ราคาซื้อ)", range(len(fbuys)),
                          format_func=lambda i: _fmt_opt(fbuys.iloc[i]), key="buy_sel")
        src = fbuys.iloc[bi].to_dict()
        buy_price = st.number_input("ราคาซื้อ (฿/กก.)", value=float(src["price"]),
                                    step=0.05, format="%.2f")
    with c2:
        st.markdown("##### 🟧 ปลายทาง — ขายให้โรงงาน")
        si = st.selectbox("โรงงาน (ราคาขาย)", range(len(fsells)),
                          format_func=lambda i: _fmt_opt(fsells.iloc[i]), key="sell_sel")
        dst = fsells.iloc[si].to_dict()
        sell_price = st.number_input("ราคาขาย (฿/กก.)", value=float(dst["price"]),
                                     step=0.05, format="%.2f")
    src["price"], dst["price"] = buy_price, sell_price

    # ---- พารามิเตอร์ขนส่ง ----
    p1, p2, p3 = st.columns([1, 1, 1])
    truck = p1.selectbox("ชนิดรถ", list(TRUCKS.keys()))
    ton = p2.number_input("ตัน/คัน", value=float(TON_PER_TRUCK[truck]), step=1.0)
    with p3:
        with st.expander("⚙️ ตั้งค่าระยะทาง"):
            road_factor = st.slider("ตัวคูณระยะถนน (เทียบเส้นตรง)", 1.0, 1.6, 1.30, 0.05,
                                    help="ระยะจริงบนถนนยาวกว่าเส้นตรง ~1.2–1.4 เท่า")
            manual = st.checkbox("กำหนดระยะทางเอง (กม.)")

    if pd.isna(src["lat"]) or pd.isna(dst["lat"]):
        st.error("คู่ค้าที่เลือกยังไม่มีพิกัด GPS — เลือกที่อื่น หรือเติมพิกัดใน nl_locations.csv")
        st.stop()

    straight = haversine_km(src["lat"], src["lon"], dst["lat"], dst["lon"])
    est_km = straight * road_factor
    if manual:
        est_km = st.number_input("ระยะทาง (กม.)", value=float(round(est_km)), step=5.0)

    rate, over = transport_rate(est_km, truck)
    landed = buy_price + rate
    margin = sell_price - landed
    margin_truck = margin * ton * 1000

    # ---- ผลลัพธ์ ----
    if src["counterparty"] == dst["counterparty"]:
        st.warning("ต้นทางและปลายทางเป็นที่เดียวกัน — ระยะทาง 0")
    if bool(src.get("needs_review")) or bool(dst.get("needs_review")):
        st.warning("⚠️ ต้นทาง/ปลายทางบางจุด **พิกัดยังไม่ยืนยัน** (จับคู่อัตโนมัติ) — "
                   "ตรวจ/แก้ได้ใน nl_locations.csv ก่อนใช้ตัดสินใจจริง")

    st.divider()
    m = st.columns(5)
    m[0].metric("ระยะทาง", f"{est_km:,.0f} กม." + (" ⚠️" if over else ""),
                help="เส้นตรง × ตัวคูณถนน" + (" · เกินตาราง 700 กม. เป็นประมาณการ" if over else ""))
    m[1].metric("ค่าขนส่ง", f"{rate:.2f} ฿/กก.", help=f"{truck} · ตามช่วงระยะทาง")
    m[2].metric("ราคาสุทธิถึงปลายทาง", f"{landed:.2f} ฿/กก.", help="ราคาซื้อ + ค่าขนส่ง")
    m[3].metric("margin", f"{margin:+.2f} ฿/กก.",
                delta="คุ้ม" if margin >= 0 else "ขาดทุน",
                delta_color="normal" if margin >= 0 else "inverse")
    m[4].metric(f"margin/คัน ({ton:.0f} ตัน)", f"{margin_truck:+,.0f} ฿")

    if margin >= 0:
        st.success(f"🟢 ซื้อ {buy_price:.2f} + ขนส่ง {rate:.2f} = **{landed:.2f}** ฿/กก. · "
                   f"ขายได้ {sell_price:.2f} → กำไร **{margin:+.2f}** ฿/กก. "
                   f"(~{margin_truck:+,.0f} ฿/คัน)")
    else:
        st.error(f"🔴 ราคาสุทธิ {landed:.2f} ฿/กก. สูงกว่าราคาขาย {sell_price:.2f} → "
                 f"ขาดทุน **{margin:.2f}** ฿/กก.")

    st.plotly_chart(route_map(src, dst, margin), use_container_width=True)
    st.caption(f"เส้นตรง {straight:,.0f} กม. → ประเมินระยะถนน {est_km:,.0f} กม. · "
               f"อัตราค่าขนส่งอ้างอิงตาราง (ฐานน้ำมัน 37.50 บาท/ลิตร, 1 ก.ค. 2569)")

    # ---- Anchored rankings ----
    st.divider()
    st.subheader("🎯 หาจังหวะที่คุ้มสุด")
    same_cls_sells = fsells[fsells["cls"] == src["cls"]] if csel == "ทั้งหมด" else fsells
    same_cls_buys = fbuys[fbuys["cls"] == dst["cls"]] if csel == "ทั้งหมด" else fbuys

    t1, t2 = st.tabs(["ขายที่ไหนคุ้มสุด (ตรึงต้นทาง)", "ซื้อจากที่ไหนถูกสุด (ตรึงปลายทาง)"])
    with t1:
        st.caption(f"ตรึงต้นทาง **{src['counterparty']}** (ซื้อ {buy_price:.2f}฿) · "
                   f"เทียบขายทุกโรงงานในกลุ่มเดียวกัน หัก {truck}")
        r = rank_lanes(src, same_cls_sells, buy_price, truck, road_factor, anchor_is_buy=True)
        if r.empty:
            st.info("ไม่มีปลายทางในกลุ่มสินค้าเดียวกัน")
        else:
            st.dataframe(r, use_container_width=True, hide_index=True)
    with t2:
        st.caption(f"ตรึงปลายทาง **{dst['counterparty']}** (ขาย {sell_price:.2f}฿) · "
                   f"เทียบซื้อทุกโรงสีในกลุ่มเดียวกัน หัก {truck}")
        r = rank_lanes(dst, same_cls_buys, None, truck, road_factor, anchor_is_buy=False)
        if r.empty:
            st.info("ไม่มีต้นทางในกลุ่มสินค้าเดียวกัน")
        else:
            st.dataframe(r, use_container_width=True, hide_index=True)

    with st.expander("📋 ตารางอัตราค่าบรรทุก (บาท/กก.)"):
        rate_df = pd.DataFrame(TRANSPORT_RATES, columns=["ระยะไม่เกิน (กม.)", "รถพ่วง", "รถเดี่ยว"])
        st.dataframe(rate_df, use_container_width=True, hide_index=True)
        st.caption("เกิน 700 กม. = ประมาณการต่อจากช่วงสุดท้าย · ปรับอัตราลง 3% แล้ว (ตามหมายเหตุในตาราง)")

    nrev = int(locs["needs_review"].sum()) if "needs_review" in locs else 0
    if nrev:
        st.caption(f"ℹ️ มีคู่ค้า {nrev} รายที่จับคู่พิกัดอัตโนมัติแบบยังไม่ยืนยัน (⚠️) — "
                   "แก้พิกัดได้ในไฟล์ nl_locations.csv")


if __name__ == "__main__":
    st.set_page_config(page_title="โลจิสติกส์ / ราคาส่ง", page_icon="🚚", layout="wide")
    page_logistics()
