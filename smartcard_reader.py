# smartcard_reader.py
# ==============================================================
# Thai National ID Smart Card Reader (PC/SC via pyscard)
# ==============================================================
# pip install pyscard --break-system-packages
#
# ตัวอย่างการใช้งานร่วมกับ Flask (ดู smartcard_routes() ด้านล่าง)

import base64
import json
import os
import threading
import time
from datetime import datetime, timezone
from smartcard.System import readers as pcsc_readers
from smartcard.util import toHexString
from smartcard.Exceptions import NoCardException, CardConnectionException
from smartcard.CardMonitoring import CardMonitor, CardObserver

# ✅ เครื่องอ่านบัตร (PC/SC) รับได้ทีละ 1 connection เท่านั้น
# ถ้ามีหลาย request (เช่น /terminals กับ /read-card-only) ยิงพร้อมกัน
# จะไป "รีเซ็ตบัตร" กลางคันของกันและกัน — ใช้ lock นี้บังคับให้ทำทีละคำสั่งเท่านั้น
_SMARTCARD_LOCK = threading.Lock()

# ✅ หน่วงเวลาสั้นๆ ระหว่างคำสั่ง APDU ตอนอ่านรูป (40 คำสั่งติดกัน — จุดเดียวที่เคยเจอ
# "communications error" (0x8010002F) / "card reset" (0x80100068) มาก่อน)
# ฟิลด์ทั่วไปอื่นๆ สั้นแค่ 2 คำสั่ง ไม่เคย error เลยไม่ต้องหน่วง (เร็วขึ้น)
_APDU_DELAY_SEC = 0.01

# --------------------------------------------------------------
# APDU Commands (มาตรฐานสำหรับบัตรประชาชนไทย - Thai National ID Card)
# --------------------------------------------------------------
CMD_SELECT_APPLET = [0x00, 0xA4, 0x04, 0x00, 0x08,
                      0xA0, 0x00, 0x00, 0x00, 0x54, 0x48, 0x00, 0x01]

CMD_CID          = [0x80, 0xB0, 0x00, 0x04, 0x02, 0x00, 0x0D]
CMD_FULLNAME_TH  = [0x80, 0xB0, 0x00, 0x11, 0x02, 0x00, 0x64]
CMD_FULLNAME_EN  = [0x80, 0xB0, 0x00, 0x75, 0x02, 0x00, 0x64]
CMD_BIRTH        = [0x80, 0xB0, 0x00, 0xD9, 0x02, 0x00, 0x08]
CMD_SEX          = [0x80, 0xB0, 0x00, 0xE1, 0x02, 0x00, 0x01]
CMD_CARD_ISSUER  = [0x80, 0xB0, 0x00, 0xF6, 0x02, 0x00, 0x64]
CMD_ISSUE_DATE   = [0x80, 0xB0, 0x01, 0x67, 0x02, 0x00, 0x08]
CMD_EXPIRE_DATE  = [0x80, 0xB0, 0x01, 0x6F, 0x02, 0x00, 0x08]
CMD_ADDRESS      = [0x80, 0xB0, 0x15, 0x79, 0x02, 0x00, 0x64]

CMD_GET_RESPONSE = [0x00, 0xC0, 0x00, 0x00]

# รูปถ่ายแบ่งเป็น 20 บล็อค (มาตรฐานตำแหน่งของบัตรประชาชนไทย)
CMD_PHOTO_BLOCKS = [
    [0x80, 0xB0, 0x01, 0x7B, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x02, 0x7A, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x03, 0x79, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x04, 0x78, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x05, 0x77, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x06, 0x76, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x07, 0x75, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x08, 0x74, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x09, 0x73, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x0A, 0x72, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x0B, 0x71, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x0C, 0x70, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x0D, 0x6F, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x0E, 0x6E, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x0F, 0x6D, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x10, 0x6C, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x11, 0x6B, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x12, 0x6A, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x13, 0x69, 0x02, 0x00, 0xFF],
    [0x80, 0xB0, 0x14, 0x68, 0x02, 0x00, 0xFF],
]


class SmartCardError(Exception):
    pass


class CardNotPresentError(SmartCardError):
    """ยกขึ้นเมื่อเครื่องอ่านเจอ แต่ไม่มีบัตรเสียบอยู่ในเครื่อง"""
    pass


class SmartCardBusyError(SmartCardError):
    """ยกขึ้นเมื่อมีการอ่านบัตรอีก request กำลังทำงานอยู่แล้ว (กันชนกัน)"""
    pass


class _CardInsertObserver(CardObserver):
    """
    ดักจับเหตุการณ์เสียบ/ถอดบัตรจาก pyscard CardMonitor แล้วสั่งให้ ThaiIDCardReader
    อ่านข้อมูล (ตอนเสียบ) หรือล้างแคช (ตอนถอด) — ทำงานเฉพาะเครื่องอ่านที่เลือกไว้ใน config
    (ถ้ายังไม่ได้เลือกไว้ จะรับบัตรจากเครื่องอ่านตัวแรกที่เจอเหตุการณ์)
    """

    def __init__(self, card_reader):
        super().__init__()
        self.card_reader = card_reader

    def update(self, observable, actions):
        added_cards, removed_cards = actions
        try:
            cfg = self.card_reader.get_smartcard_config()
            selected = cfg.get("selected_reader")
        except Exception:
            selected = None

        for card in added_cards:
            reader_name = str(getattr(card, "reader", ""))
            if selected and reader_name != selected:
                continue
            # ✅ หน่วงเล็กน้อยให้บัตรตั้งตัว (contact settle) ก่อนเริ่มอ่านจริง
            time.sleep(0.4)
            self.card_reader._read_and_cache()

        for card in removed_cards:
            reader_name = str(getattr(card, "reader", ""))
            if selected and reader_name != selected:
                continue
            self.card_reader._clear_cache_on_removal()


class ThaiIDCardReader:
    """
    อ่านข้อมูลจากบัตรประชาชนไทยผ่านเครื่องอ่านบัตร (PC/SC).
    Config (ชื่อเครื่องอ่านที่เลือกใช้) เก็บแยกไว้ใน config.json คีย์ "smartcard"
    """

    def __init__(self, config_path):
        self.config_path = config_path
        self._last_terminal_status = []  # cache ล่าสุด ใช้ตอนมีการอ่านบัตรอยู่พอดี
        # ✅ request coalescing: ถ้ามีการอ่านบัตรแบบเดียวกัน (read_image ตรงกัน)
        # กำลังทำงานอยู่พอดี ให้ request ที่มาทีหลังรอผลลัพธ์เดียวกันแทนที่จะอ่านซ้ำ/โดนปฏิเสธ
        self._inflight_lock = threading.Lock()
        self._inflight = None

        # ✅ แคชข้อมูลบัตรที่อ่านโดย background watcher (เมื่อมีการเสียบบัตรจริง)
        # API endpoints จะอ่านจากตรงนี้เท่านั้น ไม่ไปแตะฮาร์ดแวร์เองอีกต่อไป
        self._cache_lock = threading.Lock()
        self._cached_data = None      # dict ผลลัพธ์เต็มที่อ่านได้ล่าสุด (มี image เสมอ)
        self._cached_error = None     # Exception ล่าสุดถ้าอ่านไม่สำเร็จตอนเสียบบัตร
        self._card_present = False    # มีบัตรเสียบอยู่ในเครื่องที่เลือกไว้ไหม (ตามที่ watcher เห็นล่าสุด)
        self._watcher_started = False
        self._image_refreshing = False  # กำลังอ่านบัตรซ้ำเพื่อเติมรูปอยู่ (กันสั่งซ้อน)

    # ---------------- Config helpers ----------------

    def _load_config(self):
        if not os.path.exists(self.config_path):
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self, cfg):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    def get_smartcard_config(self):
        cfg = self._load_config()
        smartcard = dict(cfg.get("smartcard") or {})
        smartcard.setdefault("selected_reader", None)
        smartcard["read_image"] = bool(smartcard.get("read_image", True))  # ✅ ค่าเริ่มต้น: อ่านรูป
        return smartcard

    def is_read_image_enabled(self):
        return bool(self.get_smartcard_config().get("read_image", True))

    def set_smartcard_reader(self, reader_name=None, read_image=None):
        """บันทึกเครื่องอ่านที่เลือก และ/หรือ การเปิด-ปิดอ่านรูป (ค่าที่เป็น None = คงค่าเดิม)"""
        cfg = self._load_config()
        smartcard = dict(cfg.get("smartcard") or {})
        if reader_name is not None:
            smartcard["selected_reader"] = reader_name
        if read_image is not None:
            smartcard["read_image"] = bool(read_image)
        smartcard.setdefault("selected_reader", None)
        smartcard.setdefault("read_image", True)
        cfg["smartcard"] = smartcard
        self._save_config(cfg)
        return smartcard

    # ---------------- Reader discovery ----------------

    @staticmethod
    def list_readers():
        try:
            return [str(r) for r in pcsc_readers()]
        except Exception as e:
            raise SmartCardError(f"ไม่สามารถอ่านรายชื่อเครื่องอ่านบัตรได้: {e}")

    def list_terminals_with_status(self):
        """
        คืนสถานะของแต่ละเครื่องอ่าน พร้อมบอกว่ามีบัตรเสียบอยู่ไหม (isPresent)
        รูปแบบ: [{"terminalName": "...", "isPresent": true/false}, ...]

        ✅ ถ้าตอนนี้มีการอ่านบัตร (read_card) กำลังทำงานอยู่พอดี (lock ถูกถือ)
        จะไม่ไปแตะเครื่องอ่านซ้ำ (ป้องกันบัตรรีเซ็ตกลางคัน) แต่คืนค่าสถานะล่าสุด
        ที่เคยเช็คได้แทน — เร็วกว่าและไม่ชนกับการอ่านที่กำลังทำอยู่
        """
        try:
            available = pcsc_readers()
        except Exception as e:
            raise SmartCardError(f"ไม่สามารถอ่านรายชื่อเครื่องอ่านบัตรได้: {e}")

        acquired = _SMARTCARD_LOCK.acquire(blocking=False)
        if not acquired:
            if self._last_terminal_status:
                return self._last_terminal_status
            # ยังไม่เคยเช็คสำเร็จมาก่อนเลย แต่ตอนนี้ก็ชนพอดี — ตอบสถานะ "ไม่ทราบ" ไปก่อน
            return [{"terminalName": str(r), "isPresent": None} for r in available]

        try:
            results = []
            for r in available:
                name = str(r)
                is_present = False
                try:
                    conn = r.createConnection()
                    conn.connect()
                    is_present = True
                    try:
                        conn.disconnect()
                    except Exception:
                        pass
                except Exception:
                    is_present = False
                results.append({"terminalName": name, "isPresent": is_present})
            self._last_terminal_status = results
            return results
        finally:
            _SMARTCARD_LOCK.release()

    # ---------------- Background card watcher ----------------

    def start_background_watcher(self):
        """
        ✅ เริ่มเฝ้าดูการเสียบ/ถอดบัตรแบบอัตโนมัติในเบื้องหลัง (เรียกครั้งเดียวตอนเปิดโปรแกรม)
        เมื่อมีการเสียบบัตรจริง จะอ่านข้อมูลครั้งเดียวแล้วเก็บไว้ในแคช — API endpoints
        ทั้งหมดจะอ่านจากแคชนี้เท่านั้น ไม่ไปแตะเครื่องอ่านบัตรเองอีกต่อไป
        """
        if self._watcher_started:
            return
        self._watcher_started = True

        # ✅ เช็คก่อนว่ามีบัตรเสียบค้างอยู่แล้วตั้งแต่ก่อนเปิดโปรแกรมไหม (CardMonitor จะจับได้
        # เฉพาะเหตุการณ์เสียบ/ถอด "หลังจาก" เริ่มเฝ้าดูเท่านั้น ไม่ใช่บัตรที่เสียบค้างอยู่ก่อน)
        def _initial_check():
            try:
                cfg = self.get_smartcard_config()
                selected = cfg.get("selected_reader")
                statuses = self.list_terminals_with_status()
                for s in statuses:
                    if (not selected or s["terminalName"] == selected) and s["isPresent"]:
                        self._read_and_cache()
                        break
            except Exception:
                pass

        threading.Thread(target=_initial_check, daemon=True).start()

        self._card_monitor = CardMonitor()
        self._card_observer = _CardInsertObserver(self)
        self._card_monitor.addObserver(self._card_observer)

    def request_image_refresh(self):
        """
        ✅ เพิ่งเปิดการอ่านรูปขณะบัตรเสียบค้างอยู่ (แคชยังไม่มีรูป) — สั่งอ่านบัตรใหม่ในเบื้องหลัง
        ระหว่างนี้ API ยังตอบข้อมูลเดิมได้ตามปกติ (รูปเป็นค่าว่าง) จนอ่านเสร็จ
        """
        with self._cache_lock:
            data = self._cached_data
            if data is None or "image" in data or self._image_refreshing:
                return
            self._image_refreshing = True

        def _worker():
            try:
                self._read_and_cache()
            finally:
                self._image_refreshing = False

        threading.Thread(target=_worker, daemon=True).start()

    def _read_and_cache(self):
        """อ่านบัตรจริง (ครั้งเดียว) แล้วเก็บผลไว้ในแคช — เรียกจาก watcher เท่านั้น"""
        try:
            # ✅ ปิดการอ่านรูปไว้ = ไม่อ่านรูปจากบัตรเลย (ประหยัดเวลาส่วนที่นานที่สุด)
            data = self.read_card(read_image=self.is_read_image_enabled())
            with self._cache_lock:
                self._cached_data = data
                self._cached_error = None
                self._card_present = True
        except Exception as e:
            with self._cache_lock:
                self._cached_data = None
                self._cached_error = e
                self._card_present = True  # เสียบอยู่ แต่อ่านไม่สำเร็จ

    def _clear_cache_on_removal(self):
        with self._cache_lock:
            self._cached_data = None
            self._cached_error = None
            self._card_present = False

    def get_cached_result(self):
        """คืน (data, error, is_present) จากแคชปัจจุบัน — ไม่แตะฮาร์ดแวร์"""
        with self._cache_lock:
            return self._cached_data, self._cached_error, self._card_present

    def _get_connection(self):
        available = pcsc_readers()
        if not available:
            raise SmartCardError("ไม่พบเครื่องอ่านบัตร (smart card reader) ที่เชื่อมต่ออยู่")

        cfg = self.get_smartcard_config()
        selected_name = cfg.get("selected_reader")

        target_reader = None
        if selected_name:
            for r in available:
                if str(r) == selected_name:
                    target_reader = r
                    break
            if target_reader is None:
                raise SmartCardError(
                    f"ไม่พบเครื่องอ่านที่ตั้งค่าไว้ ('{selected_name}'). "
                    f"เครื่องที่มีอยู่: {[str(r) for r in available]}"
                )
        else:
            # ถ้ายังไม่ได้ตั้งค่า ใช้เครื่องแรกที่เจอ
            target_reader = available[0]

        connection = target_reader.createConnection()
        try:
            connection.connect()
        except NoCardException as e:
            raise CardNotPresentError(f"ไม่มีบัตรเสียบอยู่ในเครื่อง '{target_reader}': {e}")
        except CardConnectionException as e:
            msg = str(e).lower()
            if any(kw in msg for kw in [
                "no smartcard", "not present", "no card", "card is not",
                "no_smartcard", "scard_e_no_smartcard", "scard_w_removed_card"
            ]):
                raise CardNotPresentError(f"ไม่มีบัตรเสียบอยู่ในเครื่อง '{target_reader}': {e}")
            raise SmartCardError(f"เชื่อมต่อเครื่องอ่าน '{target_reader}' ไม่สำเร็จ: {e}")
        except Exception as e:
            msg = str(e).lower()
            if any(kw in msg for kw in [
                "no smartcard", "not present", "no card", "card is not",
                "no_smartcard", "scard_e_no_smartcard", "scard_w_removed_card"
            ]):
                raise CardNotPresentError(f"ไม่มีบัตรเสียบอยู่ในเครื่อง '{target_reader}': {e}")
            raise SmartCardError(f"เชื่อมต่อเครื่องอ่าน '{target_reader}' ไม่สำเร็จ: {e}")
        return connection

    # ---------------- Low level APDU ----------------

    @staticmethod
    def _send(connection, command):
        data, sw1, sw2 = connection.transmit(command)
        return data, sw1, sw2

    def _read_field(self, connection, command):
        # ✅ ฟิลด์ทั่วไปสั้น (2 คำสั่ง/ฟิลด์) ไม่เคยเจอ comm error — ไม่ใส่ delay เพื่อความเร็ว
        _, sw1, sw2 = self._send(connection, command)
        get_response_cmd = CMD_GET_RESPONSE + [sw2]
        data, sw1, sw2 = self._send(connection, get_response_cmd)
        return data

    @staticmethod
    def _decode_raw(raw_bytes):
        """decode แบบเก็บ '#' ไว้ก่อน — ใช้กับฟิลด์ที่ต้อง split (ชื่อ, ที่อยู่)"""
        try:
            text = bytes(raw_bytes).decode("tis-620", errors="ignore")
        except Exception:
            text = bytes(raw_bytes).decode("latin-1", errors="ignore")
        return text

    @classmethod
    def _decode_thai(cls, raw_bytes):
        """decode แบบลบ '#' ทิ้ง — ใช้กับฟิลด์เดี่ยวๆ ที่ไม่มีการแบ่งย่อย"""
        text = cls._decode_raw(raw_bytes)
        return text.replace("#", "").strip()

    # ---------------- Public read ----------------

    def read_card(self, read_image=False):
        """
        ✅ Request coalescing: ถ้ามีการอ่านบัตรแบบเดียวกัน (read_image ตรงกัน) กำลังทำงาน
        อยู่พอดี (เช่น frontend เรียกซ้อนกันจากหลาย component) request ที่มาทีหลังจะ
        "รอผลลัพธ์เดียวกัน" จากการอ่านที่กำลังทำอยู่ แทนที่จะไปแย่งอ่านซ้ำ (ช้าลง+เสี่ยง error)
        หรือโดนปฏิเสธด้วย 409 ทันที
        """
        with self._inflight_lock:
            current = self._inflight
            if current is not None and current["read_image"] == read_image:
                event = current["event"]
                is_leader = False
            else:
                event = threading.Event()
                self._inflight = {"read_image": read_image, "event": event, "result": None, "error": None}
                is_leader = True

        if not is_leader:
            # รอผลลัพธ์จาก request แรกที่กำลังอ่านอยู่ (ให้เวลาพอสำหรับ retry ครบ 5 รอบ)
            finished = event.wait(timeout=20)
            with self._inflight_lock:
                snapshot = self._inflight if self._inflight is not None and self._inflight["event"] is event else None
            if not finished:
                raise SmartCardBusyError("เครื่องอ่านบัตรกำลังถูกใช้งานอยู่ กรุณารอสักครู่แล้วลองใหม่")
            if snapshot is not None and snapshot["error"] is not None:
                raise snapshot["error"]
            if snapshot is not None:
                return snapshot["result"]
            # เผื่อกรณีหายากที่ state ถูกเคลียร์ไปแล้วพอดี — อ่านเองใหม่แทนพลาดไปเลย
            return self._do_actual_read(read_image)

        # เราเป็น "หัวขบวน" ที่ต้องอ่านจริง
        try:
            result = self._do_actual_read(read_image)
            with self._inflight_lock:
                self._inflight["result"] = result
            return result
        except Exception as e:
            with self._inflight_lock:
                self._inflight["error"] = e
            raise
        finally:
            with self._inflight_lock:
                event.set()
                if self._inflight is not None and self._inflight["event"] is event:
                    self._inflight = None

    def _do_actual_read(self, read_image):
        # ✅ รอสั้นๆ (เผื่อ /terminals ปล่อย lock พอดี) ถ้ายังไม่ว่างจริงๆ ให้ตอบกลับทันที
        # แทนที่จะรอค้างจนอาจ timeout ฝั่ง frontend
        acquired = _SMARTCARD_LOCK.acquire(timeout=4)
        if not acquired:
            raise SmartCardBusyError("เครื่องอ่านบัตรกำลังถูกใช้งานอยู่ กรุณารอสักครู่แล้วลองใหม่")
        try:
            max_attempts = 5
            last_error = None
            for attempt in range(1, max_attempts + 1):
                connection = None
                try:
                    connection = self._get_connection()
                    self._send(connection, CMD_SELECT_APPLET)
                    return self._read_all_fields(connection, read_image)
                except CardNotPresentError:
                    # ไม่มีบัตรจริงๆ (ไม่ใช่ปัญหาชั่วคราว) — ไม่ retry ปล่อยให้ route ดักไปตอบทันที
                    raise
                except (CardConnectionException, NoCardException, Exception) as e:
                    last_error = e
                    msg = str(e).lower()
                    is_reset = "reset" in msg
                    if attempt < max_attempts:
                        # ✅ ปัญหาฮาร์ดแวร์/การสื่อสารชั่วขณะ (USB power saving, หน้าสัมผัสหลวม, ฯลฯ)
                        # ไม่ว่าจะเป็น exception ชนิดไหนก็ retry ให้ก่อน โดยผู้ใช้ไม่ต้องกดซ้ำเอง
                        # หน่วงเวลาเพิ่มขึ้นเรื่อยๆ ทุกครั้งที่ retry (0.4, 0.8, 1.2, 1.6 วินาที)
                        time.sleep(0.4 * attempt)
                        continue
                    if is_reset:
                        raise SmartCardError(
                            f"บัตรถูกรีเซ็ตระหว่างอ่านข้อมูลซ้ำหลายครั้งติดต่อกัน (ลองแล้ว {max_attempts} ครั้ง) "
                            f"อาจเกิดจากปัญหาฮาร์ดแวร์ (USB power saving / หน้าสัมผัสหลวม) "
                            f"กรุณาตรวจสอบเครื่องอ่าน/บัตรแล้วลองใหม่: {e}"
                        )
                    raise SmartCardError(
                        f"เกิดข้อผิดพลาดขณะอ่านข้อมูลจากบัตรซ้ำหลายครั้งติดต่อกัน "
                        f"(ลองแล้ว {max_attempts} ครั้ง): {e}"
                    )
                finally:
                    if connection is not None:
                        try:
                            connection.disconnect()
                        except Exception:
                            pass
        finally:
            _SMARTCARD_LOCK.release()

    def _read_all_fields(self, connection, read_image):
        cid = self._decode_thai(self._read_field(connection, CMD_CID))

        # รูปแบบฟิลด์ชื่อบนชิป: title#firstname#middlename#lastname
        # (middlename อาจว่างถ้าไม่มีชื่อกลาง แต่ตำแหน่ง # ยังคงที่ 3 ตัวเสมอ)
        fullname_th_raw = self._decode_raw(self._read_field(connection, CMD_FULLNAME_TH))
        th_parts = fullname_th_raw.split("#")
        title_th = th_parts[0].strip() if len(th_parts) > 0 else ""
        fname_th = th_parts[1].strip() if len(th_parts) > 1 else ""
        mname_th = th_parts[2].strip() if len(th_parts) > 2 else ""
        lname_th = th_parts[3].strip() if len(th_parts) > 3 else ""

        fullname_en_raw = self._decode_raw(self._read_field(connection, CMD_FULLNAME_EN))
        en_parts = fullname_en_raw.split("#")
        title_en = en_parts[0].strip() if len(en_parts) > 0 else ""
        fname_en = en_parts[1].strip() if len(en_parts) > 1 else ""
        mname_en = en_parts[2].strip() if len(en_parts) > 2 else ""
        lname_en = en_parts[3].strip() if len(en_parts) > 3 else ""

        birth_raw = self._decode_thai(self._read_field(connection, CMD_BIRTH))  # YYYYMMDD (พ.ศ.)

        sex_raw = self._decode_thai(self._read_field(connection, CMD_SEX))

        card_issuer = self._decode_thai(self._read_field(connection, CMD_CARD_ISSUER))

        issue_date_raw = self._decode_thai(self._read_field(connection, CMD_ISSUE_DATE))
        expire_date_raw = self._decode_thai(self._read_field(connection, CMD_EXPIRE_DATE))

        # ที่อยู่บนชิปแบ่งด้วย # เป็นท่อนๆ แต่จำนวนช่องว่าง (ตรอก/ซอย/ถนน) ไม่เท่ากันทุกใบ
        # จึงจับคู่ด้วย "คำนำหน้า" ที่ติดมากับข้อมูลแทนตำแหน่งคงที่ แล้วตัดคำนำหน้าออกเหลือแค่ชื่อ
        # หมายเหตุ: ชิปเก็บเป็น "ชื่อ" เท่านั้น ไม่มีรหัสตำบล/อำเภอ/จังหวัดอยู่บนชิป
        address_raw = self._decode_raw(self._read_field(connection, CMD_ADDRESS))
        addr_non_empty = [p.strip() for p in address_raw.split("#") if p.strip() != ""]
        address = " ".join(addr_non_empty)

        village_no = ""
        sub_district = ""
        district = ""
        province = ""
        remaining = []  # ส่วนที่ไม่ตรงคำนำหน้าใดๆ (บ้านเลขที่ / ตรอกซอย / ถนน)

        prefix_map = [
            (("หมู่ที่", "หมู่บ้าน"), "village_no"),
            (("ตำบล", "แขวง"), "sub_district"),
            (("อำเภอ", "เขต"), "district"),
            (("จังหวัด",), "province"),
        ]

        for part in addr_non_empty:
            matched_field = None
            matched_prefix = ""
            for prefixes, field in prefix_map:
                for pre in prefixes:
                    if part.startswith(pre):
                        matched_field = field
                        matched_prefix = pre
                        break
                if matched_field:
                    break

            if matched_field:
                value = part[len(matched_prefix):].strip()
                if matched_field == "village_no":
                    village_no = value
                elif matched_field == "sub_district":
                    sub_district = value
                elif matched_field == "district":
                    district = value
                elif matched_field == "province":
                    province = value
            else:
                remaining.append(part)

        # ส่วนที่เหลือ (ไม่มีคำนำหน้า) เรียงตามลำดับเดิมบนบัตร: บ้านเลขที่ ตามด้วย ตรอก/ซอย/ถนน
        house_no = remaining[0] if len(remaining) > 0 else ""
        lane = remaining[1] if len(remaining) > 1 else ""
        road = remaining[2] if len(remaining) > 2 else ""
        # รวมตรอก/ซอย/ถนน เป็นช่องเดียว (ตรงกับฟอร์มที่มีช่องกรอกเดียว)
        lane_road = " ".join([p for p in remaining[1:] if p != ""])

        result = {
            "pid": cid,
            "titleName": title_th,
            "fname": fname_th,
            "mname": mname_th,
            "lname": lname_th,
            "titleNameEng": title_en,
            "fnameEng": fname_en,
            "mnameEng": mname_en,
            "lnameEng": lname_en,
            "birthDate": birth_raw,
            "sex": sex_raw,
            "cardIssuer": card_issuer,
            "issueDate": issue_date_raw,
            "expireDate": expire_date_raw,
            "address": address,
            "houseNo": house_no,
            "villageNo": village_no,
            "lane": lane,
            "road": road,
            "laneRoad": lane_road,
            "subDistrict": sub_district,
            "district": district,
            "province": province,
        }

        if read_image:
            result["image"] = self._read_photo(connection)

        return result

    def _read_photo(self, connection):
        photo_bytes = bytearray()
        for cmd in CMD_PHOTO_BLOCKS:
            # ✅ ต้องใช้ sw2 ที่ชิปตอบกลับมาจริง (จำนวนไบต์ที่พร้อมให้อ่าน)
            # ไม่ใช่ค่า Le ที่เรา "ขอ" ไปตอนแรก (cmd[-1]) เพราะบางบล็อกชิปมีข้อมูล
            # จริงน้อยกว่าที่ขอ ถ้าใช้ค่าขอไปตรงๆ จะได้ error กลับมาแทนข้อมูล ทำให้รูปสั้นกว่าจริง
            _, sw1, sw2 = self._send(connection, cmd)
            time.sleep(_APDU_DELAY_SEC)
            get_response_cmd = CMD_GET_RESPONSE + [sw2]
            data, sw1, sw2 = self._send(connection, get_response_cmd)
            time.sleep(_APDU_DELAY_SEC)
            photo_bytes.extend(data)
        return base64.b64encode(bytes(photo_bytes)).decode("ascii")


# ==============================================================
# Flask route registration helper
# ==============================================================

def register_smartcard_routes(app, config_path):
    """
    เรียกใน main.py:
        from smartcard_reader import register_smartcard_routes
        register_smartcard_routes(app, CONFIG_FILE)
    """
    from flask import request, jsonify

    card_reader = ThaiIDCardReader(config_path)
    # ✅ เริ่มเฝ้าดูการเสียบ/ถอดบัตรอัตโนมัติ — จากนี้ไป endpoints ทั้งหมด
    # จะอ่านจากแคชเท่านั้น ไม่ไปแตะเครื่องอ่านบัตรเองอีกต่อไป
    card_reader.start_background_watcher()

    @app.route("/api/smartcard/readers", methods=["GET"])
    def list_smartcard_readers():
        try:
            reader_list = card_reader.list_readers()
            current_cfg = card_reader.get_smartcard_config()
            return jsonify({
                "available_readers": reader_list,
                "selected_reader": current_cfg.get("selected_reader")
            }), 200
        except SmartCardError as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/smartcard/terminals", methods=["GET"])
    def smartcard_terminals():
        """
        ✅ ไม่แตะฮาร์ดแวร์อีกต่อไป — แค่บอกชื่อเครื่องอ่านที่มีอยู่ (enumerate เฉยๆ ไม่ connect)
        พร้อมสถานะ isPresent ของเครื่องที่เลือกไว้จากแคชที่ background watcher อัปเดตให้
        """
        try:
            available = card_reader.list_readers()
        except SmartCardError as e:
            return jsonify({"error": str(e)}), 500

        cfg = card_reader.get_smartcard_config()
        selected = cfg.get("selected_reader")
        _, _, is_present = card_reader.get_cached_result()

        results = []
        for name in available:
            if not selected or name == selected:
                results.append({"terminalName": name, "isPresent": is_present})
            else:
                # เครื่องอ่านอื่นที่ไม่ได้เลือกไว้ — ไม่ได้เฝ้าดู ไม่รู้สถานะจริง
                results.append({"terminalName": name, "isPresent": None})
        return jsonify(results), 200

    @app.route("/api/smartcard/config", methods=["GET"])
    def get_smartcard_config():
        return jsonify(card_reader.get_smartcard_config()), 200

    @app.route("/api/smartcard/config", methods=["POST"])
    def set_smartcard_config():
        data = request.json or {}
        reader_name = data.get("reader_name")
        read_image = data.get("read_image")
        if not reader_name and read_image is None:
            return jsonify({"error": "Missing 'reader_name'"}), 400
        updated = card_reader.set_smartcard_reader(reader_name or None,
                                                   None if read_image is None else bool(read_image))
        return jsonify(updated), 200

    def _build_error_envelope(message, status=500, error_label="Internal Server Error"):
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}+00:00"
        return {
            "timestamp": timestamp,
            "status": status,
            "error": error_label,
            "message": message,
        }

    def _get_cached_response():
        """
        ✅ อ่านจากแคชเท่านั้น (ไม่แตะฮาร์ดแวร์) คืน (data_dict, http_status)
        data เป็น None ถ้าไม่มีบัตรเสียบ/อ่านไม่สำเร็จ — status บอกว่าควรตอบอะไรกลับไป
        """
        data, error, is_present = card_reader.get_cached_result()

        if data is not None:
            return data, 200

        if error is not None:
            if isinstance(error, SmartCardBusyError):
                return _build_error_envelope(str(error), status=409, error_label="Conflict"), 409
            if isinstance(error, SmartCardError):
                return _build_error_envelope(str(error)), 500
            return _build_error_envelope(f"Unexpected error: {error}"), 500

        # ไม่มี error แต่ก็ไม่มีข้อมูล แปลว่ายังไม่มีบัตรเสียบเลย
        return _build_error_envelope(
            "jnasmartcardio.Smartcardio$JnaCardNotPresentException: Card not present."
        ), 500

    @app.route("/api/smartcard/read-card-only", methods=["GET"])
    def read_card_only():
        """คืนข้อมูลทั้งหมดที่อ่านได้จากบัตรจากแคช (รูปจะแนบมาด้วยถ้า readImageFlag=true)"""
        read_image_flag = request.args.get("readImageFlag", "false").lower() == "true"
        data, status = _get_cached_response()

        if status != 200:
            return jsonify(data), status

        result = dict(data)  # ก๊อปปี้ออกมาก่อน ไม่แก้ dict ต้นฉบับในแคชโดยตรง
        if not read_image_flag:
            result.pop("image", None)
        elif not card_reader.is_read_image_enabled():
            # ✅ ปิดการอ่านรูปไว้ — ต่อให้ขอ readImageFlag=true ก็ส่งรูปเป็นค่าว่าง
            result["image"] = ""
        elif "image" not in result:
            # เพิ่งเปิดการอ่านรูปขณะบัตรเสียบค้างอยู่ — ส่งค่าว่างไปก่อน แล้วอ่านรูปในเบื้องหลัง
            result["image"] = ""
            card_reader.request_image_refresh()

        return jsonify(result), 200

    return card_reader