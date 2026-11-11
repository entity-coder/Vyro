"""
BillBook — AI features (buildathon set, 2026-11-10).

Pure functions first (no GUI imports, so they can be tested headless);
the AI Insights screen is built by ai_screen_class() at the bottom and
imported lazily by ui.py.

What lives here, in build order:
  1. Demand forecasting — per-item average daily sales over the last
     28 days, from final bills. Plain arithmetic, no ML library.
  2. Smart reorder — forecast-based reorder points, suggested order
     quantities (rounded up to pack size), draft purchase orders grouped
     by supplier, and stock-more / stop-ordering / push-this-week
     recommendations. Nothing is ordered without the shopkeeper's
     approval: a draft is only loaded into Purchases on a button tap.
  3. Expiring products — builds on db.near_expiry_products (60-day
     warnings) and purchase lot expiry dates: predicted unsold stock at
     expiry, clearance suggestions, a sell-first (FEFO) list, a weekly
     risk summary, expired items blocked from billing, and write-off.
     Stock is not lot-tracked at billing, so "predicted unsold" is an
     estimate (stock minus expected sales before the expiry date) and
     a product is only billing-blocked when it has stock and no
     unexpired lot left.
  4. Local AI assistant — Qwen3-4B (Instruct) via Ollama as the local
     option, Gemini API as the cloud fallback. The model only
     interprets plain-language asks, explains results and drafts text
     for review. Forecasting, reorder quantities and expiry risk are
     calculated from data by the functions above, never by the LLM.
     Local AI degrades gracefully when Ollama is not installed.
  5. Auto outstanding reminders — personalised reminders in English, Hindi
     or Marathi, scheduled from the outstanding aging buckets, sent
     through the existing wa.me share path (one tap per customer).
     True auto-send is not safely possible: there is no official
     WhatsApp API for this, and unofficial automation risks a ban —
     so this builds scheduled drafts + one-tap send + a sent log,
     and says so in the UI.
  6. Dead-stock prediction, price/margin suggestions, customer
     insights (regulars who stopped coming).
  7. Voice assistant — typed commands are parsed by parse_command
     and the common ones (stock, dues, expiry, forecast, order) are
     answered straight from the shop's own data by answer_from_data,
     with no AI model installed. Anything else goes to the LLM.
     Voice input itself needs a microphone and a speech-to-text
     engine, which this PC does not have; voice_available() says so
     and the Assistant tab takes typed questions instead.

Wording rule (2026-11-10): no mention of any personal/family shop in
user-facing strings — generic "wholesale/kirana shop" only.
"""

import json
import local_ai_setup
import math
import re
import urllib.error
import urllib.request
from datetime import date, timedelta

# -- forecasting / reorder constants (documented, change in one place) ---
FORECAST_WINDOW_DAYS = 28     # days of sales history behind each rate
FORECAST_HORIZON_DAYS = 14    # days ahead each forecast covers
LEAD_DAYS = 3                 # days a supplier order takes to arrive
COVER_DAYS = 14               # days of demand a new order should cover
SAFETY_DAYS = 2               # extra days of demand kept as safety stock
DEAD_STOCK_DAYS = 90          # no sale in this long + stock on hand = dead
LAPSED_DAYS = 60              # no purchase in this long = lapsed regular
REMINDER_GAP_DAYS = 7         # days before the same customer is reminded again
EXPIRY_WARN_DAYS = 60         # same window as db.near_expiry_products

# -- local AI defaults ------------------------------------------------------
AI_LOCAL_MODEL = "qwen3:4b"   # Qwen3-4B Instruct, Apache 2.0, Hindi+Marathi
AI_LOCAL_URL = "http://localhost:11434"
AI_GEMINI_MODEL = "gemini-2.0-flash"


def _as_of(as_of):
    """A date object for `as_of` ('YYYY-MM-DD' or date), default today."""
    if as_of is None:
        return date.today()
    if isinstance(as_of, date):
        return as_of
    return date.fromisoformat(as_of)


def _days_ago(as_of, days):
    return (_as_of(as_of) - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# 1. Demand forecasting
# ---------------------------------------------------------------------------

def daily_sales_rate(db, product_id, window=FORECAST_WINDOW_DAYS,
                     as_of=None):
    """Average units sold per day over the last `window` days (calendar
    days, so slow items get low rates). 0.0 when nothing sold."""
    as_of = _as_of(as_of)
    start = (as_of - timedelta(days=window)).isoformat()
    r = db._one(
        "SELECT COALESCE(SUM(bi.qty), 0) q FROM bill_items bi "
        "JOIN bills b ON b.id=bi.bill_id "
        "WHERE bi.product_id=? AND b.date > ? AND b.date <= ?",
        (product_id, start, as_of.isoformat()))
    return float(r["q"] or 0) / window


def last_sale_date(db, product_id):
    """Latest bill date on which this product sold, or None."""
    r = db._one(
        "SELECT MAX(b.date) d FROM bill_items bi "
        "JOIN bills b ON b.id=bi.bill_id WHERE bi.product_id=?",
        (product_id,))
    return r["d"] if r and r["d"] else None


def forecast_demand(db, product_id, horizon=FORECAST_HORIZON_DAYS,
                    window=FORECAST_WINDOW_DAYS, as_of=None):
    """Forecast for one product, or None when it sold nothing in the
    window (no history to forecast from)."""
    rate = daily_sales_rate(db, product_id, window, as_of)
    if rate <= 0:
        return None
    p = db.get_product(product_id)
    if not p:
        return None
    stock = float(p["stock"] or 0)
    return {"product_id": product_id, "name": p["name"],
            "unit": p["unit"] or "pcs", "stock": stock,
            "daily_rate": round(rate, 3),
            "forecast_qty": round(rate * horizon, 1),
            "days_of_stock": (round(stock / rate, 1) if rate > 0
                              else None),
            "last_sale": last_sale_date(db, product_id)}


def forecast_all(db, horizon=FORECAST_HORIZON_DAYS,
                 window=FORECAST_WINDOW_DAYS, as_of=None):
    """Forecasts for every product with sales in the window, highest
    forecast first."""
    out = []
    for p in db.list_products():
        f = forecast_demand(db, p["id"], horizon, window, as_of)
        if f:
            out.append(f)
    out.sort(key=lambda f: -f["forecast_qty"])
    return out


# ---------------------------------------------------------------------------
# 2. Smart reorder + ordering assistant
# ---------------------------------------------------------------------------

def reorder_suggestions(db, as_of=None, lead_days=LEAD_DAYS,
                        cover_days=COVER_DAYS, safety_days=SAFETY_DAYS):
    """Forecast-based reorder list. A product is listed only when its
    stock will not cover lead + cover + safety days of demand.
    suggested_qty is rounded up to the product's pack size.
    Urgency: 'urgent' when stock runs out inside the lead time,
    otherwise 'soon'."""
    as_of = _as_of(as_of)
    out = []
    for f in forecast_all(db, horizon=cover_days, as_of=as_of):
        p = db.get_product(f["product_id"])
        rate = f["daily_rate"]
        need = rate * (lead_days + cover_days + safety_days)
        if f["stock"] >= need:
            continue
        qty = need - f["stock"]
        pack = max(int(p.get("pack_size") or 1), 1)
        qty = math.ceil(qty / pack) * pack
        last_rate = float(p["purchase_price"] or 0)
        out.append({"product_id": f["product_id"], "name": f["name"],
                    "unit": f["unit"], "stock": f["stock"],
                    "daily_rate": rate, "forecast_qty": f["forecast_qty"],
                    "reorder_point": round(rate * (lead_days + cover_days), 1),
                    "suggested_qty": float(qty),
                    "supplier": (p.get("supplier") or "").strip(),
                    "last_rate": last_rate,
                    "est_amount": round(qty * last_rate, 2),
                    "urgency": ("urgent" if f["stock"] <= rate * lead_days
                                else "soon")})
    out.sort(key=lambda r: (r["urgency"] != "urgent", -r["forecast_qty"]))
    return out


def draft_purchase_orders(db, suggestions=None, as_of=None):
    """Draft purchase orders from reorder suggestions, grouped by
    supplier (products with no supplier saved go in one 'No supplier'
    draft). Drafts only — nothing is ordered or saved here."""
    if suggestions is None:
        suggestions = reorder_suggestions(db, as_of=as_of)
    by_supplier = {}
    for s in suggestions:
        by_supplier.setdefault(s["supplier"] or "No supplier saved",
                               []).append(s)
    drafts = []
    for supplier, items in by_supplier.items():
        drafts.append({"supplier": supplier,
                       "items": [{"product_id": i["product_id"],
                                  "name": i["name"], "unit": i["unit"],
                                  "qty": i["suggested_qty"],
                                  "cost": i["last_rate"],
                                  "gst_percent": float(
                                      db.get_product(i["product_id"])
                                      ["gst_percent"] or 0),
                                  "expiry_date": ""}
                                 for i in items],
                       "total": round(sum(i["est_amount"] for i in items), 2)})
    drafts.sort(key=lambda d: -d["total"])
    return drafts


def create_purchase_from_draft(db, draft, supplier_id, date_str):
    """Save an approved draft as a real purchase (stock updates then,
    via db.create_purchase). The shopkeeper chooses the supplier and
    the date; this is only called from the approval button."""
    return db.create_purchase(supplier_id, date_str, "",
                              draft["items"])


def stock_recommendations(db, as_of=None):
    """Three plain-language lists from forecast + stock + expiry data:
    stock more (demand outruns stock), stop ordering (stock covers
    60+ days or the item is dead), push this week (near expiry or
    dead stock with stock on hand)."""
    as_of = _as_of(as_of)
    more, stop, push = [], [], []
    forecasts = {f["product_id"]: f for f in forecast_all(db, as_of=as_of)}
    for p in db.list_products():
        stock = float(p["stock"] or 0)
        if stock <= 0:
            continue
        f = forecasts.get(p["id"])
        if f:
            days = f["days_of_stock"] or 0
            if days < (LEAD_DAYS + COVER_DAYS):
                more.append({"name": p["name"],
                             "reason": f"sells ~{f['daily_rate']:g} "
                                       f"{f['unit']}/day, only {days:g} "
                                       f"days of stock left"})
            elif days > 60:
                stop.append({"name": p["name"],
                             "reason": f"~{days:g} days of stock on hand"})
        else:
            last = last_sale_date(db, p["id"])
            if last is None or (_as_of(as_of) -
                                date.fromisoformat(last)).days >= DEAD_STOCK_DAYS:
                stop.append({"name": p["name"],
                             "reason": "no sale in 90+ days"})
    for e in expiry_risk(db, within_days=EXPIRY_WARN_DAYS, as_of=as_of):
        if e["band"] in ("urgent", "watch") and e["predicted_unsold"] > 0:
            push.append({"name": e["name"],
                         "reason": f"~{e['predicted_unsold']:g} "
                                   f"{e['unit']} may expire unsold by "
                                   f"{e['expiry']}"})
    return {"stock_more": more, "stop_ordering": stop,
            "push_this_week": push}


# ---------------------------------------------------------------------------
# 3. Expiring-products system (builds on the 60-day warnings)
# ---------------------------------------------------------------------------

def expiry_risk(db, within_days=EXPIRY_WARN_DAYS,
                window=FORECAST_WINDOW_DAYS, as_of=None):
    """One row per product with a dated purchase lot expiring within
    `within_days` (or already expired). predicted_unsold is an estimate:
    stock minus expected sales before the expiry date, floored at 0.
    Band: 'expired' (date passed), 'urgent' (<=7 days), 'watch'
    (<=30 days), 'safe' (further out)."""
    as_of = _as_of(as_of)
    out = []
    for row in db.near_expiry_products(within_days):
        pid = row["id"]
        expiry = row["expiry"]
        days_left = (date.fromisoformat(expiry) - as_of).days
        stock = float(row["stock"] or 0)
        rate = daily_sales_rate(db, pid, window, as_of)
        predicted = max(0.0, stock - rate * max(days_left, 0))
        cost = float(db.get_product(pid)["purchase_price"] or 0)
        if days_left < 0:
            band, action = "expired", "write off — do not bill"
        elif days_left <= 7:
            band, action = "urgent", "clearance — suggest 15% off"
        elif days_left <= 30:
            band, action = "watch", "clearance — suggest 10% off"
        else:
            band, action = "safe", "sell normally"
        out.append({"product_id": pid, "name": row["name"],
                    "unit": row["unit"] or "pcs", "stock": stock,
                    "expiry": expiry, "days_left": days_left,
                    "daily_rate": round(rate, 3),
                    "predicted_unsold": round(predicted, 1),
                    "value_at_risk": round(predicted * cost, 2),
                    "band": band, "suggested_action": action})
    out.sort(key=lambda e: e["days_left"])
    return out


def expired_products(db, as_of=None):
    """Products that must not be billed: stock on hand and every dated
    purchase lot already expired (a product with a fresh lot left is
    fine — the fresh lot sells first)."""
    as_of = _as_of(as_of)
    today = as_of.isoformat()
    out = []
    for p in db.list_products():
        if float(p["stock"] or 0) <= 0:
            continue
        lots = db._rows(
            "SELECT expiry_date FROM purchase_items "
            "WHERE product_id=? AND expiry_date <> ''", (p["id"],))
        if not lots:
            continue
        if all(l["expiry_date"] < today for l in lots):
            out.append({"product_id": p["id"], "name": p["name"],
                        "stock": float(p["stock"]),
                        "earliest_expiry": min(l["expiry_date"]
                                               for l in lots)})
    return out


def billing_blocked_lines(db, items):
    """Names of bill lines whose product is expired-blocked (by
    product_id; lines without one are never blocked). Used by the
    billing validation before a bill is saved."""
    blocked_ids = {e["product_id"] for e in expired_products(db)}
    return [it["name"] for it in items
            if it.get("product_id") in blocked_ids]


def suggest_write_off(db, product_id, as_of=None):
    """Suggested write-off for an expired product: the smaller of
    current stock and the total qty of its expired lots (lot qty is
    what was bought, not what is left — so this is an upper bound,
    capped at stock). Returns None when nothing is expired."""
    as_of = _as_of(as_of)
    p = db.get_product(product_id)
    if not p:
        return None
    r = db._one(
        "SELECT COALESCE(SUM(qty), 0) q FROM purchase_items "
        "WHERE product_id=? AND expiry_date <> '' AND expiry_date < ?",
        (product_id, as_of.isoformat()))
    expired_qty = float(r["q"] or 0)
    if expired_qty <= 0:
        return None
    qty = min(float(p["stock"] or 0), expired_qty)
    if qty <= 0:
        return None
    cost = float(p["purchase_price"] or 0)
    return {"product_id": product_id, "name": p["name"],
            "qty": qty, "value": round(qty * cost, 2)}


def write_off_expired(db, product_id, qty, note="Expired stock write-off"):
    """Reduce stock for expired goods and log the movement. The
    shopkeeper confirms the qty first; this only runs on approval."""
    qty = float(qty)
    if qty <= 0:
        return False
    p = db.get_product(product_id)
    if not p or float(p["stock"] or 0) < qty:
        return False
    db.adjust_stock(product_id, -qty, "expiry-writeoff", note)
    return True


def sell_first_order(db, within_days=EXPIRY_WARN_DAYS, as_of=None):
    """FEFO sell-first list: expiry-risk rows soonest first. Stock is
    not lot-tracked at billing, so this list — not a billing change —
    is how first-expiry-first-out is applied in practice."""
    return expiry_risk(db, within_days, as_of=as_of)


def weekly_expiry_summary(db, as_of=None):
    """Plain-text weekly expiry-risk summary for the AI Insights tab."""
    as_of = _as_of(as_of)
    rows = expiry_risk(db, as_of=as_of)
    if not rows:
        return ("Expiry: nothing expiring in the next 60 days. "
                "No action needed this week.")
    lines = [f"Expiry risk — week of {as_of.isoformat()}: "
             f"{len(rows)} product(s) with a dated lot expiring soon."]
    total_risk = 0.0
    for e in rows:
        total_risk += e["value_at_risk"]
        lines.append(
            f"- {e['name']}: {e['stock']:g} {e['unit']} on hand, "
            f"expires {e['expiry']} ({e['days_left']} days), "
            f"~{e['predicted_unsold']:g} may go unsold "
            f"(Rs. {e['value_at_risk']:.2f} at risk) — "
            f"{e['suggested_action']}.")
    lines.append(f"Total value at risk: Rs. {total_risk:.2f}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 6. Dead stock, price/margin suggestions, customer insights
# ---------------------------------------------------------------------------

def dead_stock(db, days=DEAD_STOCK_DAYS, as_of=None):
    """Products with stock on hand and no sale in `days` (or never
    sold). Value uses the current purchase price."""
    as_of = _as_of(as_of)
    cutoff = (as_of - timedelta(days=days)).isoformat()
    rows = db._rows(
        "SELECT p.*, MAX(b.date) last_sale FROM products p "
        "LEFT JOIN bill_items bi ON bi.product_id=p.id "
        "LEFT JOIN bills b ON b.id=bi.bill_id "
        "GROUP BY p.id HAVING p.stock > 0 "
        "AND (last_sale IS NULL OR last_sale < ?)",
        (cutoff,))
    out = []
    for r in rows:
        stock = float(r["stock"] or 0)
        out.append({"product_id": r["id"], "name": r["name"],
                    "unit": r["unit"] or "pcs", "stock": stock,
                    "last_sale": r["last_sale"],
                    "value": round(stock * float(r["purchase_price"] or 0),
                                   2)})
    out.sort(key=lambda d: -d["value"])
    return out


def price_suggestions(db):
    """Margin check per product on the wholesale price. 'loss' when the
    wholesale price is at or below cost; 'thin' when the margin is
    under 5%; otherwise 'healthy'. The suggestion is cost + 10% for
    loss/thin items (a starting point, not a rule)."""
    out = []
    for p in db.list_products():
        cost = float(p["purchase_price"] or 0)
        ws = float(p["wholesale_price"] or 0)
        if cost <= 0:
            continue
        margin = (ws - cost) / cost
        if ws <= cost:
            flag, suggestion = "loss", round(cost * 1.10, 2)
        elif margin < 0.05:
            flag, suggestion = "thin", round(cost * 1.10, 2)
        else:
            flag, suggestion = "healthy", ws
        out.append({"product_id": p["id"], "name": p["name"],
                    "cost": cost, "wholesale_price": ws,
                    "margin_pct": round(margin * 100, 1),
                    "flag": flag, "suggested_price": suggestion})
    out.sort(key=lambda s: (s["flag"] != "loss", s["flag"] != "thin",
                            s["margin_pct"]))
    return out


def lapsed_customers(db, days=LAPSED_DAYS, as_of=None):
    """Regulars who stopped coming: customers with at least one bill
    whose latest purchase is `days` or more ago, biggest spenders
    first. Walk-in (no-customer) bills have no one to win back and
    are excluded."""
    as_of = _as_of(as_of)
    cutoff = (as_of - timedelta(days=days)).isoformat()
    rows = db._rows(
        "SELECT c.id, c.name, c.phone, COUNT(*) n, "
        "SUM(b.grand_total) t, MAX(b.date) last_date FROM bills b "
        "JOIN customers c ON c.id=b.customer_id "
        "GROUP BY c.id HAVING last_date <= ? ORDER BY t DESC",
        (cutoff,))
    return [{"customer_id": r["id"], "name": r["name"],
             "phone": r.get("phone") or "", "bills": int(r["n"]),
             "total_spent": round(float(r["t"] or 0), 2),
             "last_purchase": r["last_date"]} for r in rows]


# ---------------------------------------------------------------------------
# 5. Auto outstanding reminders (scheduled drafts + one-tap send + sent log)
# ---------------------------------------------------------------------------

def ensure_ai_tables(db):
    """Create the AI reminder log if it is missing. Additive only;
    db.py is untouched."""
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_reminder_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "customer_id INTEGER NOT NULL, sent_date TEXT NOT NULL, "
        "channel TEXT NOT NULL DEFAULT 'whatsapp', "
        "language TEXT NOT NULL DEFAULT 'en', "
        "message TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL)")
    db.conn.commit()


REMINDER_TEMPLATES = {
    "en": ("Hello {name}, this is {shop}. Your outstanding balance is "
           "Rs. {balance:.2f}. Kindly pay at your convenience. Thank you!"),
    "hi": ("नमस्ते {name} जी, यह {shop} की ओर से संदेश है। आपका बकाया "
           "शेष ₹{balance:.2f} है। कृपया अपनी सुविधा से भुगतान करें। "
           "धन्यवाद!"),
    "mr": ("नमस्कार {name}, हा {shop} कडून संदेश आहे. तुमचे थकबाकी "
           "शिल्लक ₹{balance:.2f} आहे. कृपया सोयीनुसार भरणा करा. "
           "धन्यवाद!"),
}


def reminder_message(shop_name, customer_name, balance, lang="en"):
    """Personalised reminder text in English, Hindi or Marathi.
    Unknown language codes fall back to English."""
    shop = shop_name or "BillBook"
    template = REMINDER_TEMPLATES.get(lang) or REMINDER_TEMPLATES["en"]
    return template.format(name=customer_name, shop=shop,
                           balance=float(balance))


def log_reminder(db, customer_id, channel, language, message,
                 sent_date=None):
    """Record a reminder as sent (or queued). Called after the
    shopkeeper taps WhatsApp, so the schedule knows not to repeat it."""
    ensure_ai_tables(db)
    db.conn.execute(
        "INSERT INTO ai_reminder_log (customer_id, sent_date, channel, "
        "language, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (customer_id, sent_date or date.today().isoformat(), channel,
         language, message,
         date.today().isoformat()))
    db.conn.commit()


def last_reminder(db, customer_id):
    """Latest logged reminder for a customer, or None."""
    ensure_ai_tables(db)
    return db._one(
        "SELECT * FROM ai_reminder_log WHERE customer_id=? "
        "ORDER BY sent_date DESC, id DESC LIMIT 1", (customer_id,))


def _aging_bucket(db, customer_id):
    """Oldest outstanding bucket index for a customer (0 = 1-30 days
    ... 5 = 241+ days), or None when they owe nothing."""
    for c in db.customer_aging():
        if c["id"] == customer_id:
            for i, b in enumerate(c["buckets"]):
                if b > 0.004:
                    return i
    return None


def due_reminders(db, shop_name="", lang="en", as_of=None):
    """Reminders due now: customers with an outstanding balance whose
    oldest unpaid amount is over 30 days old, and who were not
    reminded in the last REMINDER_GAP_DAYS. Oldest first. Each row
    carries the ready-to-send message and wa.me link; sending itself
    is one tap in the UI (WhatsApp has no safe auto-send path)."""
    from new_features import whatsapp_link
    as_of = _as_of(as_of)
    out = []
    for c in db.outstanding_list():
        bucket = _aging_bucket(db, c["id"])
        if bucket is None or bucket < 1:
            continue
        last = last_reminder(db, c["id"])
        if last:
            gap = (as_of - date.fromisoformat(last["sent_date"])).days
            if gap < REMINDER_GAP_DAYS:
                continue
        message = reminder_message(shop_name, c["name"], c["balance"],
                                   lang)
        out.append({"customer_id": c["id"], "name": c["name"],
                    "phone": c.get("phone") or "",
                    "balance": float(c["balance"]),
                    "age_bucket": db.aging_buckets()[bucket],
                    "overdue": bucket >= 2,
                    "message": message,
                    "whatsapp": whatsapp_link(c.get("phone") or "",
                                              message)})
    return out


# ---------------------------------------------------------------------------
# 4. Local AI assistant (Ollama local, Gemini API fallback)
# ---------------------------------------------------------------------------

def ai_settings(db):
    """AI settings from the key/value store (defaults when unset)."""
    return {
        "provider": db.get_setting("ai_provider", "auto") or "auto",
        "local_model": (db.get_setting("ai_local_model", AI_LOCAL_MODEL)
                        or AI_LOCAL_MODEL),
        "local_url": (db.get_setting("ai_local_url", AI_LOCAL_URL)
                      or AI_LOCAL_URL),
        "gemini_key": db.get_setting("ai_gemini_key", "") or "",
        "gemini_model": (db.get_setting("ai_gemini_model", AI_GEMINI_MODEL)
                         or AI_GEMINI_MODEL),
    }


def ollama_status(url=AI_LOCAL_URL, timeout=2):
    """Is Ollama reachable, and which models are installed? Never
    raises — returns {"available": bool, "models": [...]}."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = [m.get("name", "") for m in data.get("models", [])]
        return {"available": True, "models": models}
    except Exception:
        return {"available": False, "models": []}


def ollama_chat(model, messages, url=AI_LOCAL_URL, timeout=60):
    """One non-streaming chat call to a local Ollama model. Returns
    {"ok": True, "answer": str} or {"ok": False, "error": str}."""
    try:
        payload = json.dumps({"model": model, "messages": messages,
                              "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            url.rstrip("/") + "/api/chat", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"ok": True,
                "answer": data.get("message", {}).get("content", "")}
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:
            detail = ""
        return {"ok": False,
                "error": f"Ollama said: {detail or e}"}
    except Exception as e:
        return {"ok": False, "error": f"Could not reach Ollama: {e}"}


def gemini_chat(api_key, prompt, model=AI_GEMINI_MODEL, timeout=60):
    """One Gemini API call (plain urllib, no extra dependency).
    Returns {"ok": True, "answer": str} or {"ok": False, "error": str}."""
    if not (api_key or "").strip():
        return {"ok": False, "error": "No Gemini API key saved."}
    try:
        payload = json.dumps(
            {"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}",
            data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data["candidates"][0]["content"]["parts"]
        return {"ok": True,
                "answer": "".join(p.get("text", "") for p in parts)}
    except Exception as e:
        return {"ok": False, "error": f"Gemini API failed: {e}"}


def assistant_context(db, as_of=None):
    """Compact numbers-only summary the assistant may explain. The
    LLM never computes these — they come from the functions above."""
    as_of = _as_of(as_of)
    lines = ["Shop summary (numbers only, already calculated):"]
    sugg = reorder_suggestions(db, as_of=as_of)
    lines.append(f"- {len(sugg)} product(s) need re-ordering soon.")
    for s in sugg[:5]:
        lines.append(f"  * {s['name']}: stock {s['stock']:g}, "
                     f"sells ~{s['daily_rate']:g}/day, order "
                     f"{s['suggested_qty']:g} {s['unit']}.")
    exp = expiry_risk(db, as_of=as_of)
    lines.append(f"- {len(exp)} product(s) expiring in 60 days; "
                 f"total value at risk Rs. "
                 f"{sum(e['value_at_risk'] for e in exp):.2f}.")
    dead = dead_stock(db, as_of=as_of)
    lines.append(f"- {len(dead)} dead-stock product(s), value "
                 f"Rs. {sum(d['value'] for d in dead):.2f}.")
    lines.append(f"- Total outstanding from customers: "
                 f"Rs. {float(db.total_outstanding() or 0):.2f}.")
    lapsed = lapsed_customers(db, as_of=as_of)
    lines.append(f"- {len(lapsed)} regular customer(s) have not "
                 f"bought in 60+ days.")
    return "\n".join(lines)


ASSISTANT_SYSTEM = (
    "You are a billing assistant for a wholesale/kirana shop. "
    "Answer in plain, short language. Use ONLY the numbers in the "
    "shop summary below — never invent sales, stock or money figures. "
    "If a question needs data that is not in the summary, say what is "
    "missing instead of guessing. Keep every draft (order, reminder, "
    "summary) ready for the shopkeeper to review before it is used.")


def assistant_ask(db, question, provider=None, as_of=None):
    """Ask the assistant a plain-language question. Provider order:
    'local' (Ollama only), 'api' (Gemini only), 'auto' (local first,
    API fallback). Common shop questions are answered straight from
    the shop's own data first (see answer_from_data) — the LLM is
    only needed for the rest. Always returns a dict — never raises,
    never crashes when Ollama is missing."""
    direct = answer_from_data(db, question, as_of=as_of)
    if direct is not None:
        return {"ok": True, "provider": "shop data",
                "model": "no AI model needed", "answer": direct}
    cfg = ai_settings(db)
    provider = provider or cfg["provider"]
    context = assistant_context(db, as_of=as_of)
    prompt = (ASSISTANT_SYSTEM + "\n\n" + context + "\n\nQuestion: "
              + (question or "").strip())
    tried = []
    if provider in ("local", "auto"):
        status = ollama_status(cfg["local_url"])
        if status["available"]:
            if cfg["local_model"] not in status["models"]:
                tried.append(f"Ollama is running but the model "
                             f"'{cfg['local_model']}' is not installed "
                             f"(run: ollama pull {cfg['local_model']}).")
            else:
                res = ollama_chat(cfg["local_model"],
                                  [{"role": "user", "content": prompt}],
                                  url=cfg["local_url"])
                if res["ok"]:
                    res["provider"] = "local"
                    res["model"] = cfg["local_model"]
                    return res
                tried.append(res["error"])
        else:
            tried.append("Ollama is not running on this PC. Install "
                         "Ollama and pull the model, or switch to the "
                         "Gemini API in Settings.")
        if provider == "local":
            return {"ok": False, "provider": "local",
                    "error": " ".join(tried)}
    if provider in ("api", "auto"):
        res = gemini_chat(cfg["gemini_key"], prompt,
                          model=cfg["gemini_model"])
        if res["ok"]:
            res["provider"] = "api"
            res["model"] = cfg["gemini_model"]
            return res
        tried.append(res["error"])
    return {"ok": False, "provider": provider,
            "error": " ".join(tried) if tried else
                     "No AI provider is available."}


# ---------------------------------------------------------------------------
# 7. Voice assistant — text-command hookup only (see module docstring)
# ---------------------------------------------------------------------------

def voice_available():
    """Voice input needs a microphone and a speech-to-text engine.
    Neither is available in this app, so voice is honestly
    unavailable; the Assistant tab takes typed questions instead."""
    return (False, "Voice input needs a microphone and a speech-to-text "
                   "engine — neither is set up on this PC. Type the "
                   "question instead; the same assistant answers it.")


_COMMAND_WORDS = {
    "order": ("order", "reorder", "buy", "purchase", "mangao", "order karo"),
    "stock": ("stock", "left", "available", "kitna bacha", "bacha"),
    "outstanding": ("due", "pending", "payment", "owe", "owes", "udhar",
             "bakaya", "outstanding"),
    "expiry": ("expir", "expiry", "expire"),
    "forecast": ("sell", "sales", "forecast", "demand", "bikega"),
}


def parse_command(text, db=None):
    """Map a typed (or later spoken) question to an intent + product.
    Returns {"intent": str, "product": name-or-None, "text": str}.
    Intent is 'general' when nothing matches."""
    t = (text or "").strip().lower()
    intent = "general"
    for name, words in _COMMAND_WORDS.items():
        if any(w in t for w in words):
            intent = name
            break
    product = None
    if db is not None:
        for p in db.list_products():
            if p["name"].lower() in t:
                product = p["name"]
                break
    return {"intent": intent, "product": product, "text": text or ""}


def _product_named(db, name):
    """Product row whose name matches (case-insensitive), or None."""
    for p in db.list_products():
        if p["name"].lower() == name.lower():
            return p
    return None


def answer_from_data(db, question, as_of=None):
    """Answer common shop questions straight from the shop's own data —
    no AI model, no internet, no waiting. Returns the answer text, or
    None when the question is not one of the known kinds (the caller
    then falls through to the LLM). Every figure comes from the same
    pure functions the AI Insights tabs use, so the answers always
    agree with the numbers on screen."""
    as_of = _as_of(as_of)
    cmd = parse_command(question, db)
    intent, name = cmd["intent"], cmd["product"]
    if intent == "general":
        return None
    if intent == "stock":
        if name:
            p = _product_named(db, name)
            if not p:
                return None
            stock = float(p["stock"] or 0)
            line = f"{p['name']}: {stock:g} {p['unit'] or 'pcs'} in stock."
            f = forecast_demand(db, p["id"], as_of=as_of)
            if f:
                line += (f" It sells about {f['daily_rate']} a day, so "
                         f"this lasts about {f['days_of_stock']} days.")
            return line
        rows = sorted(db.list_products(),
                      key=lambda p: float(p["stock"] or 0))
        if not rows:
            return "No products saved yet — add products first."
        lines = ["Lowest stock right now:"]
        for p in rows[:5]:
            lines.append(f"- {p['name']}: {float(p['stock'] or 0):g} "
                         f"{p['unit'] or 'pcs'}")
        return "\n".join(lines)
    if intent == "outstanding":
        rows = db.outstanding_list()
        t = (question or "").strip().lower()
        for c in rows:
            if c["name"].lower() in t:
                return (f"{c['name']} owes "
                        f"Rs. {float(c['balance']):,.2f}.")
        if not rows:
            return ("Nobody owes anything right now — "
                    "no outstanding balances.")
        total = db.total_outstanding()
        lines = [f"Outstanding balances (Rs. {total:,.2f} in total):"]
        for c in rows[:5]:
            lines.append(f"- {c['name']}: Rs. {float(c['balance']):,.2f}")
        if len(rows) > 5:
            lines.append(f"...and {len(rows) - 5} more customers.")
        return "\n".join(lines)
    if intent == "expiry":
        risks = expiry_risk(db, as_of=as_of)
        if name:
            risks = [r for r in risks if r["name"] == name]
            if not risks:
                return (f"{name} has no purchase lot expiring in the "
                        f"next {EXPIRY_WARN_DAYS} days.")
        if not risks:
            return f"Nothing expires in the next {EXPIRY_WARN_DAYS} days."
        lines = ["Expiring soon (earliest first):"]
        for r in risks[:5]:
            lines.append(f"- {r['name']}: {r['stock']:g} {r['unit']} left, "
                         f"expires {r['expiry']} ({r['days_left']} days) — "
                         f"about {r['predicted_unsold']:g} may stay unsold. "
                         f"{r['suggested_action']}.")
        return "\n".join(lines)
    if intent == "forecast":
        if name:
            p = _product_named(db, name)
            if not p:
                return None
            f = forecast_demand(db, p["id"], as_of=as_of)
            if not f:
                return (f"{name} hasn't sold in the last "
                        f"{FORECAST_WINDOW_DAYS} days, so there is no "
                        "sales history to forecast from.")
            return (f"{name} sells about {f['daily_rate']} {f['unit']} "
                    f"a day — expect about {f['forecast_qty']} in the "
                    f"next {FORECAST_HORIZON_DAYS} days. Stock is "
                    f"{f['stock']:g}, about {f['days_of_stock']} days' "
                    "worth.")
        rows = forecast_all(db, as_of=as_of)
        if not rows:
            return (f"No sales in the last {FORECAST_WINDOW_DAYS} days, "
                    "so there is nothing to forecast yet.")
        lines = [f"Top sellers — expected sales in the next "
                 f"{FORECAST_HORIZON_DAYS} days:"]
        for f in rows[:5]:
            lines.append(f"- {f['name']}: about {f['forecast_qty']} "
                         f"{f['unit']} (stock {f['stock']:g}, "
                         f"~{f['days_of_stock']} days)")
        return "\n".join(lines)
    if intent == "order":
        sug = reorder_suggestions(db, as_of=as_of)
        if name:
            sug = [s for s in sug if s["name"] == name]
            if not sug:
                return (f"{name} does not need ordering right now — "
                        "stock covers forecast demand.")
        if not sug:
            return ("Nothing needs ordering right now — stock covers "
                    "forecast demand.")
        total = sum(s["est_amount"] for s in sug)
        lines = [f"Order list (about Rs. {total:,.2f} at last purchase "
                 "prices):"]
        for s in sug[:5]:
            lines.append(f"- {s['name']}: order {s['suggested_qty']:g} "
                         f"{s['unit']} (stock {s['stock']:g}, "
                         f"{s['urgency']})"
                         + (f" — supplier {s['supplier']}"
                            if s["supplier"] else ""))
        if len(sug) > 5:
            lines.append(f"...and {len(sug) - 5} more items — see the "
                         "Reorder tab.")
        return "\n".join(lines)
    return None


# ---------------------------------------------------------------------------
# Plain-text reports for the AI Insights screen (pure, testable)
# ---------------------------------------------------------------------------

def forecast_report(db, as_of=None):
    """Forecast section as plain text."""
    rows = forecast_all(db, as_of=as_of)
    if not rows:
        return ("Forecast: no sales in the last 28 days, so there is "
                "nothing to forecast from yet. Sell something first — "
                "the forecast appears after the first bills.")
    lines = [f"Demand forecast — next {FORECAST_HORIZON_DAYS} days "
             f"(from the last {FORECAST_WINDOW_DAYS} days of sales):"]
    for f in rows:
        lines.append(f"- {f['name']}: sells ~{f['daily_rate']:g} "
                     f"{f['unit']}/day, expect ~{f['forecast_qty']:g} "
                     f"in {FORECAST_HORIZON_DAYS} days, "
                     f"{f['stock']:g} in stock "
                     f"(~{f['days_of_stock']:g} days).")
    return "\n".join(lines)


def reorder_report(db, as_of=None):
    """Reorder section as plain text."""
    rows = reorder_suggestions(db, as_of=as_of)
    if not rows:
        return ("Re-Order: stock covers the next "
                f"{LEAD_DAYS + COVER_DAYS + SAFETY_DAYS} days of demand "
                "for every selling item. Nothing needs ordering today.")
    lines = ["Smart re-order — forecast-based (lead 3 days, cover 14, "
             "safety 2). Nothing is ordered until you approve it:"]
    total = 0.0
    for r in rows:
        total += r["est_amount"]
        lines.append(f"- [{r['urgency']}] {r['name']}: stock "
                     f"{r['stock']:g}, sells ~{r['daily_rate']:g}/day, "
                     f"order {r['suggested_qty']:g} {r['unit']} "
                     f"({r['supplier'] or 'no supplier saved'}) — "
                     f"about Rs. {r['est_amount']:.2f}.")
    lines.append(f"Estimated total: Rs. {total:.2f}.")
    return "\n".join(lines)


def expiry_report(db, as_of=None):
    """Expiry section as plain text (risk summary + billing block)."""
    parts = [weekly_expiry_summary(db, as_of=as_of)]
    blocked = expired_products(db, as_of=as_of)
    if blocked:
        parts.append("\nBlocked from billing until written off:")
        for b in blocked:
            s = suggest_write_off(db, b["product_id"], as_of=as_of)
            qty = s["qty"] if s else b["stock"]
            parts.append(f"- {b['name']}: {b['stock']:g} in stock, "
                         f"all lots expired (earliest "
                         f"{b['earliest_expiry']}) — suggested write-off "
                         f"{qty:g}.")
    else:
        parts.append("\nNo expired stock is blocking billing.")
    first = sell_first_order(db, as_of=as_of)
    if first:
        parts.append("\nSell first (earliest expiry): " +
                     ", ".join(e["name"] for e in first[:5]) + ".")
    return "\n".join(parts)


def insights_report(db, as_of=None):
    """Dead stock + price + lapsed customers + recommendations."""
    recs = stock_recommendations(db, as_of=as_of)
    dead = dead_stock(db, as_of=as_of)
    prices = [p for p in price_suggestions(db)
              if p["flag"] in ("loss", "thin")]
    lapsed = lapsed_customers(db, as_of=as_of)
    lines = ["Insights — from sales, stock and customer data:"]
    lines.append("\nStock more:")
    lines += ([f"- {r['name']} ({r['reason']})" for r in recs["stock_more"]]
              or ["- Nothing is running short."])
    lines.append("\nStop ordering:")
    lines += ([f"- {r['name']} ({r['reason']})" for r in recs["stop_ordering"]]
              or ["- Nothing is overstocked."])
    lines.append("\nPush this week:")
    lines += ([f"- {r['name']} ({r['reason']})"
               for r in recs["push_this_week"]]
              or ["- Nothing needs pushing."])
    lines.append("\nDead stock (no sale in 90+ days):")
    lines += ([f"- {d['name']}: {d['stock']:g} {d['unit']} "
               f"(Rs. {d['value']:.2f})" for d in dead]
              or ["- None."])
    lines.append("\nPrice check (selling at a loss or under 5% margin):")
    lines += ([f"- {p['name']}: cost Rs. {p['cost']:.2f}, wholesale "
               f"Rs. {p['wholesale_price']:.2f} "
               f"({p['margin_pct']:.1f}% margin) — suggest "
               f"Rs. {p['suggested_price']:.2f}" for p in prices]
              or ["- All margins look healthy."])
    lines.append("\nRegulars who stopped coming (no purchase in 60+ days):")
    lines += ([f"- {c['name']}: last bought {c['last_purchase']}, "
               f"spent Rs. {c['total_spent']:.2f} over {c['bills']} bill(s)"
               for c in lapsed[:10]]
              or ["- None."])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AI Insights screen (built lazily so this module stays headless-safe)
# ---------------------------------------------------------------------------

def ai_screen_class():
    """The AI Insights screen class (a CTkFrame like ReOrderFrame).
    Defined inside this factory so importing this module never needs
    a GUI — ui.py calls ai_screen_class() only when the screen opens."""
    from tkinter import messagebox
    import customtkinter as ctk

    class AIInsightsFrame(ctk.CTkFrame):
        def __init__(self, parent, db, app):
            super().__init__(parent, fg_color="transparent")
            self.db, self.app = db, app
            self.section = "forecast"
            ctk.CTkLabel(self, text="AI Insights",
                         font=ctk.CTkFont(size=22, weight="bold")).pack(
                             anchor="w", pady=(4, 2))
            ctk.CTkLabel(
                self,
                text="Forecasts, re-orders, expiry and reminders are "
                     "calculated from your own sales, stock and outstanding data. "
                     "The AI assistant only explains the numbers and drafts "
                     "text for you to review — it never orders anything.",
                text_color="gray", wraplength=760,
                justify="left").pack(anchor="w", pady=(0, 6))
            btns = ctk.CTkFrame(self, fg_color="transparent")
            btns.pack(fill="x", pady=4)
            for label, key in (("Forecast", "forecast"),
                               ("Re-Order", "reorder"),
                               ("Expiry", "expiry"),
                               ("Reminders", "reminders"),
                               ("Insights", "insights"),
                               ("Assistant", "assistant")):
                ctk.CTkButton(btns, text=label, width=110,
                              command=lambda k=key: self._show(k)).pack(
                                  side="left", padx=3)
            self.text = ctk.CTkTextbox(self, wrap="word")
            self.text.pack(fill="both", expand=True, pady=6)
            actions = ctk.CTkFrame(self, fg_color="transparent")
            actions.pack(fill="x", pady=4)
            ctk.CTkButton(actions, text="Load re-order into Purchases",
                          fg_color="#1f6f43", hover_color="#175733",
                          command=self._load_reorder).pack(side="left",
                                                           padx=3)
            ctk.CTkButton(actions, text="Open reminder list",
                          command=self._open_reminders).pack(side="left",
                                                             padx=3)
            ctk.CTkButton(actions, text="Copy",
                          command=self._copy).pack(side="left", padx=3)
            ctk.CTkButton(actions, text="Refresh",
                          command=self._refresh).pack(side="right", padx=3)
            ask = ctk.CTkFrame(self, fg_color="transparent")
            ask.pack(fill="x", pady=4)
            self.ask_entry = ctk.CTkEntry(
                ask, placeholder_text="Ask the assistant in plain words "
                "(e.g. what should I order this week?)")
            self.ask_entry.pack(side="left", fill="x", expand=True, padx=3)
            self.ask_entry.bind("<Return>", lambda e: self._ask())
            ctk.CTkButton(ask, text="Ask", width=80,
                          command=self._ask).pack(side="left", padx=3)
            ai_row = ctk.CTkFrame(self, fg_color="transparent")
            ai_row.pack(fill="x", pady=4)
            self.prov_var = ctk.StringVar(
                value=ai_settings(self.db)["provider"])
            ctk.CTkSegmentedButton(ai_row, values=["auto", "local", "api"],
                                   variable=self.prov_var,
                                   command=self._save_provider).pack(
                                       side="left", padx=3)
            self.key_entry = ctk.CTkEntry(
                ai_row,
                placeholder_text="Gemini API key (optional, cloud fallback)",
                show="*")
            self.key_entry.pack(side="left", fill="x", expand=True, padx=3)
            ctk.CTkButton(ai_row, text="Save key", width=80,
                          command=self._save_key).pack(side="left", padx=3)
            setup_row = ctk.CTkFrame(self, fg_color="transparent")
            self.setup_row = setup_row
            self.setup_btn = ctk.CTkButton(
                setup_row, text="Download local AI",
                command=self._setup_local_ai)
            self.setup_btn.pack(side="left", padx=3)
            self.setup_bar = ctk.CTkProgressBar(setup_row, width=220)
            self.setup_bar.set(0)
            self.setup_bar.pack(side="left", fill="x", expand=True, padx=3)
            self.setup_cancel = ctk.CTkButton(
                setup_row, text="Cancel", width=80,
                command=self._cancel_setup, state="disabled")
            self.setup_cancel.pack(side="left", padx=3)
            self._setup_cancelled = False
            setup_row.pack(fill="x", pady=4)
            self.status = ctk.CTkLabel(self, text="", text_color="gray")
            self.status.pack(anchor="w")
            self._refresh()

        def _report(self):
            if self.section == "forecast":
                return forecast_report(self.db)
            if self.section == "reorder":
                return reorder_report(self.db)
            if self.section == "expiry":
                return expiry_report(self.db)
            if self.section == "reminders":
                shop = self.db.shop_profile().get("shop_name") or ""
                due = due_reminders(self.db, shop)
                if not due:
                    return ("Reminders: nothing is due right now. "
                            "Reminders are scheduled from the outstanding "
                            "aging (over 30 days old) and repeat only after "
                            "7 days. Use 'Open reminder list' for the full "
                            "outstanding list.\n\nNote: WhatsApp has no "
                            "safe auto-send — each reminder is one tap to "
                            "send, and sent reminders are logged so they "
                            "are not repeated.")
                lines = ["Reminders due now (tap 'Open reminder list' "
                         "to send):"]
                for r in due:
                    lines.append(f"- {r['name']}: Rs. {r['balance']:.2f} "
                                 f"({r['age_bucket']} days old)"
                                 f"{' — overdue' if r['overdue'] else ''}")
                return "\n".join(lines)
            if self.section == "insights":
                return insights_report(self.db)
            ok, why = voice_available()
            cfg = ai_settings(self.db)
            status = ollama_status(cfg["local_url"])
            local = ("Ollama: running, models: "
                     + (", ".join(status["models"]) or "none installed")
                     if status["available"] else
                     "Ollama: not running on this PC")
            label = local_ai_setup.button_label(
                local_ai_setup.detect_state(
                    local_ai_setup.find_ollama(), status["models"],
                    cfg["local_model"]))
            return ("Assistant — ask in plain words. It explains the "
                    "numbers on the other tabs and drafts orders, "
                    "reminders and summaries for review. Stock, dues, "
                    "expiry, forecast and order questions are answered "
                    "straight from your shop data — no AI download "
                    "needed.\n\n"
                    f"Local AI: {cfg['local_model']} ({local}). "
                    "Cloud fallback: Gemini API"
                    f"({'key saved' if cfg['gemini_key'] else 'no key saved'}).\n"
                    f"Voice: {why if not ok else 'available'}\n\n"
                    "Try: 'what should I order this week?' or "
                    "'which customers owe the most?'\n\n"
                    f"Tip: tap '{label}' below and BillBook installs "
                    "it for you. "
                    f"{local_ai_setup.manual_steps_text(cfg['local_model'])}")

        def _show(self, key):
            self.section = key
            self._refresh()

        def _refresh(self):
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", self._report())
            self.text.configure(state="disabled")
            if self.section == "assistant":
                self.setup_btn.configure(
                    text=local_ai_setup.button_label(
                        self._setup_state()))
                self.setup_row.pack(fill="x", pady=4)
            else:
                self.setup_row.pack_forget()

        def _copy(self):
            self.clipboard_clear()
            self.clipboard_append(self.text.get("1.0", "end"))
            messagebox.showinfo("Copied", "Report text copied.")

        def _save_provider(self, value):
            self.db.set_setting("ai_provider", value)
            self._refresh()

        def _save_key(self):
            key = self.key_entry.get().strip()
            if key:
                self.db.set_setting("ai_gemini_key", key)
                self.key_entry.delete(0, "end")
                messagebox.showinfo("Assistant", "Gemini API key saved.")
            self._refresh()

        def _setup_state(self):
            cfg = ai_settings(self.db)
            return local_ai_setup.current_state(cfg["local_model"],
                                                cfg["local_url"])

        def _setup_local_ai(self):
            import threading
            cfg = ai_settings(self.db)
            state = local_ai_setup.current_state(cfg["local_model"],
                                                 cfg["local_url"])
            if not messagebox.askyesno(
                    "Download local AI",
                    local_ai_setup.confirm_text(state,
                                                cfg["local_model"])):
                return
            self._setup_cancelled = False
            self.setup_btn.configure(state="disabled")
            self.setup_cancel.configure(state="normal")
            self.setup_bar.set(0)
            self.status.configure(text="Starting…")

            def on_status(text):
                try:
                    self.after(0, lambda t=text: self._setup_status(t))
                except Exception:
                    pass  # window closed mid-setup — nothing to show

            def on_progress(value):
                try:
                    self.after(0,
                               lambda v=value: self._setup_progress(v))
                except Exception:
                    pass

            def work():
                res = local_ai_setup.run_setup(
                    cfg["local_model"], cfg["local_url"], on_status,
                    on_progress, lambda: self._setup_cancelled)
                try:
                    self.after(0, lambda: self._setup_done(res))
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True).start()

        def _cancel_setup(self):
            self._setup_cancelled = True
            self.setup_cancel.configure(state="disabled")
            self.status.configure(text="Cancelling…")

        def _setup_status(self, text):
            self.status.configure(text=text)

        def _setup_progress(self, value):
            if value is None:
                self.setup_bar.start()
            else:
                self.setup_bar.stop()
                self.setup_bar.set(max(0.0, min(1.0, value)))

        def _setup_done(self, res):
            self.setup_btn.configure(state="normal")
            self.setup_cancel.configure(state="disabled")
            self.setup_bar.stop()
            if res["ok"]:
                self.setup_bar.set(1.0)
                # Provider flip on the GUI thread: the worker never
                # touches the database (SQLite is single-thread).
                self.db.set_setting("ai_provider", "local")
                self.prov_var.set("local")
                self.status.configure(
                    text="Local AI ready (Qwen3-4B, on this PC) — the "
                         "assistant now answers offline.")
            else:
                self.setup_bar.set(0)
                self.status.configure(text=res["error"])
            self._refresh()

        def _load_reorder(self):
            rows = reorder_suggestions(self.db)
            if not rows:
                messagebox.showinfo("Re-Order",
                                    "Nothing needs ordering today.")
                return
            self.app.show("purchases")
            pf = self.app.screens["purchases"]
            payload = [{"product_id": r["product_id"], "name": r["name"],
                        "unit": r["unit"], "qty": r["suggested_qty"],
                        "cost": r["last_rate"],
                        "gst_percent": float(self.db.get_product(
                            r["product_id"])["gst_percent"] or 0),
                        "expiry_date": ""} for r in rows]
            n = pf.prefill_items(payload)
            messagebox.showinfo(
                "Re-Order",
                f"Loaded {n} item(s) into Purchases from the forecast. "
                "Choose the supplier and save — nothing is ordered until "
                "you save it.")

        def _open_reminders(self):
            from new_features import open_outstanding_reminders_dialog
            shop = self.db.shop_profile().get("shop_name") or ""
            open_outstanding_reminders_dialog(self, self.db, shop)

        def _ask(self):
            import threading
            q = self.ask_entry.get().strip()
            if not q:
                return
            self.status.configure(text="Asking…")
            self.ask_entry.configure(state="disabled")

            def work():
                res = assistant_ask(self.db, q)
                try:
                    self.after(0, lambda: self._show_answer(q, res))
                except Exception:
                    pass  # window closed while asking — nothing to show

            threading.Thread(target=work, daemon=True).start()

        def _show_answer(self, q, res):
            self.ask_entry.configure(state="normal")
            if res.get("ok"):
                self.status.configure(
                    text=f"Answered by {res.get('provider')} "
                         f"({res.get('model')}).")
                self.text.configure(state="normal")
                self.text.delete("1.0", "end")
                self.text.insert("1.0", f"Q: {q}\n\n{res['answer']}")
                self.text.configure(state="disabled")
            else:
                self.status.configure(text="")
                messagebox.showinfo("Assistant",
                                    f"Could not answer:\n{res['error']}")

    return AIInsightsFrame
