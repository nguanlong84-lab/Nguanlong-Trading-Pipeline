"""
dashboard.py — ง่วนล้ง Commodity Dashboard (v2: decision-first + คำอธิบาย)
หน้า: ภาพรวม + เจาะราย commodity (ข้าวโพด / ปลายข้าว / รำ)
แนวคิด: เอาข้อมูลตัดสินใจขึ้นก่อน (ซื้อถูก/แพงกว่าตลาด, margin) กราฟรองซ่อนใน expander
รัน: streamlit run dashboard.py   (ต้องมี env DATABASE_URL)
"""
from __future__ import annotations
import os
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# ------------------------------------------------------------------
OKABE = ["#0072B2", "#E69F00", "#009E73", "#D55E00",
         "#CC79A7", "#56B4E9", "#F0E442", "#999999"]
INK, GRID = "#1a1a1a", "#e5e7eb"
METRIC_TON_KG = 1000.0
SHORT_TON_KG = 907.185                      # CBOT soybean meal = short ton

LABELS = {
    "fx_usdthb": "USD/THB", "enso_oni": "ENSO / ONI",
    "cbot_corn": "CBOT Corn (¢/bu)", "cbot_corn_thb_kg": "ข้าวโพดโลก (฿/kg)",
    "cbot_soymeal": "กากถั่วเหลือง CBOT ($/ton)",
    "trea_a1_fob": "ปลายข้าว A1 FOB", "trea_wr5_fob": "ข้าวขาว 5% FOB",
    "cpf_feed_corn": "CPF ข้าวโพด", "cpf_feed_broken": "CPF ปลายข้าว",
    "cpf_feed_bran": "CPF รำ", "tmpa": "ข้าวโพด (TMPA รายวัน)",
    "cassava_chip": "มันเส้น (สินค้าทดแทน)", "brent_oil": "น้ำมัน Brent",
    "wti_oil": "น้ำมัน WTI", "fertilizer_urea": "ยูเรีย", "dam_level": "น้ำเขื่อน %",
    "cpf_livestock": "ลูกไก่เนื้อ (฿/ตัว)", "live_hog": "สุกรมีชีวิต (฿/kg)",
    "burma_corn": "ข้าวโพดชายแดน",
    "nl_buy_corn": "ง่วนล้ง ซื้อ", "nl_sell_corn": "ง่วนล้ง ขาย",
    "nl_buy_broken": "ง่วนล้ง ซื้อ", "nl_sell_broken": "ง่วนล้ง ขาย",
    "nl_buy_bran": "ง่วนล้ง ซื้อ", "nl_sell_bran": "ง่วนล้ง ขาย",
    "trm_broken": "ปลายข้าว (โรงสี รายวัน)", "trm_bran": "รำ (โรงสี รายวัน)",
}

# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------
def latest_prev_by_source(obs):
    out = {}
    if obs.empty:
        return out
    for sid, g in obs.sort_values("obs_date").groupby("source_id"):
        vals, dates = g["value"].tolist(), g["obs_date"].tolist()
        prev = vals[-2] if len(vals) >= 2 else None
        out[sid] = {"date": dates[-1], "value": vals[-1], "prev": prev,
                    "delta": (vals[-1] - prev) if prev is not None else None}
    return out


def series(obs, sid):
    return (obs[obs["source_id"] == sid][["obs_date", "value"]]
            .sort_values("obs_date").reset_index(drop=True))


def latest_buyers(obs):
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


def basis_frame(obs, thai, world):
    a = series(obs, thai).rename(columns={"value": "thai"})
    b = series(obs, world).rename(columns={"value": "world"})
    if a.empty or b.empty:
        return pd.DataFrame(columns=["obs_date", "thai", "world", "basis"])
    m = pd.merge(a, b, on="obs_date", how="outer").sort_values("obs_date")
    m["basis"] = m["thai"] - m["world"]
    return m.reset_index(drop=True)


def usd_ton_to_thb_kg(obs, sid, kg_per_ton=METRIC_TON_KG):
    """แปลง series USD/ton -> ฿/kg ด้วย FX รายวัน (kg_per_ton=907.185 สำหรับ short ton)."""
    s = series(obs, sid).rename(columns={"value": "usd_ton"})
    fx = series(obs, "fx_usdthb").rename(columns={"value": "fx"})
    if s.empty or fx.empty:
        return pd.DataFrame(columns=["obs_date", "value"])
    m = pd.merge(s, fx, on="obs_date", how="left").sort_values("obs_date")
    m["fx"] = m["fx"].ffill().bfill()
    m["value"] = m["usd_ton"] / kg_per_ton * m["fx"]
    return m[["obs_date", "value"]].reset_index(drop=True)


def _last(obs, sid):
    s = series(obs, sid)
    return float(s["value"].iloc[-1]) if not s.empty else None


# ------------------------------------------------------------------
# Data load
# ------------------------------------------------------------------
def _load_data():
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    obs = pd.read_sql("SELECT source_id, obs_date, value, meta, ingested_at FROM observations", conn)
    src = pd.read_sql("SELECT * FROM sources", conn)
    runs = pd.read_sql("SELECT DISTINCT ON (source_id) source_id, status, rows, message, run_at "
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
# UI helpers
# ------------------------------------------------------------------
def line(obs, ids, title, ytitle, extra=None, height=340):
    fig = go.Figure()
    k = 0
    for sid in ids:
        s = series(obs, sid)
        if not s.empty:
            fig.add_trace(go.Scatter(x=s["obs_date"], y=s["value"], mode="lines+markers",
                          name=LABELS.get(sid, sid), line=dict(width=2.5, color=OKABE[k % len(OKABE)]),
                          marker=dict(size=6)))
            k += 1
    for name, df in (extra or []):
        if not df.empty:
            fig.add_trace(go.Scatter(x=df["obs_date"], y=df["value"], mode="lines+markers",
                          name=name, line=dict(width=2.5, color=OKABE[k % len(OKABE)]),
                          marker=dict(size=6)))
            k += 1
    fig.update_layout(title=title, yaxis_title=ytitle, height=height, hovermode="x unified",
                      margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="white",
                      legend=dict(orientation="h", y=-0.2), font=dict(color=INK))
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig


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
        st.warning("ยังไม่มีข้อมูล — รอ pipeline รันรอบแรก")
        st.stop()
    return obs, src, runs


def _caption(obs):
    last = pd.to_datetime(obs["ingested_at"]).max()
    st.caption(f"อัปเดตล่าสุด: {last:%Y-%m-%d %H:%M} · ข้อมูลรีเฟรชทุกวันอัตโนมัติ (cache 10 นาที)")


def basis_banner(obs, buy_sid, market_sid, name):
    """แถบสรุปสถานะ: ง่วนล้งซื้อถูก/แพงกว่าตลาด."""
    bf = basis_frame(obs, thai=buy_sid, world=market_sid)
    if bf.empty or not bf["basis"].notna().any():
        st.info(f"ยังไม่มีข้อมูลราคาซื้อ{name}ของง่วนล้ง หรือราคาตลาด — รอ pipeline / ตั้งค่า Google Sheet")
        return
    b = bf.dropna(subset=["basis"]).iloc[-1]["basis"]
    if b <= 0:
        st.success(f"🟢 วันนี้ง่วนล้งซื้อ{name} **ถูกกว่าตลาด {abs(b):.2f} บาท/กก** — ได้เปรียบ")
    else:
        st.warning(f"🟡 วันนี้ง่วนล้งซื้อ{name} **แพงกว่าตลาด {b:.2f} บาท/กก** — น่าจับตา")


def summary_card(obs, lp, name, market_sid, buy_sid, sell_sid):
    st.markdown(f"#### {name}")
    m = lp.get(market_sid)
    st.metric("ราคาตลาดวันนี้ (฿/kg)", f"{m['value']:.2f}" if m else "—",
              f"{m['delta']:+.2f}" if m and m["delta"] is not None else None)
    b, s = _last(obs, buy_sid), _last(obs, sell_sid)
    if b is not None:
        st.markdown(f"ง่วนล้งซื้อ: **{b:.2f}**")
        if m:
            diff = b - m["value"]
            emo = "🟢 ถูกกว่าตลาด" if diff <= 0 else "🔴 แพงกว่าตลาด"
            st.markdown(f"{emo} **{abs(diff):.2f}**")
        if s is not None:
            st.markdown(f"margin (ขาย−ซื้อ): **{s - b:+.2f}**")
    else:
        st.markdown("_ยังไม่มีราคาง่วนล้ง_")


def health_table(runs):
    if runs.empty:
        return
    emoji = {"ok": "🟢", "skipped": "⚪", "error": "🔴"}
    rr = runs.copy()
    rr["แหล่ง"] = rr["source_id"].map(lambda s: LABELS.get(s, s))
    rr["สถานะ"] = rr["status"].map(lambda s: f"{emoji.get(s, '❔')} {s}")
    rr["รันล่าสุด"] = pd.to_datetime(rr["run_at"]).dt.strftime("%m-%d %H:%M")
    st.dataframe(rr[["แหล่ง", "สถานะ", "รันล่าสุด", "message"]],
                 use_container_width=True, hide_index=True)


# ------------------------------------------------------------------
# PAGES
# ------------------------------------------------------------------
def page_overview():
    st.title("🌾 ง่วนล้ง Commodity Dashboard")
    obs, src, runs = _get_data_or_stop()
    _caption(obs)
    st.markdown("ดูราคาวัตถุดิบหลัก 3 ตัว เทียบ **ราคาที่ง่วนล้งซื้อจริง** กับ **ราคาตลาดรายวัน** — "
                "เพื่อรู้ว่าซื้อได้ถูกกว่าตลาดไหม และ margin กว้างพอไหม · เลือกดูรายสินค้าได้ที่เมนูซ้าย")

    lp = latest_prev_by_source(obs)
    st.subheader("📊 สรุปวันนี้")
    comms = [("ข้าวโพด", "tmpa", "nl_buy_corn", "nl_sell_corn"),
             ("ปลายข้าว", "trm_broken", "nl_buy_broken", "nl_sell_broken"),
             ("รำ", "trm_bran", "nl_buy_bran", "nl_sell_bran")]
    for col, c in zip(st.columns(3), comms):
        with col:
            summary_card(obs, lp, *c)

    st.divider()
    st.subheader("แนวโน้มราคาตลาด (฿/kg)")
    st.plotly_chart(line(obs, ["tmpa", "trm_broken", "trm_bran", "cassava_chip"], "", "฿/kg"),
                    use_container_width=True)
    st.caption("ราคาตลาดรายวัน — ข้าวโพด: TMPA · ปลายข้าว/รำ: สมาคมโรงสีข้าวไทย · มันเส้น: TTTA (สินค้าทดแทนข้าวโพด)")

    with st.expander("🌍 ราคาตลาดโลก (ข้าวโพด/กากถั่ว/น้ำมัน)"):
        w = st.columns(3)
        with w[0]:
            st.plotly_chart(line(obs, ["cbot_corn"], "ข้าวโพด CBOT", "¢/bu"), use_container_width=True)
        with w[1]:
            st.plotly_chart(line(obs, ["cbot_soymeal"], "กากถั่ว CBOT", "$/ton"), use_container_width=True)
        with w[2]:
            st.plotly_chart(line(obs, ["brent_oil", "wti_oil"], "น้ำมันดิบ", "$/bbl"), use_container_width=True)

    with st.expander("🐷 สัญญาณดีมานด์ & ปัจจัยขับเคลื่อน"):
        d = st.columns(2)
        with d[0]:
            st.plotly_chart(line(obs, ["live_hog"], "สุกรมีชีวิต (ดีมานด์อาหารสัตว์)", "฿/kg"),
                            use_container_width=True)
        with d[1]:
            st.plotly_chart(line(obs, ["cpf_livestock"], "ลูกไก่เนื้อ (สัญญาณ restock)", "฿/ตัว"),
                            use_container_width=True)
        dr = st.columns(4)
        for col, sid, yt in zip(dr, ["fx_usdthb", "enso_oni", "dam_level", "fertilizer_urea"],
                                ["THB/USD", "index", "%", "$/ton"]):
            with col:
                st.plotly_chart(line(obs, [sid], LABELS.get(sid, sid), yt), use_container_width=True)

    with st.expander("🔧 สถานะแหล่งข้อมูล — เช็กว่าแต่ละแหล่งอัปเดตล่าสุดเมื่อไร / มี error ไหม"):
        health_table(runs)


def _commodity_head(obs, lp, market_sid, market_label, buy, sell):
    """แถว KPI หลัก + แถบสถานะ ใช้ร่วมทุกหน้า commodity."""
    m = lp.get(market_sid)
    bp, sp = _last(obs, buy), _last(obs, sell)
    c = st.columns(4)
    with c[0]:
        st.metric(f"ราคาตลาดวันนี้", f"{m['value']:.2f}" if m else "—",
                  f"{m['delta']:+.2f}" if m and m["delta"] is not None else None,
                  help=f"{market_label} · หน่วย ฿/kg")
    with c[1]:
        st.metric("ง่วนล้งซื้อ", f"{bp:.2f}" if bp is not None else "—", help="฿/kg (จาก ledger)")
    with c[2]:
        if bp is not None and m:
            st.metric("ส่วนต่าง (ซื้อ−ตลาด)", f"{bp - m['value']:+.2f}",
                      help="ลบ = ซื้อถูกกว่าตลาด (ดี) · บวก = แพงกว่า")
        else:
            st.metric("ส่วนต่าง (ซื้อ−ตลาด)", "—")
    with c[3]:
        if bp is not None and sp is not None:
            st.metric("margin (ขาย−ซื้อ)", f"{sp - bp:+.2f}", help="กำไรต่อ กก. ก่อนต้นทุนอื่น")
        else:
            st.metric("margin (ขาย−ซื้อ)", "—")


def page_corn():
    st.title("🌽 ข้าวโพด")
    obs, _, _ = _get_data_or_stop()
    _caption(obs)
    lp = latest_prev_by_source(obs)
    _commodity_head(obs, lp, "tmpa", "TMPA รายวัน", "nl_buy_corn", "nl_sell_corn")
    basis_banner(obs, "nl_buy_corn", "tmpa", "ข้าวโพด")

    st.divider()
    st.subheader("ราคาง่วนล้ง ซื้อ/ขาย เทียบราคาตลาด (฿/kg)")
    st.plotly_chart(line(obs, ["nl_buy_corn", "nl_sell_corn", "tmpa"], "", "฿/kg", height=380),
                    use_container_width=True)
    st.caption("💡 วิธีอ่าน: ถ้าเส้น 'ง่วนล้ง ซื้อ' อยู่ **ต่ำกว่า** เส้นตลาด = ซื้อได้ถูกกว่าตลาด (ดี) · "
               "ช่องว่างระหว่างเส้น 'ขาย' กับ 'ซื้อ' = margin")

    with st.expander("🆚 ราคาตลาดในประเทศ: TMPA vs CPF & สินค้าทดแทน (มันเส้น)"):
        st.plotly_chart(line(obs, ["tmpa", "cpf_feed_corn", "cbot_corn_thb_kg", "cassava_chip"],
                             "", "฿/kg"), use_container_width=True)
        st.caption("TMPA=รายวัน (หลัก) · CPF=รายสัปดาห์ · ข้าวโพดโลก=CBOT แปลง฿/kg · "
                   "มันเส้นถูกกว่ามาก → โรงงานสลับไปใช้ ดีมานด์ข้าวโพดอ่อน")

    with st.expander("🏭 ราคารับซื้อข้าวโพดรายโรงงาน (TMPA ล่าสุด)"):
        b = latest_buyers(obs)
        if b:
            bdf = (pd.DataFrame({"buyer": list(b.keys()), "price": [float(v) for v in b.values()]})
                   .sort_values("price"))
            fig = go.Figure(go.Bar(x=bdf["price"], y=bdf["buyer"], orientation="h", marker_color=OKABE[0]))
            fig.update_layout(height=max(280, 26 * len(bdf)), xaxis_title="฿/kg",
                              margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white", font=dict(color=INK))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("ราคาที่โรงงานอาหารสัตว์แต่ละเจ้ารับซื้อข้าวโพด — ต่างกันตามทำเล")
        else:
            st.info("ยังไม่มีข้อมูลรายโรงงาน")

    with st.expander("🌍 ตลาดโลก & ปัจจัย (CBOT / น้ำมัน / น้ำเขื่อน)"):
        c = st.columns(3)
        with c[0]:
            st.plotly_chart(line(obs, ["cbot_corn"], "CBOT Corn", "¢/bu"), use_container_width=True)
        with c[1]:
            st.plotly_chart(line(obs, ["brent_oil"], "น้ำมัน (freight/ethanol)", "$/bbl"),
                            use_container_width=True)
        with c[2]:
            st.plotly_chart(line(obs, ["dam_level"], "น้ำเขื่อน (ผลผลิต)", "%"), use_container_width=True)

    with st.expander("🐷 ดีมานด์ปศุสัตว์ (ยิ่งสูง ยิ่งซื้ออาหารสัตว์)"):
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
    _commodity_head(obs, lp, "trm_broken", "โรงสี รายวัน", "nl_buy_broken", "nl_sell_broken")
    basis_banner(obs, "nl_buy_broken", "trm_broken", "ปลายข้าว")

    st.divider()
    st.subheader("ราคาง่วนล้ง ซื้อ/ขาย เทียบราคาตลาด (฿/kg)")
    st.plotly_chart(line(obs, ["nl_buy_broken", "nl_sell_broken", "trm_broken"], "", "฿/kg", height=380),
                    use_container_width=True)
    st.caption("💡 ราคาตลาด = ปลายข้าวเอวันเลิศ (สมาคมโรงสีข้าวไทย รายวัน) · เส้นซื้อต่ำกว่าตลาด = ได้เปรียบ")

    with st.expander("🆚 ตลาดในประเทศ: โรงสี (รายวัน) vs CPF (รายสัปดาห์)"):
        st.plotly_chart(line(obs, ["trm_broken", "cpf_feed_broken"], "", "฿/kg"), use_container_width=True)

    with st.expander("🚢 ราคาส่งออก (A1 แปลงเป็น ฿/kg เทียบในประเทศ)"):
        a1 = usd_ton_to_thb_kg(obs, "trea_a1_fob")
        extra = [("ปลายข้าว A1 ส่งออก (฿/kg)", a1)] if not a1.empty else []
        st.plotly_chart(line(obs, ["trm_broken"], "", "฿/kg", extra=extra), use_container_width=True)
        st.caption("A1 Super (ปลายข้าว 100%) จาก FOB USD/ton แปลงด้วย FX รายวัน เพื่อเทียบราคาในประเทศ")

    with st.expander("🌾 ในกลุ่มวัตถุดิบอาหารสัตว์ (฿/kg)"):
        st.plotly_chart(line(obs, ["trm_broken", "tmpa", "trm_bran"], "", "฿/kg"),
                        use_container_width=True)
        st.caption("ปลายข้าว/ข้าวโพด/รำ แข่งกันเป็นแหล่งพลังงานในสูตรอาหารสัตว์")


def page_bran():
    st.title("🌾 รำข้าว")
    obs, _, _ = _get_data_or_stop()
    _caption(obs)
    lp = latest_prev_by_source(obs)
    _commodity_head(obs, lp, "trm_bran", "โรงสี รายวัน", "nl_buy_bran", "nl_sell_bran")
    basis_banner(obs, "nl_buy_bran", "trm_bran", "รำ")

    st.divider()
    st.subheader("ราคาง่วนล้ง ซื้อ/ขาย เทียบราคาตลาด (฿/kg)")
    st.plotly_chart(line(obs, ["nl_buy_bran", "nl_sell_bran", "trm_bran"], "", "฿/kg", height=380),
                    use_container_width=True)
    st.caption("💡 ราคาตลาด = รำข้าวขาว (สมาคมโรงสีข้าวไทย รายวัน) · เส้นซื้อต่ำกว่าตลาด = ได้เปรียบ")

    with st.expander("🆚 ตลาดในประเทศ: โรงสี (รายวัน) vs CPF (รายสัปดาห์)"):
        st.plotly_chart(line(obs, ["trm_bran", "cpf_feed_bran"], "", "฿/kg"), use_container_width=True)

    with st.expander("🫘 เทียบกากถั่วเหลือง (ฝั่งโปรตีน, แปลงเป็น ฿/kg)"):
        sm = usd_ton_to_thb_kg(obs, "cbot_soymeal", kg_per_ton=SHORT_TON_KG)
        sm_now = f"{sm['value'].iloc[-1]:.2f}" if not sm.empty else "—"
        st.metric("กากถั่วเหลือง (฿/kg)", sm_now, help="CBOT $/short ton (907 กก.) × FX")
        extra = [("กากถั่วเหลือง (฿/kg)", sm)] if not sm.empty else []
        st.plotly_chart(line(obs, ["trm_bran"], "", "฿/kg", extra=extra), use_container_width=True)
        st.caption("กากถั่วเป็นแหล่งโปรตีน · แปลงจาก $/short ton (ไม่ใช่ metric ton) ด้วย FX รายวัน")

    with st.expander("🌾 ในกลุ่มวัตถุดิบพลังงาน (฿/kg)"):
        st.plotly_chart(line(obs, ["trm_bran", "tmpa", "trm_broken"], "", "฿/kg"),
                        use_container_width=True)
        st.caption("รำแข่งกับข้าวโพด/ปลายข้าวเป็นแหล่งพลังงานในสูตรอาหารสัตว์")

    with st.expander("🐷 ดีมานด์ปศุสัตว์"):
        d = st.columns(2)
        with d[0]:
            st.plotly_chart(line(obs, ["live_hog"], "สุกรมีชีวิต", "฿/kg"), use_container_width=True)
        with d[1]:
            st.plotly_chart(line(obs, ["cpf_livestock"], "ลูกไก่เนื้อ", "฿/ตัว"), use_container_width=True)


def main():
    st.set_page_config(page_title="ง่วนล้ง Commodity Dashboard", page_icon="🌾", layout="wide")
    st.navigation([
        st.Page(page_overview, title="ภาพรวม", icon="🏠", default=True),
        st.Page(page_corn, title="ข้าวโพด", icon="🌽"),
        st.Page(page_broken, title="ปลายข้าว / ข้าวท่อน", icon="🍚"),
        st.Page(page_bran, title="รำข้าว", icon="🌾"),
    ]).run()


if __name__ == "__main__":
    main()
