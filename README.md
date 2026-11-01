# BillBook — Wholesale Billing App

A desktop billing application for a small Indian wholesale shop: fast counter
billing with a saved product catalog, GST invoices you can print, customer
khata (ledger), stock management, and sales reports — all offline.

Built with **Python + CustomTkinter** (dark mode default, light toggle) and
**SQLite** (Python stdlib, no server needed). Invoices are generated as
proper **PDFs** (reportlab) and printed **directly through Windows' own
print system** — pick any installed printer from a dropdown, no browser and
no Chrome extension needed.

> **Shop PC note:** this repo ships source code plus a one-click
> `build_exe.bat`. Run that batch file **once on a Windows PC** to compile
> `BillBook.exe`. A Windows `.exe` can only be built on Windows — it was
> **not** compiled or tested on Windows during development (the author works
> on Linux).

## Features

- **Reports (round 13, Nov 2026)** — sales summary export to CSV
  (summary + day-wise + GST + top products + profit by product),
  profit-by-product tab in Reports, invoice search by bill no / customer
  **and** date range, dues-reminder window with copy-ready WhatsApp text
  per customer, and barcode label sheets (Code128, 3 per row) from the
  product catalog. Negative customer balances now show as "Advance"
  instead of a negative dues figure.
- **Dashboard** — today's sales (bill count + total), pending dues, low-stock
  alerts, top-selling products of the last 7 days, total stock value.
- **Billing (multi-bill tabs)** — open several bills at once: park one
  customer's bill, serve the next, switch tabs freely. Each tab keeps its own
  customer, items, and totals until finalized or discarded.
  - Customer (required — pick from saved customers or create new) and payment
    type (**Cash / UPI / Credit**, required) are chosen first.
  - Search-as-you-type product picker, quantity, per-line discount, per-bill
    discount.
  - **Wholesale/Retail toggle** — wholesale price or retail price is applied
    automatically (defaults from the customer's type).
  - Per-line GST breakup, round-off to the nearest rupee, sequential bill
    numbers (`BB-0001`, `BB-0002`, …).
  - Keyboard shortcuts for fast counters: **F2** new bill tab, **F3** jump to
    product search, **F4** choose customer, **Enter** adds a line,
    **Tab** walks entry row → card qty → rate → discount, **Esc** clears the
    entry row (or closes the customer picker), **Ctrl+S** finalize,
    **Ctrl+P** print/preview. Every field is typeable — no mouse needed for
    a full bill.
  - **Right-side menu + keyboard travel** — the Billing/options menu sits on
    the right edge of the window. **F10** jumps focus to the menu (press
    again to jump back), **Up/Down** moves between menu items,
    **Enter** opens the highlighted screen, **Esc** returns without
    switching.
  - **Autocomplete dropdown** — typing any letter in the product search
    opens a live dropdown under the field, ranked by relevance
    (name-starts-with → name-contains → SKU match), showing name + SKU +
    price. **Up/Down** moves the highlight, **Enter** picks the highlighted
    product, **Esc** closes the dropdown, click also picks. Typing never
    loses focus.
  - **Duplicate products merge** into one line; **low-stock warnings** (⚠)
    appear on lines that would push stock to/below the threshold; inline
    warnings (not popups) flag a missing customer or payment type in the
    sticky totals footer, which always shows subtotal, GST, discount,
    round-off, and the grand total.
  - **Barcode scan → instant add** — a USB scanner types the barcode + Enter.
    If the typed text exactly matches a product's SKU/barcode
    (case-insensitive), the line is added **immediately** with qty 1
    (merging with the existing line if already on the bill) — no dropdown.
    Anything else falls back to the normal autocomplete dropdown.
  - **Repeat last bill** — one button picks a customer and reloads *their*
    most recent bill's items into a fresh tab at **current** prices (qty as
    billed), with a note showing which bill it was loaded from. Handy for
    regular weekly orders.
  - **Grid / Cards picker view** (Marg-ERP style) — the product picker has
    two views, switched with the **Grid | Cards** toggle above the tabs or
    **Ctrl+G** (choice is remembered). **Grid** is the default: the product
    grid starts **empty** — the list appears only once you start typing in
    the **"Find Name ? >>"** box underneath (matches product name *and*
    SKU, case-insensitive), and clears back to empty when the find box is
    cleared. Columns **DESCRIPTION | PACKING | STOCK | UNIT | RATE**, and an
    item-detail footer for the highlighted row showing **PurRate, M.R.P.,
    Margin % and Company** ("—" when unknown).
    **Up/Down** move the highlight once you're in the list, **Enter** (or
    **Down**) in the find box moves focus into the list with the first row
    highlighted, **Enter** on a row picks the product into the normal qty →
    rate → discount flow, **Esc** in the find box clears the filter, and
    **F3** focuses the find box. The grid shows the same low-stock ⚠ warnings billing
    already uses and follows the tab's Wholesale/Retail price mode.
    Under the grid, a **Bill lines** table (ITEM | QTY | UNIT | RATE | DISC
    | AMOUNT) shows everything added to the bill — click a row to select it
    for the existing Remove / Edit / Delete flows, double-click to edit.
    **Cards** is the original card-based line view, unchanged.
  - **Billing by boxes** — wholesale FMCG bills by boxes, so in Grid view
    the line-entry row has a **Boxes** field: enter boxes and the line qty
    becomes boxes × the product's **pack size** (pieces math, stock checks
    and line merging work exactly as with typed qty; **Enter** in the Boxes
    field adds the line). Boxes is grid-view only.
  - **Compact line cards** — bill line-item cards are two rows (name +
    low-stock badge + line total + remove on row 1; Qty / unit / Rate /
    Disc / GST entries on row 2), so more lines fit on screen. All
    behaviors are unchanged: inline editing with focus commit, click to
    select, double-click to edit, × remove button, flash on add.
  - **Marg-style sale chrome** — a compact bill header row (Customer picker
    · Payment Cash/UPI/Credit · Price Wholesale/Retail · Bill disc · **Bill
    No.** next-number preview · **Date**), and a **Last Bills** strip under
    the totals showing the 5 most recent bills as
    `customer:billno:₹amount` chips — click one to view/preview/reprint it
    (same dialog as Reprint on the Invoices screen).
- **Product catalog** — name, SKU/barcode, purchase / wholesale / retail
  price, unit (pcs, kg, bag, box, litre…), **pack size** (pieces per pack,
  e.g. 12 for a dozen-box; shown as the PACKING column in the billing
  grid), GST %, stock, low-stock threshold,
  supplier. Add/edit/delete (with validation: name required, numeric prices
  and stock; delete is blocked for products on saved bills), search,
  **bulk import/export via CSV** (`sample_products.csv` included with 14
  realistic FMCG rows). The add/edit dialog is keyboard-friendly: it opens
  with the name field focused, **Enter** saves, **Esc** closes.
- **Purchases (stock in)** — wholesale shops buy stock from suppliers, so
  there is a dedicated **Purchases** screen: pick or create a supplier (name,
  phone), enter the date and supplier invoice/ref number, then add items
  (product picker, qty, purchase cost/unit, GST%). Saving **increases
  stock**, logs the movement, and sets each product's purchase price to the
  **weighted average** of old stock and the new lot. Past purchases are
  listed with a view dialog; deleting one **reverses the stock** (with
  confirmation). Validates qty > 0 and cost ≥ 0.
- **Stock management** — dedicated Stock IN screen (qty received, note for
  supplier) and Stock OUT (damage/returns), low-stock alerts, total stock
  value, and a full movement log (audit trail).
- **Customer ledger (khata)** — per-customer outstanding dues, record
  payments received (reduces dues), dues reminder view, per-customer
  statement (bills + payments).
  - **Collect payment** — each customer row shows total outstanding; the
    dialog takes amount, date, mode (**Cash / UPI / Bank**) and a note.
    The amount **cannot exceed the outstanding dues** (partial payments are
    fine). Recording prints a small **payment receipt PDF** (A4 + thermal).
    Outstanding = credit bills − payments received − credit notes, kept
    consistent in the khata balance.
- **Invoices (PDF)** — proper GST invoice layout as a **PDF** with GST slab
  breakup (CGST/SGST), shop header, and signature lines. Reprint any past
  bill from the Invoices screen. **Bills stay editable after finalizing**:
  reopen a completed bill, change items/quantities/discounts, print the
  corrected bill — stock and khata are reversed and re-applied, and the edit
  is recorded in bill history. PDFs are saved per bill under
  `billbook_data/invoices/<bill_no>_invoice.pdf` for records.
- **Sales returns / credit notes** — the Invoices screen has a **Return**
  button per bill: a dialog lists the bill's items with billed qty and
  already-returned qty, and you enter the return qty per line (capped so the
  same item can never be returned twice). Confirming **adds the stock back**,
  creates a numbered **credit note** (`CN-0001`, …), reduces the customer's
  khata dues for credit bills, and generates a printable **credit-note PDF**
  (A4 + thermal, honoring your invoice-design settings).
- **WhatsApp bill share** — the Invoices screen has a **WhatsApp** button per
  bill: it builds a text summary (shop name, bill no/date, item lines with
  qty and amounts, total, payment type, balance due for credit bills) and
  opens `wa.me/<customer-phone>` with the message ready to send. If the
  customer has no phone saved, it prompts to add one first. Indian numbers
  are normalized automatically (10 digits → `91` prefix). No API keys, no
  extra dependencies.
- **Universal printing (no browser, no extension)** — invoices print
  **directly** through Windows' print system:
  - The Print dialog lists **all installed printers** in a dropdown (OS
    default pre-selected) plus a copies field.
  - After every saved bill, a **"Print invoice?"** offer appears (Print /
    Preview / Skip) with a "Remember my choice" option, so the counter can
    auto-print every bill.
  - Print and Preview buttons also live on the billing screen; the Invoices
    screen reprints any past bill with the same flow.
  - **Silent printing** — on Windows the bill prints with **no PDF window
    opening at all**: each page is rasterized at 203 dpi (thermal-printer
    resolution) and drawn straight to the printer, so nothing pops up on
    screen. Needs `pymupdf` + `pillow` + `pywin32` (all installed by
    `build_exe.bat`). If silent printing is unavailable, the app falls back
    to the classic Windows print verb (which may visibly open the PDF app —
    it does print), and only if that fails too does it report the failure.
  - The app **never opens the PDF on its own** when printing: on failure it
    shows the reason, the saved PDF path, and a fix hint
    ("check the default printer in Windows Settings > Printers"), with a
    manual **Open PDF** button if you want to print it by hand. Preview
    buttons still open the PDF — that's intentional.
  - On non-Windows the app honestly reports it can't print directly and
    points at the saved PDF instead of claiming the job printed.
- **Print customization** — show/hide GSTIN, item codes, discount column;
  header/footer notes; accent color; **A4 or thermal 80mm** paper; **live
  preview** before printing.
- **Invoice Design** (new sidebar screen) — make the invoice fully yours,
  with an instant live preview (renders the real PDF when PyMuPDF is
  available, otherwise a close approximation):
  - **Header**: toggle tagline / address / phone / GSTIN individually, and
    upload a shop **logo** (PNG/JPG — shown on the invoice header; stored
    safely in `billbook_data/logos/`).
  - **Title & text**: editable invoice title ("TAX INVOICE" / "BILL" /
    "RECEIPT"…), Compact / Standard / Large text size, accent color.
  - **Columns & tables**: GST slab breakup table, HSN column (uses the
    product SKU as the HSN value; A4 only — too narrow for thermal),
    discount column, item codes.
  - **Bill details**: round-off line, customer address, CREDIT — due badge,
    signature lines (A4 only).
  - **Footer**: multi-line **terms & conditions**, thank-you message
    (toggle + editable text).
  - **Paper & numbering**: default thermal 80mm (A4 switchable), default copies,
    editable invoice number **prefix** (e.g. `BB-`, `INV/`) — the next bill
    number previews live as you type.
  - Every choice saves to the database and applies to **every invoice from
    then on** — new prints, reprints, and previews. Missing settings fall
    back to the original defaults, so old databases keep working.
- **Reports** — day-wise / monthly sales totals, GST summary by slab, profit
  estimate (sale price − purchase price per line), top products.
- **Backup/restore** — one-click backup writes a timestamped `.zip`
  (`billbook_backup_YYYYMMDD_HHMMSS.zip`) with the database, all saved
  invoice PDFs and the shop logo to any folder you pick (pen drive / Drive).
  Restore accepts a `.zip` or a legacy `.db`, validates it is a BillBook
  database, and always saves a safety copy of the current data first
  (`billbook_data/backups/auto_before_restore_…db`) — then asks you to
  restart the app.
- **Automatic backup on exit** — every time the app closes, it silently
  writes a timestamped backup (`billbook_auto_backup_YYYYMMDD_HHMMSS.zip`,
  same contents as a manual backup) to the auto-backup folder, then closes
  normally. It is ON by default; toggle it or change the folder from the
  **Backup** screen ("Back up automatically every time the app closes" /
  "Choose folder…"). Default folder is `billbook_data/backups/`. Only the
  last **14** automatic backups are kept — older ones are deleted, manual
  backups are never touched.
- **Self-update from GitHub** — on startup the app quietly checks the
  public `entity-coder/billbook` repo for a newer commit (background
  thread; offline or failure = silently skipped, the app runs normally).
  If an update exists, a small non-intrusive **"⬆ Update available"**
  button appears in the sidebar — never forced, never interrupts billing.
  Clicking it asks for confirmation, downloads the new source ZIP, and
  writes an `apply_update.bat` that runs *after the app exits* (Windows
  can't overwrite a running `.exe`): it copies the new files over the app
  folder **excluding `billbook_data/`**, re-runs the PyInstaller build, and
  restarts the app. If the build fails, the old `.exe` is left untouched
  and the log is shown. `version.txt` next to the app records the running
  commit. A manual **"Check for updates"** button lives in Settings. The backup never blocks shutdown: if it fails
  (disk full, folder unreachable) the app still closes quietly.
- **Shop profile** — one-time setup for shop name, tagline, address, phone,
  GSTIN — printed on every bill header.
- **Today at a glance** — the Dashboard top row is a Marg-style summary
  strip, all computed live from the database: today's bill count + sales,
  cash in hand, debtors (customer outstanding), creditors (supplier
  outstanding), and stock value. Cash in hand = cash-book opening + cash IN
  − cash OUT. Note: bank is not tracked as a separate account yet.
- **Outstanding aging report** — new **Aging** sidebar screen: per-customer
  and per-supplier rows bucketed **1–30 / 31–60 / 61–90 / 91–120 / 121–240 /
  241+ days** by the age of the originating bill, with bucket totals and a
  grand total. **FIFO assumption:** payments are assumed to settle the
  oldest bills first — a payment against a ₹2,100 hundred-day-old bill and a
  ₹525 forty-day-old bill lands on the older bill first, so the aged rows
  reflect which bills are truly still unpaid, not a bill-by-bill settlement.
- **Item master upgrade** — products now carry **MRP** and **Company**
  (manufacturer). The add/edit dialog has both fields, the product list
  shows a computed **Margin %** column (`(wholesale − purchase) / purchase`),
  and the billing autocomplete dropdown shows the MRP next to each product.
  Both are CSV import/export columns too. Existing databases pick them up
  automatically (`mrp` = 0, company empty) — no data loss.
- **Cash Book (day book)** — new sidebar screen recording cash movement
  **outside** bills: expenses, owner drawings, salary, rent, income. Entries
  are dated IN/OUT with description + category, the list shows a running
  balance, and the opening balance is settable on the screen. Amounts must
  be > 0. Bill payments are deliberately **not** recorded here — bill cash
  stays on the bills, so nothing is double counted. Cash in hand on the
  Dashboard = this book's balance.
- **Supplier ledger (creditors)** — new **Suppliers** screen mirroring
  customer dues: each supplier's outstanding (purchases − payments made),
  a **Pay supplier** dialog (amount, date, mode Cash/UPI/Bank, note) that
  **cannot exceed the outstanding**, and a per-supplier payment history.
  Creditor totals feed the Dashboard strip and the supplier side of the
  Aging report.
- **Delivery challans** — the Invoices screen has **New challan**, and there
  is a dedicated **Challans** sidebar screen. Pick a customer, add items
  (same picker as billing), save — no GST/tax, numbered `CH-0001`, … and the
  challan prints a **CHALLAN PDF** (A4 + 80mm thermal, honoring your
  invoice-design header). **Challans do not touch stock or khata until
  converted** — each row has **Convert to bill**, which loads its items
  into a fresh billing tab; normal billing then decrements stock and
  updates khata when the bill is saved.
- **Expiry tracking** — purchase item rows have an optional **Expiry**
  (YYYY-MM-DD) field. The Stock screen shows the earliest upcoming expiry
  per product, and the Dashboard warns about stock **expiring within 60
  days** (expired lots shown in red). Kept simple: no lot-level sale
  matching.
- **Re-Order list** — a dedicated **Re-Order** sidebar screen answering
  "what do I order from which supplier today?": every product at/below its
  low-stock threshold (products with no threshold set are skipped), sorted
  by urgency (stock ÷ threshold, lowest first). Each row shows the
  suggested **order qty** (2× threshold − stock, min 1), the last
  (weighted-average) purchase rate, estimated amount, supplier name + phone,
  and nearest expiry. Select rows → **Load into Purchases** pre-fills the
  Purchases entry rows at the last purchase rate (you just pick the
  supplier and save); **Print list** makes an order-list PDF (A4 + 80mm
  thermal, honoring your invoice-design header). No database migration —
  it reuses the existing stock/threshold/supplier/cost/expiry columns.
  Keyboard friendly: arrows move, Enter toggles a row, Esc clears the
  selection; a healthy stock shows "All stock is healthy" instead of an
  empty grid.

## Deliberately out of scope (why)

- **e-Way bills** — generating an e-Way bill needs the live GST portal API
  with the shop's GST login credentials; an offline desktop app can't do
  this safely or reliably.
- **Payment-gateway / UPI integration** — collecting money online needs a
  merchant account, KYC, and settlement contracts; the app records Cash/UPI/
  Bank as *modes* of payment, but the actual transfer stays in the shop's
  UPI app.
- **ERP-to-ERP ordering** — sending purchase orders into a supplier's ERP
  system needs both sides on a shared protocol the suppliers don't have.

## How to run (developers)

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python main.py
```

Data is stored in `billbook_data/billbook.db` next to the source (or next to
`BillBook.exe` in the packaged build). To try it instantly: open **Products**
→ **Import CSV** → choose `sample_products.csv`, then open **Billing**.

## Build the Windows .exe (shop PC)

1. On the **Windows** shop PC, install Python 3.10+ from python.org (tick
   **"Add python.exe to PATH"** during setup).
2. Copy this project folder to the shop PC and double-click **`build_exe.bat`**.
   It installs `customtkinter` + `pyinstaller` + `reportlab` + `pywin32` +
   `pymupdf` + `pillow` and compiles the app — takes a few minutes.
   (`pymupdf`/`pillow` power the silent printing: bills print with no PDF
   window opening.)
3. Done: `dist\BillBook.exe` is the standalone app. Copy it to the Desktop.
   Afterwards the shop PC **never needs Python again**.
4. Keep the `billbook_data` folder next to the `.exe` — that is your data.
   Use the in-app **Backup** screen regularly (pen drive / Drive folder).

## Run with Docker (optional)

Handy on Linux dev machines or anywhere without a Python install — the
Windows `.exe` above is still the recommended path for the shop PC
(Docker Desktop on Windows needs an extra X server like VcXsrv/X410 for
GUI apps, so the `.exe` is simpler there).

On Linux:

```bash
docker compose build
xhost +local:docker      # allow the container to use your display (per session)
docker compose up        # launches BillBook in a window
```

Data (SQLite db + invoice PDFs) lives in the `billbook_data` Docker volume,
so bills survive container rebuilds. To start fresh, `docker volume rm
billbook_data`. After code changes, rebuild with `docker compose build`.

## Project structure

| File | What it does |
|---|---|
| `main.py` | Entry point — loads theme, opens the app window |
| `db.py` | SQLite schema + all data access: products, customers/khata, bills, bill items, payments, stock movements, bill history, suppliers, purchases, returns/credit notes, cash book, delivery challans, supplier payments, aging (FIFO), expiry; billing math (`compute_totals`) |
| `invoices.py` | Invoice generation as **PDF** (reportlab, A4 + 80mm thermal) + print orchestration: builds the PDF per bill, saves it under `billbook_data/invoices/` |
| `printing.py` | Universal print engine: PDF rendering, printer enumeration (`win32print` on Windows), direct OS printing via `os.startfile(path, "print")`, graceful PDF-only fallback elsewhere |
| `ui.py` | Core screens: dashboard, billing (multi-tab), products, stock, customers, invoices, reports, invoice design, backup, settings |
| `print_ui.py` | Print offer dialog, print settings dialog, invoice live preview, accent palette (split out of `ui.py` to keep modules small) |
| `purchases_ui.py` | Purchases screen: supplier picker, purchase entry, purchase history |
| `returns_ui.py` | Sales-return dialog (credit notes) + WhatsApp bill sharing |
| `shop_ui.py` | Marg-parity screens: Cash Book (day book), delivery challans (+ challan dialog), Suppliers ledger, Outstanding aging report, Re-Order list |
| `grid_billing.py` | Marg-style sale-entry grid for billing: DESCRIPTION/PACKING/STOCK/UNIT/RATE treeview, "Find Name ? >>" live filter, item-detail footer (PurRate/MRP/Margin%/Company), bill-lines table (ITEM/QTY/UNIT/RATE/DISC/AMOUNT) with selection syncing, Boxes→pieces helper, view toggle wiring; data-only panel that hands picks back to the billing flow (split out of `ui.py` to keep modules small) |
| `backup.py` | Backup engine + Backup & restore screen: manual timestamped zips, restore with safety copy, silent auto-backup on exit with 14-backup retention |
| `updater.py` | Self-update from GitHub: background latest-commit check, source-ZIP download + staging, `apply_update.bat` generator (copies new files excluding `billbook_data/`, rebuilds the `.exe` after exit, restarts) |
| `version.txt` | Commit SHA of the running build — written at push/build time; the updater compares it with GitHub's latest |
| `sample_products.csv` | 14 realistic Indian wholesale FMCG rows for demo import |
| `build_exe.bat` | One-click Windows build (PyInstaller) |
| `requirements.txt` | `customtkinter`, `reportlab` (PDF invoices) |

## How billing math works

- **Line total** = (qty × rate − line discount) + GST on that amount.
  Line discounts are pre-GST (standard practice).
- **Bill discount** is a flat ₹ amount applied *after* GST, then the payable
  is rounded to the nearest rupee (round-off line shown on the bill).
- **Credit** bills add the grand total to the customer's khata balance;
  recording a payment reduces it; a credit note (sales return) on a credit
  bill reduces it too. Outstanding = credit bills − payments − credit notes.
- **Purchases** increase stock and re-price inventory to the weighted
  average of old stock and the new lot; deleting a purchase reverses the
  stock (the averaged cost is left as-is).
- Finalizing a bill decrements stock and writes stock movements; editing a
  finalized bill reverses the old stock/credit effect first, then re-applies
  the new one, logging everything to bill history.

## Limitations (honest)

- **Direct printing was developed and tested on Linux only** — the print
  pipeline degrades gracefully (saves/opens the PDF) where `win32print` is
  unavailable. On the Windows shop PC it uses the OS print path
  (`os.startfile(path, "print")`), which was **not tested against a real
  printer**; verify with one test print on the shop's printer first.
- **Barcode scanning** works with any USB scanner that types the barcode +
  Enter (instant-add on exact SKU match). There is no *camera* scanning —
  that would need OpenCV/a camera dependency the shop PC doesn't have.
- Invoices print via the OS print dialog (spooler), not raw thermal-printer
  ESC/POS commands — fine for A4 and 80mm paper, but no raw-printer control.
- Single-user, single-PC: SQLite lives in one file; no multi-counter sync.
- Profit estimate is sale − purchase per line only; it ignores overheads,
  wastage, and purchase-price changes over time.
- Every bill requires a saved customer (walk-in bills must pick one) — dues
  need a customer record to track against.

## Interview notes

**What is this project?** BillBook is an offline-first desktop billing app
for a wholesale shop: product catalog, fast multi-tab billing with GST,
customer khata, stock management, printable GST invoices, reports, and
one-click backup — packaged as a single Windows `.exe` so a non-technical
shop owner can run it with zero setup.

**Why CustomTkinter instead of Tkinter/PyQt/Electron?** Plain Tkinter looks
dated and styling it is painful; PyQt licensing is murky for a sellable app
(PyQt is GPL/commercial, PySide is LGPL but heavier); Electron would mean
shipping a whole browser for a local CRUD app. CustomTkinter gives a modern
dark/light UI on top of stdlib Tkinter with one `pip install`, and
PyInstaller bundles it into a single `.exe` — the shop PC installs nothing.

**Why SQLite instead of MySQL/Postgres?** The shop has one PC and no IT
staff. SQLite is a single file: zero server setup, zero maintenance, and
backup is literally copying a file. The trade-off is no multi-user sync —
accepted deliberately, because the requirement is one billing counter, and
complexity that the user can't maintain is a liability, not a feature.

**Why generate invoices as PDF + direct OS printing instead of HTML in the
browser?** The original build opened a self-contained HTML invoice in the
browser for Ctrl+P printing. That worked, but it added a manual step at the
counter and depended on the browser's print dialog every time. The current
flow renders the same invoice (shop header, GST slabs, totals) to PDF with
reportlab — A4 and 80mm thermal layouts — and on Windows hands it to the OS
print spooler via `os.startfile(path, "print")`, with the printer chosen
from `win32print`'s installed-printer list (temporarily set as default so
the call targets the right device, then restored). No browser, no Chrome
extension, no raw ESC/POS driver work. The honest trade-off: direct printing
was only exercised on Linux in "PDF saved" mode — the Windows print path
needs one real test print on the shop's printer. And `print_pdf` never claims
success it didn't get: on failure the app opens the PDF for manual printing.

**Keyboard-first billing UX:** counters bill fast, so the billing screen is
driven by keys — F1 shortcut help, F2 new tab, F3 focus search (opens the
product list), F4 customer picker (Esc closes it), F6 toggle
Wholesale/Retail prices, F8 jump to bill discount, F9 repeat last bill,
Enter adds a line then chains each card's qty → rate → discount fields and
re-opens the product list for the next item, Tab walks fields, Up/Down move
in the dropdown, Delete removes the selected bill line, End opens the
finish-bill dialog (Save is default, Enter confirms), Insert adds a new
product, PgUp/PgDn switch bill tabs, Ctrl+S or Ctrl+Enter saves, Ctrl+P
prints, Esc closes dropdowns/clears the entry row. End/Delete/Insert never
hijack typing — inside a text field they behave normally. The focused
field gets an accent border so the cashier always knows where they are, and
committing a card field (Enter or focus-out) updates the line total in place
without rebuilding the card — focus is never stolen mid-flow. Shortcut hints
are printed on the buttons themselves and in a footer label. Inline warnings
(missing customer) live in the sticky totals footer instead
of popping dialogs mid-flow. Small touches with real counter value: adding
the same product twice merges the line instead of duplicating it, and a ⚠
marker appears on lines that would push stock to or below the low-stock
threshold.

**Product cards:** each bill line is its own bordered card, not a table row —
kept compact (two rows: name + low-stock badge + line total + × remove on
row 1; Qty / unit / Rate / Disc / GST entries on row 2) so more lines fit on
screen. A plain typed quantity field (no +/− steppers), editable rate and
line-discount fields right on the card, bold line total. Clicking a card
selects it (accent border); double-click opens the full line editor; adding
a duplicate merges into the existing card and flashes it so the cashier sees
where it went. An empty bill shows a clean "Bill is empty" placeholder.

**Grid / Cards product picker:** the shop's previous software (Marg ERP)
shows products in a grid — DESCRIPTION | PACKING | STOCK | UNIT | RATE —
with a "Find Name ? >>" type-to-filter box, so the billing screen offers
that same view alongside the original cards. The grid is a separate module
(`grid_billing.py`) on purpose: it's a data-only panel (treeview + find box
+ detail footer) that hands the picked product back to the existing billing
flow via `on_add`, so the qty → rate → discount chain, line merging,
low-stock checks and shortcuts are shared, not duplicated. The grid starts
empty by design (the user's ask — no wall of products on load) and lists
matches only while the find box has text. PACKING comes
from the new `pack_size` column on products (pieces per pack, default 1,
migrated additively like mrp/company before it); RATE follows the tab's
Wholesale/Retail mode; the find box filters on name *and* SKU
case-insensitively and selects the first match Marg-style; the footer reads
PurRate/MRP/Margin%/Company from columns that already existed. View choice
is a per-tab state with a frame-level toggle + Ctrl+G, persisted in
settings. The trade-off: two picker UIs to maintain instead of one — kept
because the user explicitly asked for the Marg-style grid, and the cards
view stays for anyone who prefers it. Follow-up fixes after real counter
use: (1) the grid hid the bill lines entirely, so a **Bill lines**
treeview (ITEM | QTY | UNIT | RATE | DISC | AMOUNT) was added under the
grid — row selection syncs `card_sel`, so the existing Remove / Edit /
Delete / double-click-edit flows work unchanged in grid view; (2) a
**Boxes** entry in grid view computes qty = boxes × pack_size for
wholesale box billing (pieces math, stock checks and merging unchanged);
(3) Escape in the grid find box no longer wipes the line-entry row — the
app-level Escape handler returns early when focus is inside the find entry
(CTkEntry wraps a real tk Entry child, so the check compares widget *paths*,
not widget identity), letting the grid's own handler clear just the filter.
editor; adding a duplicate merges into the existing card and flashes it so
the cashier sees where it went. An empty bill shows a clean "Bill is empty"
placeholder.

**Invoice design system:** every visual/textual part of the invoice is a
database setting, edited in the **Invoice Design** sidebar screen with a
live preview. The preview renders the *actual* PDF via PyMuPDF when it's
installed (zero new hard dependency — it falls back to a widget
approximation, the same renderer the Print dialog uses). Toggles cover
tagline/address/phone/GSTIN, GST slab table, HSN column (SKU doubles as
the HSN value — Indian retail shops commonly print SKU in that column),
round-off line, customer address, the CREDIT — due badge, and signature
lines; text fields cover the invoice title, multi-line terms & conditions,
and the thank-you message; Compact/Standard/Large scale the PDF font
sizes; the logo is uploaded once, copied into `billbook_data/logos/`, and
drawn in the PDF header with graceful fallback if the file goes missing.
The 80mm thermal layout hides what can't fit (HSN column, signature
lines) rather than breaking the layout. Backward compatibility is by
construction: `print_prefs()` fills missing keys with the old defaults, so
an existing `billbook.db` from the shop PC keeps working, and the invoice
number prefix (`invoice_number_prefix`, default `BB-`) only affects newly
generated numbers — old bills keep theirs.

**Key design decisions in the code:**
- *Billing math lives in one place* (`DB.compute_totals`): line discounts
  pre-GST, flat bill discount post-GST, round to nearest rupee. Every screen
  (billing tab, edit flow, invoice) uses the same function, so totals can't
  drift between screens.
- *Draft bill tabs are in-memory; only finalized bills touch the DB.* This
  makes "park a bill, serve the next customer" trivial and discard free —
  nothing half-written pollutes stock or khata.
- *Editing a finalized bill reverses then re-applies.* Stock and credit
  balance are undone from the old version before the new version is written,
  and each step is logged to `bill_history` — so the audit trail survives
  corrections instead of being silently rewritten.
- *Settings are a key/value table*, not a config file: the shop owner edits
  them in the Settings screen and they apply immediately, including print
  preferences with a live preview.
- *Bill lines are cards, not table rows.* A ttk Treeview was cheaper, but at a
  busy counter the cashier needs big touch/click targets and per-line editing
  without opening dialogs — so each line is a bordered `CTkFrame` card with
  a typed quantity field (steppers were removed: typing is faster and keeps
  the flow keyboard-only), rate/discount entries (committed on Enter /
  focus-out, with revert-on-invalid and in-place total refresh so focus is
  never stolen), and remove button. Selection state is a plain index in
  the tab's widget dict; merge-flash is a 500 ms `after()` callback guarded
  by `winfo_exists()` so tab switches can't crash it.
- *Automatic on-exit backup.* Closing the window (`WM_DELETE_WINDOW`) runs a
  silent backup first — same zip contents as a manual backup, written to a
  configurable folder (default `billbook_data/backups/`), with a 14-file
  retention policy that only prunes files with the auto-backup filename
  prefix so manual backups are never deleted. The whole path is wrapped so
  it can never block shutdown: no dialogs, commit failures and missing
  folders are caught, and a bad custom folder falls back to the default.
  It's a user setting (`auto_backup_on_exit`), not hardcoded, because the
  shop owner should be able to turn it off — e.g. on a metered machine.
- *Self-update that respects the counter.* A billing PC can't afford a
  surprise restart mid-sale, so the update check runs in a daemon thread
  2.5 s after startup (never blocks the UI; offline = silently skipped)
  and the only UI is a small sidebar badge. Applying it is a two-phase
  dance because Windows can't overwrite a running `.exe`: Python downloads
  + stages the source ZIP and writes `apply_update.bat`, then quits; the
  bat waits on the PID, `robocopy`s the new tree over the app folder
  *excluding* `billbook_data/`, re-runs the exact PyInstaller command, and
  only swaps the exe on build success — a failed build leaves the old
  version working and opens the log. `version.txt` is the whole versioning
  scheme: one SHA, compared against the GitHub API, no auth needed.
- *Autocomplete that doesn't fight the keyboard.* The product search shows
  a live dropdown ranked by relevance (name-starts-with, then contains,
  then SKU) rather than DB order. Arrow keys move a highlight index,
  Enter picks, Esc closes — all handled in widget-level bindings that
  return `"break"` so they never leak into the app-level shortcuts, and
  the dropdown never takes focus away from typing. Keeping "Enter adds
  top match" when the dropdown is closed preserves the old fast path.

**Trade-offs / what I'd do differently:** I'd add a proper migration system
if the schema ever changes (currently `CREATE TABLE IF NOT EXISTS` only);
I'd move invoice templates to user-editable files for shops that want
custom layouts; and for multiple counters I'd replace SQLite with a small
local server (e.g. FastAPI + SQLite/Postgres) rather than bolting sync onto
a file.

**How I'd extend it:** UPI QR code on the invoice for the grand total,
per-day cash-register closing (denomination count), and GST filing export
(GSTR-1 style CSV of outward supplies by slab — the `gst_summary` query
already computes the needed numbers). (Barcode scan-to-add and the supplier
purchase ledger were on this list — both are now built.)

**Shop-floor features (delegated round):** the shop owner asked for "whatever
a shop needs to make billing easy", so six features were added in one round:
(1) *Barcode scan → instant add* — USB scanners act as keyboards (barcode +
Enter), so the billing search checks `find_by_sku()` for an exact
case-insensitive match on Return *before* the autocomplete path and adds
qty 1 immediately (merging with the existing line), clearing the field for
the next scan; non-matches fall through to the dropdown. (2) *Purchases* —
a new screen + `suppliers`/`purchases`/`purchase_items` tables; saving a
purchase increases stock and re-prices inventory to the weighted average of
old and new stock, and deleting a purchase reverses the stock (the averaged
cost is deliberately left as-is — reversing it exactly would need full lot
history). (3) *Sales returns* — `returns`/`return_items` tables; per-line
return qty is capped at billed-minus-already-returned (tracked in
`return_items`), stock goes back up, credit bills reduce the khata balance,
and a numbered credit note (`CN-0001`…) prints via a credit-note PDF that
reuses the invoice Platypus layout with a CREDIT NOTE title. (4) *Dues
collection* — the khata dialog now takes date + mode (Cash/UPI/Bank, stored
in a migrated `payments.mode` column), refuses amounts above the
outstanding dues, and prints a payment-receipt PDF; outstanding stays
consistent by construction (credit bills add, payments and credit notes
subtract). (5) *Repeat last bill* — loads the customer's latest bill into a
fresh tab at current prices with a "loaded from bill X" note, for regular
weekly orders. (6) *WhatsApp share* — builds a text bill summary and opens
`wa.me/<normalized-IN-number>?text=…` via `webbrowser` (no API keys);
missing phone numbers prompt to add one first. To keep `ui.py` under the
push size limit, the print dialogs moved to `print_ui.py`, purchases to
`purchases_ui.py`, and returns/WhatsApp to `returns_ui.py` — pure moves plus
the new code, verified by 25 headless Xvfb tests covering every feature
end-to-end.

**Marg-ERP parity round (7 features):** the shop owner showed photos of the
shop's current software (Marg ERP) and asked for the missing pieces, so seven
features were added: (1) *Today-at-a-glance strip* — the Dashboard now shows
bills + sales today, cash in hand (from the cash book), debtors, creditors,
and stock value, all live from the DB; bank is noted as untracked since no
bank account is modelled. (2) *Outstanding aging* — a new **Aging** screen
with the classic 1–30 … 241+ day buckets for customers and suppliers; ages
come from the originating bill's date and **payments settle the oldest
bills first (FIFO)**, implemented in `DB._allocate_fifo` — this is an
assumption, not a ledger link: BillBook doesn't tie individual payments to
specific bills, so FIFO is the documented convention. (3) *Item master* —
`mrp` and `company` columns added via guarded `ALTER TABLE` in `_migrate`
(the same pattern `payments.mode` used), wired into the product dialog,
a computed Margin % column, billing autocomplete, and CSV import/export;
old databases get `mrp=0` / empty company. (4) *Cash book* — a **Cash Book**
screen with dated IN/OUT entries, categories, running balance, settable
opening balance, and amount > 0 validation; it tracks **non-bill cash only**
so cash sales are never double counted, and the Dashboard's cash-in-hand
reads from it. (5) *Supplier ledger* — `supplier_payments` table, a
**Suppliers** screen with per-supplier outstanding, a Pay-supplier dialog
capped at the outstanding, and payment history; feeds the Dashboard and the
creditor side of aging. (6) *Delivery challans* — `challans` /
`challan_items` tables numbered `CH-0001`…, a **Challans** screen plus a
New-challan button on Invoices, a no-GST challan PDF (A4 + thermal) reusing
the Platypus invoice patterns, and **Convert to bill** which loads the items
into a billing tab; challans move no stock/khata until the bill is saved.
(7) *Expiry tracking* — optional `purchase_items.expiry_date` (guarded
ALTER), earliest-expiry column on Stock, and a 60-day near-expiry warning
on the Dashboard; deliberately lot-agnostic (no per-sale lot matching).
One real bug was caught by the headless tests: converting a challan
switched to the billing screen — which destroys the challans frame — then
called `self.refresh()` on the dead widget; the mark-converted write was
moved before the screen switch. To keep `ui.py` under the 128 KB push-file
limit, the parity screens went into a new `shop_ui.py` module and `ui.py`
only gained lazy imports plus small dashboard/products/stock/invoices edits.
**Out of scope, with reasons:** e-Way bills (needs live GST portal API +
shop login), payment-gateway/UPI integration (needs merchant account/KYC),
ERP-to-ERP ordering (suppliers aren't on a shared protocol). Verified by 14
headless checks: py_compile of all modules, DB-level aging/FIFO/cash/supplier/
challan/expiry math, old-DB migration, A4 + thermal challan PDFs, and a
full Xvfb GUI run showing every screen including the convert-to-bill flow.
(8) *Re-Order list* — no schema change at all: `reorder_products()` in
`db.py` queries `stock <= low_stock_threshold AND low_stock_threshold > 0`
and sorts in Python by urgency (stock ÷ threshold, lowest first — SQL could
sort it too, but the division-by-zero guard reads cleaner in Python).
Suggested order qty is `max(1, 2×threshold − stock)` — a simple heuristic
that refills to twice the threshold; it's deliberately not a demand forecast
(it would need sales velocity, lead time, seasonality). The screen reuses
`purchases_ui.prefill_items()` instead of duplicating the entry-row logic,
so "Load into Purchases" just hands off and the normal save path updates
stock and weighted-average cost. Supplier phone comes from a
`get_supplier_by_name()` exact-match lookup because the product `supplier`
field is free text. Verified by 32 headless checks: urgency sort, order-qty
math (including negative stock and stock == threshold), threshold-0
exclusion, Enter/Esc keyboard toggles, prefill payload, A4 + thermal PDFs,
and the empty-state message.
(9) *Marg-style grid billing* — new `grid_billing.py` module (the product
grid, find box, detail footer, bill-lines table, and the Last-Bills/header/
boxes chrome helpers all live here so `ui.py` stays under the 128 KB
push-file limit). The grid starts **empty** — `refresh()` sets `_shown = []`
on an empty query and filters name+SKU otherwise; pressing Enter in the
find box focuses the treeview (first row highlighted) instead of picking,
so arrows move and Enter picks. The bill-lines `ttk.Treeview` is the grid
view's read-out of `tab.items`; row selection writes `w["card_sel"]` so the
existing remove/edit/Delete/double-click flows work unchanged, and
`set_lines` restores selection when valid. Boxes billing multiplies by the
product's `pack_size` (already in the schema — no migration); pieces math,
stock checks and line merging are untouched. Compact cards keep every
behavior (inline edit, select, double-click, ×, flash) with tighter
two-row layout.
(10) *Silent printing* — `printing.silent_print_pdf()` rasterizes each PDF
page with PyMuPDF at 203 dpi (thermal resolution), converts to a PIL image
(normalizing gray/CMYK → RGB, dropping alpha), and draws it to the printer
device context via `win32ui` — no PDF viewer window ever opens. Windows +
pywin32 + fitz + PIL are all required; any missing piece returns
`(False, reason)` instead of raising. `print_pdf()` tries silent first,
then the legacy `os.startfile(path, "print")` verb as an emergency backup
(it does print, but may visibly open the PDF app), and only on total
failure returns `(False, reason + saved path + fix hint)` — nothing ever
auto-opens on the print path; the Print dialog offers a manual "Open PDF"
button instead. `build_exe.bat` installs `pymupdf` + `pillow` and passes
`--hidden-import fitz` to PyInstaller. Verified headless: graceful
`(False, …)` on Linux, no `open_pdf` call on any print path (monkeypatched),
fallback order silent → legacy → fail, and preview paths still open.
