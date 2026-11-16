# app_paths.py
# ==============================================================
# ตำแหน่งไฟล์ที่ใช้ร่วมกันระหว่าง tray_runner.py กับ main.py
#
# - APP_DIR    : โฟลเดอร์ที่ตัวโปรแกรมอยู่ (เช่น C:\Program Files\AuthenAPI) — อ่านอย่างเดียว
# - CONFIG_FILE: %APPDATA%\AuthenAPI\config.json — ต้องเขียนได้เสมอ แม้ติดตั้งไว้ใน Program Files
#                (ผู้ใช้ทั่วไปไม่มีสิทธิ์เขียนไฟล์ใน Program Files)
# ตอนรันจาก .py (พัฒนา) ใช้ config.json ข้างไฟล์ .py เหมือนเดิม
# ==============================================================

import os
import shutil
import sys

APP_NAME = "AuthenAPI"

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    _appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    DATA_DIR = os.path.join(_appdata, APP_NAME)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = APP_DIR

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")


def migrate_legacy_config():
    """
    ✅ เวอร์ชันก่อน 2.1 เก็บ config.json ไว้ข้างไฟล์ .exe — ย้ายมาไว้ที่ %APPDATA%\\AuthenAPI ครั้งแรก
    (ถ้ามีไฟล์ใหม่อยู่แล้วจะไม่แตะ) ทำให้ผู้ใช้เดิมไม่ต้องตั้งค่าเครื่องพิมพ์/เครื่องอ่านบัตรใหม่
    """
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError as e:
        print("⚠️ สร้างโฟลเดอร์ config ไม่สำเร็จ:", e)
        return
    if os.path.exists(CONFIG_FILE) or DATA_DIR == APP_DIR:
        return
    candidates = [
        os.path.join(APP_DIR, "config.json"),
        os.path.join(APP_DIR, APP_NAME, "config.json"),  # โฟลเดอร์ที่เวอร์ชันเก่าติดตั้งตัวเองไว้
    ]
    for src in candidates:
        if os.path.isfile(src):
            try:
                shutil.copy2(src, CONFIG_FILE)
                print(f"📦 ย้าย config เดิมจาก {src} -> {CONFIG_FILE}")
            except OSError as e:
                print("⚠️ ย้าย config เดิมไม่สำเร็จ:", e)
            return
