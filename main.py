from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
import io
import os
import sys
from PIL import Image, ImageWin
import win32print
import win32ui

from smartcard_reader import register_smartcard_routes

app = Flask(__name__)
CORS(app)

# ✅ config อยู่ที่ %APPDATA%\AuthenAPI\config.json (ตอนรัน .exe) — ดู app_paths.py
from app_paths import APP_DIR as base_path, CONFIG_FILE

card_reader = register_smartcard_routes(app, CONFIG_FILE)


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok"}), 200


@app.route("/print", methods=["POST"])
def print_image():
    try:
        data = request.json
        base64_image = data.get("imageBase64")

        if not base64_image:
            return jsonify({"error": "Missing base64 image"}), 400

        # ลบ prefix เช่น data:image/png;base64,
        base64_image = base64_image.split(",")[-1]

        # แปลง base64 เป็น image object
        image_data = base64.b64decode(base64_image)
        image = Image.open(io.BytesIO(image_data))

        # พิมพ์ภาพ
        print_image_win(image)

        # สั่งตัดกระดาษ (ถ้าเครื่องพิมพ์รองรับ ESC/POS)
        # cut_paper()

        return jsonify({"message": "✅ พิมพ์สำเร็จ"}), 200

    except Exception as e:
        print("❌ Error:", e)
        return jsonify({"error": str(e)}), 500


def print_image_win(image: Image.Image):
    printer_name = win32print.GetDefaultPrinter()
    hPrinter = win32print.OpenPrinter(printer_name)

    hDC = win32ui.CreateDC()
    hDC.CreatePrinterDC(printer_name)
    hDC.StartDoc("Print Job")
    hDC.StartPage()

    # ขนาดความกว้าง 80mm = 576px (สำหรับเครื่องพิมพ์ทั่วไป)
    width = 576
    ratio = width / image.width
    height = int(image.height * ratio)
    image = image.resize((width, height))

    dib = ImageWin.Dib(image)
    dib.draw(hDC.GetHandleOutput(), (0, 0, width, height))

    hDC.EndPage()
    hDC.EndDoc()
    hDC.DeleteDC()
    win32print.ClosePrinter(hPrinter)


def cut_paper(printer_name=None):
    try:
        if not printer_name:
            printer_name = win32print.GetDefaultPrinter()

        hPrinter = win32print.OpenPrinter(printer_name)
        hJob = win32print.StartDocPrinter(hPrinter, 1, ("Cut Paper", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)

        # คำสั่ง ESC/POS ตัดกระดาษ
        cut_command = b'\x1D\x56\x00'  # หรือ b'\x1D\x56\x41\x00'

        win32print.WritePrinter(hPrinter, cut_command)

        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)
    except Exception as e:
        print("❌ Cut Error:", e)
    finally:
        try:
            win32print.ClosePrinter(hPrinter)
        except:
            pass


@app.route("/printers", methods=["GET"])
def get_printers():
    try:
        printers = list_printers()
        default_printer = win32print.GetDefaultPrinter()
        return jsonify({
            "default_printer": default_printer,
            "available_printers": printers
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def list_printers():
    printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
    return [printer[2] for printer in printers]


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9333)