"""
Vyro — printing.py
Universal print system. No browser, no Chrome extension.

Pipeline: invoice data -> reportlab PDF -> the OS's own print path.
* PDF generation works on any OS (A4 + 80mm thermal layouts).
* On Windows, installed printers are enumerated with win32print and the PDF
  is sent to the chosen printer through os.startfile(path, "print") — the
  same "right-click -> Print" action a user can do by hand.
* Anywhere else (or if printing fails), the app saves/opens the PDF instead
  of pretending the job reached a printer. Callers get an honest
  (ok, message) result and can show it to the user.
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from db import data_dir, DB


# ---------------------------------------------------------------------------
# Rupees in PDFs
# ---------------------------------------------------------------------------
_FONT_NAME = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_HAS_RUPEE = False


def _register_rupee_font():
    """Try to register a TTF that contains the ₹ glyph (DejaVu / Nirmala).
    Falls back to 'Rs.' text when none is found."""
    global _FONT_NAME, _FONT_BOLD, _HAS_RUPEE
    candidates = [
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        os.path.expanduser("~/.fonts/DejaVuSans.ttf"),
        # Windows
        r"C:\Windows\Fonts\Nirmala.ttf",
        r"C:\Windows\Fonts\DejaVuSans.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    bold_map = {
        "DejaVuSans.ttf": "DejaVuSans-Bold.ttf",
        "Nirmala.ttf": "NirmalaB.ttf",
    }
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            pdfmetrics.registerFont(TTFont("Vyro", path))
            bold_path = path
            for suffix, bold_suffix in bold_map.items():
                if path.endswith(suffix):
                    cand = path[: -len(suffix)] + bold_suffix
                    if os.path.isfile(cand):
                        bold_path = cand
                    break
            pdfmetrics.registerFont(TTFont("Vyro-Bold", bold_path))
            _FONT_NAME, _FONT_BOLD, _HAS_RUPEE = "Vyro", "Vyro-Bold", True
            return
        except Exception:
            continue


_register_rupee_font()


def money(n):
    """Currency string that always renders in the generated PDF."""
    v = float(n)
    if _HAS_RUPEE:
        return f"\u20b9{v:,.2f}"
    return f"Rs. {v:,.2f}"


# ---------------------------------------------------------------------------
# Printer enumeration (Windows)
# ---------------------------------------------------------------------------
def _win32print():
    """Return the win32print module, or None outside Windows / when
    pywin32 is not installed."""
    if sys.platform != "win32":
        return None
    try:
        import win32print
        return win32print
    except ImportError:
        return None


def list_printers():
    """Names of installed printers. Empty list on non-Windows or on error —
    callers should treat that as 'no printer choice available'."""
    wp = _win32print()
    if wp is None:
        return []
    try:
        flags = wp.PRINTER_ENUM_LOCAL | wp.PRINTER_ENUM_CONNECTIONS
        return sorted(p[2] for p in wp.EnumPrinters(flags) if p[2])
    except Exception:
        return []


def get_default_printer():
    wp = _win32print()
    if wp is None:
        return ""
    try:
        return wp.GetDefaultPrinter()
    except Exception:
        return ""


def print_fail_text(msg, pdf_path):
    """User-facing text for a failed direct print.

    States the reason, where the PDF was saved, and a one-line fix hint.
    Never opens anything — the caller shows this text and lets the user
    decide (e.g. via an "Open PDF" button).
    """
    if sys.platform == "win32":
        hint = ("Check: a default printer is set in Windows Settings > "
                "Printers, and a PDF reader is installed.")
    else:
        hint = ("Check: a default printer is set and a PDF viewer is "
                "installed.")
    return f"{msg}\n\nPDF saved at: {pdf_path}\n{hint}"


def silent_print_pdf(pdf_path, printer=None, copies=1):
    """Print a PDF directly WITHOUT opening any viewer window.

    Windows-only. Rasterizes each page with PyMuPDF at 203 dpi (standard
    thermal-printer resolution) and draws the bitmaps straight to the
    printer device context via win32ui — the PDF app is never involved.

    Returns (ok, message). Never raises and never opens the PDF in a
    viewer; on any failure ok is False with a reason.
    """
    pdf_path = str(pdf_path)
    if sys.platform != "win32":
        return False, "Silent printing needs Windows."
    try:
        try:
            import pymupdf as fitz  # PyMuPDF (new package name)
        except ImportError:
            import fitz  # PyMuPDF (legacy package name)
        from PIL import Image, ImageWin
        import win32print
        import win32ui
    except Exception as e:
        return False, f"Silent printing unavailable ({e})."
    copies = max(int(copies or 1), 1)
    try:
        printer_name = printer or win32print.GetDefaultPrinter()
    except Exception as e:
        return False, f"Silent print failed: no default printer ({e})."
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return False, f"Silent print failed: cannot read PDF ({e})."
    try:
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        try:
            for _ in range(copies):
                hdc.StartDoc("Vyro")
                try:
                    for page in doc:
                        pix = page.get_pixmap(dpi=203)
                        if pix.n != 3:  # gray / CMYK -> RGB
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        if pix.alpha:
                            pix = fitz.Pixmap(pix, 0)
                        img = Image.frombytes(
                            "RGB", [pix.width, pix.height], pix.samples)
                        hdc.StartPage()
                        try:
                            pw = hdc.GetDeviceCaps(8)    # HORZRES
                            ph = hdc.GetDeviceCaps(10)   # VERTRES
                            iw, ih = img.size
                            scale = min(pw / iw, ph / ih)
                            dw, dh = int(iw * scale), int(ih * scale)
                            ImageWin.Dib(img).draw(
                                hdc.GetHandleOutput(), (0, 0, dw, dh))
                        finally:
                            hdc.EndPage()
                finally:
                    hdc.EndDoc()
        finally:
            hdc.DeleteDC()
    except Exception as e:
        return False, f"Silent print failed: {e}."
    finally:
        doc.close()
    return True, f"Sent to printer '{printer_name}'."


def print_pdf(pdf_path, printer=None, copies=1):
    """Send a PDF to a printer via the OS.

    Tries the silent path first (rasterize + draw to the printer DC — no
    viewer window ever opens). If silent printing is unavailable, falls
    back to the legacy ``os.startfile(path, "print")`` verb on Windows
    (this hands the file to the PDF app, which may open visibly — kept as
    an emergency backup because it does print).

    Returns (ok, message). On total failure ok is False and the message
    carries the reason, the saved PDF path, and a fix hint. This function
    never opens the PDF itself.
    """
    pdf_path = str(pdf_path)
    ok, msg = silent_print_pdf(pdf_path, printer=printer, copies=copies)
    if ok:
        return True, msg
    detail = msg
    if sys.platform == "win32":
        ok2, msg2 = _startfile_print(pdf_path, printer=printer,
                                     copies=copies)
        if ok2:
            return True, msg2
        detail = f"{msg} Backup print also failed: {msg2}"
    return False, print_fail_text(detail, pdf_path)


def _startfile_print(pdf_path, printer=None, copies=1):
    """Legacy Windows backup: ``os.startfile(path, "print")``.

    Hands the file to the registered PDF app, which may open visibly.
    Returns (ok, message).
    """
    pdf_path = str(pdf_path)
    wp = _win32print()
    if wp is None:
        return False, "pywin32 is not installed."
    copies = max(int(copies or 1), 1)
    try:
        # Temporarily make the chosen printer the default so
        # os.startfile(path, "print") targets it, then restore.
        restore = None
        if printer:
            try:
                current = wp.GetDefaultPrinter()
            except Exception:
                current = None
            if current and current != printer:
                wp.SetDefaultPrinter(printer)
                restore = current
        try:
            for _ in range(copies):
                os.startfile(pdf_path, "print")
        finally:
            if restore:
                try:
                    wp.SetDefaultPrinter(restore)
                except Exception:
                    pass
        return True, f"Sent to printer '{printer or 'default'}'."
    except Exception as e:
        return False, f"Print command failed ({e})."


def open_pdf(pdf_path):
    """Open the PDF in the default viewer. Returns True on best effort."""
    pdf_path = str(pdf_path)
    try:
        if sys.platform == "win32":
            os.startfile(pdf_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", pdf_path], check=False)
        else:
            subprocess.run(["xdg-open", pdf_path], check=False)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# PDF invoice generation (reportlab)
# ---------------------------------------------------------------------------
def invoices_dir() -> Path:
    d = data_dir() / "invoices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slabs(items):
    """GST breakup: slab -> [taxable, gst]."""
    out = {}
    for it in items:
        slab = float(it.get("gst_percent", 0) or 0)
        taxable = max(float(it["qty"]) * float(it["price"])
                      - float(it.get("line_discount", 0) or 0), 0.0)
        gst = taxable * slab / 100.0
        out.setdefault(slab, [0.0, 0.0])
        out[slab][0] += taxable
        out[slab][1] += gst
    return out


def _story(bill, items, profile, prefs, narrow):
    """Build the Platypus story (shared by A4 + thermal)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (HRFlowable, Paragraph, Spacer, Table,
                                    TableStyle)

    accent = prefs.get("accent", "#1f6f43") or "#1f6f43"
    accent_c = colors.HexColor(accent)
    dark = colors.HexColor("#222222")
    grey = colors.HexColor("#777777")

    # Font-size preset (Compact / Standard / Large)
    fscale = {"compact": 0.85, "standard": 1.0,
              "large": 1.18}.get(prefs.get("font_size", "standard"), 1.0)
    fs = round((8 if narrow else 10) * fscale)        # base font size
    fs_title = round((13 if narrow else 20) * fscale)
    fs_h = round((10 if narrow else 12) * fscale)

    def P(text, size=fs, bold=False, color=dark, align=TA_LEFT, space=2):
        return Paragraph(
            text, ParagraphStyle(
                "s", fontName=_FONT_BOLD if bold else _FONT_NAME,
                fontSize=size, leading=size * 1.3, textColor=color,
                alignment=align, spaceAfter=space))

    def _logo_image():
        """Shop logo scaled to fit the header, or None (missing/unreadable)."""
        from reportlab.lib.units import mm
        from reportlab.platypus import Image as RLImage
        p = prefs.get("logo_path") or ""
        if not p or not os.path.isfile(p):
            return None
        try:
            img = RLImage(p)
            max_h = 16 * mm if narrow else 26 * mm
            iw, ih = float(img.imageWidth), float(img.imageHeight)
            if ih <= 0:
                return None
            img.drawHeight = max_h
            img.drawWidth = iw * max_h / ih
            return img
        except Exception:
            return None

    story = []
    # -- shop header -----------------------------------------------------
    head_lines = [P(profile.get("shop_name") or "Vyro Shop",
                    size=fs_title, bold=True, color=accent_c,
                    align=TA_CENTER, space=1)]
    if prefs.get("show_tagline", True) and profile.get("shop_tagline"):
        head_lines.append(P(profile["shop_tagline"], align=TA_CENTER,
                            space=1))
    if prefs.get("show_address", True) and profile.get("shop_address"):
        head_lines.append(P(profile["shop_address"], color=grey,
                            align=TA_CENTER, space=1))
    if prefs.get("show_phone", True) and profile.get("shop_phone"):
        head_lines.append(P(f"Phone: {profile['shop_phone']}", color=grey,
                            align=TA_CENTER, space=1))
    if prefs.get("show_gstin") and profile.get("shop_gstin"):
        head_lines.append(P(f"GSTIN: {profile['shop_gstin']}", color=grey,
                            align=TA_CENTER, space=1))
    if prefs.get("header_note"):
        head_lines.append(P(prefs["header_note"], align=TA_CENTER, space=1))
    logo = _logo_image()
    if logo is not None:
        # Logo left, shop block right (top-aligned, centered text).
        story.append(Table([[logo, head_lines]],
                           colWidths=[logo.drawWidth,
                                      _usable_width(narrow) - logo.drawWidth]))
    else:
        story.extend(head_lines)
    story.append(HRFlowable(width="100%", thickness=2.5, color=accent_c,
                            spaceAfter=6, spaceBefore=4))

    # -- invoice title ----------------------------------------------------
    title = prefs.get("invoice_title", "TAX INVOICE") or "TAX INVOICE"
    story.append(P(title, size=fs_h + 2, bold=True, color=accent_c,
                   align=TA_CENTER, space=6))

    # -- bill meta --------------------------------------------------------
    cust = bill.get("customer_name") or "Walk-in"
    show_cust_addr = prefs.get("show_customer_address", True)
    pay_line = f"<b>Payment:</b> {bill.get('payment_type', '')}"
    if prefs.get("show_payment_badge", True) \
            and bill.get("payment_type") == "Credit":
        pay_line += "  <b><font color='#b3261e'>CREDIT — due</font></b>"
    addr_line = (f"<b>Address:</b> {bill.get('customer_address') or '-'}"
                 if show_cust_addr else "")
    meta = [
        [P(f"<b>Bill No:</b> {bill['bill_no']}", size=fs_h),
         P(f"<b>Customer:</b> {cust}", size=fs_h)],
        [P(f"<b>Date:</b> {bill['date']}", size=fs_h),
         P(f"<b>Phone:</b> {bill.get('customer_phone') or '-'}", size=fs_h)],
        [P(pay_line, size=fs_h),
         P(addr_line, size=fs_h) if addr_line else Spacer(1, 1)],
    ]
    story.append(Table(meta, colWidths=["50%", "50%"]))
    story.append(Spacer(1, 8))

    # -- items ------------------------------------------------------------
    show_disc = prefs.get("show_discounts", True)
    show_codes = prefs.get("show_item_codes", True)
    # HSN column: SKU doubles as the HSN value; too narrow for 80mm thermal.
    show_hsn = bool(prefs.get("show_hsn")) and not narrow

    # Column specs in order: (header, width in points, flexible?)
    if narrow:  # 80mm thermal: tight columns; Item takes the remainder.
        colspec = [("#", 12), ("Item", None), ("Qty", 24), ("Rate", 36)]
        if show_disc:
            colspec.append(("Disc.", 30))
        colspec += [("GST%", 26), ("Amount", 44)]
    else:
        colspec = [("#", 22), ("Item", None)]
        if show_hsn:
            colspec.append(("HSN", 52))
        colspec += [("Qty", 52), ("Rate", 62)]
        if show_disc:
            colspec.append(("Disc.", 62))
        colspec += [("GST%", 44), ("Amount", 78)]

    data = [[h for h, _ in colspec]]
    for i, it in enumerate(items, 1):
        name = it["name"]
        if show_codes and it.get("sku"):
            name = f"{name}<br/><font color='#777777' size={fs - 1}>{it['sku']}</font>"
        disc = money(it.get("line_discount", 0)) if it.get("line_discount") else "-"
        row = [str(i), Paragraph(name, ParagraphStyle(
            "n", fontName=_FONT_NAME, fontSize=fs, leading=fs * 1.3))]
        if show_hsn:
            row.append(it.get("sku") or "-")
        row += [f"{float(it['qty']):g} {it.get('unit', '')}",
                money(it["price"])]
        if show_disc:
            row.append(disc)
        taxable = max(float(it["qty"]) * float(it["price"])
                      - float(it.get("line_discount", 0) or 0), 0.0)
        row += [f"{float(it.get('gst_percent', 0) or 0):g}%",
                money(taxable * (1 + float(it.get("gst_percent", 0) or 0) / 100))]
        data.append(row)

    # Resolve the flexible Item column
    total_w = _usable_width(narrow)
    fixed = sum(w for _, w in colspec if w is not None)
    widths = [total_w - fixed if w is None else w for _, w in colspec]

    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), accent_c),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
             ("FONTSIZE", (0, 0), (-1, -1), fs),
             ("FONTNAME", (0, 1), (-1, -1), _FONT_NAME),
             ("ALIGN", (3 if show_hsn else 2, 0), (-1, -1), "RIGHT"),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1),
              [colors.white, colors.HexColor("#f7f7f7")])]
    if show_hsn:
        style.append(("ALIGN", (2, 1), (2, -1), "CENTER"))
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 8))

    # -- GST breakup -------------------------------------------------------
    if prefs.get("show_gst_table", True):
        slabs = _slabs(items)
        gdata = [["Slab", "Taxable", "CGST", "SGST", "GST"]]
        for slab in sorted(slabs):
            taxable, gst = slabs[slab]
            gdata.append([f"{slab:g}%", money(taxable), money(gst / 2),
                          money(gst / 2), money(gst)])
        gt = Table(gdata, colWidths=[total_w * w for w in
                                     (0.16, 0.24, 0.2, 0.2, 0.2)])
        gt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
            ("FONTNAME", (0, 1), (-1, -1), _FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), fs - 1 if narrow else fs),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ]))
        story.append(gt)
        story.append(Spacer(1, 8))

    # -- totals ------------------------------------------------------------
    tdata = [["Subtotal", money(bill["subtotal"])],
             ["Total GST", money(bill["gst_total"])]]
    if float(bill.get("discount", 0) or 0):
        tdata.append(["Discount", f"- {money(bill['discount'])}"])
    if prefs.get("show_roundoff", True):
        tdata.append(["Round off", money(bill.get("round_off", 0) or 0)])
    tdata.append(["Grand Total", money(bill["grand_total"])])
    tw = total_w * (0.75 if narrow else 0.46)
    tt = Table(tdata, colWidths=[tw * 0.55, tw * 0.45])
    tt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTNAME", (0, -1), (-1, -1), _FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -2), fs),
        ("FONTSIZE", (0, -1), (-1, -1), fs + (2 if not narrow else 1)),
        ("TEXTCOLOR", (0, -1), (-1, -1), accent_c),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 2, accent_c),
    ]))
    story.append(Table([[Spacer(1, 1), tt]],
                       colWidths=[total_w - tw, tw]))
    story.append(Spacer(1, 10))

    # -- footer ------------------------------------------------------------
    if prefs.get("footer_note"):
        story.append(P(prefs["footer_note"], align=TA_CENTER,
                       color=grey, space=6))
    if prefs.get("show_thankyou", True):
        thankyou = (prefs.get("thankyou_text")
                    or "Thank you for your business!")
        story.append(P(thankyou, align=TA_CENTER, bold=True,
                       color=accent_c, space=6))
    # Signature lines: skipped on 80mm thermal (no room).
    if prefs.get("show_signature", True) and not narrow:
        story.append(Table(
            [[P("Customer signature", color=grey),
              P(f"For {profile.get('shop_name') or 'Shop'}", color=grey,
                align=TA_RIGHT)]],
            colWidths=["50%", "50%"]))
    now = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    story.append(P(f"Generated by Vyro — {now}", size=fs - 1,
                   color=grey, align=TA_CENTER, space=2))
    return story


def _usable_width(narrow):
    from reportlab.lib.units import mm
    return (80 * mm - 4 * mm) if narrow else (210 * mm - 24 * mm)


def _render_pdf(bill, items, profile, prefs, dest_path):
    """Build a Platypus PDF from a bill-like dict. Shared by invoices,
    credit notes and receipts."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    narrow = prefs.get("paper") == "thermal"
    dest_path = Path(dest_path)
    if narrow:
        width = 80 * mm
        # Thermal rolls print as one long receipt; over-estimate generously
        # so everything lands on a single page (unused space is harmless).
        height = 150 * mm + len(items) * 10 * mm
        pagesize = (width, height)
        margins = dict(leftMargin=2 * mm, rightMargin=2 * mm,
                       topMargin=3 * mm, bottomMargin=3 * mm)
    else:
        pagesize = A4
        margins = dict(leftMargin=12 * mm, rightMargin=12 * mm,
                       topMargin=12 * mm, bottomMargin=12 * mm)

    doc = SimpleDocTemplate(str(dest_path), pagesize=pagesize,
                            title=f"Invoice {bill['bill_no']}",
                            author=profile.get("shop_name") or "Vyro",
                            **margins)
    doc.build(_story(bill, items, profile, prefs, narrow))
    return dest_path


def generate_invoice_pdf(bill, items, profile, prefs, dest_path=None):
    """Render the invoice as a PDF (A4 or 80mm thermal per prefs).
    Returns the Path of the written file."""
    if dest_path is None:
        safe = str(bill["bill_no"]).replace("/", "-")
        dest_path = invoices_dir() / f"{safe}_invoice.pdf"
    return _render_pdf(bill, items, profile, prefs, dest_path)


def generate_credit_note_pdf(cn, items, profile, prefs, dest_path=None):
    """Printable credit note for a sales return. Reuses the invoice layout
    with a CREDIT NOTE title; honors invoice-design settings."""
    bill = {
        "bill_no": cn["credit_note_no"],
        "date": cn["date"],
        "payment_type": f"Credit Note (against bill {cn.get('bill_no') or ''})",
        "subtotal": cn["subtotal"],
        "discount": 0,
        "gst_total": cn["gst_total"],
        "round_off": round(cn["total"] - cn["subtotal"] - cn["gst_total"], 2),
        "grand_total": cn["total"],
        "customer_name": cn.get("customer_name") or "Walk-in",
        "customer_phone": cn.get("customer_phone") or "",
        "customer_address": cn.get("customer_address") or "",
    }
    prefs2 = dict(prefs)
    prefs2["invoice_title"] = "CREDIT NOTE"
    if dest_path is None:
        safe = str(cn["credit_note_no"]).replace("/", "-")
        dest_path = invoices_dir() / f"{safe}_credit_note.pdf"
    return _render_pdf(bill, items, profile, prefs2, dest_path)


def generate_payment_receipt_pdf(payment, customer, profile, prefs,
                                 dest_path=None):
    """Small payment receipt PDF for a khata collection (A4 + thermal)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    narrow = prefs.get("paper") == "thermal"
    accent = colors.HexColor(prefs.get("accent", "#1f6f43") or "#1f6f43")
    dark, grey = colors.HexColor("#222222"), colors.HexColor("#777777")
    fs = 9 if narrow else 11

    def P(text, size=fs, bold=False, color=dark, align=TA_LEFT):
        return Paragraph(text, ParagraphStyle(
            "r", fontName=_FONT_BOLD if bold else _FONT_NAME,
            fontSize=size, leading=size * 1.35, textColor=color,
            alignment=align, spaceAfter=3))

    story = [
        P(profile.get("shop_name") or "Vyro Shop", size=fs + 6, bold=True,
          color=accent, align=TA_CENTER),
    ]
    if profile.get("shop_phone"):
        story.append(P(f"Phone: {profile['shop_phone']}", color=grey,
                       align=TA_CENTER))
    story += [
        HRFlowable(width="100%", thickness=2, color=accent,
                   spaceAfter=6, spaceBefore=4),
        P("PAYMENT RECEIPT", size=fs + 3, bold=True, color=accent,
          align=TA_CENTER),
        Spacer(1, 6),
    ]
    rows = [
        ["Receipt No:", f"RCP-{int(payment['id']):04d}"],
        ["Date:", payment["date"]],
        ["Received from:", customer["name"] if customer else "-"],
        ["Mode:", payment.get("mode") or "Cash"],
    ]
    if payment.get("note"):
        rows.append(["Note:", payment["note"]])
    t = Table([[P(f"<b>{k}</b>", size=fs), P(v, size=fs)] for k, v in rows],
              colWidths=["38%", "62%"] if not narrow else ["40%", "60%"])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(P(f"Amount received: <b>{money(payment['amount'])}</b>",
                   size=fs + 4, bold=True, color=accent, align=TA_CENTER))
    story.append(Spacer(1, 6))
    if customer:
        story.append(P(
            f"Outstanding balance after this payment: "
            f"<b>{money(customer['balance'])}</b>", align=TA_CENTER))
    story.append(Spacer(1, 10))
    story.append(P("Thank you!", bold=True, color=accent, align=TA_CENTER))
    if not narrow:
        story.append(Spacer(1, 24))
        story.append(Table(
            [[P("Customer signature", color=grey),
              P(f"For {profile.get('shop_name') or 'Shop'}", color=grey,
                align=TA_CENTER)]],
            colWidths=["50%", "50%"]))

    if dest_path is None:
        dest_path = (invoices_dir()
                     / f"RCP-{int(payment['id']):04d}_receipt.pdf")
    dest_path = Path(dest_path)
    if narrow:
        pagesize = (80 * mm, 120 * mm)
        margins = dict(leftMargin=2 * mm, rightMargin=2 * mm,
                       topMargin=3 * mm, bottomMargin=3 * mm)
    else:
        pagesize = A4
        margins = dict(leftMargin=12 * mm, rightMargin=12 * mm,
                       topMargin=12 * mm, bottomMargin=12 * mm)
    doc = SimpleDocTemplate(str(dest_path), pagesize=pagesize,
                            title=f"Receipt RCP-{int(payment['id']):04d}",
                            author=profile.get("shop_name") or "Vyro",
                            **margins)
    doc.build(story)
    return dest_path


def generate_challan_pdf(challan, items, profile, prefs, dest_path=None):
    """Delivery challan PDF (no GST/tax). Honors the invoice-design shop
    header; A4 + 80mm thermal layouts."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    narrow = prefs.get("paper") == "thermal"
    accent = colors.HexColor(prefs.get("accent", "#1f6f43") or "#1f6f43")
    dark, grey = colors.HexColor("#222222"), colors.HexColor("#777777")
    fscale = {"compact": 0.85, "standard": 1.0,
              "large": 1.18}.get(prefs.get("font_size", "standard"), 1.0)
    fs = round((8 if narrow else 10) * fscale)
    fs_title = round((13 if narrow else 20) * fscale)

    def P(text, size=fs, bold=False, color=dark, align=TA_LEFT, space=2):
        return Paragraph(text, ParagraphStyle(
            "ch", fontName=_FONT_BOLD if bold else _FONT_NAME,
            fontSize=size, leading=size * 1.3, textColor=color,
            alignment=align, spaceAfter=space))

    story = [P(profile.get("shop_name") or "Vyro Shop", size=fs_title,
               bold=True, color=accent, align=TA_CENTER, space=1)]
    if prefs.get("show_tagline", True) and profile.get("shop_tagline"):
        story.append(P(profile["shop_tagline"], align=TA_CENTER, space=1))
    if prefs.get("show_address", True) and profile.get("shop_address"):
        story.append(P(profile["shop_address"], color=grey,
                       align=TA_CENTER, space=1))
    if prefs.get("show_phone", True) and profile.get("shop_phone"):
        story.append(P(f"Phone: {profile['shop_phone']}", color=grey,
                       align=TA_CENTER, space=1))
    story.append(HRFlowable(width="100%", thickness=2.5, color=accent,
                            spaceAfter=6, spaceBefore=4))
    story.append(P("DELIVERY CHALLAN", size=fs + 4, bold=True, color=accent,
                   align=TA_CENTER, space=6))
    story.append(P("Goods sent on approval — not a tax invoice.",
                   color=grey, align=TA_CENTER, space=6))

    cust = challan.get("customer_name") or "Walk-in"
    meta = [
        [P(f"<b>Challan No:</b> {challan['challan_no']}"),
         P(f"<b>Customer:</b> {cust}")],
        [P(f"<b>Date:</b> {challan['date']}"),
         P(f"<b>Phone:</b> {challan.get('customer_phone') or '-'}")],
    ]
    if challan.get("note"):
        meta.append([P(f"<b>Note:</b> {challan['note']}"), Spacer(1, 1)])
    story.append(Table(meta, colWidths=["50%", "50%"]))
    story.append(Spacer(1, 8))

    total_w = _usable_width(narrow)
    if narrow:
        colspec = [("#", 14), ("Item", None), ("Qty", 30), ("Rate", 44),
                   ("Amount", 52)]
    else:
        colspec = [("#", 24), ("Item", None), ("Qty", 60), ("Rate", 70),
                   ("Amount", 90)]
    data = [[h for h, _ in colspec]]
    total_qty, total_amt = 0.0, 0.0
    for i, it in enumerate(items, 1):
        q = float(it["qty"])
        amt = q * float(it.get("price", 0) or 0)
        total_qty += q
        total_amt += amt
        data.append([str(i), it["name"], f"{q:g} {it.get('unit', '')}",
                     money(it.get("price", 0) or 0), money(amt)])
    data.append(["", P("<b>Total</b>", bold=True), f"{total_qty:g}",
                 "", P(f"<b>{money(total_amt)}</b>", bold=True,
                       align=TA_RIGHT)])
    fixed = sum(w for _, w in colspec if w is not None)
    widths = [total_w - fixed if w is None else w for _, w in colspec]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("FONTNAME", (0, 1), (-1, -1), _FONT_NAME),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2),
         [colors.white, colors.HexColor("#f7f7f7")]),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, accent),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))
    if prefs.get("footer_note"):
        story.append(P(prefs["footer_note"], align=TA_CENTER, color=grey,
                       space=6))
    if not narrow:
        story.append(Spacer(1, 18))
        story.append(Table(
            [[P("Receiver signature", color=grey),
              P(f"For {profile.get('shop_name') or 'Shop'}", color=grey,
                align=TA_RIGHT)]],
            colWidths=["50%", "50%"]))
    now = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    story.append(P(f"Generated by Vyro — {now}", size=fs - 1,
                   color=grey, align=TA_CENTER, space=2))

    if dest_path is None:
        safe = str(challan["challan_no"]).replace("/", "-")
        dest_path = invoices_dir() / f"{safe}_challan.pdf"
    dest_path = Path(dest_path)
    if narrow:
        pagesize = (80 * mm, 130 * mm + len(items) * 8 * mm)
        margins = dict(leftMargin=2 * mm, rightMargin=2 * mm,
                       topMargin=3 * mm, bottomMargin=3 * mm)
    else:
        pagesize = A4
        margins = dict(leftMargin=12 * mm, rightMargin=12 * mm,
                       topMargin=12 * mm, bottomMargin=12 * mm)
    doc = SimpleDocTemplate(str(dest_path), pagesize=pagesize,
                            title=f"Challan {challan['challan_no']}",
                            author=profile.get("shop_name") or "Vyro",
                            **margins)
    doc.build(story)
    return dest_path


def generate_reorder_pdf(rows, profile, prefs, dest_path=None):
    """Re-order list PDF: products below their low-stock threshold with
    suggested order qty, last rate and supplier. Honors the invoice-design
    shop header; A4 + 80mm thermal layouts. Each row is a dict with:
    name, sku, stock, threshold, order_qty, last_rate, supplier, phone,
    expiry."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    narrow = prefs.get("paper") == "thermal"
    accent = colors.HexColor(prefs.get("accent", "#1f6f43") or "#1f6f43")
    dark, grey = colors.HexColor("#222222"), colors.HexColor("#777777")
    fscale = {"compact": 0.85, "standard": 1.0,
              "large": 1.18}.get(prefs.get("font_size", "standard"), 1.0)
    fs = round((8 if narrow else 10) * fscale)
    fs_title = round((13 if narrow else 20) * fscale)

    def P(text, size=fs, bold=False, color=dark, align=TA_LEFT, space=2):
        return Paragraph(text, ParagraphStyle(
            "ro", fontName=_FONT_BOLD if bold else _FONT_NAME,
            fontSize=size, leading=size * 1.3, textColor=color,
            alignment=align, spaceAfter=space))

    story = [P(profile.get("shop_name") or "Vyro Shop", size=fs_title,
               bold=True, color=accent, align=TA_CENTER, space=1)]
    if prefs.get("show_tagline", True) and profile.get("shop_tagline"):
        story.append(P(profile["shop_tagline"], align=TA_CENTER, space=1))
    if prefs.get("show_address", True) and profile.get("shop_address"):
        story.append(P(profile["shop_address"], color=grey,
                       align=TA_CENTER, space=1))
    if prefs.get("show_phone", True) and profile.get("shop_phone"):
        story.append(P(f"Phone: {profile['shop_phone']}", color=grey,
                       align=TA_CENTER, space=1))
    story.append(HRFlowable(width="100%", thickness=2.5, color=accent,
                            spaceAfter=6, spaceBefore=4))
    story.append(P("RE-ORDER LIST", size=fs + 4, bold=True, color=accent,
                   align=TA_CENTER, space=2))
    story.append(P("Stock at or below the low-stock threshold — "
                   "suggested order quantities are 2x threshold minus stock.",
                   color=grey, align=TA_CENTER, space=6))
    story.append(P(f"<b>Date:</b> {datetime.now().strftime('%d-%m-%Y')}",
                   align=TA_LEFT, space=8))

    total_w = _usable_width(narrow)
    if narrow:
        colspec = [("#", 12), ("Product", None), ("Order", 32),
                   ("Rate", 40), ("Supplier", None)]
    else:
        colspec = [("#", 24), ("Product", None), ("Stock", 50),
                   ("Order", 55), ("Last rate", 75), ("Est. amount", 85),
                   ("Supplier", None), ("Expiry", 80)]
    data = [[h for h, _ in colspec]]
    tot_amt = 0.0
    for i, r in enumerate(rows, 1):
        est = float(r["order_qty"]) * float(r["last_rate"] or 0)
        tot_amt += est
        if narrow:
            data.append([str(i),
                         f"{r['name']}" + (f" ({r['sku']})" if r.get("sku")
                                           else ""),
                         f"{r['order_qty']:g}", money(r["last_rate"]),
                         r.get("supplier") or "-"])
        else:
            sup = r.get("supplier") or "-"
            if r.get("phone"):
                sup += f" ({r['phone']})"
            data.append([str(i),
                         f"{r['name']}" + (f"  · {r['sku']}"
                                           if r.get("sku") else ""),
                         f"{float(r['stock']):g}",
                         f"{float(r['order_qty']):g}",
                         money(r["last_rate"]), money(est), sup,
                         r.get("expiry") or "-"])
    if not narrow:
        data.append(["", "", "", "", "",
                     P(f"<b>{money(tot_amt)}</b>", bold=True, align=TA_RIGHT),
                     "", ""])
    fixed = sum(w for _, w in colspec if w is not None)
    widths = [total_w - fixed if w is None else w for _, w in colspec]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), fs),
        ("FONTNAME", (0, 1), (-1, -1), _FONT_NAME),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2),
         [colors.white, colors.HexColor("#f7f7f7")]),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, accent),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))
    now = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    story.append(P(f"Generated by Vyro — {now}", size=fs - 1,
                   color=grey, align=TA_CENTER, space=2))

    if dest_path is None:
        dest_path = invoices_dir() / (
            f"reorder_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
    dest_path = Path(dest_path)
    if narrow:
        pagesize = (80 * mm, 130 * mm + len(rows) * 8 * mm)
        margins = dict(leftMargin=2 * mm, rightMargin=2 * mm,
                       topMargin=3 * mm, bottomMargin=3 * mm)
    else:
        pagesize = A4
        margins = dict(leftMargin=12 * mm, rightMargin=12 * mm,
                       topMargin=12 * mm, bottomMargin=12 * mm)
    doc = SimpleDocTemplate(str(dest_path), pagesize=pagesize,
                            title="Re-Order List",
                            author=profile.get("shop_name") or "Vyro",
                            **margins)
    doc.build(story)
    return dest_path


# ---------------------------------------------------------------------------
# High-level: build + print one saved bill
# ---------------------------------------------------------------------------
def print_bill_pdf(bill_id, db_path=None, printer=None, copies=1,
                   preview=False):
    """Generate the PDF invoice for a saved bill and either open it
    (preview) or send it to a printer.

    Returns (pdf_path, printed: bool, message: str). printed is True only
    when the OS accepted the print job; callers must not claim otherwise.
    """
    db = DB(db_path) if db_path else DB()
    try:
        bill = db.get_bill(bill_id)
        if not bill:
            raise ValueError("Bill not found")
        items = db.bill_items(bill_id)
        for it in items:  # attach SKU for the item-code toggle
            p = db.get_product(it["product_id"]) if it.get("product_id") else None
            it["sku"] = (p or {}).get("sku", "")
        path = generate_invoice_pdf(bill, items, db.shop_profile(),
                                    db.print_prefs())
        if preview:
            ok = open_pdf(path)
            db.log_bill_action(bill_id, "reprinted",
                               f"Invoice preview opened: {path.name}")
            db.close()
            return path, False, ("Invoice preview opened."
                                 if ok else f"PDF saved at {path}")
        ok, msg = print_pdf(path, printer=printer, copies=copies)
        db.log_bill_action(bill_id, "reprinted",
                           f"Invoice PDF: {path.name} — {msg}")
        db.close()
        # NOTE: never auto-open the PDF on print failure — the caller shows
        # msg (reason + saved path + fix hint) and offers a manual Open.
        return path, ok, msg
    except Exception:
        db.close()
        raise
