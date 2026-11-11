"""
Vyro — retail counter offers (Round 25, Nov 2026).

Supermarket-style counter billing: quantity slabs, buy-X-get-Y-free,
bundles, party-wise rates, per-customer discounts, credit limits,
loyalty points, split payment and card charges.

Money math here is plain and deterministic. Vyro only records how a
bill was paid — it never processes a payment.

Importing this module never needs a GUI: the offers screen and the
split-payment dialog import customtkinter lazily, like ai_features.
"""

from datetime import date, timedelta

RETAIL_SCHEMA = """
CREATE TABLE IF NOT EXISTS qty_slabs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id       INTEGER NOT NULL,
    min_qty          REAL NOT NULL,
    discount_percent REAL NOT NULL DEFAULT 0,
    special_price    REAL,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE IF NOT EXISTS buy_x_get_y (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL UNIQUE,
    buy_qty    REAL NOT NULL,
    free_qty   REAL NOT NULL,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE IF NOT EXISTS bundles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    bundle_price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bundle_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_id  INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    qty        REAL NOT NULL,
    FOREIGN KEY (bundle_id) REFERENCES bundles(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE IF NOT EXISTS focus_items (
    product_id INTEGER PRIMARY KEY,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE IF NOT EXISTS party_rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    product_id  INTEGER NOT NULL,
    price       REAL NOT NULL,
    UNIQUE (customer_id, product_id),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE IF NOT EXISTS bill_payments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL,
    mode    TEXT NOT NULL,
    amount  REAL NOT NULL,
    FOREIGN KEY (bill_id) REFERENCES bills(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS loyalty_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    bill_id     INTEGER,
    points      REAL NOT NULL,   -- +earned / -redeemed
    kind        TEXT NOT NULL,   -- 'earn' / 'redeem'
    date        TEXT NOT NULL,
    note        TEXT DEFAULT '',
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
"""

SPLIT_MODES = ("Cash", "UPI", "Card")


def ensure_retail_tables(db):
    db.conn.executescript(RETAIL_SCHEMA)
    db.conn.commit()


# -- settings ---------------------------------------------------------------
def loyalty_settings(db):
    """Earn rate (points per Rs. 100 spent) and point value (Rs. off
    per point redeemed). Both configurable in settings."""
    try:
        per_100 = float(db.get_setting("loyalty_points_per_100", "1") or 1)
    except ValueError:
        per_100 = 1.0
    try:
        value = float(db.get_setting("loyalty_point_value_rs", "1") or 1)
    except ValueError:
        value = 1.0
    return {"points_per_100": per_100, "point_value_rs": value}


def card_charge_percent(db):
    try:
        return float(db.get_setting("card_charge_percent", "2") or 2)
    except ValueError:
        return 2.0


# -- lookups ----------------------------------------------------------------
def find_product(db, text):
    text = (text or "").strip()
    if not text:
        return None
    rows = db.list_products(text)
    for r in rows:
        if r["name"].lower() == text.lower() \
                or (r.get("sku") or "").lower() == text.lower():
            return r
    return rows[0] if rows else None


def find_customer(db, text):
    text = (text or "").strip()
    if not text:
        return None
    rows = db.list_customers(text)
    for r in rows:
        if r["phone"] == text or r["name"].lower() == text.lower():
            return r
    return rows[0] if rows else None


# -- quantity slabs (#6) ----------------------------------------------------
def list_qty_slabs(db):
    ensure_retail_tables(db)
    return db._rows(
        "SELECT s.*, p.name AS product_name FROM qty_slabs s "
        "JOIN products p ON p.id=s.product_id ORDER BY p.name, s.min_qty")


def add_qty_slab(db, product_id, min_qty, discount_percent=0.0,
                 special_price=None):
    """One slab: at min_qty+ either discount_percent off, or the
    special_price per unit. Returns the slab id, or None when the
    rule is empty or invalid."""
    ensure_retail_tables(db)
    if float(min_qty) <= 0:
        return None
    if special_price is not None and float(special_price) < 0:
        return None
    if not discount_percent and special_price is None:
        return None
    cur = db.conn.execute(
        "INSERT INTO qty_slabs (product_id, min_qty, discount_percent, "
        "special_price) VALUES (?, ?, ?, ?)",
        (product_id, float(min_qty), float(discount_percent or 0),
         None if special_price is None else float(special_price)))
    db.conn.commit()
    return cur.lastrowid


def delete_qty_slab(db, slab_id):
    ensure_retail_tables(db)
    db.conn.execute("DELETE FROM qty_slabs WHERE id=?", (slab_id,))
    db.conn.commit()


def qty_slab(db, product_id, qty):
    """Best slab for this qty: the highest min_qty not above it."""
    ensure_retail_tables(db)
    return db._one(
        "SELECT * FROM qty_slabs WHERE product_id=? AND min_qty<=? "
        "ORDER BY min_qty DESC LIMIT 1", (product_id, float(qty)))


# -- buy-X-get-Y-free (#7) --------------------------------------------------
def list_buy_x_get_y(db):
    ensure_retail_tables(db)
    return db._rows(
        "SELECT b.*, p.name AS product_name FROM buy_x_get_y b "
        "JOIN products p ON p.id=b.product_id ORDER BY p.name")


def add_buy_x_get_y(db, product_id, buy_qty, free_qty):
    """One rule per product (replacing the old one). Returns the rule
    id, or None when the numbers are invalid."""
    ensure_retail_tables(db)
    if float(buy_qty) <= 0 or float(free_qty) <= 0:
        return None
    cur = db.conn.execute(
        "INSERT OR REPLACE INTO buy_x_get_y (product_id, buy_qty, free_qty) "
        "VALUES (?, ?, ?)",
        (product_id, float(buy_qty), float(free_qty)))
    db.conn.commit()
    return cur.lastrowid


def delete_buy_x_get_y(db, rule_id):
    ensure_retail_tables(db)
    db.conn.execute("DELETE FROM buy_x_get_y WHERE id=?", (rule_id,))
    db.conn.commit()


def free_qty_for(db, product_id, qty):
    """Free units earned by this qty (whole sets only)."""
    ensure_retail_tables(db)
    row = db._one("SELECT * FROM buy_x_get_y WHERE product_id=?",
                  (product_id,))
    if not row:
        return 0.0
    sets = int(float(qty) // float(row["buy_qty"]))
    return sets * float(row["free_qty"])


# -- bundles / combos (#8) --------------------------------------------------
def list_bundles(db):
    ensure_retail_tables(db)
    rows = db._rows("SELECT * FROM bundles ORDER BY name")
    for b in rows:
        b["items"] = db._rows(
            "SELECT bi.*, p.name AS product_name FROM bundle_items bi "
            "JOIN products p ON p.id=bi.product_id WHERE bi.bundle_id=?",
            (b["id"],))
    return rows


def get_bundle(db, bundle_id):
    ensure_retail_tables(db)
    b = db._one("SELECT * FROM bundles WHERE id=?", (bundle_id,))
    if not b:
        return None
    b["items"] = db._rows(
        "SELECT bi.*, p.name AS product_name FROM bundle_items bi "
        "JOIN products p ON p.id=bi.product_id WHERE bi.bundle_id=?",
        (bundle_id,))
    return b


def add_bundle(db, name, bundle_price, items):
    """items: [(product_id, qty)]. Returns the bundle id, or None
    when the name, price or items are invalid."""
    ensure_retail_tables(db)
    name = (name or "").strip()
    items = [(pid, float(q)) for pid, q in items if float(q) > 0]
    if not name or float(bundle_price) < 0 or not items:
        return None
    cur = db.conn.execute(
        "INSERT INTO bundles (name, bundle_price) VALUES (?, ?)",
        (name, float(bundle_price)))
    bid = cur.lastrowid
    for pid, q in items:
        db.conn.execute(
            "INSERT INTO bundle_items (bundle_id, product_id, qty) "
            "VALUES (?, ?, ?)", (bid, pid, q))
    db.conn.commit()
    return bid


def delete_bundle(db, bundle_id):
    ensure_retail_tables(db)
    db.conn.execute("DELETE FROM bundle_items WHERE bundle_id=?",
                    (bundle_id,))
    db.conn.execute("DELETE FROM bundles WHERE id=?", (bundle_id,))
    db.conn.commit()


def bundle_lines(db, bundle_id, price_mode="wholesale", customer_id=None):
    """Expand a bundle into bill lines. The bundle discount is spread
    across the component lines (proportional to value, last line takes
    the rounding residual) so the pre-GST total equals the bundle
    price; GST then applies on top of the discounted lines."""
    b = get_bundle(db, bundle_id)
    if not b:
        return []
    lines, total = [], 0.0
    for bi in b["items"]:
        p = db.get_product(bi["product_id"])
        if not p:
            continue
        price = party_rate(db, customer_id, p["id"]) if customer_id else None
        if price is None:
            price = float(p["wholesale_price"]
                          if price_mode == "wholesale"
                          else p["retail_price"])
        total += float(bi["qty"]) * price
        lines.append({
            "product_id": p["id"], "name": p["name"], "unit": p["unit"],
            "qty": float(bi["qty"]), "price": price, "line_discount": 0.0,
            "gst_percent": p["gst_percent"], "sku": p["sku"],
            "base_price": price, "bundle": b["name"]})
    if not lines:
        return []
    discount = max(0.0, round(total - float(b["bundle_price"]), 2))
    if discount > 0 and total > 0:
        spread = 0.0
        for i, ln in enumerate(lines):
            if i == len(lines) - 1:
                ln["line_discount"] = round(discount - spread, 2)
            else:
                share = round(discount * (ln["qty"] * ln["price"]) / total, 2)
                ln["line_discount"] = share
                spread += share
    return lines


def parse_bundle_items(db, text):
    """'Rice x2, Dal x1' → (items, errors). Unknown names are reported
    so nothing is silently skipped."""
    items, errors = [], []
    for chunk in (text or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, qty = chunk, 1.0
        if "x" in chunk:
            head, _, tail = chunk.rpartition("x")
            try:
                qty = float(tail.strip())
                name = head.strip()
            except ValueError:
                pass
        p = find_product(db, name)
        if not p:
            errors.append(name)
        else:
            items.append((p["id"], qty))
    return items, errors


# -- party-wise rates (#13) + customer discount (#5) ------------------------
def party_rate(db, customer_id, product_id):
    if not customer_id or not product_id:
        return None
    ensure_retail_tables(db)
    r = db._one("SELECT price FROM party_rates "
                "WHERE customer_id=? AND product_id=?",
                (customer_id, product_id))
    return float(r["price"]) if r else None


def set_party_rate(db, customer_id, product_id, price):
    ensure_retail_tables(db)
    db.conn.execute(
        "INSERT OR REPLACE INTO party_rates (customer_id, product_id, price) "
        "VALUES (?, ?, ?)", (customer_id, product_id, float(price)))
    db.conn.commit()


def delete_party_rate(db, rate_id):
    ensure_retail_tables(db)
    db.conn.execute("DELETE FROM party_rates WHERE id=?", (rate_id,))
    db.conn.commit()


def delete_party_rate_for(db, customer_id, product_id):
    ensure_retail_tables(db)
    db.conn.execute(
        "DELETE FROM party_rates WHERE customer_id=? AND product_id=?",
        (customer_id, product_id))
    db.conn.commit()


def list_party_rates(db, customer_id=None):
    ensure_retail_tables(db)
    if customer_id:
        return db._rows(
            "SELECT r.*, p.name AS product_name, c.name AS customer_name "
            "FROM party_rates r JOIN products p ON p.id=r.product_id "
            "JOIN customers c ON c.id=r.customer_id "
            "WHERE r.customer_id=? ORDER BY p.name", (customer_id,))
    return db._rows(
        "SELECT r.*, p.name AS product_name, c.name AS customer_name "
        "FROM party_rates r JOIN products p ON p.id=r.product_id "
        "JOIN customers c ON c.id=r.customer_id "
        "ORDER BY c.name, p.name")


def set_customer_offer(db, customer_id, discount_percent=None,
                       credit_limit=None):
    """Per-customer discount % (applied to every bill) and/or credit
    limit (0 = no limit). Only the values passed are changed."""
    kw = {}
    if discount_percent is not None:
        kw["discount_percent"] = float(discount_percent)
    if credit_limit is not None:
        kw["credit_limit"] = float(credit_limit)
    if kw:
        db.update_customer(customer_id, **kw)


# -- focus items (#9) + suggested items (#10) -------------------------------
def add_focus(db, product_id):
    ensure_retail_tables(db)
    db.conn.execute("INSERT OR IGNORE INTO focus_items (product_id) "
                    "VALUES (?)", (product_id,))
    db.conn.commit()


def remove_focus(db, product_id):
    ensure_retail_tables(db)
    db.conn.execute("DELETE FROM focus_items WHERE product_id=?",
                    (product_id,))
    db.conn.commit()


def list_focus_items(db):
    ensure_retail_tables(db)
    return db._rows(
        "SELECT f.product_id, p.name, p.stock, p.unit FROM focus_items f "
        "JOIN products p ON p.id=f.product_id ORDER BY p.name")


def focus_suggestions(db, limit=6):
    """Focus items that are actually in stock."""
    ensure_retail_tables(db)
    return db._rows(
        "SELECT f.product_id, p.name FROM focus_items f "
        "JOIN products p ON p.id=f.product_id WHERE p.stock > 0 "
        "ORDER BY p.name LIMIT ?", (limit,))


def most_sold_items(db, days=30, limit=8, as_of=None):
    """Most-sold products over the last `days` days, by quantity."""
    if as_of is None:
        as_of = date.today()
    elif isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    since = (as_of - timedelta(days=days)).isoformat()
    return db._rows(
        "SELECT bi.product_id, p.name, SUM(bi.qty) AS sold "
        "FROM bill_items bi JOIN bills b ON b.id=bi.bill_id "
        "JOIN products p ON p.id=bi.product_id "
        "WHERE bi.product_id IS NOT NULL AND bi.price > 0 AND b.date>=? "
        "GROUP BY bi.product_id ORDER BY sold DESC LIMIT ?",
        (since, limit))


def suggested_items(db, exclude_ids=(), limit=6):
    """Focus items first, then most-sold; never a product already on
    the bill. Each row: {product_id, name, why}."""
    exclude = {int(i) for i in exclude_ids if i}
    out, seen = [], set(exclude)
    for f in focus_suggestions(db, limit=limit):
        if f["product_id"] not in seen:
            out.append({"product_id": f["product_id"], "name": f["name"],
                        "why": "focus"})
            seen.add(f["product_id"])
    if len(out) < limit:
        for m in most_sold_items(db, limit=limit):
            if m["product_id"] not in seen:
                out.append({"product_id": m["product_id"], "name": m["name"],
                            "why": "most-sold"})
                seen.add(m["product_id"])
            if len(out) >= limit:
                break
    return out[:limit]


def add_suggested_line(billing, tab, product_id):
    """Add one suggested product to a live billing tab (qty 1, at the
    tab's price mode / party rate). Returns False when not found."""
    p = billing.db.get_product(product_id)
    if not p:
        return False
    cid = tab.customer["id"] if getattr(tab, "customer", None) else None
    price = party_rate(billing.db, cid, product_id)
    if price is None:
        price = float(p["wholesale_price"]
                      if getattr(tab, "price_mode", "wholesale") == "wholesale"
                      else p["retail_price"])
    tab.items.append({
        "product_id": p["id"], "name": p["name"], "unit": p["unit"],
        "qty": 1, "price": price, "line_discount": 0,
        "gst_percent": p["gst_percent"], "sku": p["sku"],
        "base_price": price})
    return True


# -- credit limit (#11) -----------------------------------------------------
def credit_limit_blocked(db, customer, payment_type, grand_total,
                         exclude_bill_id=None):
    """Error text when a Credit bill would cross the customer's limit,
    else None. Limit 0/blank = no limit; Cash/UPI/Card are unaffected.
    exclude_bill_id: when editing a bill, its old total does not count
    twice against the balance."""
    if payment_type != "Credit" or not customer:
        return None
    c = db.get_customer(customer["id"])
    if not c:
        return None
    limit = float(c.get("credit_limit") or 0)
    if limit <= 0:
        return None
    balance = float(c.get("balance") or 0)
    if exclude_bill_id:
        old = db.get_bill(exclude_bill_id)
        if old and old.get("payment_type") == "Credit" \
                and old.get("customer_id") == c["id"]:
            balance -= float(old["grand_total"])
    if balance + float(grand_total) > limit + 0.004:
        return (f"Credit limit of \u20b9{limit:g} for {c['name']} would be "
                f"crossed (outstanding \u20b9{balance:,.2f} + this bill "
                f"\u20b9{float(grand_total):,.2f}). Take a payment first, "
                "or bill as Cash / UPI.")
    return None


# -- loyalty points (#12) ---------------------------------------------------
def loyalty_balance(db, customer_id):
    ensure_retail_tables(db)
    r = db._one("SELECT COALESCE(SUM(points), 0) p FROM loyalty_ledger "
                "WHERE customer_id=?", (customer_id,))
    return float(r["p"])


def record_loyalty_for_bill(db, bill_id, customer_id, grand_total,
                            redeem_points=0):
    """Write the ledger rows for a finalized bill: redeem first, then
    earn (1 point per Rs. 100 by default). Returns points earned."""
    if not customer_id:
        return 0.0
    ensure_retail_tables(db)
    st = loyalty_settings(db)
    earned = 0.0
    if grand_total and float(grand_total) > 0:
        earned = float(int(float(grand_total) // 100)
                       * st["points_per_100"])
    today = date.today().isoformat()
    if redeem_points and float(redeem_points) > 0:
        db.conn.execute(
            "INSERT INTO loyalty_ledger (customer_id, bill_id, points, "
            "kind, date, note) VALUES (?, ?, ?, 'redeem', ?, 'Redeemed')",
            (customer_id, bill_id, -float(redeem_points), today))
    if earned > 0:
        db.conn.execute(
            "INSERT INTO loyalty_ledger (customer_id, bill_id, points, "
            "kind, date, note) VALUES (?, ?, ?, 'earn', ?, 'Earned')",
            (customer_id, bill_id, earned, today))
    db.conn.commit()
    return earned


# -- split payment (#14) + card charges (#15) -------------------------------
def card_surcharge_for(amount, pct):
    return round(float(amount) * float(pct) / 100.0, 2)


def split_parts_valid(parts, due):
    """parts: [(mode, amount)]. Returns an error string, or None when
    the parts add up to the amount due."""
    if not parts:
        return "Enter at least one payment."
    total = 0.0
    for mode, amount in parts:
        if mode not in SPLIT_MODES:
            return f"Unknown payment mode: {mode}."
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return "Amounts must be numbers."
        if amount < 0:
            return "Amounts cannot be negative."
        total += amount
    if total <= 0:
        return "Enter at least one payment."
    if abs(total - float(due)) > 0.02:
        return (f"Parts add up to \u20b9{total:,.2f} but the bill is "
                f"\u20b9{float(due):,.2f}.")
    return None


def record_split_payment(db, bill_id, parts):
    ensure_retail_tables(db)
    for mode, amount in parts:
        if float(amount) > 0:
            db.conn.execute(
                "INSERT INTO bill_payments (bill_id, mode, amount) "
                "VALUES (?, ?, ?)", (bill_id, mode, float(amount)))
    db.conn.commit()


def list_bill_payments(db, bill_id):
    ensure_retail_tables(db)
    return db._rows("SELECT * FROM bill_payments WHERE bill_id=? "
                    "ORDER BY id", (bill_id,))


def complete_split_bill(db, tab, parts, surcharge=0.0):
    """Finalize a split-payment bill: the card surcharge (if any) is a
    visible 'Card charges' line, the bill is saved as payment type
    'Split', each part is recorded in bill_payments, and loyalty is
    recorded for the customer."""
    items = [dict(it) for it in tab.items]
    if surcharge and float(surcharge) > 0:
        items.append({"product_id": None, "name": "Card charges",
                      "unit": "pcs", "qty": 1,
                      "price": round(float(surcharge), 2),
                      "line_discount": 0, "gst_percent": 0})
    cid = tab.customer["id"] if getattr(tab, "customer", None) else None
    offer = getattr(tab, "offer", {}) or {}
    bill_discount = float(getattr(tab, "bill_discount", 0) or 0) \
        + float(offer.get("discount", 0) or 0)
    bill_id = db.create_bill(cid, "Split", items, bill_discount)
    record_split_payment(db, bill_id, parts)
    bill = db.get_bill(bill_id)
    record_loyalty_for_bill(db, bill_id, cid, bill["grand_total"],
                            offer.get("redeem_points", 0))
    return bill_id


# -- live offers on the billing tab -----------------------------------------
def _auto_kind(it):
    """Lines this module generated: flagged, or recognisable by the
    name they were saved with (an edited bill reloads them without
    the flag)."""
    if it.get("auto"):
        return it["auto"]
    if it.get("product_id") is None and it["name"] == "Card charges":
        return "surcharge"
    if it["name"].endswith(" (free)"):
        return "free"
    return None


def refresh_offers(db, tab):
    """Apply the counter offers to a live billing tab, in place.

    Party rates and quantity slabs only rewrite a line whose price /
    discount the operator has not changed by hand (a hand-edited line
    keeps the operator's numbers). Free units and the card-charges
    line are rebuilt from scratch on every call, so they never go
    stale or duplicate. Bundle lines keep their bundle price. The
    per-customer discount and any loyalty redemption land in
    tab.offer['discount'], which BillTab.totals() adds to the manual
    bill discount — so the footer always shows the offers before the
    bill is saved.
    """
    ensure_retail_tables(db)
    items = list(getattr(tab, "items", []) or [])
    paid = [it for it in items if not _auto_kind(it)]
    notes = []
    customer = getattr(tab, "customer", None)
    cid = customer["id"] if customer else None
    for it in paid:
        pid = it.get("product_id")
        if not pid or it.get("bundle"):
            continue
        base = float(it.get("base_price", it["price"]))
        price = float(it["price"])
        disc = float(it.get("line_discount", 0) or 0)
        price_touched = price != float(it.get("offer_price", base))
        disc_touched = disc != float(it.get("offer_disc", 0) or 0)
        if price_touched:
            it["base_price"] = price
        else:
            new_price = base
            pr = party_rate(db, cid, pid)
            if pr is not None:
                new_price = pr
                notes.append(f"Party rate on {it['name']}: \u20b9{pr:g}")
            slab = qty_slab(db, pid, float(it["qty"]))
            if slab and slab.get("special_price") is not None:
                new_price = float(slab["special_price"])
                notes.append(f"Qty rate on {it['name']}: \u20b9{new_price:g} "
                             f"for {float(it['qty']):g}+ pcs")
            it["price"] = new_price
            it["offer_price"] = new_price
        if not disc_touched:
            new_disc = 0.0
            slab = qty_slab(db, pid, float(it["qty"]))
            if slab and slab.get("special_price") is None \
                    and float(slab.get("discount_percent") or 0) > 0:
                new_disc = round(float(it["qty"]) * float(it["price"])
                                 * float(slab["discount_percent"]) / 100.0, 2)
                notes.append(
                    f"Qty discount on {it['name']}: "
                    f"{float(slab['discount_percent']):g}% off")
            it["line_discount"] = new_disc
            it["offer_disc"] = new_disc
    # Free units (buy-X-get-Y): Rs. 0 lines, stock still decremented.
    free_lines = []
    for it in paid:
        pid = it.get("product_id")
        if not pid or it.get("bundle"):
            continue
        fq = free_qty_for(db, pid, float(it["qty"]))
        if fq > 0:
            p = db.get_product(pid)
            if not p:
                continue
            free_lines.append({
                "product_id": pid, "name": f"{it['name']} (free)",
                "unit": it.get("unit", "pcs"), "qty": fq, "price": 0,
                "line_discount": 0, "gst_percent": p["gst_percent"],
                "sku": p.get("sku", ""), "auto": "free"})
            notes.append(f"Buy offer on {it['name']}: +{fq:g} free")
    # Per-customer discount (percent of the pre-GST subtotal). An
    # edited bill keeps the discount it was saved with (it is already
    # inside tab.bill_discount), so this only applies to new bills.
    offer = getattr(tab, "offer", None)
    if offer is None:
        offer = tab.offer = {}
    offer_discount = float(offer.get("redeem_rs", 0) or 0)
    if cid and not getattr(tab, "edit_bill_id", None):
        c = db.get_customer(cid)
        pct = float((c or {}).get("discount_percent") or 0)
        if pct > 0:
            sub = sum(max(float(it["qty"]) * float(it["price"])
                          - float(it.get("line_discount", 0) or 0), 0.0)
                      for it in paid)
            cd = round(sub * pct / 100.0, 2)
            offer_discount += cd
            notes.append(f"Customer discount {pct:g}%: \u2212\u20b9{cd:,.2f}")
    if offer.get("redeem_rs"):
        notes.append(
            f"Loyalty redeemed: \u2212\u20b9{float(offer['redeem_rs']):,.2f} "
            f"({float(offer.get('redeem_points', 0)):g} points)")
    # Card charges: a visible line on Card bills, on the goods total.
    surcharge = 0.0
    if getattr(tab, "payment_type", None) == "Card":
        goods_total = db.compute_totals(
            paid + free_lines,
            float(getattr(tab, "bill_discount", 0) or 0) + offer_discount)
        pct = card_charge_percent(db)
        surcharge = card_surcharge_for(goods_total["grand_total"], pct)
    out = paid + free_lines
    if surcharge > 0:
        out.append({"product_id": None, "name": "Card charges",
                    "unit": "pcs", "qty": 1, "price": surcharge,
                    "line_discount": 0, "gst_percent": 0,
                    "auto": "surcharge"})
        notes.append(f"Card charges {card_charge_percent(db):g}%: "
                     f"\u20b9{surcharge:,.2f}")
    tab.items = out
    offer["discount"] = round(offer_discount, 2)
    offer["notes"] = notes
    return notes


def refresh_suggestion_strip(billing, tab, w):
    """Rebuild the one-tap suggestion strip on a billing tab: focus
    items first, then most-sold. Products already on the bill are
    hidden. No suggestions → the strip hides itself."""
    import customtkinter as ctk
    strip = w.get("suggest_strip")
    if strip is None:
        # Created lazily so ui.py needs no extra wiring for the strip.
        strip = ctk.CTkFrame(w["frame"], fg_color="transparent")
        w["suggest_strip"] = strip
    for ch in strip.winfo_children():
        ch.destroy()
    on_bill = {it.get("product_id") for it in tab.items
               if it.get("product_id")}
    sugg = suggested_items(billing.db, on_bill, limit=6)
    if not sugg:
        strip.pack_forget()
        return
    ctk.CTkLabel(strip, text="Suggested:", text_color="gray",
                 font=ctk.CTkFont(size=12)).pack(side="left", padx=(4, 2))
    for s in sugg:
        label = f"+ {s['name']}"
        if s["why"] == "focus":
            label += "  \u2022  focus"
        ctk.CTkButton(
            strip, text=label, width=170,
            command=lambda pid=s["product_id"]: (
                add_suggested_line(billing, tab, pid),
                billing._refresh_totals(tab.name))
            ).pack(side="left", padx=3)
    if w.get("cards_sf") is not None:
        strip.pack(fill="x", pady=2, before=w["cards_sf"])
    else:
        strip.pack(fill="x", pady=2)


# -- split-payment dialog (GUI, lazy import) --------------------------------
def open_split_dialog(parent, db, tab, on_done):
    """Ask how a bill is split across Cash / UPI / Card. The card
    charge is shown live and added to the amount due; confirming
    calls on_done(tab, parts, surcharge)."""
    import customtkinter as ctk
    from tkinter import messagebox
    totals = tab.totals(db)
    grand = float(totals["grand_total"])
    pct = card_charge_percent(db)
    win = ctk.CTkToplevel(parent)
    win.title("Split payment")
    win.geometry("380x380")
    win.transient(parent)
    win.grab_set()
    ctk.CTkLabel(win, text=f"Bill total  \u20b9{grand:,.2f}",
                 font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(12, 4))
    ctk.CTkLabel(
        win, text=f"Card payments add a {pct:g}% card charge, shown as a "
                  "'Card charges' line on the bill.",
        text_color="gray", wraplength=340).pack(pady=(0, 8))
    ents = {}
    for mode in SPLIT_MODES:
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row, text=f"{mode}  \u20b9", width=70).pack(side="left")
        e = ctk.CTkEntry(row, width=140)
        e.pack(side="left")
        ents[mode] = e
    due_lbl = ctk.CTkLabel(win, text="", font=ctk.CTkFont(weight="bold"))
    due_lbl.pack(pady=8)
    left_lbl = ctk.CTkLabel(win, text="", text_color="gray")
    left_lbl.pack(pady=2)

    def _amt(mode):
        try:
            return max(float(ents[mode].get() or 0), 0.0)
        except ValueError:
            return 0.0

    def recalc(_e=None):
        sur = card_surcharge_for(_amt("Card"), pct)
        # The customer pays the rounded payable, like every other bill.
        due = round(grand + sur)
        paid = _amt("Cash") + _amt("UPI") + _amt("Card")
        due_lbl.configure(
            text=f"Card charges \u20b9{sur:,.2f}  \u00b7  "
                 f"Amount due \u20b9{due:,.2f}")
        left = due - paid
        left_lbl.configure(
            text=(f"\u20b9{left:,.2f} left to split" if left > 0.01
                  else ("Split matches the bill." if abs(left) <= 0.01
                        else f"\u20b9{-left:,.2f} over \u2014 reduce a part.")))

    for e in ents.values():
        e.bind("<KeyRelease>", recalc)
    recalc()

    def confirm():
        parts = []
        for mode in SPLIT_MODES:
            try:
                v = float(ents[mode].get() or 0)
            except ValueError:
                messagebox.showerror(
                    "Split payment", f"{mode} amount is not a number.")
                return
            if v > 0:
                parts.append((mode, v))
        sur = card_surcharge_for(
            sum(v for m, v in parts if m == "Card"), pct)
        err = split_parts_valid(parts, round(grand + sur))
        if err:
            messagebox.showerror("Split payment", err)
            return
        win.destroy()
        on_done(tab, parts, sur)

    ctk.CTkButton(win, text="Save split bill", fg_color="#1f6f43",
                  command=confirm).pack(pady=12)
    ctk.CTkButton(win, text="Cancel",
                  command=win.destroy).pack(pady=2)


# -- Retail Offers screen (GUI, lazy import) --------------------------------
def retail_screen_class():
    """The Retail Offers screen class (a CTkFrame like AIInsightsFrame).
    Defined inside this factory so importing this module never needs
    a GUI — ui.py calls retail_screen_class() only when the screen
    opens."""
    from tkinter import messagebox
    import customtkinter as ctk

    class RetailOffersFrame(ctk.CTkFrame):
        def __init__(self, parent, db, app):
            super().__init__(parent, fg_color="transparent")
            self.db, self.app = db, app
            self.section = "offers"
            ctk.CTkLabel(self, text="Retail Offers",
                         font=ctk.CTkFont(size=22, weight="bold")).pack(
                             anchor="w", pady=(4, 2))
            ctk.CTkLabel(
                self,
                text="Counter offers, party rates, credit limits, loyalty "
                     "and split payment. Offers apply to the live bill "
                     "before it is saved \u2014 nothing is added silently "
                     "at save time.",
                text_color="gray", wraplength=760,
                justify="left").pack(anchor="w", pady=(0, 6))
            btns = ctk.CTkFrame(self, fg_color="transparent")
            btns.pack(fill="x", pady=4)
            for label, key in (("Offers", "offers"),
                               ("Bundles", "bundles"),
                               ("Party rates", "party"),
                               ("Customers", "customers"),
                               ("Focus & suggestions", "focus"),
                               ("Loyalty", "loyalty"),
                               ("Settings", "settings")):
                ctk.CTkButton(btns, text=label, width=118,
                              command=lambda k=key: self._show(k)).pack(
                                  side="left", padx=3)
            self.text = ctk.CTkTextbox(self, wrap="word")
            self.text.pack(fill="both", expand=True, pady=6)
            self.actions = ctk.CTkFrame(self, fg_color="transparent")
            self.actions.pack(fill="x", pady=4)
            self._show("offers")

        # -- generic helpers ------------------------------------------------
        def _ask(self, title, fields):
            """Modal dialog. fields: [(label, key, default)].
            Returns a dict of answers, or None when cancelled."""
            win = ctk.CTkToplevel(self)
            win.title(title)
            win.geometry(f"420x{120 + 46 * len(fields)}")
            win.transient(self)
            win.grab_set()
            ents = {}
            for label, key, default in fields:
                ctk.CTkLabel(win, text=label).pack(anchor="w", padx=14,
                                                   pady=(6, 0))
                e = ctk.CTkEntry(win)
                e.insert(0, str(default or ""))
                e.pack(fill="x", padx=14)
                ents[key] = e
            out = {}

            def save():
                for k, e in ents.items():
                    out[k] = e.get().strip()
                win.destroy()

            ctk.CTkButton(win, text="Save", command=save).pack(pady=14)
            win.wait_window()
            return out or None

        def _num(self, d, key):
            try:
                return float(d[key])
            except (KeyError, TypeError, ValueError):
                return None

        def _current_tab(self):
            billing = self.app.screens.get("billing")
            if not billing:
                return None
            cur = billing.current()
            return cur[0] if cur else None

        def _refresh_billing(self, tab):
            billing = self.app.screens.get("billing")
            if billing and tab:
                billing._refresh_totals(tab.name)

        def _pick_product(self, d):
            p = find_product(self.db, d.get("product", ""))
            if not p:
                messagebox.showerror(
                    "Retail Offers",
                    f"No product found for '{d.get('product', '')}'.")
            return p

        def _pick_customer(self, d):
            c = find_customer(self.db, d.get("customer", ""))
            if not c:
                messagebox.showerror(
                    "Retail Offers",
                    f"No customer found for '{d.get('customer', '')}'.")
            return c

        # -- sections -------------------------------------------------------
        def _show(self, section):
            self.section = section
            self.text.delete("1.0", "end")
            self.text.insert("end", self._report(section))
            for ch in self.actions.winfo_children():
                ch.destroy()
            for label, fn in self._actions(section):
                ctk.CTkButton(self.actions, text=label, width=170,
                              command=fn).pack(side="left", padx=3)
            ctk.CTkButton(self.actions, text="Refresh",
                          command=lambda: self._show(section)).pack(
                              side="right", padx=3)

        def _actions(self, section):
            return {
                "offers": [("Add qty slab", self._add_qty_slab),
                           ("Add buy-X-get-Y", self._add_buy_x_get_y),
                           ("Remove slab\u2026", self._remove_qty_slab),
                           ("Remove buy-X\u2026", self._remove_buy_x_get_y)],
                "bundles": [("Add bundle", self._add_bundle),
                            ("Add bundle to current bill",
                             self._add_bundle_to_bill),
                            ("Remove bundle\u2026", self._remove_bundle)],
                "party": [("Set party rate", self._set_party_rate),
                          ("Remove party rate\u2026",
                           self._remove_party_rate)],
                "customers": [("Set discount / credit limit",
                               self._set_customer_offer),
                              ("Loyalty lookup\u2026",
                               self._loyalty_lookup)],
                "focus": [("Mark focus item", self._mark_focus),
                          ("Unmark focus item", self._unmark_focus),
                          ("Add suggestion to current bill",
                           self._add_suggestion_to_bill)],
                "loyalty": [("Redeem points on current bill",
                             self._redeem_points),
                            ("Set earn rate / point value",
                             self._set_loyalty_settings)],
                "settings": [("Set card charge %", self._set_card_charge),
                             ("Set earn rate", self._set_loyalty_settings),
                             ("Set point value", self._set_loyalty_settings)],
            }[section]

        def _report(self, section):
            db = self.db
            if section == "offers":
                lines = ["QUANTITY SLABS \u2014 discount % or a special rate "
                         "once the qty reaches the slab", ""]
                for s in list_qty_slabs(db):
                    if s["special_price"] is not None:
                        lines.append(f"  #{s['id']}  {s['product_name']}: "
                                     f"{s['min_qty']:g}+ pcs \u2192 "
                                     f"\u20b9{s['special_price']:g} each")
                    else:
                        lines.append(f"  #{s['id']}  {s['product_name']}: "
                                     f"{s['min_qty']:g}+ pcs \u2192 "
                                     f"{s['discount_percent']:g}% off")
                lines += ["", "BUY-X-GET-Y-FREE", ""]
                for b in list_buy_x_get_y(db):
                    lines.append(f"  #{b['id']}  {b['product_name']}: buy "
                                 f"{b['buy_qty']:g}, get {b['free_qty']:g} "
                                 "free")
                if not list_qty_slabs(db) and not list_buy_x_get_y(db):
                    lines.append("  No offers yet \u2014 add one below.")
                return "\n".join(lines)
            if section == "bundles":
                lines = ["BUNDLES \u2014 a set of items sold together at one "
                         "bundle price", ""]
                for b in list_bundles(db):
                    lines.append(f"  #{b['id']}  {b['name']} \u2014 "
                                 f"\u20b9{b['bundle_price']:,.2f}")
                    for it in b["items"]:
                        lines.append(f"      {it['qty']:g} x "
                                     f"{it['product_name']}")
                if not list_bundles(db):
                    lines.append("  No bundles yet \u2014 add one below.")
                return "\n".join(lines)
            if section == "party":
                lines = ["PARTY-WISE RATES \u2014 a special price per "
                         "customer per item (wholesale parties)", ""]
                for r in list_party_rates(db):
                    lines.append(f"  #{r['id']}  {r['customer_name']} \u2014 "
                                 f"{r['product_name']}: \u20b9{r['price']:g}")
                if not list_party_rates(db):
                    lines.append("  No party rates yet \u2014 add one below.")
                return "\n".join(lines)
            if section == "customers":
                lines = ["CUSTOMERS \u2014 discount % on every bill, credit "
                         "limit (0 = no limit), loyalty points", ""]
                for c in db.list_customers():
                    pts = loyalty_balance(db, c["id"])
                    lines.append(
                        f"  {c['name']}  ({c['phone'] or 'no phone'}) \u2014 "
                        f"discount {float(c.get('discount_percent') or 0):g}%, "
                        f"credit limit "
                        f"\u20b9{float(c.get('credit_limit') or 0):,.0f}, "
                        f"outstanding \u20b9{float(c['balance'] or 0):,.2f}, "
                        f"{pts:g} points")
                return "\n".join(lines)
            if section == "focus":
                lines = ["FOCUS ITEMS \u2014 slow stock suggested on every "
                         "bill (one tap to add, removable like any line)", ""]
                for f in list_focus_items(db):
                    lines.append(f"  {f['name']} \u2014 {f['stock']:g} "
                                 f"{f['unit']} in stock")
                if not list_focus_items(db):
                    lines.append("  No focus items yet \u2014 mark one below.")
                lines += ["", "MOST-SOLD (last 30 days)", ""]
                for m in most_sold_items(db):
                    lines.append(f"  {m['name']} \u2014 {float(m['sold']):g} "
                                 "sold")
                if not most_sold_items(db):
                    lines.append("  No sales yet.")
                return "\n".join(lines)
            if section == "loyalty":
                st = loyalty_settings(db)
                lines = [f"LOYALTY \u2014 {st['points_per_100']:g} point(s) "
                         f"per \u20b9100 spent, 1 point = "
                         f"\u20b9{st['point_value_rs']:g} off when redeemed",
                         ""]
                ranked = sorted(
                    ((loyalty_balance(db, c["id"]), c)
                     for c in db.list_customers()),
                    key=lambda t: -t[0])
                for pts, c in ranked[:15]:
                    if pts > 0:
                        lines.append(f"  {c['name']} \u2014 {pts:g} points")
                if not any(p > 0 for p, _ in ranked):
                    lines.append("  No points earned yet.")
                return "\n".join(lines)
            st = loyalty_settings(db)
            return ("\n".join([
                "SETTINGS",
                "",
                f"  Card charge: {card_charge_percent(db):g}% of a card "
                "payment (added as a visible 'Card charges' line)",
                f"  Loyalty earn rate: {st['points_per_100']:g} point(s) "
                "per \u20b9100 spent",
                f"  Loyalty point value: \u20b9{st['point_value_rs']:g} off "
                "per point redeemed",
                "",
                "  Vyro records how a bill was paid. It does not process "
                "payments." ]))

        # -- offer actions --------------------------------------------------
        def _add_qty_slab(self):
            d = self._ask("Add quantity slab", [
                ("Product name", "product", ""),
                ("Minimum qty", "min_qty", "10"),
                ("Discount % (blank for a special rate)", "disc", "5"),
                ("Special rate \u20b9 (blank for a discount %)", "rate", "")])
            if not d:
                return
            p = self._pick_product(d)
            if not p:
                return
            min_qty = self._num(d, "min_qty")
            rate = self._num(d, "rate") if d.get("rate") else None
            disc = self._num(d, "disc") if d.get("disc") else 0.0
            if min_qty is None or min_qty <= 0 or disc is None:
                messagebox.showerror("Retail Offers",
                                     "Enter valid numbers.")
                return
            if add_qty_slab(self.db, p["id"], min_qty, disc, rate) is None:
                messagebox.showerror(
                    "Retail Offers",
                    "Give either a discount % or a special rate.")
                return
            self._show("offers")

        def _add_buy_x_get_y(self):
            d = self._ask("Add buy-X-get-Y-free", [
                ("Product name", "product", ""),
                ("Buy qty", "buy_qty", "2"),
                ("Free qty", "free_qty", "1")])
            if not d:
                return
            p = self._pick_product(d)
            if not p:
                return
            buy = self._num(d, "buy_qty")
            free = self._num(d, "free_qty")
            if buy is None or free is None:
                messagebox.showerror("Retail Offers",
                                     "Enter valid numbers.")
                return
            if add_buy_x_get_y(self.db, p["id"], buy, free) is None:
                messagebox.showerror(
                    "Retail Offers",
                    "Buy and free quantities must be above zero.")
                return
            self._show("offers")

        def _remove_qty_slab(self):
            d = self._ask("Remove quantity slab", [("Slab #", "id", "")])
            if not d:
                return
            try:
                delete_qty_slab(self.db, int(d["id"]))
            except ValueError:
                messagebox.showerror("Retail Offers", "Enter a slab #.")
                return
            self._show("offers")

        def _remove_buy_x_get_y(self):
            d = self._ask("Remove buy-X-get-Y rule", [("Rule #", "id", "")])
            if not d:
                return
            try:
                delete_buy_x_get_y(self.db, int(d["id"]))
            except ValueError:
                messagebox.showerror("Retail Offers", "Enter a rule #.")
                return
            self._show("offers")

        # -- bundle actions -------------------------------------------------
        def _add_bundle(self):
            d = self._ask("Add bundle", [
                ("Bundle name (e.g. Dairy bundle)", "name", ""),
                ("Bundle price \u20b9", "price", ""),
                ("Items: Product x qty, Product x qty", "items", "")])
            if not d:
                return
            price = self._num(d, "price")
            items, errors = parse_bundle_items(self.db, d.get("items", ""))
            if price is None or price < 0:
                messagebox.showerror("Retail Offers",
                                     "Enter a valid bundle price.")
                return
            if errors:
                messagebox.showerror(
                    "Retail Offers",
                    f"Unknown product(s): {', '.join(errors)}.")
                return
            if add_bundle(self.db, d["name"], price, items) is None:
                messagebox.showerror(
                    "Retail Offers",
                    "Give a bundle name, a price and at least one item.")
                return
            self._show("bundles")

        def _add_bundle_to_bill(self):
            tab = self._current_tab()
            if not tab:
                messagebox.showinfo("Retail Offers",
                                    "Open a bill in Billing first.")
                return
            d = self._ask("Add bundle to current bill",
                          [("Bundle name", "name", "")])
            if not d:
                return
            found = [b for b in list_bundles(self.db)
                     if b["name"].lower() == d["name"].lower()]
            if not found:
                messagebox.showerror(
                    "Retail Offers", f"No bundle named '{d['name']}'.")
                return
            lines = bundle_lines(
                self.db, found[0]["id"], tab.price_mode,
                tab.customer["id"] if tab.customer else None)
            for ln in lines:
                tab.items.append(ln)
            self._refresh_billing(tab)
            messagebox.showinfo(
                "Retail Offers",
                f"Added bundle '{found[0]['name']}' ({len(lines)} lines) "
                "to the bill.")

        def _remove_bundle(self):
            d = self._ask("Remove bundle", [("Bundle #", "id", "")])
            if not d:
                return
            try:
                delete_bundle(self.db, int(d["id"]))
            except ValueError:
                messagebox.showerror("Retail Offers", "Enter a bundle #.")
                return
            self._show("bundles")

        # -- party rate + customer actions ----------------------------------
        def _set_party_rate(self):
            d = self._ask("Set party rate", [
                ("Customer name or phone", "customer", ""),
                ("Product name", "product", ""),
                ("Special price \u20b9", "price", "")])
            if not d:
                return
            c = self._pick_customer(d)
            p = self._pick_product(d) if c else None
            if not p:
                return
            price = self._num(d, "price")
            if price is None or price < 0:
                messagebox.showerror("Retail Offers",
                                     "Enter a valid price.")
                return
            set_party_rate(self.db, c["id"], p["id"], price)
            self._show("party")

        def _remove_party_rate(self):
            d = self._ask("Remove party rate", [("Rate #", "id", "")])
            if not d:
                return
            try:
                delete_party_rate(self.db, int(d["id"]))
            except ValueError:
                messagebox.showerror("Retail Offers", "Enter a rate #.")
                return
            self._show("party")

        def _set_customer_offer(self):
            d = self._ask("Customer discount & credit limit", [
                ("Customer name or phone", "customer", ""),
                ("Discount % on every bill (0 = none)", "disc", "0"),
                ("Credit limit \u20b9 (0 = no limit)", "limit", "0")])
            if not d:
                return
            c = self._pick_customer(d)
            if not c:
                return
            disc = self._num(d, "disc")
            limit = self._num(d, "limit")
            if disc is None or limit is None or disc < 0 or limit < 0:
                messagebox.showerror("Retail Offers",
                                     "Enter valid numbers.")
                return
            set_customer_offer(self.db, c["id"], disc, limit)
            self._show("customers")

        def _loyalty_lookup(self):
            d = self._ask("Loyalty lookup",
                          [("Customer name or phone", "customer", "")])
            if not d:
                return
            c = self._pick_customer(d)
            if not c:
                return
            pts = loyalty_balance(self.db, c["id"])
            st = loyalty_settings(self.db)
            messagebox.showinfo(
                "Loyalty lookup",
                f"{c['name']} ({c['phone'] or 'no phone'})\n"
                f"Points balance: {pts:g}\n"
                f"Worth: \u20b9{pts * st['point_value_rs']:,.2f} off a bill\n"
                f"Outstanding: \u20b9{float(c['balance'] or 0):,.2f}")

        # -- focus + suggestion actions -------------------------------------
        def _mark_focus(self):
            d = self._ask("Mark focus item",
                          [("Product name", "product", "")])
            if not d:
                return
            p = self._pick_product(d)
            if not p:
                return
            add_focus(self.db, p["id"])
            self._show("focus")

        def _unmark_focus(self):
            d = self._ask("Unmark focus item",
                          [("Product name", "product", "")])
            if not d:
                return
            p = self._pick_product(d)
            if not p:
                return
            remove_focus(self.db, p["id"])
            self._show("focus")

        def _add_suggestion_to_bill(self):
            tab = self._current_tab()
            if not tab:
                messagebox.showinfo("Retail Offers",
                                    "Open a bill in Billing first.")
                return
            d = self._ask("Add suggestion to current bill",
                          [("Product name", "product", "")])
            if not d:
                return
            p = self._pick_product(d)
            if not p:
                return
            add_suggested_line(self, tab, p["id"])
            self._refresh_billing(tab)

        # -- loyalty + settings actions -------------------------------------
        def _redeem_points(self):
            tab = self._current_tab()
            if not tab or not tab.customer:
                messagebox.showinfo(
                    "Retail Offers",
                    "Open a bill in Billing and choose the customer first.")
                return
            if getattr(tab, "edit_bill_id", None):
                messagebox.showinfo(
                    "Retail Offers",
                    "Points can only be redeemed on a new bill, not on "
                    "a bill being edited.")
                return
            c = self.db.get_customer(tab.customer["id"])
            bal = loyalty_balance(self.db, c["id"])
            st = loyalty_settings(self.db)
            d = self._ask(
                f"Redeem points \u2014 {c['name']} has {bal:g} points",
                [("Points to redeem", "points", "")])
            if not d:
                return
            try:
                pts = int(float(d["points"]))
            except ValueError:
                messagebox.showerror("Retail Offers",
                                     "Enter a whole number of points.")
                return
            if pts <= 0 or pts > bal:
                messagebox.showerror(
                    "Retail Offers",
                    f"Enter 1 to {bal:g} points.")
                return
            rs = round(pts * st["point_value_rs"], 2)
            base_total = float(tab.totals(self.db)["grand_total"]) \
                + float(tab.offer.get("redeem_rs", 0) or 0)
            if rs > base_total:
                pts = int(base_total // st["point_value_rs"]) \
                    if st["point_value_rs"] > 0 else 0
                rs = round(pts * st["point_value_rs"], 2)
            if pts <= 0:
                messagebox.showerror(
                    "Retail Offers",
                    "This bill is too small to redeem points on.")
                return
            tab.offer["redeem_points"] = pts
            tab.offer["redeem_rs"] = rs
            self._refresh_billing(tab)
            messagebox.showinfo(
                "Retail Offers",
                f"Redeemed {pts} points \u2014 \u20b9{rs:,.2f} off this bill.")

        def _set_loyalty_settings(self):
            st = loyalty_settings(self.db)
            d = self._ask("Loyalty earn rate & point value", [
                ("Points earned per \u20b9100 spent",
                 "per_100", f"{st['points_per_100']:g}"),
                ("Rs. off per point redeemed",
                 "value", f"{st['point_value_rs']:g}")])
            if not d:
                return
            per_100 = self._num(d, "per_100")
            value = self._num(d, "value")
            if per_100 is None or value is None \
                    or per_100 < 0 or value < 0:
                messagebox.showerror("Retail Offers",
                                     "Enter valid numbers.")
                return
            self.db.set_setting("loyalty_points_per_100", str(per_100))
            self.db.set_setting("loyalty_point_value_rs", str(value))
            self._show("loyalty")

        def _set_card_charge(self):
            d = self._ask("Card charge %", [
                ("Card charge % added to card payments (0\u201310)",
                 "pct", f"{card_charge_percent(self.db):g}")])
            if not d:
                return
            pct = self._num(d, "pct")
            if pct is None or pct < 0 or pct > 10:
                messagebox.showerror("Retail Offers",
                                     "Enter a % between 0 and 10.")
                return
            self.db.set_setting("card_charge_percent", str(pct))
            self._show("settings")

    return RetailOffersFrame
