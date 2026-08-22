-- ง่วนล้ง Commodity Price Pipeline — schema (external-first)
-- ออกแบบให้ราคาง่วนล้งเสียบเข้าทีหลังได้โดยไม่ต้องแก้โครงสร้าง

-- ทะเบียนแหล่งข้อมูล (ขับ scheduler ด้วยคอลัมน์ frequency)
CREATE TABLE IF NOT EXISTS sources (
    source_id   text PRIMARY KEY,          -- 'fx_usdthb', 'trea_a1_fob', 'nl_buy_corn'
    label       text NOT NULL,
    layer       text NOT NULL              -- 'world' | 'thai' | 'nguanlong' | 'driver'
                 CHECK (layer IN ('world','thai','nguanlong','driver')),
    commodity   text,                      -- 'corn' | 'broken' | 'bran' | NULL (ใช้ร่วม/ทั้งหมด)
    method      text NOT NULL              -- 'api' | 'scrape' | 'manual'
                 CHECK (method IN ('api','scrape','manual')),
    frequency   text NOT NULL              -- 'daily' | 'weekly' | 'monthly' | 'event'
                 CHECK (frequency IN ('daily','weekly','monthly','event')),
    unit        text,
    active      boolean DEFAULT true
);

-- ข้อมูลราคา/ค่าตัวแปร แบบ long/tidy (1 แถว = 1 แหล่ง 1 วัน)
CREATE TABLE IF NOT EXISTS observations (
    id           bigserial PRIMARY KEY,
    source_id    text NOT NULL REFERENCES sources(source_id),
    obs_date     date NOT NULL,
    value        numeric,
    meta         jsonb DEFAULT '{}'::jsonb, -- เก็บ raw/หน่วย/หมายเหตุต่อจุด
    ingested_at  timestamptz DEFAULT now(),
    UNIQUE (source_id, obs_date)            -- กันซ้ำ + รองรับ upsert
);
CREATE INDEX IF NOT EXISTS ix_obs_source_date ON observations(source_id, obs_date);

-- log การรันแต่ละรอบ (ไว้ดูว่า scraper ตัวไหนล่ม)
CREATE TABLE IF NOT EXISTS ingest_runs (
    id          bigserial PRIMARY KEY,
    source_id   text REFERENCES sources(source_id),
    run_at      timestamptz DEFAULT now(),
    status      text,                       -- 'ok' | 'error' | 'skipped'
    rows        int DEFAULT 0,
    message     text
);

-- ============================================================
-- ส่วนที่เสียบทีหลัง (Phase 3): ราคาง่วนล้ง + basis + spread
-- ยังไม่ต้องรันตอนนี้ เก็บไว้เป็น blueprint
-- ============================================================
-- basis = ราคาง่วนล้งซื้อ - ราคาตลาดไทย (ต่อ commodity, ต่อวัน)
-- CREATE OR REPLACE VIEW v_basis AS
-- SELECT t.commodity, t.obs_date,
--        nl.value AS nl_price, t.value AS thai_price,
--        nl.value - t.value AS basis
-- FROM observations t
-- JOIN sources st ON st.source_id = t.source_id AND st.layer = 'thai'
-- JOIN sources snl ON snl.commodity = st.commodity AND snl.layer = 'nguanlong'
-- JOIN observations nl ON nl.source_id = snl.source_id AND nl.obs_date = t.obs_date;
