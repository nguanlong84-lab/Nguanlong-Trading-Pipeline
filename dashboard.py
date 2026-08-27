"""
dashboard.py — ง่วนล้ง Commodity Dashboard (Streamlit, หลายหน้า)
หน้า: ภาพรวม + เจาะราย commodity (ข้าวโพด / ปลายข้าว / รำข้าว)
อ่านจาก Postgres (observations / sources / ingest_runs)

รัน: streamlit run dashboard.py   (ต้องมี env DATABASE_URL)
"""
from __future__ import annotations
import os
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# ------------------------------------------------------------------
# พาเลตต์ Okabe-Ito (ปลอดภัยตาบอดสี) เรียงคงที่ ไม่วนสี
# ------------------------------------------------------------------
OKABE = ["#0072B2", "#E69F00", "#009E73", "#D55E00",
         "#CC79A7", "#56B4E9", "#F0E442", "#999999"]
INK, GRID = "#1a1a1a", "#e5e7eb"

LABELS = {
    "fx_usdthb": "USD/THB", "enso_oni": "ENSO / ONI",
    "cbot_corn": "CBOT Corn (¢/bu)", "cbot_corn_thb_kg": "ข้าวโพดโลก (฿/kg)",
    "cbot_soymeal": "กากถั่วเหลือง CBOT ($/ton)",
    "trea_a1_fob": "ปลายข้าว A1 FOB", "trea_wr5_fob": "ข้าวขาว 5% FOB",
    "cpf_feed_corn": "CPF ข้าวโพด", "cpf_feed_broken": "CPF ปลายข้าว",
    "cpf_feed_bran": "CPF รำ", "tmpa": "TMPA ข้าวโพด (benchmark)",
    "cassava_chip": "มันเส้น (substitute)", "brent_oil": "น้ำมัน Brent",
    "wti_oil": "น้ำมัน WTI", "fertilizer_urea": "ยูเรีย", "dam_level": "น้ำเขื่อน %",
    "cpf_livestock": "ลูกไก่เนื้อ (฿/ตัว)", "live_hog": "สุกรมีชีวิต (฿/kg)",
    "burma_corn": "ข้าวโพดชายแดน",
}

# ------------------------------------------------------------------
# Pure helpers (ทดสอบได้ ไม่เรียก st.*)
# ------------------------------------------------------------------
def latest_prev_by_source(obs: pd.DataFrame) -> dict:
    out = {}
    if obs.empty:
        return out
    for sid, g in obs.sort_values("obs_date").groupby("source_id"):
        vals, dates = g["value"].tolist(), g["obs_date"].tolist()
        prev = vals[-2] if len(vals) >= 2 else None
        out[sid] = {"date": dates[-1], "value": vals[-1], "prev": prev,
                    "delta": (vals[-1] - prev) if prev is not None else None}
    return out


def series(obs: pd.DataFrame, sid: str) -> pd.DataFrame:
    return (obs[obs["source_id"] == sid][["obs_date", "value"]]
            .sort_values("obs_date").reset_index(drop=True))


def latest_buyers(obs: pd.DataFrame) -> dict:
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


def basis_frame(obs, thai="tmpa", world="cbot_corn_thb_kg"):
    a = series(obs, thai).rename(columns={"value": "thai"})
    b = series(obs, world).rename(columns={"value": "world"})
    if a.empty or b.empty:
        return pd.DataFrame(columns=["obs_date", "thai", "world", "basis"])
    m = pd.merge(a, b, on="obs_date", how="outer").sort_values("obs_date")
    m["basis"] = m["thai"] - m["world"]
    return m.reset_index(drop=True)


def usd_ton_to_thb_kg(obs, sid):
    """แปลง series USD/ton -> ฿/kg ด้วย FX รายวัน (merge on date)."""
    s = series(obs, sid).rename(columns={"value": "usd_ton"})
    fx = series(obs, "fx_usdthb").rename(columns={"value": "fx"})
    if s.empty or fx.empty:
        return pd.DataFrame(columns=["obs_date", "value"])
    m = pd.merge(s, fx, on="obs_date", how="left").sort_values("obs_date")
    m["fx"] = m["fx"].ffill().bfill()
    m["value"] = m["usd_ton"] / 1000.0 * m["fx"]
    return m[["obs_date", "value"]].reset_index(drop=True)


# ------------------------------------------------------------------
# Data load (cached)
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


@st.cache_data(ttl=600)
def load():
    return _load_data()


# ------------------------------------------------------------------
# Chart / UI helpers (เรียก plotly; ปลอดภัยเรียกใน page)
# ------------------------------------------------------------------
def line(obs, ids, title, ytitle, extra=None, height=340):
    """multi-series line. extra = list ของ (name, df[obs_date,value]) เพิ่มพิเศษ."""
    fig = go.Figure()
    k = 0
    for sid in ids:
        s = series(obs, sid)
        if not s.empty:
            fig.add_trace(go.Scatter(x=s["obs_date"], y=s["value"], mode="lines+markers",
                          name=LABELS.get(sid, sid), line=dict(width=2, color=OKABE[k % len(OKABE)]),
                          marker=dict(size=6)))
            k += 1
    for name, df in (extra or []):
        if not df.empty:
            fig.add_trace(go.Scatter(x=df["obs_date"], y=df["value"], mode="lines+markers",
                          name=name, line=dict(width=2, color=OKABE[k % len(OKABE)]),
                          marker=dict(size=6)))
            k += 1
    fig.update_layout(title=title, yaxis_title=ytitle, height=height, hovermode="x unified",
                      margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="white",
                      legend=dict(orientation="h", y=-0.2), font=dict(color=INK))
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig


def kpi_row(lp, specs):
    """specs = list ของ (label_or_sid, value, delta) หรือ (sid, fmt)."""
    cols = st.columns(len(specs))
    for col, spec in zip(cols, specs):
        with col:
            if len(spec) == 2 and spec[0] in lp:
                sid, fmt = spec
                d = lp[sid]
                delta = None if d["delta"] is None else fmt.format(d["delta"])
                st.metric(LABELS.get(sid, sid), fmt.format(d["value"]), delta)
            elif len(spec) == 2:
                st.metric(LABELS.get(spec[0], spec[0]), "—")
            else:
                label, value, delta = spec
                st.metric(label, value, delta)


def buyers_bar(obs):
    b = latest_buyers(obs)
    if not b:
        return
    st.subheader("ราคารับซื้อข้าวโพดรายโรงงาน (TMPA ล่าสุด)")
    bdf = (pd.DataFrame({"buyer": list(b.keys()), "price": [float(v) for v in b.values()]})
           .sort_values("price"))
    fig = go.Figure(go.Bar(x=bdf["price"], y=bdf["buyer"], orientation="h", marker_color=OKABE[0]))
    fig.update_layout(height=max(280, 26 * len(bdf)), xaxis_title="฿/kg",
                      margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white", font=dict(color=INK))
    fig.update_xaxes(gridcolor=GRID)
    st.plotly_chart(fig, use_container_width=True)


def _get_data_or_stop():
    if not os.environ.get("DATABASE_URL"):
        st.error("ไม่พบ DATABASE_URL — ตั้ง env variable ให้ชี้ Postgres ก่อน")
        st.stop()
    try:
        obs, src, runs = load()
    except Exception as e:
        st.error(f"ต่อฐานข้อมูลไม่ได้: {e}")
        st.stop()
    if obs.empty:
        st.warning("ยังไม่มีข้อมูลใน observations — รอ pipeline รันรอบแรก")
        st.stop()
    return obs, src, runs


def _caption(obs):
    last = pd.to_datetime(obs["ingested_at"]).max()
    st.caption(f"ข้อมูลล่าสุด (ingested): {last:%Y-%m-%d %H:%M} · cache 10 นาที · อัปเดตทุกวันจาก pipeline")


# ------------------------------------------------------------------
# PAGES
# ------------------------------------------------------------------
def page_overview():
    st.title("🌽 ง่วนล้ง Commodity Dashboard")
    obs, src, runs = _get_data_or_stop()
    _caption(obs)
    lp = latest_prev_by_source(obs)

    st.subheader("สรุปวันนี้")
    kpi_row(lp, [("tmpa", "{:.2f}"), ("cbot_corn_thb_kg", "{:.2f}"), ("cpf_feed_broken", "{:.2f}"),
                 ("cpf_feed_bran", "{:.2f}"), ("fx_usdthb", "{:.3f}"), ("live_hog", "{:.1f}")])
    bf = basis_frame(obs)
    if not bf.empty and bf["basis"].notna().any():
        last = bf.dropna(subset=["basis"]).iloc[-1]
        st.metric("Basis ข้าวโพด: ไทย − โลก (฿/kg)", f"{last['basis']:.2f}")

    st.divider()
    st.subheader("ข้าวโพด: ไทย vs ตลาดโลก (฿/kg)")
    if not bf.empty:
        st.plotly_chart(line(obs, [], "", "฿/kg", height=360, extra=[
            ("ไทย (TMPA)", bf.rename(columns={"thai": "value"})[["obs_date", "value"]]),
            ("โลก (฿/kg)", bf.rename(columns={"world": "value"})[["obs_date", "value"]])]),
            use_container_width=True)

    st.subheader("วัตถุดิบอาหารสัตว์ (฿/kg)")
    st.plotly_chart(line(obs, ["cpf_feed_corn", "cpf_feed_broken", "cpf_feed_bran", "cassava_chip"],
                         "", "฿/kg"), use_container_width=True)

    buyers_bar(obs)

    st.subheader("ตลาดโลก")
    w = st.columns(3)
    with w[0]:
        st.plotly_chart(line(obs, ["cbot_corn"], "ข้าวโพด CBOT", "¢/bu"), use_container_width=True)
    with w[1]:
        st.plotly_chart(line(obs, ["cbot_soymeal"], "กากถั่วเหลือง", "$/ton"), use_container_width=True)
    with w[2]:
        st.plotly_chart(line(obs, ["brent_oil", "wti_oil"], "น้ำมันดิบ", "$/bbl"), use_container_width=True)

    st.subheader("ราคาข้าวส่งออก FOB (USD/ton)")
    st.plotly_chart(line(obs, ["trea_wr5_fob", "trea_a1_fob"], "", "USD/ton"), use_container_width=True)

    st.subheader("สัญญาณดีมานด์ปศุสัตว์")
    d = st.columns(2)
    with d[0]:
        st.plotly_chart(line(obs, ["live_hog"], "สุกรมีชีวิต", "฿/kg"), use_container_width=True)
    with d[1]:
        st.plotly_chart(line(obs, ["cpf_livestock"], "ลูกไก่เนื้อ", "฿/ตัว"), use_container_width=True)

    st.subheader("ปัจจัยขับเคลื่อน")
    dr = st.columns(4)
    for col, sid, yt in zip(dr, ["fx_usdthb", "enso_oni", "dam_level", "fertilizer_urea"],
                            ["THB/USD", "index", "%", "$/ton"]):
        with col:
            st.plotly_chart(line(obs, [sid], LABELS.get(sid, sid), yt), use_container_width=True)

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


def page_corn():
    st.title("🌽 ข้าวโพด")
    obs, _, _ = _get_data_or_stop()
    _caption(obs)
    lp = latest_prev_by_source(obs)

    kpi_row(lp, [("tmpa", "{:.2f}"), ("cpf_feed_corn", "{:.2f}"), ("cbot_corn_thb_kg", "{:.2f}"),
                 ("cassava_chip", "{:.2f}"), ("live_hog", "{:.1f}")])
    bf = basis_frame(obs)
    if not bf.empty and bf["basis"].notna().any():
        last = bf.dropna(subset=["basis"]).iloc[-1]
        st.metric("Basis: ข้าวโพดไทย − โลก (฿/kg)", f"{last['basis']:.2f}",
                  help="ช่องว่างไทยเทียบตลาดโลกแปลง ฿/kg = ค่าขนส่ง+ภาษี+มาร์จิน")

    st.divider()
    st.subheader("ไทย vs โลก vs สินค้าทดแทน (฿/kg)")
    extra = []
    if not bf.empty:
        extra = [("ไทย (TMPA)", bf.rename(columns={"thai": "value"})[["obs_date", "value"]]),
                 ("โลก (฿/kg)", bf.rename(columns={"world": "value"})[["obs_date", "value"]])]
    st.plotly_chart(line(obs, ["cassava_chip"], "", "฿/kg", extra=extra, height=380),
                    use_container_width=True)
    st.caption("มันเส้น = สินค้าทดแทนข้าวโพดในอาหารสัตว์ — ถ้าถูกกว่ามาก โรงงานสลับไปใช้ ดีมานด์ข้าวโพดอ่อน")

    st.subheader("ราคาไทย: CPF vs TMPA (฿/kg)")
    st.plotly_chart(line(obs, ["cpf_feed_corn", "tmpa"], "", "฿/kg"), use_container_width=True)

    buyers_bar(obs)

    st.subheader("ตลาดโลก & ปัจจัย")
    c = st.columns(3)
    with c[0]:
        st.plotly_chart(line(obs, ["cbot_corn"], "CBOT Corn", "¢/bu"), use_container_width=True)
    with c[1]:
        st.plotly_chart(line(obs, ["brent_oil"], "น้ำมัน (freight/ethanol)", "$/bbl"),
                        use_container_width=True)
    with c[2]:
        st.plotly_chart(line(obs, ["dam_level"], "น้ำเขื่อน (crop)", "%"), use_container_width=True)

    st.subheader("ดีมานด์ปศุสัตว์")
    d = st.columns(2)
    with d[0]:
        st.plotly_chart(line(obs, ["live_hog"], "สุกรมีชีวิต", "฿/kg"), use_container_width=True)
    with d[1]:
        st.plotly_chart(line(obs, ["cpf_livestock"], "ลูกไก่เนื้อ (restock)", "฿/ตัว"),
                        use_container_width=True)


def page_broken():
    st.title("🍚 ปลายข้าว / ข้าวท่อน")
    obs, _, _ = _get_data_or_stop()
    _caption(obs)
    lp = latest_prev_by_source(obs)

    a1_thb = usd_ton_to_thb_kg(obs, "trea_a1_fob")
    a1_kpi = ("ปลายข้าว A1 (฿/kg)", f"{a1_thb['value'].iloc[-1]:.2f}", None) if not a1_thb.empty \
        else ("ปลายข้าว A1 (฿/kg)", "—", None)
    kpi_row(lp, [("cpf_feed_broken", "{:.2f}"), a1_kpi, ("trea_a1_fob", "{:.0f}"),
                 ("trea_wr5_fob", "{:.0f}"), ("fx_usdthb", "{:.3f}")])

    st.divider()
    st.subheader("ปลายข้าวในประเทศ vs ส่งออก A1 (฿/kg เทียบหน่วยเดียว)")
    extra = [("ปลายข้าว A1 ส่งออก (฿/kg)", a1_thb)] if not a1_thb.empty else []
    st.plotly_chart(line(obs, ["cpf_feed_broken"], "", "฿/kg", extra=extra, height=380),
                    use_container_width=True)
    st.caption("A1 Super (ปลายข้าว 100%) แปลงจาก USD/ton ด้วย FX รายวัน เพื่อเทียบกับราคาซื้อในประเทศ")

    st.subheader("ราคาส่งออก FOB (USD/ton)")
    st.plotly_chart(line(obs, ["trea_a1_fob", "trea_wr5_fob"], "", "USD/ton"),
                    use_container_width=True)
    st.caption("ข้าวขาว 5% เป็นตัวอ้างอิงตลาดข้าว — A1 (ปลายข้าว) มักถูกกว่า 5%")

    st.subheader("ในกลุ่มวัตถุดิบอาหารสัตว์ (฿/kg)")
    st.plotly_chart(line(obs, ["cpf_feed_broken", "cpf_feed_corn", "cpf_feed_bran"], "", "฿/kg"),
                    use_container_width=True)

    st.subheader("ปัจจัย")
    c = st.columns(3)
    with c[0]:
        st.plotly_chart(line(obs, ["fx_usdthb"], "USD/THB", "THB/USD"), use_container_width=True)
    with c[1]:
        st.plotly_chart(line(obs, ["dam_level"], "น้ำเขื่อน (นาข้าว)", "%"), use_container_width=True)
    with c[2]:
        st.plotly_chart(line(obs, ["enso_oni"], "ENSO / ONI", "index"), use_container_width=True)


def page_bran():
    st.title("🌾 รำข้าว")
    obs, _, _ = _get_data_or_stop()
    _caption(obs)
    lp = latest_prev_by_source(obs)

    sm_thb = usd_ton_to_thb_kg(obs, "cbot_soymeal")
    sm_kpi = ("กากถั่ว (฿/kg)", f"{sm_thb['value'].iloc[-1]:.2f}", None) if not sm_thb.empty \
        else ("กากถั่ว (฿/kg)", "—", None)
    kpi_row(lp, [("cpf_feed_bran", "{:.2f}"), ("cbot_soymeal", "{:.0f}"), sm_kpi,
                 ("live_hog", "{:.1f}"), ("fx_usdthb", "{:.3f}")])

    st.divider()
    st.subheader("รำข้าวในกลุ่มวัตถุดิบพลังงาน (฿/kg)")
    st.plotly_chart(line(obs, ["cpf_feed_bran", "cpf_feed_corn", "cpf_feed_broken"], "", "฿/kg",
                    height=380), use_container_width=True)
    st.caption("รำข้าวแข่งกับข้าวโพด/ปลายข้าวเป็นแหล่งพลังงานในสูตรอาหารสัตว์ — ดูราคาสัมพัทธ์กัน")

    st.subheader("รำ vs กากถั่วเหลือง (โปรตีน, ฿/kg)")
    extra = [("กากถั่วเหลือง (฿/kg)", sm_thb)] if not sm_thb.empty else []
    st.plotly_chart(line(obs, ["cpf_feed_bran"], "", "฿/kg", extra=extra), use_container_width=True)
    st.caption("กากถั่วเหลืองแปลงจาก $/short ton ด้วย FX — เป็นตัวเทียบฝั่งโปรตีน")

    st.subheader("ดีมานด์ปศุสัตว์ & ปัจจัย")
    c = st.columns(3)
    with c[0]:
        st.plotly_chart(line(obs, ["live_hog"], "สุกรมีชีวิต", "฿/kg"), use_container_width=True)
    with c[1]:
        st.plotly_chart(line(obs, ["cpf_livestock"], "ลูกไก่เนื้อ", "฿/ตัว"), use_container_width=True)
    with c[2]:
        st.plotly_chart(line(obs, ["fx_usdthb"], "USD/THB", "THB/USD"), use_container_width=True)


def main():
    st.set_page_config(page_title="ง่วนล้ง Commodity Dashboard", page_icon="🌽", layout="wide")
    nav = st.navigation([
        st.Page(page_overview, title="ภาพรวม", icon="🏠", default=True),
        st.Page(page_corn, title="ข้าวโพด", icon="🌽"),
        st.Page(page_broken, title="ปลายข้าว / ข้าวท่อน", icon="🍚"),
        st.Page(page_bran, title="รำข้าว", icon="🌾"),
    ])
    nav.run()


if __name__ == "__main__":
    main()
