"""Vyro - backup.py
Database backup / restore: manual one-click backups, automatic backup on
app exit, and the Backup & restore screen.
"""

import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from db import data_dir


AUTO_BACKUP_PREFIX = "billbook_auto_backup_"
AUTO_BACKUP_KEEP = 14


def make_backup_zip(db, dest):
    dest = Path(dest)
    try:
        db.conn.commit()
    except Exception:
        pass
    dd = data_dir()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        if db.path.exists():
            z.write(db.path, "billbook.db")
        for sub in ("invoices", "logos"):
            d = dd / sub
            if d.is_dir():
                for f in d.rglob("*"):
                    if f.is_file():
                        z.write(f, f"{sub}/{f.relative_to(d)}")
    return dest


def auto_backup_folder(db):
    custom = (db.get_setting("auto_backup_folder") or "").strip()
    if custom:
        return Path(custom)
    return data_dir() / "backups"


def prune_auto_backups(folder, keep=AUTO_BACKUP_KEEP):
    try:
        folder = Path(folder)
        autos = sorted(folder.glob(AUTO_BACKUP_PREFIX + "*.zip"),
                       key=lambda p: p.name)
        for old in autos[:max(0, len(autos) - keep)]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def auto_backup_on_exit(db):
    try:
        if db.get_setting("auto_backup_on_exit", "1") != "1":
            return None
        folder = auto_backup_folder(db)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            folder = data_dir() / "backups"
            folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = folder / f"{AUTO_BACKUP_PREFIX}{stamp}.zip"
        make_backup_zip(db, dest)
        prune_auto_backups(folder)
        return dest
    except Exception:
        return None


class BackupFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Backup & restore",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        info = ctk.CTkFrame(self)
        info.pack(fill="x", pady=8)
        p = self.db.path
        size_kb = p.stat().st_size / 1024 if p.exists() else 0
        dd = data_dir()
        n_inv = len(list((dd / "invoices").glob("*.pdf"))) \
            if (dd / "invoices").is_dir() else 0
        ctk.CTkLabel(
            info,
            text=f"Data file: {p}\nSize: {size_kb:.1f} KB   |   "
                 f"Saved invoice PDFs: {n_inv}",
            justify="left").pack(anchor="w", padx=12, pady=10)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", pady=8)
        ctk.CTkButton(btns, text="Backup now (one click)", fg_color="#1f6f43",
                      hover_color="#175733", height=44,
                      command=self.backup).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Restore from file...", height=44,
                      command=self.restore).pack(side="left", padx=4)
        self.status = ctk.CTkLabel(btns, text="", text_color="gray")
        self.status.pack(side="left", padx=12)

        auto = ctk.CTkFrame(self)
        auto.pack(fill="x", pady=8)
        ctk.CTkLabel(auto, text="Automatic backup on exit",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
                         anchor="w", padx=12, pady=(10, 2))
        self.auto_var = ctk.BooleanVar(
            value=db.get_setting("auto_backup_on_exit", "1") == "1")
        ctk.CTkCheckBox(
            auto, text="Back up automatically every time the app closes",
            variable=self.auto_var, command=self.save_auto_toggle).pack(
                anchor="w", padx=12, pady=2)
        frow = ctk.CTkFrame(auto, fg_color="transparent")
        frow.pack(fill="x", padx=12, pady=(4, 4))
        ctk.CTkLabel(frow, text="Auto-backup folder:").pack(side="left")
        self.auto_folder_label = ctk.CTkLabel(
            frow, text=str(auto_backup_folder(db)), text_color="gray",
            wraplength=420, justify="left")
        self.auto_folder_label.pack(side="left", padx=8)
        ctk.CTkButton(frow, text="Choose folder...", width=130,
                      command=self.choose_auto_folder).pack(side="left",
                                                           padx=4)
        ctk.CTkButton(frow, text="Use default", width=100,
                      command=self.reset_auto_folder).pack(side="left",
                                                          padx=4)
        ctk.CTkLabel(
            auto,
            text=f"The last {AUTO_BACKUP_KEEP} automatic backups are kept; "
                 "older ones are deleted automatically. Manual backups are "
                 "never deleted.",
            text_color="gray", wraplength=700, justify="left").pack(
                anchor="w", padx=12, pady=(0, 10))

        ctk.CTkLabel(
            self,
            text="A backup is a single .zip with the database, all saved "
                 "invoice PDFs and the shop logo. Back up daily to a pen "
                 "drive or Google Drive folder so a PC crash never loses "
                 "your bills and khata.\n\n"
                 "Restore always saves a safety copy of your CURRENT data "
                 "first (in billbook_data/backups), so nothing is ever "
                 "lost by accident.",
            text_color="gray", wraplength=700, justify="left").pack(
                anchor="w", pady=12)

    def save_auto_toggle(self):
        self.db.set_setting("auto_backup_on_exit",
                            "1" if self.auto_var.get() else "0")

    def choose_auto_folder(self):
        folder = filedialog.askdirectory(title="Choose auto-backup folder")
        if not folder:
            return
        self.db.set_setting("auto_backup_folder", folder)
        self.auto_folder_label.configure(text=folder)

    def reset_auto_folder(self):
        self.db.set_setting("auto_backup_folder", "")
        self.auto_folder_label.configure(text=str(auto_backup_folder(
            self.db)))

    def backup(self):
        folder = filedialog.askdirectory(title="Choose backup folder")
        if not folder:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path(folder) / f"billbook_backup_{stamp}.zip"
        try:
            make_backup_zip(self.db, dest)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Backup", f"Backup failed:\n{e}")
            return
        self.status.configure(text=f"Backed up to {dest.name}")
        messagebox.showinfo("Backup", f"Backup saved:\n{dest}")

    def restore(self):
        path = filedialog.askopenfilename(
            filetypes=[("Vyro backup", "*.zip"), ("SQLite DB", "*.db")],
            title="Choose backup file")
        if not path:
            return
        if not messagebox.askyesno(
                "Restore",
                "Replace ALL current data with this backup?\n"
                "Current bills, stock and khata will be overwritten.\n\n"
                "A safety copy of your current data is saved first."):
            return
        dd = data_dir()
        safe_dir = dd / "backups"
        try:
            safe_dir.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.db.conn.commit()
            shutil.copy2(self.db.path,
                         safe_dir / f"auto_before_restore_{stamp}.db")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Restore",
                                 f"Could not make a safety copy: {e}\n"
                                 "Restore cancelled — nothing was changed.")
            return
        import sqlite3
        tmp = None
        try:
            if path.lower().endswith(".zip"):
                tmp = Path(tempfile.mkdtemp(prefix="billbook_restore_"))
                with zipfile.ZipFile(path) as z:
                    z.extractall(tmp)
                cands = (list(tmp.rglob("billbook.db"))
                         or list(tmp.rglob("*.db")))
                if not cands:
                    raise ValueError("No database found inside the zip.")
                db_src = cands[0]
                for sub in ("invoices", "logos"):
                    src_d = tmp / sub
                    if src_d.is_dir():
                        dst_d = dd / sub
                        dst_d.mkdir(exist_ok=True)
                        for f in src_d.rglob("*"):
                            if f.is_file():
                                dst = dst_d / f.relative_to(src_d)
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(f, dst)
            else:
                db_src = Path(path)
            probe = sqlite3.connect(str(db_src))
            tables = {r[0] for r in probe.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            probe.close()
            if not {"products", "bills", "customers"} <= tables:
                raise ValueError("This file is not a Vyro backup.")
            self.db.close()
            shutil.copy2(db_src, self.db.path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Restore",
                                 f"Restore failed: {e}\n\n"
                                 "Your current data was NOT touched — a "
                                 "safety copy is in billbook_data/backups.")
            return
        finally:
            if tmp is not None and tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        messagebox.showinfo("Restore",
                            "Backup restored. Please close and reopen "
                            "Vyro to continue with the restored data.")


