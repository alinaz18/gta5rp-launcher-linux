#!/usr/bin/env python3
"""SVG → многоразмерный .ico для Windows-сборки: make_ico.py in.svg out.ico"""
import sys
from io import BytesIO

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

app = QGuiApplication(sys.argv[:1])
r = QSvgRenderer(sys.argv[1])
img = QImage(256, 256, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
r.render(p)
p.end()
ba = QByteArray()
buf = QBuffer(ba)
buf.open(QIODevice.WriteOnly)
img.save(buf, "PNG")
Image.open(BytesIO(bytes(ba))).save(sys.argv[2], sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ico:", sys.argv[2])
