"""zeichess — ortak .db dosyası üzerinden çok oyunculu satranç (PySide6).

Çalıştır:  py zeichess.py
"""
import math
import os
import queue
import random
import struct
import sys
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QSettings, QUrl
from PySide6.QtGui import (QPainter, QColor, QPainterPath, QFont, QPen, QPixmap, QBrush,
                           QRadialGradient, QFontDatabase, QFontMetrics, QPolygonF,
                           QShortcut, QKeySequence, QGuiApplication)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QStackedWidget, QVBoxLayout,
                               QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit,
                               QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
                               QAbstractItemView, QTabWidget, QTextBrowser, QDialog, QSlider,
                               QCheckBox, QComboBox, QFrame, QSizePolicy, QMessageBox,
                               QButtonGroup)

import chess_engine as ce
import db as zdb

APP_NAME = "zeichess"
APP_VERSION = "1.0.0"

C_BG = "#161512"
C_PANEL = "#262421"
C_PANEL2 = "#302e2c"
C_BORDER = "#3d3a37"
C_TEXT = "#bababa"
C_BRIGHT = "#e2e2e2"
C_DIM = "#8b8a88"
C_BLUE = "#3692e7"
C_GREEN = "#629924"
C_RED = "#cc3333"

QSS = """
QWidget { background: %(bg)s; color: %(text)s; font-size: 13px; }
QLabel { background: transparent; }
QFrame#panel, QWidget#panel { background: %(panel)s; border-radius: 4px; }
QPushButton { background: %(panel2)s; color: %(text)s; border: 1px solid %(border)s;
              border-radius: 4px; padding: 6px 12px; }
QPushButton:hover { background: #3a3835; color: %(bright)s; }
QPushButton:pressed { background: #45423e; }
QPushButton:disabled { color: #5c5a57; border-color: #2e2c2a; }
QPushButton#primary { background: %(blue)s; color: white; border: none; font-weight: bold; }
QPushButton#primary:hover { background: #4aa2f0; }
QPushButton#green { background: %(green)s; color: white; border: none; font-weight: bold; }
QPushButton#green:hover { background: #72ad2c; }
QPushButton#red { background: %(red)s; color: white; border: none; font-weight: bold; }
QPushButton#flat { background: transparent; border: none; }
QPushButton#flat:hover { color: %(bright)s; }
QPushButton#pool { background: %(panel)s; border: 1px solid %(border)s; font-size: 20px;
                   color: %(text)s; padding: 14px 6px; }
QPushButton#pool:hover { background: #2f3d4a; border-color: %(blue)s; color: %(bright)s; }
QPushButton#poolOn { background: #233548; border: 2px solid %(blue)s; font-size: 16px;
                     color: %(bright)s; padding: 14px 6px; }
QLineEdit, QComboBox { background: %(panel2)s; border: 1px solid %(border)s; border-radius: 4px;
                       padding: 6px; color: %(bright)s; }
QLineEdit:focus { border-color: %(blue)s; }
QTableWidget { background: %(panel)s; border: none; gridline-color: %(border)s;
               selection-background-color: #2f4a63; selection-color: %(bright)s; }
QHeaderView::section { background: %(panel2)s; color: %(dim)s; border: none; padding: 6px;
                       font-weight: bold; }
QTabWidget::pane { border: none; background: %(panel)s; }
QTabBar::tab { background: transparent; color: %(dim)s; padding: 8px 16px; border: none; }
QTabBar::tab:selected { color: %(bright)s; border-bottom: 2px solid %(blue)s; }
QTextBrowser { background: %(panel)s; border: none; }
QScrollBar:vertical { background: %(panel)s; width: 10px; }
QScrollBar::handle:vertical { background: #4a4744; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QCheckBox { background: transparent; }
QSlider::groove:horizontal { height: 6px; background: %(panel2)s; border-radius: 3px; }
QSlider::handle:horizontal { background: %(blue)s; width: 16px; margin: -6px 0; border-radius: 8px; }
QToolTip { background: %(panel2)s; color: %(bright)s; border: 1px solid %(border)s; }
""" % dict(bg=C_BG, panel=C_PANEL, panel2=C_PANEL2, border=C_BORDER, text=C_TEXT,
           bright=C_BRIGHT, dim=C_DIM, blue=C_BLUE, green=C_GREEN, red=C_RED)

REASONS = {
    "mate": "Şah mat", "resign": "{loser} pes etti", "timeout": "{loser} için süre bitti",
    "timeout_draw": "Süre bitti • yetersiz materyal", "stalemate": "Pat",
    "repetition": "Üç kez tekrar", "fifty": "50 hamle kuralı", "material": "Yetersiz materyal",
    "agreement": "Anlaşmalı beraberlik", "abort": "Oyun iptal edildi",
}
POOLS = [(1, 0), (2, 1), (3, 0), (3, 2), (5, 0), (5, 3), (10, 0), (10, 5), (15, 10), (30, 0),
         (30, 20)]
MINUTES = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18,
           19, 20, 25, 30, 35, 40, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180]
INCREMENTS = list(range(0, 21)) + [25, 30, 35, 40, 45, 60, 90, 120, 150, 180]
GLYPH = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙"}


def fmt_clock(ms):
    ms = max(0, ms)
    s = ms / 1000.0
    if s >= 3600:
        return "%d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)
    if s < 10:
        return "0:%04.1f" % (math.floor(s * 10) / 10)
    s = int(s)
    return "%02d:%02d" % (s // 60, s % 60)


def rating_text(r, games):
    return "%d%s" % (r, "?" if games < 10 else "")


# =============================================================== arka plan DB
class Net:
    """Tüm veritabanı işleri tek bir arka plan iş parçacığında sırayla çalışır;
    arayüz donmaz. Sonuçlar ana iş parçacığında geri çağrılır."""

    def __init__(self, path):
        self.q = queue.Queue()
        self.ex = ThreadPoolExecutor(max_workers=1)
        self.db = None
        self.ex.submit(self._open, path).result()

    def _open(self, path):
        self.db = zdb.DB(path)

    def call(self, method, *args, cb=None, err=None):
        fut = self.ex.submit(getattr(self.db, method), *args)
        fut.add_done_callback(lambda f: self.q.put((cb, err, f)))

    def sync(self, method, *args):
        return self.ex.submit(getattr(self.db, method), *args).result()

    def pump(self):
        while True:
            try:
                cb, err, f = self.q.get_nowait()
            except queue.Empty:
                return
            exc = f.exception()
            try:
                if exc is not None:
                    if err:
                        err(exc)
                    else:
                        print("DB hatası:", exc, file=sys.stderr)
                elif cb:
                    cb(f.result())
            except Exception as e:  # geri çağrıdaki hata uygulamayı düşürmesin
                import traceback
                traceback.print_exc()
                print("Arayüz hatası:", e, file=sys.stderr)

    def close(self):
        try:
            self.ex.submit(self.db.close).result(timeout=3)
        except Exception:
            pass
        self.ex.shutdown(wait=False)


# =============================================================== sesler
def _write_wav(path, samples, rate=22050):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 30000))
                               for s in samples))


def _tock(freq, dur, decay, noise, rate=22050, seed=1):
    rnd = random.Random(seed)
    out, lp = [], 0.0
    for i in range(int(dur * rate)):
        t = i / rate
        lp = lp * 0.75 + rnd.uniform(-1, 1) * 0.25
        out.append(math.exp(-t * decay) * (0.7 * math.sin(2 * math.pi * freq * t) + noise * lp))
    return out


def _chime(rate=22050):
    out = []
    for f, d in ((660, 0.12), (880, 0.22)):
        for i in range(int(d * rate)):
            t = i / rate
            out.append(0.35 * math.exp(-t * 9) * math.sin(2 * math.pi * f * t))
    return out


class Sounds:
    def __init__(self):
        self.enabled = True
        self.fx = {}
        try:
            from PySide6.QtMultimedia import QSoundEffect
            d = tempfile.mkdtemp(prefix="zeichess_")
            specs = {"move": _tock(220, 0.09, 55, 0.9),
                     "capture": _tock(160, 0.14, 35, 1.4, seed=2),
                     "notify": _chime()}
            for name, samples in specs.items():
                p = os.path.join(d, name + ".wav")
                _write_wav(p, samples)
                e = QSoundEffect()
                e.setSource(QUrl.fromLocalFile(p))
                e.setVolume(0.7)
                self.fx[name] = e
        except Exception:
            self.fx = {}

    def play(self, name):
        if self.enabled and name in self.fx:
            self.fx[name].play()


# =============================================================== taşlar
_PIECE_FONT = None


def piece_font():
    global _PIECE_FONT
    if _PIECE_FONT is None:
        fams = set(QFontDatabase.families())
        for fam in ("Segoe UI Symbol", "Apple Symbols", "DejaVu Sans", "Noto Sans Symbols2",
                    "FreeSerif", "Arial Unicode MS", "Segoe UI"):
            if fam in fams:
                f = QFont(fam)
                if QFontMetrics(f).inFontUcs4(0x265A):
                    _PIECE_FONT = f
                    break
        if _PIECE_FONT is None:
            _PIECE_FONT = QFont()
    return _PIECE_FONT


_SVG = {}


def _svg_renderer(p):
    """cburnett SVG çizici; QtSvg yoksa None (yazı tipi taşlarına düşer)."""
    key = ("w" if p.isupper() else "b") + p.upper()
    if key not in _SVG:
        try:
            from PySide6.QtCore import QByteArray
            from PySide6.QtSvg import QSvgRenderer
            import pieces
            r = QSvgRenderer(QByteArray(pieces.SVG[key].encode("utf-8")))
            _SVG[key] = r if r.isValid() else None
        except Exception:
            _SVG[key] = None
    return _SVG[key]


def piece_pixmap(p, size, dpr=1.0):
    px = int(size * dpr)
    r = _svg_renderer(p)
    if r is not None:
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        qp = QPainter(pm)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setRenderHint(QPainter.SmoothPixmapTransform)
        r.render(qp, QRectF(0, 0, px, px))
        qp.end()
        pm.setDevicePixelRatio(dpr)
        return pm
    return _glyph_pixmap(p, px, dpr)


def _glyph_pixmap(p, px, dpr):
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    idx = "KQRBNP".index(p.upper())
    f = QFont(piece_font())
    f.setPixelSize(int(px * 0.86))
    solid, outline = QPainterPath(), QPainterPath()
    solid.addText(0, 0, f, chr(0x265A + idx))
    outline.addText(0, 0, f, chr(0x2654 + idx))
    br = solid.boundingRect()
    dx = (px - br.width()) / 2 - br.x()
    dy = (px - br.height()) / 2 - br.y() + px * 0.01
    solid.translate(dx, dy)
    outline.translate(dx, dy)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.Antialiasing)
    # hafif gölge
    sh = QPainterPath(solid)
    sh.translate(px * 0.015, px * 0.025)
    qp.fillPath(sh, QColor(0, 0, 0, 70))
    if p.isupper():
        qp.fillPath(solid, QColor("#ffffff"))
        qp.fillPath(outline, QColor("#111111"))
        qp.strokePath(solid, QPen(QColor("#111111"), px * 0.012))
    else:
        qp.fillPath(solid, QColor("#262421"))
        qp.fillPath(outline, QColor("#d8d4cc"))
        qp.strokePath(solid, QPen(QColor("#000000"), px * 0.035))
    qp.end()
    pm.setDevicePixelRatio(dpr)
    return pm


# =============================================================== tahta
class BoardWidget(QWidget):
    moveMade = Signal(str)
    premoveChanged = Signal(object)

    LIGHT = QColor("#f0d9b5")
    DARK = QColor("#b58863")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.pos = ce.Position()
        self.orient = "w"
        self.mode = None          # None | 'move' | 'premove'
        self.my_color = None
        self.legal = []
        self.last = None
        self.sel = None
        self.drag = None          # [kare, QPointF]
        self._was_sel = False
        self.hover = None
        self.premove = None
        self.arrows = []
        self.circles = []
        self.rdrag = None
        self.promo = None         # (frm, to)
        self._pix = {}
        self._pix_key = None

    # ---------------------------------------------------------- durum
    def set_state(self, pos, last=None, mode=None, my_color=None):
        changed = pos.fen() != self.pos.fen()
        self.pos, self.last, self.mode, self.my_color = pos, last, mode, my_color
        self.legal = pos.legal_moves() if mode == "move" else []
        if changed:
            self.promo = None
        if self.sel is not None:
            p = pos.board[self.sel]
            if not mode or not p or ce.color(p) != my_color:
                self.sel = None
                self.drag = None
        if mode != "premove" and self.premove:
            self.premove = None
        self.update()

    def set_orientation(self, c):
        self.orient = c
        self.update()

    def clear_premove(self):
        if self.premove:
            self.premove = None
            self.premoveChanged.emit(None)
            self.update()

    # ---------------------------------------------------------- geometri
    def _geom(self):
        side = int(min(self.width(), self.height()) // 8 * 8)
        return (self.width() - side) / 2.0, (self.height() - side) / 2.0, side / 8.0

    def sq_rect(self, s):
        ox, oy, q = self._geom()
        f, r = s & 7, s >> 3
        col = f if self.orient == "w" else 7 - f
        row = 7 - r if self.orient == "w" else r
        return QRectF(ox + col * q, oy + row * q, q, q)

    def sq_at(self, pt):
        ox, oy, q = self._geom()
        col = math.floor((pt.x() - ox) / q)
        row = math.floor((pt.y() - oy) / q)
        if not (0 <= col < 8 and 0 <= row < 8):
            return None
        f = col if self.orient == "w" else 7 - col
        r = 7 - row if self.orient == "w" else row
        return r * 8 + f

    def dests(self, s):
        if self.mode == "move":
            return {m.to for m in self.legal if m.frm == s}
        if self.mode == "premove":
            return set(ce.premove_dests(self.pos, s))
        return set()

    def _pixmap(self, p, q):
        key = (int(q), self.devicePixelRatioF())
        if key != self._pix_key:
            self._pix = {}
            self._pix_key = key
        if p not in self._pix:
            self._pix[p] = piece_pixmap(p, int(q), self.devicePixelRatioF())
        return self._pix[p]

    def _promo_squares(self):
        frm, to = self.promo
        white = self.pos.board[frm].isupper()
        f = to & 7
        ranks = [7, 6, 5, 4] if white else [0, 1, 2, 3]
        return [(r * 8 + f, pc) for r, pc in zip(ranks, "QNRB")]

    # ---------------------------------------------------------- çizim
    def paintEvent(self, ev):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setRenderHint(QPainter.SmoothPixmapTransform)
        ox, oy, q = self._geom()
        b = self.pos.board
        for s in range(64):
            light = ((s & 7) + (s >> 3)) % 2 == 1
            qp.fillRect(self.sq_rect(s), self.LIGHT if light else self.DARK)
        # son hamle, seçim, ön hamle
        if self.last:
            for s in self.last:
                qp.fillRect(self.sq_rect(s), QColor(155, 199, 0, 105))
        if self.premove:
            for s in self.premove:
                qp.fillRect(self.sq_rect(s), QColor(20, 30, 85, 110))
        if self.sel is not None:
            qp.fillRect(self.sq_rect(self.sel), QColor(20, 85, 30, 128))
        # şah
        if self.pos.in_check():
            k = self.pos.king(self.pos.turn)
            r = self.sq_rect(k)
            g = QRadialGradient(r.center(), q * 0.7)
            g.setColorAt(0, QColor(255, 0, 0, 255))
            g.setColorAt(0.25, QColor(231, 0, 0, 255))
            g.setColorAt(0.9, QColor(169, 0, 0, 0))
            qp.fillRect(r, QBrush(g))
        # koordinatlar
        cf = QFont()
        cf.setPixelSize(max(9, int(q * 0.17)))
        cf.setBold(True)
        qp.setFont(cf)
        for i in range(8):
            f = i if self.orient == "w" else 7 - i
            s = (0 if self.orient == "w" else 7) * 8 + f
            r = self.sq_rect(s)
            light = ((s & 7) + (s >> 3)) % 2 == 1
            qp.setPen(self.DARK if light else self.LIGHT)
            qp.drawText(r.adjusted(0, 0, -q * 0.06, -q * 0.03), Qt.AlignRight | Qt.AlignBottom,
                        ce.FILES[f])
            rk = 7 - i if self.orient == "w" else i
            s = rk * 8 + (0 if self.orient == "w" else 7)
            r = self.sq_rect(s)
            light = ((s & 7) + (s >> 3)) % 2 == 1
            qp.setPen(self.DARK if light else self.LIGHT)
            qp.drawText(r.adjusted(q * 0.05, q * 0.03, 0, 0), Qt.AlignLeft | Qt.AlignTop,
                        str(rk + 1))
        # hedef kareler
        src = self.drag[0] if self.drag else self.sel
        if src is not None:
            premove = self.mode == "premove"
            col = QColor(20, 30, 85, 128) if premove else QColor(20, 85, 30, 128)
            for t in self.dests(src):
                r = self.sq_rect(t)
                if self.drag and self.hover == t:
                    qp.fillRect(r, QColor(col.red(), col.green(), col.blue(), 75))
                if b[t]:
                    path = QPainterPath()
                    path.addRect(r)
                    inner = QPainterPath()
                    inner.addEllipse(r.center(), q * 0.5, q * 0.5)
                    qp.fillPath(path.subtracted(inner), col)
                else:
                    qp.setPen(Qt.NoPen)
                    qp.setBrush(col)
                    qp.drawEllipse(r.center(), q * 0.15, q * 0.15)
        # taşlar
        for s, p in enumerate(b):
            if not p:
                continue
            if self.drag and self.drag[0] == s:
                qp.setOpacity(0.3)
                qp.drawPixmap(self.sq_rect(s).topLeft(), self._pixmap(p, q))
                qp.setOpacity(1.0)
                continue
            if self.promo and s == self.promo[0]:
                continue
            qp.drawPixmap(self.sq_rect(s).topLeft(), self._pixmap(p, q))
        # oklar ve daireler
        green = QColor(21, 120, 27, 170)
        for s in self.circles:
            r = self.sq_rect(s)
            qp.setPen(QPen(green, q * 0.07))
            qp.setBrush(Qt.NoBrush)
            qp.drawEllipse(r.center(), q * 0.46, q * 0.46)
        for a, c in self.arrows:
            self._arrow(qp, self.sq_rect(a).center(), self.sq_rect(c).center(), q, green)
        if self.rdrag is not None and self.hover is not None and self.hover != self.rdrag:
            self._arrow(qp, self.sq_rect(self.rdrag).center(), self.sq_rect(self.hover).center(),
                        q, QColor(21, 120, 27, 110))
        # sürüklenen taş
        if self.drag and b[self.drag[0]]:
            pm = self._pixmap(b[self.drag[0]], q)
            sz = q * 1.15
            qp.drawPixmap(QRectF(self.drag[1].x() - sz / 2, self.drag[1].y() - sz / 2, sz, sz),
                          pm, QRectF(0, 0, pm.width(), pm.height()))
        # terfi seçimi
        if self.promo:
            qp.fillRect(QRectF(ox, oy, q * 8, q * 8), QColor(0, 0, 0, 120))
            white = self.pos.board[self.promo[0]].isupper()
            for s, pc in self._promo_squares():
                r = self.sq_rect(s)
                hov = self.hover == s
                qp.setPen(Qt.NoPen)
                qp.setBrush(QColor("#d0d0d0") if not hov else QColor("#f0a030"))
                qp.drawEllipse(r.center(), q * 0.48, q * 0.48)
                pm = self._pixmap(pc if white else pc.lower(), q)
                qp.drawPixmap(r.adjusted(q * 0.08, q * 0.08, -q * 0.08, -q * 0.08), pm,
                              QRectF(0, 0, pm.width(), pm.height()))
        qp.end()

    @staticmethod
    def _arrow(qp, a, b, q, col):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        ln = math.hypot(dx, dy)
        if ln < 1:
            return
        ux, uy = dx / ln, dy / ln
        head = q * 0.42
        end = QPointF(b.x() - ux * head * 0.9, b.y() - uy * head * 0.9)
        start = QPointF(a.x() + ux * q * 0.2, a.y() + uy * q * 0.2)
        pen = QPen(col, q * 0.16)
        pen.setCapStyle(Qt.FlatCap)
        qp.setPen(pen)
        qp.drawLine(start, end)
        px, py = -uy, ux
        tip = QPointF(b.x() - ux * q * 0.08, b.y() - uy * q * 0.08)
        poly = QPolygonF([tip,
                          QPointF(tip.x() - ux * head + px * head * 0.55,
                                  tip.y() - uy * head + py * head * 0.55),
                          QPointF(tip.x() - ux * head - px * head * 0.55,
                                  tip.y() - uy * head - py * head * 0.55)])
        qp.setPen(Qt.NoPen)
        qp.setBrush(col)
        qp.drawPolygon(poly)

    # ---------------------------------------------------------- fare
    def mousePressEvent(self, ev):
        pt = ev.position()
        s = self.sq_at(pt)
        if self.promo:
            if ev.button() == Qt.LeftButton:
                for ps, pc in self._promo_squares():
                    if ps == s:
                        frm, to = self.promo
                        self.promo = None
                        self.update()
                        self.moveMade.emit(ce.Move(frm, to, pc).uci())
                        return
            self.promo = None
            self.update()
            return
        if ev.button() == Qt.RightButton:
            self.sel = None
            self.drag = None
            self.clear_premove()
            self.rdrag = s
            self.update()
            return
        if ev.button() != Qt.LeftButton:
            return
        self.arrows, self.circles = [], []
        if s is None:
            self.sel = None
            self.update()
            return
        if self.sel is not None and s != self.sel and s in self.dests(self.sel):
            self._complete(self.sel, s)
            return
        p = self.pos.board[s]
        if self.mode and p and ce.color(p) == self.my_color:
            if self.mode == "premove" and self.premove:
                self.clear_premove()
            self._was_sel = self.sel == s
            self.sel = s
            self.drag = [s, pt]
            self.hover = s
            self.update()
            return
        self.sel = None
        self.clear_premove()
        self.update()

    def mouseMoveEvent(self, ev):
        pt = ev.position()
        h = self.sq_at(pt)
        if self.drag:
            self.drag[1] = pt
            self.hover = h
            self.update()
        elif h != self.hover:
            self.hover = h
            if self.rdrag is not None or self.promo:
                self.update()

    def mouseReleaseEvent(self, ev):
        t = self.sq_at(ev.position())
        if ev.button() == Qt.RightButton:
            a = self.rdrag
            self.rdrag = None
            if a is not None and t is not None:
                if a == t:
                    if t in self.circles:
                        self.circles.remove(t)
                    else:
                        self.circles.append(t)
                else:
                    if (a, t) in self.arrows:
                        self.arrows.remove((a, t))
                    else:
                        self.arrows.append((a, t))
            self.update()
            return
        if ev.button() != Qt.LeftButton or not self.drag:
            return
        s0 = self.drag[0]
        self.drag = None
        if t is not None and t != s0 and t in self.dests(s0):
            self._complete(s0, t)
            return
        if t == s0:
            if self._was_sel:
                self.sel = None
        else:
            self.sel = None
        self.update()

    def _complete(self, frm, to):
        self.sel = None
        self.drag = None
        if self.mode == "premove":
            self.premove = (frm, to)
            self.premoveChanged.emit((frm, to))
            self.update()
            return
        if self.mode != "move":
            return
        p = self.pos.board[frm]
        if p in "Pp" and (to >> 3) in (0, 7):
            self.promo = (frm, to)
            self.update()
            return
        self.update()
        self.moveMade.emit(ce.Move(frm, to, None).uci())


# =============================================================== yardımcılar
def hbox(*items, spacing=6, margins=(0, 0, 0, 0)):
    w = QWidget()
    w.setObjectName("hb")
    w.setStyleSheet("#hb { background: transparent; }")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        else:
            lay.addWidget(it)
    return w


def label(text="", size=None, bold=False, color=None, wrap=False):
    lb = QLabel(text)
    st = []
    if size:
        st.append("font-size: %dpx" % size)
    if bold:
        st.append("font-weight: bold")
    if color:
        st.append("color: %s" % color)
    if st:
        lb.setStyleSheet("; ".join(st) + ";")
    lb.setWordWrap(wrap)
    return lb


def button(text, slot=None, obj=None, tip=None):
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setShowGrid(False)
    t.setFocusPolicy(Qt.NoFocus)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    t.setCursor(Qt.PointingHandCursor)
    return t


def cell(text, data=None, align=None, color=None):
    it = QTableWidgetItem(str(text))
    if data is not None:
        it.setData(Qt.UserRole, data)
    if align:
        it.setTextAlignment(align)
    if color:
        it.setForeground(QColor(color))
    return it


def fill_table(t, rows):
    """rows: [[QTableWidgetItem,...]] — seçimi koruyarak yeniler."""
    sel = None
    if t.currentRow() >= 0 and t.item(t.currentRow(), 0):
        sel = t.item(t.currentRow(), 0).data(Qt.UserRole)
    t.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, it in enumerate(row):
            t.setItem(i, j, it)
        if sel is not None and row and row[0].data(Qt.UserRole) == sel:
            t.selectRow(i)


# =============================================================== giriş
class LoginPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        s = win.settings
        card = QFrame()
        card.setObjectName("panel")
        card.setFixedWidth(460)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(10)
        logo = label("♞ zeichess", 34, True, C_BRIGHT)
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)
        sub = label("Ortak dosya üzerinden satranç", 13, color=C_DIM)
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(14)
        lay.addWidget(label("Ortak veritabanı dosyası (.db)", bold=True))
        self.path = QLineEdit(s.value("db_path", ""))
        self.path.setPlaceholderText(r"Örn. \\sunucu\paylasim\zeichess.db  ya da  Z:\ortak\zeichess.db")
        lay.addWidget(hbox(self.path, button("Gözat…", self.browse)))
        hint = label("Herkes aynı dosyayı seçer. Dosya yoksa oluşturulur.", 11, color=C_DIM)
        lay.addWidget(hint)
        lay.addSpacing(6)
        lay.addWidget(label("Kullanıcı adı", bold=True))
        self.name = QLineEdit(s.value("username", ""))
        self.name.setPlaceholderText("Kullanıcı adın (yoksa yeni hesap açılır)")
        self.name.returnPressed.connect(self.login)
        self.path.returnPressed.connect(self.login)
        lay.addWidget(self.name)
        self.err = label("", 12, color="#e05252", wrap=True)
        lay.addWidget(self.err)
        self.btn = button("GİRİŞ", self.login, "primary")
        self.btn.setMinimumHeight(40)
        lay.addWidget(self.btn)
        ver = label("v" + APP_VERSION, 11, color="#5c5a57")
        ver.setAlignment(Qt.AlignRight)
        lay.addWidget(ver)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(2)

    def browse(self):
        p, _ = QFileDialog.getSaveFileName(self, "Ortak veritabanı dosyası", self.path.text(),
                                           "zeichess veritabanı (*.db);;Tüm dosyalar (*)",
                                           options=QFileDialog.DontConfirmOverwrite)
        if p:
            self.path.setText(p)

    def login(self):
        path = self.path.text().strip().strip('"')
        if not path:
            self.err.setText("Veritabanı dosya yolunu gir.")
            return
        if not path.lower().endswith(".db") and not os.path.isfile(path):
            path += ".db"
            self.path.setText(path)
        self.err.setText("")
        self.btn.setEnabled(False)
        self.btn.setText("Bağlanıyor…")
        QApplication.processEvents()
        try:
            self.win.do_login(path, self.name.text())
        except Exception as e:
            self.err.setText(str(e))
        finally:
            self.btn.setEnabled(True)
            self.btn.setText("GİRİŞ")


# =============================================================== oyun oluştur
class CreateGameDialog(QDialog):
    def __init__(self, parent, players, target=None, rated=True):
        super().__init__(parent)
        self.setWindowTitle("Oyun oluştur")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(label("Oyun oluştur", 20, True, C_BRIGHT))
        lay.addWidget(label("Rakip", bold=True))
        self.opp = QComboBox()
        self.opp.setEditable(True)
        self.opp.addItem("Herkese açık ilan")
        for p in players:
            self.opp.addItem(p)
        if target:
            self.opp.setCurrentText(target)
        lay.addWidget(self.opp)
        self.min_lb = label("", bold=True)
        lay.addWidget(self.min_lb)
        self.min_sl = QSlider(Qt.Horizontal)
        self.min_sl.setRange(0, len(MINUTES) - 1)
        self.min_sl.setValue(MINUTES.index(5))
        lay.addWidget(self.min_sl)
        self.inc_lb = label("", bold=True)
        lay.addWidget(self.inc_lb)
        self.inc_sl = QSlider(Qt.Horizontal)
        self.inc_sl.setRange(0, len(INCREMENTS) - 1)
        self.inc_sl.setValue(3)
        lay.addWidget(self.inc_sl)
        self.speed_lb = label("", 12, color=C_DIM)
        lay.addWidget(self.speed_lb)
        self.rated = QCheckBox("Dereceli (Elo puanı değişir)")
        self.rated.setChecked(rated)
        lay.addWidget(self.rated)
        lay.addWidget(label("Renk", bold=True))
        self.color = "random"
        grp = QButtonGroup(self)
        row = []
        for key, txt in (("black", "♚ Siyah"), ("random", "◐ Rastgele"), ("white", "♔ Beyaz")):
            b = QPushButton(txt)
            b.setCheckable(True)
            b.setChecked(key == "random")
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, k=key: setattr(self, "color", k))
            grp.addButton(b)
            row.append(b)
        lay.addWidget(hbox(*row))
        lay.addSpacing(6)
        ok = button("OYUN OLUŞTUR", self.accept, "primary")
        ok.setMinimumHeight(40)
        lay.addWidget(ok)
        self.min_sl.valueChanged.connect(self._upd)
        self.inc_sl.valueChanged.connect(self._upd)
        self._upd()
        self.setStyleSheet("QPushButton:checked { background: %s; color: white; border: none; }"
                           % C_BLUE)

    def _upd(self):
        self.min_lb.setText("Oyuncu başına dakika: %s" % zdb.fmt_minutes(self.base()))
        self.inc_lb.setText("Hamle başına eklenen saniye: %d" % self.inc())
        self.speed_lb.setText("Tür: " + zdb.SPEED_NAMES[zdb.speed_of(self.base(), self.inc())])

    def base(self):
        return int(MINUTES[self.min_sl.value()] * 60)

    def inc(self):
        return INCREMENTS[self.inc_sl.value()]

    def target(self):
        t = self.opp.currentText().strip()
        return None if not t or t == "Herkese açık ilan" else t


# =============================================================== lobi
class LobbyPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.seek_id = None
        self.seek_kind = None      # 'pool' | 'custom' | 'challenge'
        self.seek_info = None
        self.pool_btns = {}
        self.data = None
        self._busy = False
        self._entered = 0
        self.players_list = []

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(16)

        # sol: hızlı eşleşme
        left = QVBoxLayout()
        left.setSpacing(10)
        self.banner = QFrame()
        self.banner.setObjectName("panel")
        bl = QVBoxLayout(self.banner)
        bl.setContentsMargins(12, 10, 12, 10)
        self.banner_lb = label("", 14, True, C_BRIGHT, wrap=True)
        self.banner_btn = button("", None, "primary")
        self.banner_btn.clicked.connect(self._banner_click)
        bl.addWidget(hbox(self.banner_lb, None, self.banner_btn))
        self.banner.hide()
        left.addWidget(self.banner)
        self.incoming_box = QVBoxLayout()
        left.addLayout(self.incoming_box)
        self.incoming_widgets = {}

        left.addWidget(label("Hızlı eşleşme", 18, True, C_BRIGHT))
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (m, inc) in enumerate(POOLS):
            b = button("", None, "pool")
            b.clicked.connect(lambda _=False, m=m, inc=inc: self.pool_click(m, inc))
            b.setMinimumHeight(86)
            self.pool_btns[(m, inc)] = b
            grid.addWidget(b, i // 3, i % 3)
        custom = button("Özel", self.create_game, "pool")
        custom.setMinimumHeight(86)
        grid.addWidget(custom, 3, 2)
        self._paint_pools()
        gw = QWidget()
        gw.setLayout(grid)
        left.addWidget(gw)
        self.rated = QCheckBox("Dereceli oyna (Elo)")
        self.rated.setChecked(win.settings.value("rated", "1") == "1")
        self.rated.toggled.connect(lambda v: win.settings.setValue("rated", "1" if v else "0"))
        left.addWidget(self.rated)
        left.addWidget(hbox(button("OYUN OLUŞTUR", self.create_game, "primary"),
                            button("ARKADAŞA MEYDAN OKU", self.challenge_selected)))
        self.msg = label("", 12, color="#e05252", wrap=True)
        left.addWidget(self.msg)
        left.addStretch(1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setMaximumWidth(560)
        lw.setMinimumWidth(420)
        root.addWidget(lw, 5)

        # sağ: sekmeler
        self.tabs = QTabWidget()
        self.seeks_t = table(["Oyuncu", "Puan", "Süre", "Tür", "Mod"])
        self.seeks_t.cellDoubleClicked.connect(self._seek_dbl)
        self.seeks_t.cellClicked.connect(self._seek_click)
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.seeks_t)
        sl.addWidget(label("  İlana tıkla → oyuna katıl", 11, color=C_DIM))
        self.tabs.addTab(sw, "Lobi")
        self.play_t = table(["Beyaz", "Siyah", "Süre", "Hamle"])
        self.play_t.cellDoubleClicked.connect(self._watch)
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.play_t)
        pl.addWidget(label("  Çift tıkla → izle", 11, color=C_DIM))
        self.tabs.addTab(pw, "Oynanan oyunlar")
        self.players_t = table(["", "Oyuncu", "Bullet", "Blitz", "Rapid", "Klasik"])
        self.players_t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.players_t.setColumnWidth(0, 28)
        self.players_t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.players_t.cellDoubleClicked.connect(self._player_dbl)
        ow = QWidget()
        ol = QVBoxLayout(ow)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(self.players_t)
        ol.addWidget(hbox(label("  Çift tıkla → profil", 11, color=C_DIM), None,
                          button("Profil", self._player_profile),
                          button("Meydan oku", self.challenge_selected, "primary"),
                          margins=(0, 0, 6, 6)))
        self.tabs.addTab(ow, "Oyuncular")
        root.addWidget(self.tabs, 6)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    # ---------------------------------------------------------- yaşam döngüsü
    def enter(self):
        self._entered = time.time()
        self.msg.setText("")
        self.timer.start(900)
        self.poll()

    def leave(self):
        self.timer.stop()

    def _paint_pools(self):
        for (m, inc), b in self.pool_btns.items():
            on = self.seek_kind == "pool" and self.seek_info == (m, inc)
            b.setObjectName("poolOn" if on else "pool")
            sp = zdb.SPEED_NAMES[zdb.speed_of(m * 60, inc)]
            b.setText("%d+%d\n%s" % (m, inc, "Rakip aranıyor…" if on else sp))
            b.style().unpolish(b)
            b.style().polish(b)

    # ---------------------------------------------------------- yoklama
    def poll(self):
        if self._busy or not self.win.net:
            return
        self._busy = True
        self.win.net.call("poll_lobby", self.win.me, self.seek_id, cb=self._on_poll,
                          err=self._on_err)

    def _on_err(self, e):
        self._busy = False
        self.msg.setText("Bağlantı hatası: %s" % e)

    def _on_poll(self, d):
        self._busy = False
        if self.win.stack.currentWidget() is not self:
            return
        self.data = d
        if self.msg.text().startswith("Bağlantı hatası"):
            self.msg.setText("")
        mine = d["mine"]
        if self.seek_id and mine:
            if mine.get("game_id"):
                self._clear_seek()
                self.win.show_game(mine["game_id"])
                return
            if mine.get("gone") or mine.get("declined"):
                if mine.get("declined"):
                    self.msg.setText("%s davetini reddetti." % (mine.get("target") or "Rakip"))
                self._clear_seek()
        # yeni başlayan aktif oyun (örn. rövanş) → otomatik aç
        if d["active"] and not self.seek_id:
            self.banner_lb.setText("Devam eden bir oyunun var.")
            self.banner_btn.setText("OYUNA DÖN")
            self.banner.show()
        elif self.seek_id and self.seek_kind != "pool":
            info = self.seek_info
            if self.seek_kind == "challenge":
                self.banner_lb.setText("%s bekleniyor… (%s)" % (info[0], info[1]))
            else:
                self.banner_lb.setText("İlanın lobide: %s" % info[1])
            self.banner_btn.setText("İPTAL")
            self.banner.show()
        else:
            self.banner.hide()
        self._fill_incoming(d["incoming"])
        me = self.win.me
        rows = []
        for s in d["seeks"]:
            mine_seek = s["creator"] == me
            col = C_BLUE if mine_seek else None
            r, n = s["rating"]
            rows.append([cell(s["creator"] + (" (sen)" if mine_seek else ""), s["id"], color=col),
                         cell(rating_text(r, n)), cell(zdb.tc_text(s["base"], s["inc"])),
                         cell(zdb.SPEED_NAMES[s["speed"]]),
                         cell("Dereceli" if s["rated"] else "Dostane")])
        fill_table(self.seeks_t, rows)
        rows = []
        for g in d["playing"]:
            rows.append([cell("%s (%s)" % (g["white"], g["white_rating"]), g["id"]),
                         cell("%s (%s)" % (g["black"], g["black_rating"])),
                         cell(zdb.tc_text(g["base"], g["inc"])),
                         cell((len(g["moves"].split()) + 1) // 2)])
        fill_table(self.play_t, rows)
        self.players_list = d["players"]
        ps = sorted(d["players"], key=lambda p: (not p["online"], -p["ratings"]["blitz"][0],
                                                 p["name"].lower()))
        rows = []
        for p in ps:
            dot = cell("●", p["name"], Qt.AlignCenter, C_GREEN if p["online"] else "#4a4744")
            nm = cell(p["name"] + (" (sen)" if p["name"] == me else ""), p["name"],
                      color=C_BRIGHT if p["online"] else C_DIM)
            rows.append([dot, nm] + [cell(rating_text(*p["ratings"][s]))
                                     for s in zdb.SPEEDS])
        fill_table(self.players_t, rows)
        self.tabs.setTabText(2, "Oyuncular (%d çevrimiçi)" % sum(p["online"] for p in ps))
        self.tabs.setTabText(0, "Lobi (%d)" % len(d["seeks"]))
        self.tabs.setTabText(1, "Oynanan oyunlar (%d)" % len(d["playing"]))

    def _fill_incoming(self, incoming):
        ids = {s["id"] for s in incoming}
        for sid in list(self.incoming_widgets):
            if sid not in ids:
                self.incoming_widgets.pop(sid).deleteLater()
        new = False
        for s in incoming:
            if s["id"] in self.incoming_widgets:
                continue
            new = True
            fr = QFrame()
            fr.setObjectName("panel")
            fr.setStyleSheet("QFrame#panel { border: 2px solid %s; }" % C_GREEN)
            r, n = s["rating"]
            col = {"white": "sen siyahsın", "black": "sen beyazsın"}.get(s["color"], "renk rastgele")
            txt = "♞  %s (%s) sana meydan okuyor\n%s • %s • %s • %s" % (
                s["creator"], rating_text(r, n), zdb.tc_text(s["base"], s["inc"]),
                zdb.SPEED_NAMES[s["speed"]], "Dereceli" if s["rated"] else "Dostane", col)
            lay = QHBoxLayout(fr)
            lay.setContentsMargins(12, 8, 12, 8)
            lay.addWidget(label(txt, 13, color=C_BRIGHT, wrap=True), 1)
            lay.addWidget(button("KABUL", lambda _=False, i=s["id"]: self.accept(i), "green"))
            lay.addWidget(button("REDDET", lambda _=False, i=s["id"]: self.decline(i)))
            self.incoming_box.addWidget(fr)
            self.incoming_widgets[s["id"]] = fr
        if new:
            self.win.sounds.play("notify")
            QApplication.alert(self.win)

    # ---------------------------------------------------------- eylemler
    def _clear_seek(self):
        self.seek_id = self.seek_kind = self.seek_info = None
        self._paint_pools()

    def cancel_seek(self):
        if self.seek_id:
            self.win.net.call("cancel_seek", self.win.me, self.seek_id)
        self._clear_seek()
        self.banner.hide()

    def _banner_click(self):
        if self.seek_id:
            self.cancel_seek()
        elif self.data and self.data["active"]:
            self.win.show_game(self.data["active"])

    def _err(self, e):
        self.msg.setText(str(e))
        self.poll()

    def pool_click(self, m, inc):
        if self.seek_kind == "pool" and self.seek_info == (m, inc):
            self.cancel_seek()
            return
        if self.seek_id:
            self.cancel_seek()
        self.msg.setText("")
        rated = self.rated.isChecked()

        def done(res):
            kind, i = res
            if kind == "game":
                self.win.show_game(i)
            else:
                self.seek_id, self.seek_kind, self.seek_info = i, "pool", (m, inc)
                self._paint_pools()
        self.win.net.call("quick_pair", self.win.me, m * 60, inc, rated, cb=done, err=self._err)

    def create_game(self, target=None):
        names = [p["name"] for p in self.players_list if p["name"] != self.win.me]
        dlg = CreateGameDialog(self, names, target if isinstance(target, str) else None,
                               self.rated.isChecked())
        if dlg.exec() != QDialog.Accepted:
            return
        if self.seek_id:
            self.cancel_seek()
        base, inc, tgt = dlg.base(), dlg.inc(), dlg.target()
        tc = zdb.tc_text(base, inc)

        def done(i):
            self.seek_id = i
            self.seek_kind = "challenge" if tgt else "custom"
            self.seek_info = (tgt, tc)
            self.poll()
        self.win.net.call("create_seek", self.win.me, base, inc, dlg.rated.isChecked(),
                          dlg.color, tgt, cb=done, err=self._err)

    def challenge_selected(self):
        t = None
        r = self.players_t.currentRow()
        if self.tabs.currentIndex() == 2 and r >= 0:
            t = self.players_t.item(r, 1).data(Qt.UserRole)
            if t == self.win.me:
                t = None
        self.create_game(t or "")

    def accept(self, sid):
        if self.seek_id:
            self.cancel_seek()
        self.win.net.call("accept_seek", self.win.me, sid, cb=self.win.show_game, err=self._err)

    def decline(self, sid):
        self.win.net.call("decline_seek", self.win.me, sid, cb=lambda _: self.poll())
        w = self.incoming_widgets.pop(sid, None)
        if w:
            w.deleteLater()

    def _seek_click(self, row, col):
        sid = self.seeks_t.item(row, 0).data(Qt.UserRole)
        if sid == self.seek_id:
            return
        self.accept(sid)

    def _seek_dbl(self, row, col):
        pass

    def _watch(self, row, col):
        self.win.show_game(self.play_t.item(row, 0).data(Qt.UserRole))

    def _player_dbl(self, row, col):
        self.win.show_profile(self.players_t.item(row, 1).data(Qt.UserRole))

    def _player_profile(self):
        r = self.players_t.currentRow()
        if r >= 0:
            self.win.show_profile(self.players_t.item(r, 1).data(Qt.UserRole))


# =============================================================== oyun ekranı
class PlayerBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("pbar")
        self.setStyleSheet("#pbar { background: transparent; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)
        self.dot = label("●", 14, color="#4a4744")
        self.name = label("", 15, True, C_BRIGHT)
        self.rating = label("", 13, color=C_DIM)
        self.mat = label("", 15, color=C_DIM)
        self.rating.setTextFormat(Qt.RichText)
        for w in (self.dot, self.name, self.rating):
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addWidget(self.mat)

    def set(self, name, rating, online, diff=None, mat=""):
        self.name.setText(name)
        txt = str(rating) if rating is not None else ""
        if diff is not None:
            txt += ' <b style="color:%s">%+d</b>' % (
                C_GREEN if diff > 0 else C_RED if diff < 0 else C_DIM, diff)
        self.rating.setText(txt)
        self.dot.setStyleSheet("font-size:14px; color:%s;" % (C_GREEN if online else "#4a4744"))
        self.dot.setToolTip("Çevrimiçi" if online else "Çevrimdışı")
        self.mat.setText(mat)


class ClockLabel(QLabel):
    def __init__(self):
        super().__init__("--:--")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setMinimumWidth(150)
        self.setMinimumHeight(54)
        self._st = None
        self.set_style(False, False)

    def set_style(self, running, low):
        st = (running, low)
        if st == self._st:
            return
        self._st = st
        if running and low:
            bg, fg = "#a02222", "#ffffff"
        elif running:
            bg, fg = "#3f5a26", "#ffffff"
        else:
            bg, fg = C_PANEL, C_DIM
        self.setStyleSheet("background:%s; color:%s; font-size:34px; font-family:'Consolas',"
                           "'Menlo','DejaVu Sans Mono',monospace; padding:2px 14px; "
                           "border-radius:4px;" % (bg, fg))


class GamePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.gid = None
        self.g = None
        self.game = ce.Game()
        self.moves_str = ""
        self.my = None
        self.orient = "w"
        self.view = None
        self.turn_start = time.monotonic()
        self.epoch = 0
        self._busy = False
        self.flag_sent = None
        self.chat_after = 0
        self.premove = None
        self.online = {}
        self._resign_arm = 0
        self._last_table_n = -1
        self._last_status = None

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(14)

        # sol: bilgi + sohbet
        left = QVBoxLayout()
        info = QFrame()
        info.setObjectName("panel")
        il = QVBoxLayout(info)
        il.setContentsMargins(14, 12, 14, 12)
        self.info_tc = label("", 16, True, C_BRIGHT)
        self.info_sub = label("", 12, color=C_DIM, wrap=True)
        self.info_players = label("", 13, wrap=True)
        self.info_players.setTextFormat(Qt.RichText)
        il.addWidget(self.info_tc)
        il.addWidget(self.info_sub)
        il.addSpacing(6)
        il.addWidget(self.info_players)
        left.addWidget(info)
        chat = QFrame()
        chat.setObjectName("panel")
        cl = QVBoxLayout(chat)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.addWidget(label("Sohbet", 13, True, C_BRIGHT))
        self.chat_view = QTextBrowser()
        self.chat_view.setOpenLinks(False)
        cl.addWidget(self.chat_view, 1)
        self.chat_in = QLineEdit()
        self.chat_in.setPlaceholderText("Mesaj yaz, Enter…")
        self.chat_in.returnPressed.connect(self.send_chat)
        cl.addWidget(self.chat_in)
        left.addWidget(chat, 1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(260)
        root.addWidget(lw)

        # orta: tahta
        self.board = BoardWidget()
        self.board.moveMade.connect(self.on_board_move)
        self.board.premoveChanged.connect(self._premove_changed)
        root.addWidget(self.board, 1)

        # sağ: saatler, hamleler, düğmeler
        right = QVBoxLayout()
        right.setSpacing(0)
        self.top_clock = ClockLabel()
        self.bot_clock = ClockLabel()
        self.plus_btn = button("+15s", self.give_time, "flat", "Rakibine 15 saniye ver")
        self.top_bar = PlayerBar()
        self.bot_bar = PlayerBar()
        right.addWidget(hbox(None, self.plus_btn, self.top_clock))
        right.addSpacing(4)
        mid = QFrame()
        mid.setObjectName("panel")
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        ml.addWidget(self.top_bar)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:%s;" % C_BORDER)
        ml.addWidget(sep)
        self.moves_t = QTableWidget(0, 2)
        self.moves_t.horizontalHeader().setVisible(False)
        self.moves_t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.moves_t.verticalHeader().setDefaultSectionSize(26)
        self.moves_t.verticalHeader().setStyleSheet(
            "QHeaderView::section { background:%s; color:%s; border:none; padding: 0 8px; }"
            % (C_PANEL2, C_DIM))
        self.moves_t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.moves_t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.moves_t.setShowGrid(False)
        self.moves_t.setFocusPolicy(Qt.NoFocus)
        self.moves_t.setStyleSheet("QTableWidget { font-size: 14px; color: %s; }"
                                   "QTableWidget::item { padding-left: 10px; }"
                                   "QTableWidget::item:selected { background: #2f4a63; "
                                   "color: white; font-weight: bold; }" % C_BRIGHT)
        self.moves_t.cellClicked.connect(self._move_clicked)
        ml.addWidget(self.moves_t, 1)
        self.nav = hbox(button("⏮", lambda: self.go(0), "flat", "İlk (↑)"),
                        button("◀", lambda: self.step(-1), "flat", "Geri (←)"),
                        button("▶", lambda: self.step(1), "flat", "İleri (→)"),
                        button("⏭", lambda: self.go(None), "flat", "Son (↓)"),
                        None,
                        button("⇅", self.flip, "flat", "Tahtayı çevir (F)"),
                        spacing=2, margins=(6, 2, 6, 2))
        self.nav.setStyleSheet("#hb { background: transparent; } QPushButton { font-size: 18px; padding: 4px 10px; }")
        ml.addWidget(self.nav)
        # teklif şeridi
        self.offer = QFrame()
        self.offer.setObjectName("offer")
        self.offer.setStyleSheet("#offer { background:#3a3420; }")
        ofl = QHBoxLayout(self.offer)
        ofl.setContentsMargins(10, 6, 10, 6)
        self.offer_lb = label("", 13, True, "#f0d070", wrap=True)
        self.offer_yes = button("✓", None, "green", "Kabul et")
        self.offer_no = button("✕", None, "red", "Reddet")
        ofl.addWidget(self.offer_lb, 1)
        ofl.addWidget(self.offer_yes)
        ofl.addWidget(self.offer_no)
        self.offer_yes.clicked.connect(lambda: self._answer(True))
        self.offer_no.clicked.connect(lambda: self._answer(False))
        self.offer.hide()
        self._offer_kind = None
        ml.addWidget(self.offer)
        # sonuç
        self.result = QFrame()
        self.result.setObjectName("result")
        self.result.setStyleSheet("#result { background:%s; }" % C_PANEL2)
        rl = QVBoxLayout(self.result)
        rl.setContentsMargins(10, 10, 10, 10)
        self.res_score = label("", 22, True, C_BRIGHT)
        self.res_score.setAlignment(Qt.AlignCenter)
        self.res_text = label("", 13, color=C_TEXT)
        self.res_text.setAlignment(Qt.AlignCenter)
        rl.addWidget(self.res_score)
        rl.addWidget(self.res_text)
        self.rematch_btn = button("RÖVANŞ", self.rematch, "primary")
        self.rematch_no = button("✕", self.decline_rematch, "red", "Rövanşı reddet")
        self.lobby_btn = button("YENİ RAKİP", lambda: self.win.show_lobby())
        self.pgn_btn = button("PGN", self.copy_pgn, None, "PGN'i panoya kopyala")
        rl.addWidget(hbox(self.rematch_btn, self.rematch_no, self.lobby_btn, self.pgn_btn))
        self.result.hide()
        ml.addWidget(self.result)
        # eylem düğmeleri
        self.actions = hbox(spacing=4, margins=(6, 4, 6, 6))
        al = self.actions.layout()
        self.abort_btn = button("✕ İptal et", self.abort, None, "Oyunu iptal et (puan değişmez)")
        self.takeback_btn = button("↶ Geri al", self.takeback, None, "Hamle geri alma isteği gönder")
        self.draw_btn = button("½ Berabere", self.offer_draw, None, "Beraberlik teklif et")
        self.resign_btn = button("⚑ Pes et", self.resign, None, "Pes et")
        for b in (self.abort_btn, self.takeback_btn, self.draw_btn, self.resign_btn):
            al.addWidget(b)
        ml.addWidget(self.actions)
        self.back_btn = button("Lobiye dön", lambda: self.win.show_lobby())
        ml.addWidget(hbox(self.back_btn, margins=(6, 0, 6, 6)))
        ml.addWidget(sep2 := QFrame())
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background:%s;" % C_BORDER)
        ml.addWidget(self.bot_bar)
        right.addWidget(mid, 1)
        right.addSpacing(4)
        right.addWidget(hbox(None, self.bot_clock))
        self.status = label("", 12, color=C_DIM, wrap=True)
        right.addWidget(self.status)
        rw = QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(340)
        root.addWidget(rw)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        for key, fn in ((Qt.Key_Left, lambda: self.step(-1)), (Qt.Key_Right, lambda: self.step(1)),
                        (Qt.Key_Up, lambda: self.go(0)), (Qt.Key_Down, lambda: self.go(None)),
                        (Qt.Key_F, self.flip)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ---------------------------------------------------------- aç/kapat
    def open(self, gid):
        self.gid = gid
        self.g = None
        self.game = ce.Game()
        self.moves_str = ""
        self.view = None
        self.epoch += 1
        self.flag_sent = None
        self.chat_after = 0
        self.premove = None
        self.board.premove = None
        self.board.arrows, self.board.circles = [], []
        self.board.sel = None
        self.chat_view.clear()
        self._last_table_n = -1
        self._last_status = None
        self._busy = False
        self.status.setText("Yükleniyor…")
        self.offer.hide()
        self.result.hide()
        self.poll(force=True)
        self.poll_timer.start(200)
        self.tick_timer.start(100)
        self.setFocus()

    def leave(self):
        self.poll_timer.stop()
        self.tick_timer.stop()

    # ---------------------------------------------------------- yoklama
    def poll(self, force=False):
        if not self.gid or (self._busy and not force):
            return
        self._busy = True
        ep, gid = self.epoch, self.gid
        self.win.net.call("poll_game", gid, self.chat_after,
                          cb=lambda d: self._on_poll(d, ep, gid), err=self._poll_err)

    def _poll_err(self, e):
        self._busy = False
        self.status.setText("Bağlantı hatası: %s" % e)

    def _on_poll(self, d, ep, gid):
        self._busy = False
        if gid != self.gid or ep != self.epoch:
            return
        self.apply(d)

    def _call(self, method, *args):
        """Oyun eylemi: sonuç yeni durumu getirir. Önceki yoklamalar yok sayılır."""
        self.epoch += 1
        ep, gid = self.epoch, self.gid
        self.win.net.call(method, gid, *args, cb=lambda d: self._on_write(d, ep, gid),
                          err=self._write_err)

    def _on_write(self, d, ep, gid):
        if gid != self.gid or ep != self.epoch:
            return
        self.apply(d)

    def _write_err(self, e):
        self.status.setText(str(e))
        self.epoch += 1
        self._busy = False
        self.poll(force=True)

    # ---------------------------------------------------------- durum uygula
    def apply(self, d):
        g = d["game"]
        first = self.g is None
        old = self.g
        self.g = g
        self.online = d.get("online", {})
        me = self.win.me
        self.my = "w" if g["white"] == me else "b" if g["black"] == me else None
        if first:
            self.orient = self.my or "w"
            self.board.set_orientation(self.orient)
        if g["moves"] != self.moves_str:
            new = g["moves"].split()
            cur = self.game.moves
            if new[:len(cur)] == cur:
                for u in new[len(cur):]:
                    self.game.push_uci(u)
            else:
                self.game = ce.Game(new)
                self.view = None
            self.moves_str = g["moves"]
            if first:
                self.turn_start = time.monotonic() - max(0.0, time.time() - g["last_ts"])
            else:
                self.turn_start = time.monotonic()
                if len(new) > len(cur):
                    self._sound_last()
            self.flag_sent = None
            self._try_premove()
        for c in d.get("chat", []):
            if c["id"] <= self.chat_after:
                continue
            self.chat_after = c["id"]
            col = C_BLUE if c["name"] == me else C_BRIGHT
            self.chat_view.append('<span style="color:%s;font-weight:bold">%s</span> '
                                  '<span style="color:%s">%s</span>'
                                  % (col, c["name"], C_TEXT, _esc(c["text"])))
        if g["status"] != self._last_status:
            if self._last_status == "started" and g["status"] != "started":
                self.win.sounds.play("notify")
            elif self._last_status is None and g["status"] == "started" and not g["moves"]:
                self.win.sounds.play("notify")
            self._last_status = g["status"]
        if g.get("rematch_id") and old is not None and not old.get("rematch_id") \
                and self.my is not None:
            self.open(g["rematch_id"])
            return
        if first and g.get("rematch_id") is None and g["status"] != "started" and self.my:
            pass
        self.refresh()

    def _sound_last(self):
        san = self.game.sans[-1] if self.game.sans else ""
        self.win.sounds.play("capture" if "x" in san else "move")

    # ---------------------------------------------------------- yardımcı
    def turn(self):
        return "w" if len(self.game.moves) % 2 == 0 else "b"

    def started(self):
        return self.g is not None and self.g["status"] == "started"

    def clock_ms(self, c):
        ms = self.g["white_ms"] if c == "w" else self.g["black_ms"]
        if self.started() and len(self.game.moves) >= 2 and self.turn() == c:
            ms -= (time.monotonic() - self.turn_start) * 1000
        return ms

    def view_ply(self):
        n = len(self.game.moves)
        return n if self.view is None else max(0, min(self.view, n))

    # ---------------------------------------------------------- çizim
    def refresh(self):
        g = self.g
        if g is None:
            return
        n = len(self.game.moves)
        vp = self.view_ply()
        pos = self.game.positions[vp]
        last = None
        if vp > 0:
            m = ce.Move.from_uci(self.game.moves[vp - 1])
            last = (m.frm, m.to)
        mode = None
        live = self.started() and self.my and vp == n
        if live:
            mode = "move" if self.turn() == self.my else "premove"
        self.board.set_state(pos, last, mode, self.my)
        # oyuncular
        top = ce.opp(self.orient)
        bot = self.orient
        cnt = pos.material()
        for c, bar in ((top, self.top_bar), (bot, self.bot_bar)):
            name = g["white"] if c == "w" else g["black"]
            rating = g["white_rating"] if c == "w" else g["black_rating"]
            diff = g["white_diff"] if c == "w" else g["black_diff"]
            bar.set(name, rating, self.online.get(name, False), diff, _material_text(cnt, c))
        sp = zdb.SPEED_NAMES[g["speed"]]
        self.info_tc.setText("%s • %s" % (zdb.tc_text(g["base"], g["inc"]), sp))
        self.info_sub.setText("%s • %s" % ("Dereceli" if g["rated"] else "Dostane",
                                           time.strftime("%d.%m.%Y %H:%M",
                                                         time.localtime(g["created"]))))
        self.info_players.setText(
            '<span style="color:#fff">♔</span> %s (%s)<br><span style="color:#888">♚</span> %s (%s)'
            % (g["white"], g["white_rating"], g["black"], g["black_rating"]))
        # hamle tablosu
        if n != self._last_table_n:
            self._last_table_n = n
            rows = (n + 1) // 2
            self.moves_t.setRowCount(rows)
            self.moves_t.setVerticalHeaderLabels([str(i + 1) for i in range(rows)])
            for i, san in enumerate(self.game.sans):
                self.moves_t.setItem(i // 2, i % 2, QTableWidgetItem(san))
            if n % 2 == 1:
                self.moves_t.setItem(rows - 1, 1, QTableWidgetItem(""))
        if vp > 0:
            self.moves_t.setCurrentCell((vp - 1) // 2, (vp - 1) % 2)
            self.moves_t.scrollToItem(self.moves_t.item((vp - 1) // 2, (vp - 1) % 2))
        else:
            self.moves_t.clearSelection()
        self._refresh_controls()
        self.tick()

    def _refresh_controls(self):
        g = self.g
        n = len(self.game.moves)
        player = self.my is not None
        live = self.started()
        self.actions.setVisible(player and live)
        self.back_btn.setVisible(not player or not live)
        self.plus_btn.setVisible(player and live and n >= 2)
        if player and live:
            can_abort = n < 2
            self.abort_btn.setVisible(can_abort)
            self.takeback_btn.setVisible(not can_abort)
            self.draw_btn.setVisible(not can_abort)
            self.resign_btn.setVisible(not can_abort)
            mine_tb = g["takeback_offer"] == self.my
            self.takeback_btn.setEnabled(not g["takeback_offer"]
                                         and n >= (1 if self.my == "w" else 2))
            self.takeback_btn.setText("↶ İstek gönderildi" if mine_tb else "↶ Geri al")
            mine_dr = g["draw_offer"] == self.my
            self.draw_btn.setEnabled(not mine_dr)
            self.draw_btn.setText("½ Teklif edildi" if mine_dr else "½ Berabere")
            if time.time() - self._resign_arm > 3:
                self.resign_btn.setText("⚑ Pes et")
                self.resign_btn.setObjectName("")
                self.resign_btn.style().unpolish(self.resign_btn)
                self.resign_btn.style().polish(self.resign_btn)
        # teklif şeridi
        opp = ce.opp(self.my) if player else None
        kind = None
        if player and live and g["takeback_offer"] == opp:
            kind, txt = "takeback", "Rakip hamle geri almak istiyor"
        elif player and live and g["draw_offer"] == opp:
            kind, txt = "draw", "Rakip beraberlik teklif ediyor"
        elif player and not live and g["rematch_offer"] == opp and not g["rematch_id"]:
            kind, txt = "rematch", "Rakip rövanş istiyor"
        self._offer_kind = kind
        if kind and kind != "rematch":
            self.offer_lb.setText(txt)
            self.offer.show()
        else:
            self.offer.hide()
        # sonuç
        if not live:
            self.result.show()
            if g["status"] == "aborted":
                self.res_score.setText("İptal")
                self.res_text.setText(REASONS["abort"])
            else:
                res = g["result"]
                self.res_score.setText(res.replace("1/2", "½"))
                loser = g["white"] if res == "0-1" else g["black"]
                who = {"1-0": "Beyaz kazandı", "0-1": "Siyah kazandı"}.get(res, "Berabere")
                self.res_text.setText("%s • %s" % (REASONS.get(g["reason"], g["reason"])
                                                   .format(loser=loser), who))
            self.rematch_btn.setVisible(player and not g["rematch_id"])
            self.rematch_no.setVisible(kind == "rematch")
            if kind == "rematch":
                self.rematch_btn.setText("RÖVANŞI KABUL ET")
            elif g["rematch_offer"] == self.my:
                self.rematch_btn.setText("Rövanş teklif edildi…")
            else:
                self.rematch_btn.setText("RÖVANŞ")
            self.rematch_btn.setEnabled(g["rematch_offer"] != self.my)
            self.pgn_btn.setVisible(True)
        else:
            self.result.hide()
        # durum yazısı
        if live:
            if self.view is not None and self.view < n:
                st = "Geçmiş hamle gösteriliyor — ⏭ ile son konuma dön"
            elif player:
                st = "Sıra sende" if self.turn() == self.my else "Rakibin düşünüyor…"
                if n < 2:
                    st += " (saat ilk iki hamleden sonra başlar)"
                if self.premove:
                    st = "Ön hamle hazır • sağ tık ile iptal"
            else:
                st = "İzleniyor • Sıra %s" % ("beyazda" if self.turn() == "w" else "siyahta")
            if self.game.pos.in_check() and (self.view is None or self.view >= n):
                st = "Şah! " + st
        else:
            st = ""
        if not self.status.text().startswith("Bağlantı") or live:
            self.status.setText(st)

    def tick(self):
        if self.g is None:
            return
        live = self.started()
        n = len(self.game.moves)
        top, bot = ce.opp(self.orient), self.orient
        for c, lab in ((top, self.top_clock), (bot, self.bot_clock)):
            ms = self.clock_ms(c)
            lab.setText(fmt_clock(ms))
            running = live and self.turn() == c and n >= 2
            lab.set_style(running or (live and self.turn() == c),
                          running and ms < 10000)
        if live and self.my and n >= 2 and self.flag_sent != n:
            c = self.turn()
            ms = self.clock_ms(c)
            if (c == self.my and ms <= 0) or (c != self.my and ms <= -500):
                self.flag_sent = n
                self._call("claim_timeout", c, n)

    # ---------------------------------------------------------- tahta olayları
    def on_board_move(self, uci):
        if not self.started() or self.my != self.turn() or self.view_ply() != len(self.game.moves):
            return
        n = len(self.game.moves)
        if n >= 2 and self.clock_ms(self.my) <= 0:
            return
        think = int((time.monotonic() - self.turn_start) * 1000)
        try:
            self.game.push_uci(uci)
        except ValueError:
            return
        key = "white_ms" if self.my == "w" else "black_ms"
        if n >= 2:
            self.g[key] = self.g[key] - think + self.g["inc"] * 1000
        self.moves_str = " ".join(self.game.moves)
        self.turn_start = time.monotonic()
        self.view = None
        self._sound_last()
        self._call("play_move", self.win.me, uci, think)
        self.refresh()

    def _premove_changed(self, pm):
        self.premove = pm
        self._refresh_controls()

    def _try_premove(self):
        pm = self.premove
        if not pm or not self.started() or self.my != self.turn():
            return
        self.premove = None
        self.board.premove = None
        frm, to = pm
        for m in self.game.pos.legal_moves():
            if m.frm == frm and m.to == to and m.promo in (None, "Q"):
                QTimer.singleShot(0, lambda u=m.uci(): self.on_board_move(u))
                return

    # ---------------------------------------------------------- gezinme
    def go(self, ply):
        n = len(self.game.moves)
        self.view = None if ply is None or ply >= n else max(0, ply)
        self.refresh()

    def step(self, d):
        self.go(self.view_ply() + d)

    def flip(self):
        self.orient = ce.opp(self.orient)
        self.board.set_orientation(self.orient)
        self.refresh()

    def _move_clicked(self, row, col):
        ply = row * 2 + col + 1
        if ply <= len(self.game.moves):
            self.go(ply)

    # ---------------------------------------------------------- eylemler
    def abort(self):
        self._call("abort", self.win.me)

    def resign(self):
        if time.time() - self._resign_arm > 3:
            self._resign_arm = time.time()
            self.resign_btn.setText("Emin misin? ⚑")
            self.resign_btn.setObjectName("red")
            self.resign_btn.style().unpolish(self.resign_btn)
            self.resign_btn.style().polish(self.resign_btn)
            return
        self._resign_arm = 0
        self._call("resign", self.win.me)

    def offer_draw(self):
        self._call("offer_draw", self.win.me)

    def takeback(self):
        self._call("offer_takeback", self.win.me)

    def give_time(self):
        self._call("give_time", self.win.me)

    def _answer(self, yes):
        if self._offer_kind == "draw":
            self._call("answer_draw", self.win.me, yes)
        elif self._offer_kind == "takeback":
            self._call("answer_takeback", self.win.me, yes)
        self.offer.hide()

    def rematch(self):
        self._call("offer_rematch", self.win.me)

    def decline_rematch(self):
        self._call("decline_rematch", self.win.me)

    def send_chat(self):
        t = self.chat_in.text().strip()
        if t and self.gid:
            self.chat_in.clear()
            self.win.net.call("send_chat", self.gid, self.win.me, t, cb=lambda _: self.poll(True))

    def copy_pgn(self):
        g = self.g
        h = {"Event": "zeichess %s" % ("dereceli" if g["rated"] else "dostane"),
             "Date": time.strftime("%Y.%m.%d", time.localtime(g["created"])),
             "White": g["white"], "Black": g["black"],
             "Result": g["result"] if g["status"] == "finished" else "*",
             "WhiteElo": g["white_rating"], "BlackElo": g["black_rating"],
             "TimeControl": "%d+%d" % (g["base"], g["inc"])}
        QGuiApplication.clipboard().setText(self.game.pgn(h))
        self.status.setText("PGN panoya kopyalandı.")


def _esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _material_text(cnt, c):
    """c renginin yediği taşlar (fazlası) ve puan farkı."""
    out, score = "", 0
    for k in "QRBNP":
        w, b = cnt.get(k, 0), cnt.get(k.lower(), 0)
        score += (w - b) * ce.VALUES[k]
        d = (w - b) if c == "w" else (b - w)
        if d > 0:
            out += GLYPH[k] * d
    score = score if c == "w" else -score
    return out + (" +%d" % score if score > 0 else "")


# =============================================================== profil
class ProfilePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.name = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)
        self.title = label("", 26, True, C_BRIGHT)
        self.sub = label("", 13, color=C_DIM)
        self.chal = button("MEYDAN OKU", self.challenge, "primary")
        root.addWidget(hbox(self.title, 12, self.sub, None, self.chal,
                            button("Lobiye dön", lambda: self.win.show_lobby())))
        self.cards = QHBoxLayout()
        self.card_lbs = {}
        for s in zdb.SPEEDS:
            fr = QFrame()
            fr.setObjectName("panel")
            fl = QVBoxLayout(fr)
            fl.setContentsMargins(16, 10, 16, 10)
            fl.addWidget(label(zdb.SPEED_NAMES[s].upper(), 12, True, C_DIM))
            v = label("", 26, True, C_BRIGHT)
            n = label("", 12, color=C_DIM)
            fl.addWidget(v)
            fl.addWidget(n)
            self.card_lbs[s] = (v, n)
            self.cards.addWidget(fr)
        root.addLayout(self.cards)
        self.stats = label("", 14)
        root.addWidget(self.stats)
        self.games_t = table(["Tarih", "Beyaz", "Siyah", "Sonuç", "Sebep", "Süre", "Puan"])
        self.games_t.cellDoubleClicked.connect(self._open)
        root.addWidget(self.games_t, 1)
        root.addWidget(label("Çift tıkla → oyunu incele", 11, color=C_DIM))

    def load(self, name):
        self.name = name
        self.win.net.call("profile", name, cb=self._fill,
                          err=lambda e: QMessageBox.warning(self, APP_NAME, str(e)))

    def _fill(self, p):
        self.name = p["name"]
        self.title.setText(p["name"])
        self.sub.setText(("● çevrimiçi" if p["online"] else "çevrimdışı") + " • üye: " +
                         time.strftime("%d.%m.%Y", time.localtime(p["created"])))
        self.chal.setVisible(p["name"] != self.win.me)
        for s, (v, n) in self.card_lbs.items():
            r, g = p["ratings"][s]
            v.setText(rating_text(r, g))
            n.setText("%d oyun" % g)
        tot = p["wins"] + p["losses"] + p["draws"]
        self.stats.setText("%d oyun • <span style='color:%s'>%d galibiyet</span> • "
                           "<span style='color:%s'>%d mağlubiyet</span> • %d beraberlik"
                           % (tot, C_GREEN, p["wins"], C_RED, p["losses"], p["draws"]))
        self.stats.setTextFormat(Qt.RichText)
        rows = []
        for g in p["games"]:
            me_w = g["white"] == p["name"]
            res = g["result"]
            won = (res == "1-0") == me_w and res != "1/2-1/2"
            col = C_DIM if res == "1/2-1/2" else C_GREEN if won else C_RED
            diff = g["white_diff"] if me_w else g["black_diff"]
            loser = g["white"] if res == "0-1" else g["black"]
            rows.append([cell(time.strftime("%d.%m.%Y %H:%M", time.localtime(g["ended"] or
                                                                           g["created"])), g["id"]),
                         cell("%s (%s)" % (g["white"], g["white_rating"])),
                         cell("%s (%s)" % (g["black"], g["black_rating"])),
                         cell(res.replace("1/2", "½"), color=col),
                         cell(REASONS.get(g["reason"], g["reason"]).format(loser=loser)),
                         cell(zdb.tc_text(g["base"], g["inc"]) + ("" if g["rated"] else " dostane")),
                         cell("" if diff is None else "%+d" % diff, color=col)])
        fill_table(self.games_t, rows)

    def _open(self, row, col):
        self.win.show_game(self.games_t.item(row, 0).data(Qt.UserRole))

    def challenge(self):
        self.win.show_lobby()
        self.win.lobby.create_game(self.name)


# =============================================================== ana pencere
class MainWindow(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or QSettings(APP_NAME, APP_NAME)
        self.net = None
        self.me = None
        self.sounds = Sounds()
        self.sounds.enabled = self.settings.value("sound", "1") == "1"
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 820)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.topbar = QWidget()
        self.topbar.setObjectName("topbar")
        self.topbar.setStyleSheet("#topbar { background:%s; border-bottom:1px solid %s; }"
                                  "QPushButton { background: transparent; border: none; }"
                                  % (C_PANEL, C_BORDER))
        self.topbar.setFixedHeight(52)
        tl = QHBoxLayout(self.topbar)
        tl.setContentsMargins(16, 0, 16, 0)
        logo = button("♞ zeichess", self.show_lobby, "flat")
        logo.setStyleSheet("font-size: 22px; font-weight: bold; color: %s;" % C_BRIGHT)
        tl.addWidget(logo)
        tl.addSpacing(20)
        tl.addWidget(button("OYNA", self.show_lobby, "flat"))
        tl.addWidget(button("PROFİLİM", lambda: self.show_profile(self.me), "flat"))
        tl.addStretch(1)
        self.db_lb = label("", 11, color="#5c5a57")
        tl.addWidget(self.db_lb)
        tl.addSpacing(12)
        self.sound_btn = button("", self.toggle_sound, "flat", "Ses aç/kapat")
        tl.addWidget(self.sound_btn)
        self.user_btn = button("", lambda: self.show_profile(self.me), "flat")
        self.user_btn.setStyleSheet("font-weight: bold; color: %s;" % C_BRIGHT)
        tl.addWidget(self.user_btn)
        tl.addWidget(button("Çıkış", self.logout, "flat"))
        self.topbar.hide()
        cl.addWidget(self.topbar)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.login = LoginPage(self)
        self.lobby = LobbyPage(self)
        self.gamep = GamePage(self)
        self.profile = ProfilePage(self)
        for w in (self.login, self.lobby, self.gamep, self.profile):
            self.stack.addWidget(w)
        self._paint_sound()

        self.pump = QTimer(self)
        self.pump.timeout.connect(self._pump)
        self.pump.start(15)

    def _pump(self):
        if self.net:
            self.net.pump()

    def _paint_sound(self):
        self.sound_btn.setText("🔊" if self.sounds.enabled else "🔇")

    def toggle_sound(self):
        self.sounds.enabled = not self.sounds.enabled
        self.settings.setValue("sound", "1" if self.sounds.enabled else "0")
        self._paint_sound()

    def do_login(self, path, name):
        net = Net(path)
        try:
            me = net.sync("login", name)
        except Exception:
            net.close()
            raise
        if self.net:
            self.net.close()
        self.net, self.me = net, me
        self.settings.setValue("db_path", path)
        self.settings.setValue("username", me)
        self.user_btn.setText(me)
        self.db_lb.setText(os.path.basename(path))
        self.db_lb.setToolTip(path)
        self.topbar.show()
        self.show_lobby()

    def _switch(self, page):
        cur = self.stack.currentWidget()
        if cur is not page:
            if cur is self.lobby:
                self.lobby.leave()
            elif cur is self.gamep:
                self.gamep.leave()
        self.stack.setCurrentWidget(page)

    def show_lobby(self):
        if not self.net:
            return
        self._switch(self.lobby)
        self.lobby.enter()

    def show_game(self, gid):
        if self.stack.currentWidget() is self.lobby and self.lobby.seek_id:
            self.lobby._clear_seek()
        self._switch(self.gamep)
        self.gamep.open(gid)

    def show_profile(self, name):
        if not self.net or not name:
            return
        self._switch(self.profile)
        self.profile.load(name)

    def logout(self):
        self._switch(self.login)
        if self.net:
            try:
                self.net.sync("logout", self.me)
            except Exception:
                pass
            self.net.close()
        self.net = None
        self.me = None
        self.topbar.hide()

    def closeEvent(self, ev):
        self.lobby.leave()
        self.gamep.leave()
        if self.net:
            try:
                self.net.sync("logout", self.me)
            except Exception:
                pass
            self.net.close()
            self.net = None
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
