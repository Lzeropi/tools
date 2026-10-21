#!/usr/bin/python3
# keyviz.py — KDE Wayland 实时按键显示浮窗（evdev 直读，不依赖 X11）
# 风格参考 mulaRahul/keyviz：键帽式组合显示（底部居中），鼠标以图标键帽参与组合
# 用法：keyviz.py [--mouse]

import sys
import time
import queue
import select
import threading

import evdev
from evdev import ecodes

from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QHBoxLayout,
                             QGraphicsOpacityEffect)
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPointF
from PyQt5.QtGui import QFont, QCursor, QPainter, QColor, QPainterPath, QPen, QBrush

# ------------------------- 可调参数 -------------------------
HOLD_MS = 2500          # 组合键全部松开后保持时长（毫秒）
FADE_MS = 300           # 淡出动画时长（毫秒）
FONT_SIZE = 24          # 键帽字号
CAP_RADIUS = 10         # 键帽圆角
BOX_RADIUS = 18         # 容器圆角
CAP_GAP = 10            # 键帽间距
BOTTOM_MARGIN = 56      # 距屏幕底边距离

HILITE = '#34d399'      # 鼠标指示器高亮色（绿）
WHEEL_LINGER = 450      # 滚动箭头消失延迟（毫秒）
FOLLOW_MS = 40          # 指示器跟随光标轮询间隔

CAP_STYLE = {
    'mod':   "background:#2b2f3a;color:#e8ecf4;border-radius:%(r)dpx;"
             "padding:10px 20px;font-weight:bold;border:1px solid #3d434f;",
    'key':   "background:#eef1f6;color:#10131a;border-radius:%(r)dpx;"
             "padding:10px 20px;font-weight:600;border:1px solid #cfd5e0;",
    'mouse': "background:#1b3a5b;color:#9bd1ff;border-radius:%(r)dpx;"
             "padding:10px 20px;font-weight:bold;border:1px solid #2c5887;",
}
BOX_STYLE = "background:rgba(16,18,24,0.72);border-radius:%dpx;" % BOX_RADIUS
# ------------------------------------------------------------

MODS = {
    ecodes.KEY_LEFTCTRL: 'Ctrl', ecodes.KEY_RIGHTCTRL: 'Ctrl',
    ecodes.KEY_LEFTALT: 'Alt', ecodes.KEY_RIGHTALT: 'Alt',
    ecodes.KEY_LEFTSHIFT: 'Shift', ecodes.KEY_RIGHTSHIFT: 'Shift',
    ecodes.KEY_LEFTMETA: 'Super', ecodes.KEY_RIGHTMETA: 'Super',
}
MOD_ORDER = {'Ctrl': 0, 'Alt': 1, 'Super': 2, 'Shift': 3}

PUNCT = {
    ecodes.KEY_DOT: '.', ecodes.KEY_COMMA: ',', ecodes.KEY_SLASH: '/',
    ecodes.KEY_SEMICOLON: ';', ecodes.KEY_APOSTROPHE: "'",
    ecodes.KEY_MINUS: '-', ecodes.KEY_EQUAL: '=',
    ecodes.KEY_LEFTBRACE: '[', ecodes.KEY_RIGHTBRACE: ']',
    ecodes.KEY_BACKSLASH: '\\', ecodes.KEY_GRAVE: '`',
}
SPECIAL = {
    ecodes.KEY_SPACE: 'Space', ecodes.KEY_ENTER: 'Enter', ecodes.KEY_ESC: 'Esc',
    ecodes.KEY_TAB: 'Tab', ecodes.KEY_BACKSPACE: 'Bksp', ecodes.KEY_DELETE: 'Del',
    ecodes.KEY_INSERT: 'Ins', ecodes.KEY_HOME: 'Home', ecodes.KEY_END: 'End',
    ecodes.KEY_PAGEUP: 'PgUp', ecodes.KEY_PAGEDOWN: 'PgDn',
    ecodes.KEY_UP: 'Up', ecodes.KEY_DOWN: 'Down',
    ecodes.KEY_LEFT: 'Left', ecodes.KEY_RIGHT: 'Right',
    ecodes.KEY_CAPSLOCK: 'CapsLk', ecodes.KEY_NUMLOCK: 'NumLk',
    ecodes.KEY_PRINT: 'PrtSc', ecodes.KEY_PAUSE: 'Pause',
}
MOUSE_BTNS = {ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE,
               ecodes.BTN_SIDE, ecodes.BTN_EXTRA}
MOUSE_NAMES = {
    ecodes.BTN_LEFT: 'Click', ecodes.BTN_RIGHT: 'Right-Click',
    ecodes.BTN_MIDDLE: 'Mid-Click',
}
WHEEL_UP, WHEEL_DOWN = 'Scroll ↑', 'Scroll ↓'   # 底部条虚拟键帽
KEYBOARD_HINT = {ecodes.KEY_A, ecodes.KEY_Q, ecodes.KEY_Z, ecodes.KEY_SPACE}


def keyname(code):
    if code == WHEEL_UP or code == WHEEL_DOWN:
        return code
    if code in MOUSE_NAMES:
        return MOUSE_NAMES[code]
    if code in PUNCT:
        return PUNCT[code]
    if code in SPECIAL:
        return SPECIAL[code]
    name = ecodes.KEY.get(code, f'KEY_{code}')
    return name.split('_', 1)[-1].title() if name.startswith('KEY_') else name.title()


def dev_keys(dev):
    try:
        return set(dev.capabilities().get(ecodes.EV_KEY, []))
    except Exception:
        return set()


def is_keyboard(dev):
    return bool(dev_keys(dev) & KEYBOARD_HINT)


def is_mouse(dev):
    keys = dev_keys(dev)
    return ecodes.BTN_LEFT in keys and not (keys & KEYBOARD_HINT)


class Reader(threading.Thread):
    """事件入队格式：('k', code, val) / ('w', dy)"""

    def __init__(self, want_mouse):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.devices = {}
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
            except Exception:
                continue
            if is_keyboard(dev) or (want_mouse and is_mouse(dev)):
                self.devices[dev.fd] = dev

    def run(self):
        if not self.devices:
            print('错误：未找到键盘设备（检查 /dev/input 权限，用户需在 input 组）',
                  file=sys.stderr)
            return
        while True:
            r, _, _ = select.select(list(self.devices), [], [])
            for fd in r:
                for e in self.devices[fd].read():
                    if e.type == ecodes.EV_KEY and e.value in (0, 1):
                        self.q.put(('k', e.code, e.value))
                    elif e.type == ecodes.EV_REL and e.code == ecodes.REL_WHEEL:
                        self.q.put(('w', e.value))


class KeyCap(QLabel):
    def __init__(self, text, kind):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(CAP_STYLE[kind] % {'r': CAP_RADIUS})


class Fader(QWidget):
    """带透明度动画的通用浮窗基类"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._anim = None
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(1.0)
        self.hide()

    def appear(self):
        self._anim_stop()
        self._effect.setOpacity(1.0)
        self.show()

    def fade_out(self, ms=FADE_MS):
        if not self.isVisible():
            return
        self._anim = QPropertyAnimation(self._effect, b'opacity', self)
        self._anim.setDuration(ms)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self._anim.finished.connect(self._on_faded)
        self._anim.start()

    def _anim_stop(self):
        if self._anim:
            self._anim.stop()
            self._anim = None

    def _on_faded(self):
        if self.isVisible():
            self.hide()
        self._effect.setOpacity(1.0)


class MouseCap(QWidget):
    """底部条鼠标图标键帽：与修饰键帽同款深色衬底，白色线条；
    只画鼠标上半部（左键/右键/滚轮），左缘凸出侧键块"""

    def __init__(self, buttons=frozenset(), wheel=None):
        super().__init__()
        self.setFixedSize(70, 48)
        self.buttons = set(buttons)
        self.wheel = wheel
        self.setStyleSheet(CAP_STYLE['mod'] % {'r': CAP_RADIUS})

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        line = QColor(232, 236, 244)      # 白色线条（深色衬底上）
        hilite = QColor(HILITE)
        mw, mh = 32, 26                   # 半截鼠标宽高
        rr = mw / 2
        x0, y0 = (W - mw) / 2 - 8, 11    # 左移给侧键块留位
        x1, y1 = x0 + mw, y0 + mh
        cx = x0 + mw / 2

        # 半截鼠标轮廓（顶部圆弧 + 底部平切）
        body = QPainterPath()
        body.moveTo(x0, y1)
        body.lineTo(x0, y0 + rr)
        body.quadTo(x0, y0, x0 + rr, y0)
        body.lineTo(x1 - rr, y0)
        body.quadTo(x1, y0, x1, y0 + rr)
        body.lineTo(x1, y1)
        body.closeSubpath()

        # 左/右键高亮（对应半边填充）
        if ecodes.BTN_LEFT in self.buttons or ecodes.BTN_RIGHT in self.buttons:
            half = QPainterPath()
            side = 0 if ecodes.BTN_LEFT in self.buttons else 1
            hx = x0 + (mw / 2 if side else 0)
            half.addRect(hx, y0, mw / 2, mh + 2)
            p.fillPath(body.intersected(half), hilite)

        pen = QPen(line, 1.8)
        p.setPen(pen)
        p.drawPath(body)
        p.drawLine(QPointF(cx, y0), QPointF(cx, y1))

        # 滚轮（中键按下时绿色填充）
        mid = ecodes.BTN_MIDDLE in self.buttons
        p.setBrush(QBrush(hilite) if mid else QBrush(line))
        p.drawEllipse(QPointF(cx, y0 + mh * 0.42), 2.2, 5)
        p.setBrush(Qt.NoBrush)

        # 侧键块（左缘凸出：上 BTN_EXTRA / 下 BTN_SIDE）
        for code, sy in ((ecodes.BTN_EXTRA, y0 + 2), (ecodes.BTN_SIDE, y0 + 13)):
            blk = QPainterPath()
            blk.addRoundedRect(x0 - 8, sy, 8, 9, 2.5, 2.5)
            if code in self.buttons:
                p.fillPath(blk, hilite)
            else:
                p.setPen(QPen(line, 1.4))
                p.drawPath(blk)

        # 滚轮方向箭头（白色，半截鼠标上/下方）
        if self.wheel:
            arrow = QPainterPath()
            aw, ah = 12, 7
            if self.wheel == 'up':
                ax, ay = cx, y0 - 10
                arrow.moveTo(ax - aw / 2, ay + ah)
                arrow.lineTo(ax + aw / 2, ay + ah)
                arrow.lineTo(ax, ay)
            else:
                ax, ay = cx, y1 + 10
                arrow.moveTo(ax - aw / 2, ay - ah)
                arrow.lineTo(ax + aw / 2, ay - ah)
                arrow.lineTo(ax, ay)
            p.setPen(Qt.NoPen)
            p.fillPath(arrow, QColor(232, 236, 244, 240))


class Overlay(Fader):
    """底部居中的键帽组合条（仅键盘）"""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(BOX_STYLE)
        self.pressed = {}   # code -> 按下序号（保序）
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(lambda: self.fade_out())
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(CAP_GAP)

    def resizeEvent(self, ev):
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.bottom() - self.height() - BOTTOM_MARGIN)

    def refresh_key(self, code, val):
        if val:
            # 按下：实时重建当前组合
            self.pressed.setdefault(code, len(self.pressed))
            self._hold.stop()
            self._rebuild()
            self.appear()
        else:
            # 松开：保持已显示的组合不变（keyviz 行为）；
            # 只有全部松手后才启动保持倒计时
            self.pressed.pop(code, None)
            if not self.pressed:
                self._hold.start(HOLD_MS)

    def refresh_wheel(self, dy):
        """滚轮：作为瞬时键帽进入组合，显示后随组合保持规则淡出"""
        wkey = WHEEL_UP if dy > 0 else WHEEL_DOWN
        self.pressed[wkey] = len(self.pressed)
        self._hold.stop()
        self._rebuild()
        self.appear()
        # 立即标记松开（不重建，保持显示的组合）
        self.pressed.pop(wkey, None)
        if not self.pressed:
            self._hold.start(HOLD_MS)

    def _rebuild(self):
        lay = self.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        mod_names = sorted({MODS[c] for c in self.pressed if c in MODS},
                           key=lambda m: MOD_ORDER.get(m, 9))
        plain = [c for c in self.pressed if c not in MODS]
        for m in mod_names:
            cap = KeyCap(m, 'mod')
            f = QFont(); f.setPointSize(FONT_SIZE); f.setBold(True)
            cap.setFont(f)
            lay.addWidget(cap)
        for c in plain:
            if c in MOUSE_BTNS or c in (WHEEL_UP, WHEEL_DOWN):
                btns = {k for k in self.pressed if k in MOUSE_BTNS}
                wheel = ('up' if WHEEL_UP in self.pressed
                         else 'down' if WHEEL_DOWN in self.pressed else None)
                lay.addWidget(MouseCap(btns, wheel))
                continue
            cap = KeyCap(keyname(c), 'key')
            f = QFont(); f.setPointSize(FONT_SIZE); f.setBold(True)
            cap.setFont(f)
            lay.addWidget(cap)
        self.adjustSize()
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.bottom() - self.height() - BOTTOM_MARGIN)



def main():
    want_mouse = '--mouse' in sys.argv
    app = QApplication(sys.argv)
    overlay = Overlay()
    reader = Reader(want_mouse)
    reader.start()

    def poll():
        try:
            while True:
                ev = reader.q.get_nowait()
                if ev[0] == 'k':
                    overlay.refresh_key(ev[1], ev[2])
                elif ev[0] == 'w':
                    overlay.refresh_wheel(ev[1])
        except queue.Empty:
            pass

    t = QTimer()
    t.timeout.connect(poll)
    t.start(30)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
