# AuthenAPI — Windows

เซิร์ฟเวอร์ภายในเครื่อง (`http://127.0.0.1:9333`) สำหรับพิมพ์ใบเสร็จ ESC/POS และอ่านบัตรประชาชนไทย พร้อมไอคอนที่ System Tray

## ดาวน์โหลด / ติดตั้ง

**[ดาวน์โหลด AuthenAPI-Setup.exe (เวอร์ชันล่าสุด)](https://github.com/arofatsabuding/authenchart-printer-windows/releases/latest/download/AuthenAPI-Setup.exe)**

1. เปิด `AuthenAPI-Setup.exe` (ถ้า Windows SmartScreen เตือน กด **More info → Run anyway**)
2. เลือกโฟลเดอร์ติดตั้ง (ค่าเริ่มต้น `C:\Program Files\AuthenAPI`) และเลือกว่าจะสร้าง shortcut / เปิดอัตโนมัติตอนเปิดเครื่องไหม
3. เสร็จแล้วโปรแกรมจะอยู่ที่ System Tray — คลิกขวาที่ไอคอนเพื่อตั้งค่าเครื่องพิมพ์และเครื่องอ่านบัตร

- ค่าตั้งค่าเก็บที่ `%APPDATA%\AuthenAPI\config.json` (ย้ายจากเวอร์ชันเก่าให้อัตโนมัติ)
- อัปเดต: โปรแกรมเช็ค GitHub Releases ตอนเปิด และจากเมนู "ตรวจสอบอัปเดต" → ดาวน์โหลดตัวติดตั้งแล้วติดตั้งทับให้เอง
- ถอนการติดตั้ง: Settings → Apps → AuthenAPI

## Build release

ต้องมี: Python venv (`.venv`) + [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`)

1. แก้ `APP_VERSION` ใน `tray_runner.py` (เช่น `v2.1.1`)
2. build ตัวโปรแกรม แล้ว build ตัวติดตั้ง (PowerShell):
   ```powershell
   .venv\Scripts\python.exe -m PyInstaller AuthenAPI.spec --noconfirm --distpath dist-release --workpath build
   & "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=2.1.1 installer\AuthenAPI.iss
   ```
3. สร้าง GitHub release tag `v2.1.1` แนบไฟล์จาก `dist-release\`:
   - `AuthenAPI-Setup.exe` — ตัวที่โปรแกรม v2.1.0 ขึ้นไปใช้อัปเดต
   - `AuthenAPI.exe` — สำหรับเครื่องที่ยังเป็น v2.0.x (ตัวอัปเดตเก่าหาไฟล์ชื่อนี้)

ชื่อไฟล์ต้องตรงตามนี้เป๊ะ และ tag ต้องมีเลขสูงกว่า `APP_VERSION` ของเครื่องลูกค้า ระบบอัปเดตถึงจะเห็น
