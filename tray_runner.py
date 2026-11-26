# tray_runner.py
# =========================
# System Tray + ตั้งค่าเครื่องพิมพ์ (Thermal RAW ESC/POS) + Feed Config
# =========================

import os, sys, io, json, time, base64, threading, importlib.util
from pathlib import Path
from PIL import Image as PIL_Image
from PIL import ImageTk
import win32print
from flask_cors import CORS
import requests

from pystray import Icon, Menu, MenuItem
from PIL import Image as PILImageForTray
import tkinter as tk
from tkinter import ttk, messagebox

from smartcard_reader import ThaiIDCardReader


# ✅ ตัวโปรแกรมอยู่ที่ base_path (เช่น C:\Program Files\AuthenAPI — อ่านอย่างเดียว)
# ส่วน config อยู่ที่ %APPDATA%\AuthenAPI\config.json ซึ่งเขียนได้เสมอ — ดู app_paths.py
import app_paths
from app_paths import APP_DIR as base_path, CONFIG_FILE

BACKEND_FILE = os.path.join(base_path, "main.py")

APP_VERSION = "v2.1.1"

# ✅ ระบบอัปเดตอัตโนมัติผ่าน GitHub Releases
GITHUB_REPO = "arofatsabuding/authenchart-printer-windows"
# ชื่อไฟล์ตัวติดตั้งที่ต้องแนบไปกับทุก release บน GitHub (ต้องตรงกับชื่อนี้เป๊ะๆ)
UPDATE_ASSET_NAME = "AuthenAPI-Setup.exe"

PORT = 9333


# =========================
# DEFAULT CONFIG
# =========================
DEFAULTS = {
    "printer_type": "ESC/POS Thermal",
    "printer_name": None,
    "paper_size": "80",  # "58" | "80"
    "feed_px": 20,
    "printer_enabled": True
}


# =========================
# CONFIG MANAGEMENT
# =========================
def load_config():
    cfg = DEFAULTS.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
            cfg.update({k: v for k, v in saved.items() if k in cfg})
    except:
        pass
    if not cfg["printer_name"]:
        try:
            cfg["printer_name"] = win32print.GetDefaultPrinter()
        except:
            cfg["printer_name"] = ""
    return cfg


def save_config(cfg):
    """
    ✅ Merge กับค่าที่มีอยู่เดิมในไฟล์ (เช่น key "smartcard" ที่โมดูล
    smartcard_reader เขียนไว้) แทนที่จะเขียนทับทั้งไฟล์ — ป้องกันไม่ให้
    การบันทึกหน้าตั้งค่าเครื่องพิมพ์ไปลบการตั้งค่าเครื่องอ่านบัตรทิ้ง
    """
    existing = {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except:
        pass

    existing.update(cfg)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


# =========================
# AUTO-UPDATE (ผ่าน GitHub Releases)
# =========================
def _parse_version(v):
    """แปลง 'v2.1.0' หรือ '2.1.0' เป็น tuple (2,1,0) เพื่อเทียบเวอร์ชันแบบตัวเลข"""
    v = (v or "").strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check_for_update():
    """
    เช็คเวอร์ชันล่าสุดจาก GitHub Releases
    คืนค่า: (has_update, latest_version, download_url, error_message)
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return False, None, None, f"เช็คอัปเดตไม่สำเร็จ (HTTP {res.status_code})"
        data = res.json()
        latest_tag = data.get("tag_name", "")
        if not latest_tag:
            return False, None, None, "ไม่พบข้อมูลเวอร์ชันจาก GitHub"

        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name") == UPDATE_ASSET_NAME:
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            return False, latest_tag, None, f"ไม่พบไฟล์ {UPDATE_ASSET_NAME} แนบใน release ล่าสุด"

        has_update = _parse_version(latest_tag) > _parse_version(APP_VERSION)
        return has_update, latest_tag, download_url, None
    except Exception as e:
        return False, None, None, f"เช็คอัปเดตไม่สำเร็จ: {e}"


def download_and_apply_update(download_url):
    """
    ดาวน์โหลดตัวติดตั้ง (AuthenAPI-Setup.exe) เวอร์ชันใหม่ไว้ในโฟลเดอร์ชั่วคราว แล้วสั่งรันแบบ /SILENT
    ตัวติดตั้งจะขอสิทธิ์ admin (UAC) ปิดโปรแกรมนี้ ติดตั้งทับโฟลเดอร์เดิม แล้วเปิดโปรแกรมขึ้นมาใหม่เอง
    """
    if not getattr(sys, "frozen", False):
        raise RuntimeError("ฟีเจอร์อัปเดตอัตโนมัติใช้ได้เฉพาะตอนรันเป็น .exe เท่านั้น (ไม่ใช่ python tray_runner.py)")

    import tempfile
    setup_path = os.path.join(tempfile.gettempdir(), UPDATE_ASSET_NAME)

    # ✅ ดาวน์โหลดแบบ stream กันกินแรมเยอะกับไฟล์ใหญ่
    with requests.get(download_url, stream=True, timeout=60) as res:
        res.raise_for_status()
        with open(setup_path, "wb") as f:
            for chunk in res.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    # ✅ ต้องใช้ ShellExecute (os.startfile) ไม่ใช่ subprocess — ตัวติดตั้งต้องการสิทธิ์ admin
    # subprocess.Popen จะล้มด้วย error 740 ส่วน ShellExecute จะเด้งหน้าต่าง UAC ให้กดยืนยัน
    os.startfile(setup_path, "open", "/SILENT /SP- /SUPPRESSMSGBOXES /NORESTART")
    os._exit(0)


def _show_update_message(title, message, error=False):
    root = tk.Tk()
    root.withdraw()
    try:
        icon_path = os.path.join(base_path, "app.ico")
        root.iconbitmap(icon_path)
    except:
        pass
    if error:
        messagebox.showerror(title, message)
    else:
        messagebox.showinfo(title, message)
    root.destroy()


def _ask_yes_no_update(title, message):
    root = tk.Tk()
    root.withdraw()
    try:
        icon_path = os.path.join(base_path, "app.ico")
        root.iconbitmap(icon_path)
    except:
        pass
    result = messagebox.askyesno(title, message)
    root.destroy()
    return result


def _run_update_flow(silent_if_no_update=False):
    has_update, latest, url, err = check_for_update()

    if err:
        if not silent_if_no_update:
            _show_update_message("เช็คอัปเดตไม่สำเร็จ", err, error=True)
        return

    if not has_update:
        if not silent_if_no_update:
            _show_update_message("ตรวจสอบอัปเดต", f"ใช้เวอร์ชันล่าสุดอยู่แล้ว ({APP_VERSION})")
        return

    proceed = _ask_yes_no_update(
        "พบเวอร์ชันใหม่",
        f"พบเวอร์ชันใหม่ {latest} (ปัจจุบัน {APP_VERSION})\n\n"
        f"ต้องการดาวน์โหลดและติดตั้งตอนนี้เลยไหม?\n"
        f"(Windows จะถามสิทธิ์ผู้ดูแลระบบ — กด Yes แล้วโปรแกรมจะปิดตัวชั่วคราว\n"
        f"ระหว่างติดตั้ง และเปิดขึ้นมาใหม่อัตโนมัติ)"
    )
    if not proceed:
        return

    try:
        download_and_apply_update(url)  # ถ้าสำเร็จ โปรแกรมจะปิดตัวเองในฟังก์ชันนี้
    except Exception as e:
        _show_update_message("อัปเดตไม่สำเร็จ", str(e), error=True)


def action_check_update(icon_, item):
    threading.Thread(target=lambda: _run_update_flow(silent_if_no_update=False), daemon=True).start()


def silent_startup_update_check():
    """เช็คอัปเดตอัตโนมัติตอนเปิดโปรแกรม — เงียบๆ ถ้าไม่มีอัปเดตหรือเช็คไม่ได้ ไม่รบกวนผู้ใช้"""
    time.sleep(3)  # รอให้ระบบอื่นเริ่มทำงานเสร็จก่อน
    _run_update_flow(silent_if_no_update=True)


# =========================
# ESC/POS PRINTING (RAW)
# =========================
def escpos_print_image(img: PIL_Image.Image, printer_name: str, paper_size="80", feed_px=20):
    """พิมพ์ภาพแบบ Raster (GS v 0) รองรับ ESC/POS ทุกยี่ห้อ"""
    # แปลงเป็นขาวดำ
    img = img.convert("L").point(lambda x: 0 if x < 128 else 255, "1")

    width = 384 if str(paper_size) == "58" else 576
    if img.width != width:
        ratio = width / img.width
        height = int(img.height * ratio)
        img = img.resize((width, height))

    # ESC/POS initialize
    data = bytearray(b"\x1B\x40")  # Initialize printer

    # ใช้ GS v 0 (Raster bit image)
    width_bytes = width // 8
    img_bytes = bytearray()

    for y in range(img.height):
        row = 0
        for x in range(width_bytes):
            byte = 0
            for bit in range(8):
                if img.getpixel((x * 8 + bit, y)) == 0:
                    byte |= 1 << (7 - bit)
            img_bytes.append(byte)

    # header: GS v 0 m xL xH yL yH
    xL = width_bytes % 256
    xH = width_bytes // 256
    yL = img.height % 256
    yH = img.height // 256

    data += b"\x1D\x76\x30\x00" + bytes([xL, xH, yL, yH]) + img_bytes

    # ✅ Feed ก่อนตัด
    lines = max(1, int(feed_px / 24))
    data += b"\x1B\x64" + bytes([lines])

    # ✅ Full cut
    data += b"\x1D\x56\x00"

    # ส่งเข้าเครื่องพิมพ์
    hPrinter = win32print.OpenPrinter(printer_name)
    try:
        job = win32print.StartDocPrinter(hPrinter, 1, ("ESC/POS Raster Print", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)
        win32print.WritePrinter(hPrinter, bytes(data))
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
        print(f"🧾 ESC/POS raster printed {img.height}px, feed {feed_px}px, cut done.")
    finally:
        win32print.ClosePrinter(hPrinter)



# =========================
# LOAD FLASK + PATCH
# =========================
def load_backend_and_patch():
    """
    โหลด Flask backend จาก main.py (รองรับทั้ง .py และ .exe onefile)
    """
    backend = None

    # ✅ ถ้ารันใน exe (PyInstaller onefile)
    if getattr(sys, 'frozen', False):
        try:
            import main as backend  # main.py ถูก bundle อยู่ใน exe แล้ว
            print("📦 Loaded backend from bundled module (main)")
        except ImportError as e:
            print("⚠️ Import bundled main failed:", e)

    # ✅ ถ้ายังไม่มี backend (เช่นตอนรัน tray_runner.py ปกติ)
    if backend is None:
        # ใช้ path ปกติกรณีรัน .py
        backend_path = Path(BACKEND_FILE).resolve()
        if not backend_path.exists():
            # ✅ ถ้าไม่มีไฟล์ (เช่นอยู่ใน dist แต่รัน exe)
            # ลองใช้ path ชั่วคราวที่ PyInstaller แตกไฟล์ไว้ (_MEIPASS)
            temp_path = Path(getattr(sys, "_MEIPASS", "")) / "main.py"
            if temp_path.exists():
                backend_path = temp_path
                print(f"📁 Loaded backend from _MEIPASS: {backend_path}")
            else:
                raise FileNotFoundError(f"ไม่พบไฟล์ Flask: {backend_path}")

        spec = importlib.util.spec_from_file_location("backend_app", str(backend_path))
        backend = importlib.util.module_from_spec(spec)
        sys.modules["backend_app"] = backend
        spec.loader.exec_module(backend)
        print("📁 Loaded backend from external main.py")

    # ✅ Patch ฟังก์ชันพิมพ์
    def patched_print_image_win(image: PIL_Image.Image):
        cfg = load_config()
        if not cfg.get("printer_enabled", True):
            # ✅ ปิดใช้งานเครื่องพิมพ์ไว้ — บล็อกตรงนี้เลย ไม่ว่าใครจะยิง /print เข้ามา
            raise RuntimeError("เครื่องพิมพ์ถูกปิดใช้งานอยู่ กรุณาเปิดใช้งานที่หน้าตั้งค่าก่อนพิมพ์")
        pname = cfg.get("printer_name") or win32print.GetDefaultPrinter()
        psize = cfg.get("paper_size", "80")
        feed_px = int(cfg.get("feed_px", 20))
        print(f"🖨️ Printing ESC/POS RAW to {pname} | Paper {psize}mm | Feed {feed_px}px")
        escpos_print_image(image, pname, psize, feed_px)

    backend.print_image_win = patched_print_image_win

    # ✅ กันพลาด: ให้เซิร์ฟเวอร์ใช้ config.json ไฟล์เดียวกับหน้าตั้งค่าเสมอ
    # (เคยมีบั๊กที่สองส่วนนี้อ่านคนละไฟล์ ทำให้ปิดการอ่านรูปแล้ว API ยังส่งรูปอยู่)
    backend.CONFIG_FILE = CONFIG_FILE
    card_reader = getattr(backend, "card_reader", None)
    if card_reader is not None:
        card_reader.config_path = CONFIG_FILE
    return backend



# =========================
# GUI SETTINGS
# =========================
def open_settings_window():
    import requests
    cfg = load_config()
    win_printers = list_windows_printers()

    card_reader = ThaiIDCardReader(CONFIG_FILE)
    smartcard_cfg = card_reader.get_smartcard_config()
    try:
        available_readers = card_reader.list_readers()
    except Exception as e:
        available_readers = []
        print("⚠️ ไม่สามารถอ่านรายชื่อเครื่องอ่านบัตรได้:", e)

    root = tk.Tk()
    root.title(f"ตั้งค่า AuthenChart Printer ({APP_VERSION})")
    root.geometry("480x630")

    try:
        icon_path = os.path.join(base_path, "app.ico")
        root.iconbitmap(icon_path)
    except:
        pass

    # ===================== กรอบเครื่องพิมพ์ =====================
    printer_frame = ttk.LabelFrame(root, text="🖨️ เครื่องพิมพ์")
    printer_frame.pack(fill="x", padx=14, pady=(14, 8))

    printer_enabled_var = tk.BooleanVar(value=cfg.get("printer_enabled", True))
    test_print_btn = None  # ✅ จะถูกกำหนดจริงตอนสร้างปุ่มด้านล่าง

    def on_toggle_printer_enabled():
        state = "normal" if printer_enabled_var.get() else "disabled"
        printer_combo.configure(state=state)
        paper_combo.configure(state=("readonly" if printer_enabled_var.get() else "disabled"))
        feed_entry.configure(state=state)
        # ✅ disable แค่ปุ่ม "ทดสอบพิมพ์" — ปุ่ม "บันทึก" ต้องกดได้เสมอ ไม่งั้นกลับมาเปิดไม่ได้
        if test_print_btn is not None:
            test_print_btn.configure(state=state)

    ttk.Checkbutton(
        printer_frame,
        text="เปิดใช้งานเครื่องพิมพ์ (ถ้าปิด API /print จะไม่รับงานพิมพ์)",
        variable=printer_enabled_var,
        command=lambda: on_toggle_printer_enabled(),
    ).pack(pady=(10, 4))

    tk.Label(printer_frame, text="ประเภทเครื่องพิมพ์:").pack(pady=(10, 2))
    tk.Label(printer_frame, text="ESC/POS Thermal (RAW Mode)", fg="green").pack()

    tk.Label(printer_frame, text="เครื่องพิมพ์:").pack(pady=(10, 2))
    printer_combo = ttk.Combobox(printer_frame, values=win_printers, width=40)
    printer_combo.pack()
    printer_combo.set(cfg.get("printer_name", ""))

    tk.Label(printer_frame, text="ขนาดกระดาษ (mm):").pack(pady=(10, 2))
    paper_combo = ttk.Combobox(printer_frame, values=["58", "80"], width=10, state="readonly")
    paper_combo.pack()
    paper_combo.set(cfg.get("paper_size", "80"))

    tk.Label(printer_frame, text="ระยะ feed ก่อนตัด (px):").pack(pady=(10, 2))
    feed_entry = ttk.Entry(printer_frame, width=10)
    feed_entry.insert(0, str(cfg.get("feed_px", 20)))
    feed_entry.pack()

    printer_btn_row = tk.Frame(printer_frame)
    printer_btn_row.pack(pady=(12, 12))

    # ===================== กรอบเครื่องอ่านบัตร =====================
    smartcard_frame = ttk.LabelFrame(root, text="🪪 เครื่องอ่านบัตรประชาชน")
    smartcard_frame.pack(fill="x", padx=14, pady=(0, 14))

    tk.Label(smartcard_frame, text="เครื่องอ่านบัตร:").pack(pady=(10, 2))
    reader_combo = ttk.Combobox(smartcard_frame, values=available_readers, width=40)
    reader_combo.pack()
    current_reader = smartcard_cfg.get("selected_reader")
    if current_reader:
        reader_combo.set(current_reader)
    elif available_readers:
        reader_combo.set(available_readers[0])
    else:
        reader_combo.set("")

    def on_refresh_readers():
        try:
            readers_now = card_reader.list_readers()
        except Exception as e:
            readers_now = []
            messagebox.showerror("ผิดพลาด", f"ไม่สามารถอ่านรายชื่อเครื่องอ่านบัตรได้: {e}")
        reader_combo["values"] = readers_now
        if readers_now and not reader_combo.get():
            reader_combo.set(readers_now[0])

    ttk.Button(smartcard_frame, text="🔄 รีเฟรชรายชื่อเครื่องอ่าน", command=on_refresh_readers).pack(pady=(6, 8))

    read_image_var = tk.BooleanVar(value=bool(smartcard_cfg.get("read_image", True)))
    ttk.Checkbutton(
        smartcard_frame,
        text="อ่านรูปประจำตัว (ถ้าปิด จะส่งรูปเป็นค่าว่าง และอ่านบัตรเร็วขึ้น)",
        variable=read_image_var,
    ).pack(pady=(0, 4))

    smartcard_btn_row = tk.Frame(smartcard_frame)
    smartcard_btn_row.pack(pady=(4, 12))

    def test_print():
        from PIL import Image, ImageDraw, ImageFont
        paper_size = paper_combo.get()
        width = 384 if paper_size == "58" else 576
        height = 180
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        text = f"✅ ESC/POS Test Print\nFeed={feed_entry.get()}px"
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except:
            font = None
        draw.text((40, 60), text, fill="black", font=font)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        payload = {"imageBase64": f"data:image/png;base64,{b64}"}
        url = f"http://127.0.0.1:{PORT}/print"
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.ok:
                messagebox.showinfo("สำเร็จ", "✅ พิมพ์ทดสอบและตัดกระดาษสำเร็จ!")
            else:
                messagebox.showerror("ผิดพลาด", f"❌ พิมพ์ไม่สำเร็จ: {res.status_code}")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"เกิดข้อผิดพลาด: {e}")

    def on_save_printer():
        cfg_new = {
            "printer_type": "ESC/POS Thermal",
            "printer_name": printer_combo.get().strip(),
            "paper_size": paper_combo.get(),
            "feed_px": int(feed_entry.get() or 20),
            "printer_enabled": printer_enabled_var.get()
        }
        save_config(cfg_new)
        messagebox.showinfo("บันทึกแล้ว", "✅ บันทึกการตั้งค่าเครื่องพิมพ์เรียบร้อย")

    def on_save_smartcard():
        selected_reader = reader_combo.get().strip()
        if not selected_reader:
            messagebox.showwarning("แจ้งเตือน", "กรุณาเลือกเครื่องอ่านบัตรก่อนบันทึก")
            return
        try:
            card_reader.set_smartcard_reader(selected_reader, read_image=read_image_var.get())
            messagebox.showinfo("บันทึกแล้ว", "✅ บันทึกการตั้งค่าเครื่องอ่านบัตรเรียบร้อย")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"บันทึกเครื่องอ่านบัตรไม่สำเร็จ: {e}")

    def on_test_read_card():
        url = f"http://127.0.0.1:{PORT}/api/smartcard/read-card-only"
        try:
            res = requests.get(url, params={"readImageFlag": "true"}, timeout=15)
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"เรียก API ไม่สำเร็จ: {e}")
            return

        try:
            data = res.json()
        except Exception:
            messagebox.showerror("ผิดพลาด", f"อ่านผลลัพธ์ไม่ได้ (HTTP {res.status_code})")
            return

        if not res.ok:
            err_msg = data.get("message") or data.get("error") or f"HTTP {res.status_code}"
            messagebox.showerror("อ่านบัตรไม่สำเร็จ", err_msg)
            return

        show_card_data_window(data)

    ttk.Button(printer_btn_row, text="💾 บันทึกเครื่องพิมพ์", command=on_save_printer).pack(side="left", padx=4)
    test_print_btn = ttk.Button(printer_btn_row, text="🖨️ ทดสอบพิมพ์", command=test_print)
    test_print_btn.pack(side="left", padx=4)

    on_toggle_printer_enabled()  # ✅ ตั้ง state เริ่มต้นของช่องต่างๆ (รวมปุ่ม) ให้ตรงกับค่าที่บันทึกไว้

    ttk.Button(smartcard_btn_row, text="💾 บันทึกเครื่องอ่านบัตร", command=on_save_smartcard).pack(side="left", padx=4)
    ttk.Button(smartcard_btn_row, text="🪪 ทดสอบอ่านบัตร", command=on_test_read_card).pack(side="left", padx=4)

    tk.Label(root, text=APP_VERSION, fg="gray", font=("Tahoma", 8)).pack(side="bottom", pady=(0, 6))

    root.mainloop()


def show_card_data_window(data):
    """แสดงข้อมูลที่อ่านได้จากบัตรประชาชน ในรูปแบบเดียวกับที่ /api/smartcard/read-card-only คืนกลับ"""
    win = tk.Toplevel()
    win.title("ผลการทดสอบอ่านบัตรประชาชน")
    win.geometry("480x680")

    try:
        icon_path = os.path.join(base_path, "app.ico")
        win.iconbitmap(icon_path)
    except:
        pass

    # ✅ ทำเป็น scrollable window เพราะมีรูปถ่ายเพิ่มมา เนื้อหายาวขึ้น
    canvas = tk.Canvas(win, borderwidth=0, highlightthickness=0)
    vsb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    container = tk.Frame(canvas)
    canvas.create_window((0, 0), window=container, anchor="nw")
    container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    row_idx = 0

    # ✅ แสดงรูปถ่ายจริง (ถ้ามีข้อมูลรูปแนบมา)
    if data.get("image"):
        try:
            img_bytes = base64.b64decode(data["image"])
            pil_img = PIL_Image.open(io.BytesIO(img_bytes))
            pil_img.thumbnail((180, 220))
            photo_ref = ImageTk.PhotoImage(pil_img)
            img_label = tk.Label(container, image=photo_ref)
            img_label.image = photo_ref  # ✅ กัน garbage collect ไม่ให้รูปหาย
            img_label.grid(row=row_idx, column=0, columnspan=2, pady=(0, 12))
            row_idx += 1
        except Exception as e:
            tk.Label(container, text=f"(โหลดรูปไม่สำเร็จ: {e})", fg="red").grid(
                row=row_idx, column=0, columnspan=2, pady=(0, 12)
            )
            row_idx += 1

    field_labels = [
        ("pid", "เลขบัตรประชาชน"),
        ("titleName", "คำนำหน้า (ไทย)"),
        ("fname", "ชื่อ (ไทย)"),
        ("mname", "ชื่อกลาง (ไทย)"),
        ("lname", "นามสกุล (ไทย)"),
        ("titleNameEng", "คำนำหน้า (Eng)"),
        ("fnameEng", "ชื่อ (Eng)"),
        ("mnameEng", "ชื่อกลาง (Eng)"),
        ("lnameEng", "นามสกุล (Eng)"),
        ("birthDate", "วันเกิด (พ.ศ.)"),
        ("sex", "เพศ"),
        ("cardIssuer", "หน่วยงานที่ออกบัตร"),
        ("issueDate", "วันออกบัตร (พ.ศ.)"),
        ("expireDate", "วันหมดอายุ (พ.ศ.)"),
        ("address", "ที่อยู่ (เต็ม)"),
        ("houseNo", "บ้านเลขที่"),
        ("villageNo", "หมู่ที่"),
        ("laneRoad", "ตรอก/ซอย/ถนน"),
        ("subDistrict", "ตำบล/แขวง"),
        ("district", "อำเภอ/เขต"),
        ("province", "จังหวัด"),
    ]

    for key, label in field_labels:
        value = data.get(key, "")
        tk.Label(container, text=f"{label}:", anchor="w", font=("Tahoma", 9, "bold")).grid(
            row=row_idx, column=0, sticky="nw", pady=3, padx=(0, 8)
        )
        tk.Label(container, text=value or "-", anchor="w", wraplength=280, justify="left").grid(
            row=row_idx, column=1, sticky="nw", pady=3
        )
        row_idx += 1

    ttk.Button(win, text="ปิด", command=win.destroy).pack(side="bottom", pady=(6, 10))


# =========================
# PRINTER ENUM (ESC/POS ONLY)
# =========================
def list_windows_printers():
    """
    คืนค่ารายชื่อเครื่องพิมพ์ที่คาดว่าเป็น ESC/POS เท่านั้น
    โดยกรองจากชื่อ driver หรือ port
    """
    escpos_printers = []
    try:
        printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
        for p in printers:
            name = p[2]
            try:
                handle = win32print.OpenPrinter(name)
                info = win32print.GetPrinter(handle, 2)
                driver = info.get("pDriverName", "").upper()
                port = info.get("pPortName", "").upper()
                win32print.ClosePrinter(handle)

                # ✅ เงื่อนไขตรวจ ESC/POS printer
                if any(keyword in (name + driver + port) for keyword in [
                    "POS", "THERMAL", "XP-", "TM-", "GP-", "XPRINTER", "BIXOLON", "SUNMI", "RONGTA", "ESC", "RAW", "USB001"
                ]):
                    escpos_printers.append(name)
            except Exception:
                continue
    except Exception as e:
        print("⚠️ EnumPrinters failed:", e)
        return []

    return escpos_printers



# =========================
# SYSTEM TRAY + FLASK THREAD
# =========================
def start_tray(backend_module):
    APP_NAME = f"AuthenChart API ({APP_VERSION})"

    try:
        icon_path = Path(__file__).with_name("app.png")
        img = PILImageForTray.open(icon_path)
    except:
        img = PILImageForTray.new("RGB", (64, 64), (0, 160, 90))

    icon = Icon(APP_NAME, img, APP_NAME)

    def action_open_settings(icon_, item):
        threading.Thread(target=open_settings_window, daemon=True).start()

    def action_restart(icon_, item):
        run_flask_thread(backend_module)

    def action_quit(icon_, item):
        icon_.stop()
        os._exit(0)

    icon.menu = Menu(
        MenuItem("🖨️ ตั้งค่าเครื่องพิมพ์", action_open_settings),
        MenuItem("⬆️ ตรวจสอบอัปเดต", action_check_update),
        MenuItem("🔄 รีสตาร์ทเซิร์ฟเวอร์", action_restart),
        MenuItem("❌ ออก", action_quit),
    )
    icon.run()


def run_flask_thread(backend_module):
    def _run():
        app = backend_module.app
        try:
            CORS(app)
        except:
            pass
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    threading.Thread(target=_run, daemon=True).start()


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    app_paths.migrate_legacy_config()
    backend = load_backend_and_patch()
    run_flask_thread(backend)
    time.sleep(0.8)
    threading.Thread(target=silent_startup_update_check, daemon=True).start()
    start_tray(backend)
