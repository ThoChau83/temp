-- =============================================================================
-- Mộc Miên Florist — schema SQLite cho API nghiệp vụ giả lập
-- Chạy:  sqlite3 data/moc_mien.db < sql/schema.sql && sqlite3 data/moc_mien.db < sql/seed.sql
-- hoặc:  python scripts/init_db.py
-- Thời gian lưu dạng ISO-8601 có múi giờ (+07:00); ngày dạng YYYY-MM-DD; tiền là VND (INTEGER).
-- =============================================================================
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS service_requests;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS subscription_plans;
DROP TABLE IF EXISTS consultations;
DROP TABLE IF EXISTS order_events;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS discount_codes;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS delivery_zones;
DROP TABLE IF EXISTS delivery_slots;
DROP TABLE IF EXISTS branches;

CREATE TABLE branches (
    id            TEXT PRIMARY KEY,                 -- CN01, CN02
    name          TEXT NOT NULL,
    address       TEXT NOT NULL,
    phone         TEXT NOT NULL,
    open_time     TEXT NOT NULL,                    -- 'HH:MM'
    close_time    TEXT NOT NULL,
    has_studio    INTEGER NOT NULL DEFAULT 0,       -- có studio tư vấn hoa cưới
    slot_capacity INTEGER NOT NULL                  -- số đơn tối đa / khung giờ giao
);

CREATE TABLE delivery_slots (
    code       TEXT PRIMARY KEY,                    -- K1..K6
    start_time TEXT NOT NULL,
    end_time   TEXT NOT NULL
);

CREATE TABLE delivery_zones (
    id                  TEXT PRIMARY KEY,           -- Z1..Z4
    name                TEXT NOT NULL,
    areas               TEXT NOT NULL,              -- danh sách khu vực, phân cách dấu phẩy
    fee                 INTEGER NOT NULL,
    free_ship_min_order INTEGER,                    -- NULL = không miễn phí ship
    allowed_slots       TEXT NOT NULL,              -- 'K1,K2,...'
    express_available   INTEGER NOT NULL,
    min_days_ahead      INTEGER NOT NULL DEFAULT 0,
    default_branch_id   TEXT NOT NULL REFERENCES branches(id)
);

CREATE TABLE products (
    sku             TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT,
    main_flowers    TEXT,
    color_tone      TEXT,
    size            TEXT,
    unit            TEXT NOT NULL,
    price           INTEGER NOT NULL CHECK (price > 0),
    lead_time_hours INTEGER NOT NULL DEFAULT 0,     -- thời gian chuẩn bị tối thiểu
    freshness_days  INTEGER,                        -- cam kết tươi (NULL = không áp dụng)
    is_seasonal     INTEGER NOT NULL DEFAULT 0,
    season_note     TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE inventory (
    sku        TEXT NOT NULL REFERENCES products(sku),
    branch_id  TEXT NOT NULL REFERENCES branches(id),
    quantity   INTEGER NOT NULL CHECK (quantity >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sku, branch_id)
);

CREATE TABLE customers (
    id              TEXT PRIMARY KEY,               -- KH0001
    full_name       TEXT NOT NULL,
    phone           TEXT NOT NULL UNIQUE,           -- chuẩn hoá 10 số, bắt đầu bằng 0
    email           TEXT,
    gender          TEXT CHECK (gender IN ('nam', 'nu') OR gender IS NULL),
    birthday        TEXT,
    address         TEXT,
    customer_type   TEXT NOT NULL DEFAULT 'individual' CHECK (customer_type IN ('individual', 'business')),
    company_name    TEXT,
    tier            TEXT NOT NULL DEFAULT 'member' CHECK (tier IN ('member', 'loyal', 'vip')),
    points          INTEGER NOT NULL DEFAULT 0,
    total_spent_12m INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    note            TEXT
);

CREATE TABLE discount_codes (
    code                  TEXT PRIMARY KEY,
    description           TEXT NOT NULL,
    discount_type         TEXT NOT NULL CHECK (discount_type IN ('percent', 'fixed')),
    value                 INTEGER NOT NULL,
    max_discount          INTEGER,
    min_order             INTEGER NOT NULL DEFAULT 0,
    applicable_categories TEXT,                     -- NULL = mọi danh mục
    valid_from            TEXT NOT NULL,
    valid_to              TEXT NOT NULL,
    usage_limit           INTEGER,
    used_count            INTEGER NOT NULL DEFAULT 0,
    per_customer_limit    INTEGER,
    customer_id           TEXT REFERENCES customers(id),  -- mã riêng cho 1 khách (mã xin lỗi)
    kind                  TEXT NOT NULL CHECK (kind IN ('public', 'first_order', 'birthday', 'goodwill')),
    is_active             INTEGER NOT NULL DEFAULT 1,
    created_by            TEXT NOT NULL DEFAULT 'system',
    created_at            TEXT NOT NULL
);

CREATE TABLE orders (
    code             TEXT PRIMARY KEY,              -- MM10001
    customer_id      TEXT NOT NULL REFERENCES customers(id),
    branch_id        TEXT NOT NULL REFERENCES branches(id),
    channel          TEXT NOT NULL CHECK (channel IN ('website', 'zalo', 'hotline', 'facebook', 'store', 'agent')),
    occasion         TEXT,
    status           TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'arranging', 'delivering',
                                                     'delivered', 'failed_delivery', 'cancelled', 'refunded')),
    fulfillment      TEXT NOT NULL CHECK (fulfillment IN ('delivery', 'pickup')),
    delivery_date    TEXT NOT NULL,
    slot_code        TEXT REFERENCES delivery_slots(code),   -- NULL nếu giao hỏa tốc
    is_express       INTEGER NOT NULL DEFAULT 0,
    express_deadline TEXT,
    zone_id          TEXT REFERENCES delivery_zones(id),
    recipient_name   TEXT,
    recipient_phone  TEXT,
    delivery_address TEXT,
    card_message     TEXT,
    is_surprise      INTEGER NOT NULL DEFAULT 0,
    subtotal         INTEGER NOT NULL,
    shipping_fee     INTEGER NOT NULL DEFAULT 0,
    express_fee      INTEGER NOT NULL DEFAULT 0,
    discount_code    TEXT,
    discount_source  TEXT,                          -- code | tier | NULL
    discount_amount  INTEGER NOT NULL DEFAULT 0,
    total            INTEGER NOT NULL,
    payment_method   TEXT NOT NULL CHECK (payment_method IN ('cod', 'bank_transfer', 'momo', 'vnpay', 'card', 'cash')),
    payment_status   TEXT NOT NULL CHECK (payment_status IN ('unpaid', 'partially_paid', 'paid', 'refund_pending',
                                                             'partially_refunded', 'refunded')),
    paid_amount      INTEGER NOT NULL DEFAULT 0,
    refunded_amount  INTEGER NOT NULL DEFAULT 0,
    reschedule_count INTEGER NOT NULL DEFAULT 0,
    delivered_at     TEXT,
    cancel_reason    TEXT,
    note             TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_code   TEXT NOT NULL REFERENCES orders(code),
    sku          TEXT NOT NULL REFERENCES products(sku),
    product_name TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   INTEGER NOT NULL,
    line_total   INTEGER NOT NULL
);

CREATE TABLE order_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_code  TEXT NOT NULL REFERENCES orders(code),
    event_type  TEXT NOT NULL,                      -- created | status_changed | rescheduled | cancelled | note
    from_status TEXT,
    to_status   TEXT,
    detail      TEXT,
    actor       TEXT NOT NULL,                      -- system | staff | customer | agent
    created_at  TEXT NOT NULL
);

CREATE TABLE consultations (
    code             TEXT PRIMARY KEY,              -- TV2001
    customer_id      TEXT NOT NULL REFERENCES customers(id),
    event_type       TEXT NOT NULL CHECK (event_type IN ('wedding', 'opening', 'conference', 'party')),
    mode             TEXT NOT NULL CHECK (mode IN ('studio', 'online', 'onsite')),
    appointment_date TEXT NOT NULL,
    appointment_time TEXT NOT NULL,                 -- '09:00'
    event_date       TEXT NOT NULL,
    venue            TEXT,
    zone_id          TEXT REFERENCES delivery_zones(id),
    guest_count      INTEGER,
    budget_range     TEXT,
    status           TEXT NOT NULL CHECK (status IN ('scheduled', 'completed', 'contracted', 'cancelled', 'no_show')),
    consultant       TEXT,
    onsite_fee       INTEGER NOT NULL DEFAULT 0,
    package_name     TEXT,
    contract_value   INTEGER,
    deposit_amount   INTEGER NOT NULL DEFAULT 0,
    deposit_status   TEXT NOT NULL DEFAULT 'none' CHECK (deposit_status IN ('none', 'paid', 'refund_pending',
                                                                           'refunded', 'partially_refunded', 'forfeited')),
    reschedule_count INTEGER NOT NULL DEFAULT 0,
    event_date_change_count INTEGER NOT NULL DEFAULT 0,
    note             TEXT,
    cancel_reason    TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE subscription_plans (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    description          TEXT NOT NULL,
    frequency            TEXT NOT NULL CHECK (frequency IN ('weekly', 'biweekly', 'lunar_1_15')),
    deliveries_per_month INTEGER NOT NULL,
    price_per_delivery   INTEGER NOT NULL,
    retail_equivalent    INTEGER NOT NULL
);

CREATE TABLE subscriptions (
    code               TEXT PRIMARY KEY,            -- GD3001
    customer_id        TEXT NOT NULL REFERENCES customers(id),
    plan_id            TEXT NOT NULL REFERENCES subscription_plans(id),
    term_months        INTEGER NOT NULL CHECK (term_months IN (1, 3, 6)),
    total_deliveries   INTEGER NOT NULL,
    delivered_count    INTEGER NOT NULL DEFAULT 0,
    price_total        INTEGER NOT NULL,            -- sau giảm theo kỳ hạn
    paid_amount        INTEGER NOT NULL DEFAULT 0,
    start_date         TEXT NOT NULL,
    end_date           TEXT NOT NULL,
    delivery_weekday   INTEGER,                     -- 0 = Thứ Hai ... 6 = Chủ Nhật; NULL với gói âm lịch
    slot_code          TEXT NOT NULL REFERENCES delivery_slots(code),
    zone_id            TEXT NOT NULL REFERENCES delivery_zones(id),
    delivery_address   TEXT NOT NULL,
    recipient_name     TEXT,
    recipient_phone    TEXT,
    next_delivery_date TEXT,
    status             TEXT NOT NULL CHECK (status IN ('pending_payment', 'active', 'paused', 'cancelled', 'expired')),
    paused_until       TEXT,
    pause_count        INTEGER NOT NULL DEFAULT 0,
    note               TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE service_requests (
    code              TEXT PRIMARY KEY,             -- YC10001
    type              TEXT NOT NULL CHECK (type IN ('refund', 'exchange', 'discount', 'cancellation',
                                                    'reschedule', 'escalation')),
    customer_id       TEXT REFERENCES customers(id),
    ref_type          TEXT CHECK (ref_type IN ('order', 'consultation', 'subscription') OR ref_type IS NULL),
    ref_code          TEXT,
    reason_code       TEXT,
    description       TEXT,
    amount            INTEGER,                      -- số tiền đề nghị hoàn / giá trị giảm
    payload           TEXT,                         -- JSON chi tiết (khung giờ mới, sản phẩm đổi, % giảm...)
    status            TEXT NOT NULL CHECK (status IN ('pending_approval', 'approved', 'rejected', 'completed',
                                                      'open', 'closed')),
    requires_approval INTEGER NOT NULL DEFAULT 0,
    approval_rules    TEXT,                         -- JSON: các mã quy tắc policy (APR-xx) làm phát sinh duyệt
    resolution_note   TEXT,
    issued_code       TEXT,                         -- mã giảm giá đã cấp (nếu có)
    created_by        TEXT NOT NULL CHECK (created_by IN ('agent', 'staff', 'customer', 'system')),
    created_at        TEXT NOT NULL,
    decided_at        TEXT,
    decided_by        TEXT
);

CREATE INDEX idx_orders_customer   ON orders(customer_id);
CREATE INDEX idx_orders_delivery   ON orders(delivery_date, slot_code, branch_id);
CREATE INDEX idx_orders_status     ON orders(status);
CREATE INDEX idx_items_order       ON order_items(order_code);
CREATE INDEX idx_events_order      ON order_events(order_code);
CREATE INDEX idx_consult_date      ON consultations(appointment_date, appointment_time);
CREATE INDEX idx_consult_customer  ON consultations(customer_id);
CREATE INDEX idx_sub_customer      ON subscriptions(customer_id);
CREATE INDEX idx_requests_ref      ON service_requests(ref_type, ref_code);
CREATE INDEX idx_requests_status   ON service_requests(status);
