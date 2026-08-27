"""
dashboard.py — ง่วนล้ง Commodity Dashboard (Streamlit)
อ่านจาก Postgres (ตาราง observations / sources / ingest_runs) แล้ววาดกราฟ

รันเฉพาะที่: streamlit run dashboard.py   (ต้องมี env DATABASE_URL)
Deploy: Railway service ใหม่ในโปรเจกต์เดิม, start command = streamlit run dashboard.py
        --server.port $PORT --server.address 0.0.0.0
"""
from __future__ import annotations
import os
import pandas as pd

# ------------------------------------------------------------------
# พาเลตต์ Okabe-Ito (ปลอดภัยสำหรับตาบอดสี) — เรียงคงที่ ไม่วนสี
# ------------------------------------------------------------------
OKABE = ["#0072B2", "#E69F00", "#009E73", "#D55E00",
         "#CC79A7", "#56B4E9", "#F0E442", "#999999"]
INK = "#1a1a1a"
MUTED = "#6b7280"
GRID = "#e5e7eb"
GOOD, WARN, BAD = "#059669", "#d97706", "#dc2626"

# ป้ายกำกับ source_id -> ชื่อที่อ่านง่าย
LABELS = {
    "fx_usdthb": "USD/THB",
    "enso_oni": "ENSO / ONI",
    "cbot_corn": "CBOT Corn (¢/bu)",
    "cbot_corn_thb_kg": "ข้าวโพดโลก (฿/kg)",
    "cbot_soymeal": "กากถั่วเหลือง CBOT ($/ton)",
    "trea_a1_fob": "ปลายข้าว A1 FOB",
    "trea_wr5_fob": "ข้าวขาว 5% FOB",
    "cpf_feed_corn": "CPF ข้าวโพด",
    "cpf_feed_broken": "CPF ปลายข้าว",
    "cpf_feed_bran": "CPF รำ",
    "tmpa": "TMPA ข้าวโพด (benchmark)",
    "cassava_chip": "มันเส้น (substitute)",
    "brent_oil": "น้ำมัน Brent",
    "wti_oil": "น้ำมัน WTI",
    "fertilizer_urea": "ยูเรีย",
    "dam_level": "น้ำเขื่อน %",
    "cpf_livestock": "ลูกไก่เนื้อ (฿/ตัว)",
    "live_hog": "สุกรมีชีวิต (฿/kg)",
    "burma_corn": "ข้าวโพดชายแดน",
}

# ------------------------------------------------------------------
# Pure helpers (ทดสอบได้โดยไม่ต้องมี Streamlit/DB)
# ------------------------------------------------------------------
def latest_prev_by_source(obs: pd.DataFrame) -> dict:
    """คืน {source_id: {'date','value','prev','delta'}} จากแถวล่าสุด/ก่อนหน้าของแต่ละแหล่ง."""
    out = {}
    if obs.empty:
        return out
    for sid, g in obs.sort_values("obs_date").groupby("source_id"):
        vals = g["value"].tolist()
        dates = g["obs_date"].tolist()
        latest = vals[-1]
        prev = vals[-2] if len(vals) >= 2 else None
        out[sid] = {
            "date": dates[-1],
            "value": latest,
            "prev": prev,
            "delta": (latest - prev) if prev is not None else None,
        }
    return out


def series(obs: pd.DataFrame, sid: str) -> pd.DataFrame:
    """time series ของ 1 แหล่ง เรียงตามวันที่ (คอลัมน์ obs_date, value)."""
    g = obs[obs["source_id"] == sid][["obs_date", "value"]].sort_values("obs_date")
    return g.reset_index(drop=True)


def latest_buyers(obs: pd.DataFrame) -> dict:
    """ราคารับซื้อข้าวโพดรายโรงงานจากแถว tmpa ล่าสุด (meta.buyers)."""
    t = obs[obs["source_id"] == "tmpa"].sort_values("obs_date")
    if t.empty:
        return {}
    meta = t.iloc[-1]["meta"] or {}
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except Exception:
            return {}
    return meta.get("buyers", {}) if isinstance(meta, dict) else {}


def basis_frame(obs: pd.DataFrame, thai="tmpa", world="cbot_corn_thb_kg") -> pd.DataFrame:
    """รวมราคาไทย vs โลก(฿/kg) ต่อวัน + คำนวณ basis = ไทย - โลก."""
    a = series(obs, thai).rename(columns={"value": "thai"})
    b = series(obs, world).rename(columns={"value": "world"})
    if a.empty or b.empty:
        return pd.DataFrame(columns=["obs_date", "thai", "world", "basis"])
    m = pd.merge(a, b, on="obs_date", how="outer").sort_values("obs_date")
    m["basis"] = m["thai"] - m["world"]
    return m.reset_index(drop=True)


# ------------------------------------------------------------------
# ส่วนที่ต้องมี Streamlit — ครอบไว้ใน main() เพื่อให้ import ทดสอบ helper ได้
# ------------------------------------------------------------------
def _load_data():
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    obs = pd.read_sql(
        "SELECT source_id, obs_date, value, meta, ingested_at FROM observations", conn)
    src = pd.read_sql("SELECT * FROM sources", conn)
    runs = pd.read_sql(
        "SELECT DISTINCT ON (source_id) source_id, status, rows, message, run_at "
        "FROM ingest_runs ORDER BY source_id, run_at DESC", conn)
    conn.close()
    if not obs.empty:
        obs["value"] = obs["value"].astype(float)
        obs["obs_date"] = pd.to_datetime(obs["obs_date"])
    return obs, src, runs


def _line(obs, ids, title, ytitle):
    import plotly.graph_objects as go
    fig = go.Figure()
    for i, sid in enumerate(ids):
        s = series(obs, sid)
        if s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s["obs_date"], y=s["value"], mode="lines+markers",
            name=LABELS.get(sid, sid), line=dict(width=2, color=OKABE[i % len(OKABE)]),
            marker=dict(size=6)))
    fig.update_layout(
        title=title, yaxis_title=ytitle, height=340,
        margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified",
        legend=dict(orientation="h", y=-0.2), plot_bgcolor="white",
        font=dict(color=INK))
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig


def main():
    import streamlit as st
    import plotly.graph_objects as go

    st.set_page_config(page_title="ง่วนล้ง Commodity Dashboard",
                       page_icon="🌽", layout="wide")
    st.title("🌽 ง่วนล้ง Commodity Dashboard")

    if not os.environ.get("DATABASE_URL"):
        st.error("ไม่พบ DATABASE_URL — ตั้ง env variable ให้ชี้ Postgres ก่อน")
        st.stop()

    @st.cache_data(ttl=600)
    def load():
        return _load_data()

    try:
        obs, src, runs = load()
    except Exception as e:
        st.error(f"ต่อฐานข้อมูลไม่ได้: {e}")
        st.stop()

    if obs.empty:
        st.warning("ยังไม่มีข้อมูลใน observations — รอ pipeline รันรอบแรก")
        st.stop()

    last_ing = pd.to_datetime(obs["ingested_at"]).max()
    st.caption(f"ข้อมูลล่าสุด (ingested): {last_ing:%Y-%m-%d %H:%M} · cache 10 นาที · "
               "อัปเดตอัตโนมัติทุกวันจาก pipeline")

    lp = latest_prev_by_source(obs)

    # ---------- KPI tiles ----------
    def tile(col, sid, fmt="{:.2f}"):
        d = lp.get(sid)
        with col:
            if not d:
                st.metric(LABELS.get(sid, sid), "—")
                return
            delta = None if d["delta"] is None else fmt.format(d["delta"])
            st.metric(LABELS.get(sid, sid), fmt.format(d["value"]), delta)

    st.subheader("สรุปวันนี้")
    c = st.columns(6)
    tile(c[0], "tmpa"); tile(c[1], "cbot_corn_thb_kg"); tile(c[2], "cpf_feed_corn")
    tile(c[3], "fx_usdthb", "{:.3f}"); tile(c[4], "live_hog"); tile(c[5], "enso_oni")

    # basis KPI
    bf = basis_frame(obs)
    if not bf.empty and bf["basis"].notna().any():
        last = bf.dropna(subset=["basis"]).iloc[-1]
        st.metric("Basis: ข้าวโพดไทย − โลก (฿/kg)", f"{last['basis']:.2f}",
                  help="ช่องว่างราคาข้าวโพดไทยเทียบตลาดโลกแปลงเป็น ฿/kg")

    st.divider()

    # ---------- Basis chart ----------
    st.subheader("ราคาข้าวโพด: ไทย vs ตลาดโลก (฿/kg)")
    if not bf.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=bf["obs_date"], y=bf["thai"], name="ไทย (TMPA)",
                                 mode="lines+markers", line=dict(width=2, color=OKABE[0])))
        fig.add_trace(go.Scatter(x=bf["obs_date"], y=bf["world"], name="โลก (฿/kg)",
                                 mode="lines+markers", line=dict(width=2, color=OKABE[1])))
        fig.update_layout(height=360, hovermode="x unified", yaxis_title="฿/kg",
                          margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white",
                          legend=dict(orientation="h", y=-0.2), font=dict(color=INK))
        fig.update_xaxes(gridcolor=GRID); fig.update_yaxes(gridcolor=GRID)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("ยังไม่มีข้อมูลพอสำหรับ basis")

    # ---------- Feed ingredients (THB/kg) ----------
    st.subheader("วัตถุดิบอาหารสัตว์ (฿/kg)")
    st.plotly_chart(_line(obs, ["cpf_feed_corn", "cpf_feed_broken", "cpf_feed_bran",
                                "cassava_chip"], "", "฿/kg"), use_container_width=True)

    # ---------- Buyers bar ----------
    buyers = latest_buyers(obs)
    if buyers:
        st.subheader("ราคารับซื้อข้าวโพดรายโรงงาน (TMPA ล่าสุด)")
        bdf = (pd.DataFrame({"buyer": list(buyers.keys()),
                             "price": [float(v) for v in buyers.values()]})
               .sort_values("price", ascending=True))
        fig = go.Figure(go.Bar(x=bdf["price"], y=bdf["buyer"], orientation="h",
                               marker_color=OKABE[0]))
        fig.update_layout(height=max(300, 26 * len(bdf)), xaxis_title="฿/kg",
                          margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white",
                          font=dict(color=INK))
        fig.update_xaxes(gridcolor=GRID)
        st.plotly_chart(fig, use_container_width=True)

    # ---------- World futures (small multiples, different units) ----------
    st.subheader("ตลาดโลก")
    w = st.columns(3)
    with w[0]:
        st.plotly_chart(_line(obs, ["cbot_corn"], "ข้าวโพด CBOT", "¢/bu"),
                        use_container_width=True)
    with w[1]:
        st.plotly_chart(_line(obs, ["cbot_soymeal"], "กากถั่วเหลือง", "$/ton"),
                        use_container_width=True)
    with w[2]:
        st.plotly_chart(_line(obs, ["brent_oil", "wti_oil"], "น้ำมันดิบ", "$/bbl"),
                        use_container_width=True)

    # ---------- Rice FOB ----------
    st.subheader("ราคาข้าวส่งออก FOB (USD/ton)")
    st.plotly_chart(_line(obs, ["trea_wr5_fob", "trea_a1_fob"], "", "USD/ton"),
                    use_container_width=True)

    # ---------- Demand signals ----------
    st.subheader("สัญญาณดีมานด์ปศุสัตว์")
    d = st.columns(2)
    with d[0]:
        st.plotly_chart(_line(obs, ["live_hog"], "สุกรมีชีวิต", "฿/kg"),
                        use_container_width=True)
    with d[1]:
        st.plotly_chart(_line(obs, ["cpf_livestock"], "ลูกไก่เนื้อ", "฿/ตัว"),
                        use_container_width=True)

    # ---------- Drivers (small multiples) ----------
    st.subheader("ปัจจัยขับเคลื่อน")
    dr = st.columns(4)
    for col, sid, yt in zip(dr, ["fx_usdthb", "enso_oni", "dam_level", "fertilizer_urea"],
                            ["THB/USD", "index", "%", "$/ton"]):
        with col:
            st.plotly_chart(_line(obs, [sid], LABELS.get(sid, sid), yt),
                            use_container_width=True)

    # ---------- Data health ----------
    st.divider()
    st.subheader("สถานะแหล่งข้อมูล")
    if not runs.empty:
        emoji = {"ok": "🟢", "skipped": "⚪", "error": "🔴"}
        rr = runs.copy()
        rr["แหล่ง"] = rr["source_id"].map(lambda s: LABELS.get(s, s))
        rr["สถานะ"] = rr["status"].map(lambda s: f"{emoji.get(s, '❔')} {s}")
        rr["รันล่าสุด"] = pd.to_datetime(rr["run_at"]).dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(rr[["แหล่ง", "สถานะ", "rows", "รันล่าสุด", "message"]],
                     use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
