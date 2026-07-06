#!/usr/bin/env python3
"""Generate build assets for AutoClicker (pure standard library).

Creates:
  assets/icon.png    - 256px app icon (used as the window icon at runtime)
  assets/icon.ico    - multi-size icon embedded into the exe
  version_info.txt   - Windows version resource for PyInstaller (embedded
                       publisher/product metadata improves SmartScreen and
                       antivirus reputation for unsigned executables)

The icon (a crosshair ring on a dark rounded square, matching the app's
click-marker) is rendered parametrically with supersampling, so no binary
assets need to live in the repository.
"""

import os
import re
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))

BG = (0x17, 0x1b, 0x28)
ACCENT = (0x5b, 0x8c, 0xff)
DOT = (0xf2, 0xf4, 0xfa)


def app_version():
    src = open(os.path.join(HERE, "autoclicker.py"), encoding="utf-8").read()
    return re.search(r'APP_VERSION = "(.+?)"', src).group(1)


def _sample(u, v):
    """Color (r, g, b, a) of the icon at unit coordinates (u, v)."""
    # dark rounded square
    m, r = 0.03, 0.20
    cx = min(max(u, m + r), 1 - m - r)
    cy = min(max(v, m + r), 1 - m - r)
    if (u - cx) ** 2 + (v - cy) ** 2 > r * r:
        return (0, 0, 0, 0)
    color = BG
    du, dv = u - 0.5, v - 0.5
    d = (du * du + dv * dv) ** 0.5
    # crosshair ticks poking out of the ring
    if (abs(du) <= 0.030 and 0.40 <= abs(dv) <= 0.475) or \
       (abs(dv) <= 0.030 and 0.40 <= abs(du) <= 0.475):
        color = ACCENT
    # ring
    if 0.27 <= d <= 0.375:
        color = ACCENT
    # center dot
    if d <= 0.105:
        color = DOT
    return (*color, 255)


def render(size, supersample=3):
    """Render the icon at `size` px; returns rows of RGBA bytes."""
    rows = []
    s = supersample
    for y in range(size):
        row = bytearray()
        for x in range(size):
            acc = [0, 0, 0, 0]
            for j in range(s):
                for i in range(s):
                    u = (x + (i + 0.5) / s) / size
                    v = (y + (j + 0.5) / s) / size
                    c = _sample(u, v)
                    for k in range(4):
                        acc[k] += c[k]
            row.extend(ch // (s * s) for ch in acc)
        rows.append(bytes(row))
    return rows


def png_bytes(size, rows):
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    raw = b"".join(b"\x00" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def ico_bytes(images):
    """Build a .ico from [(size, png_bytes)] using PNG-compressed entries."""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    data = b""
    offset = 6 + 16 * len(images)
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    return header + entries + data


VERSION_TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'AutoClick Project'),
        StringStruct('FileDescription', 'AutoClicker - window keep-alive auto clicker'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'AutoClicker'),
        StringStruct('LegalCopyright', 'MIT License - github.com/albusthaw/AutoClick'),
        StringStruct('OriginalFilename', 'AutoClicker.exe'),
        StringStruct('ProductName', 'AutoClicker'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main():
    version = app_version()
    parts = (version.split(".") + ["0", "0"])[:3]
    major, minor, patch = (int(p) for p in parts)

    assets = os.path.join(HERE, "assets")
    os.makedirs(assets, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 256]
    pngs = {size: png_bytes(size, render(size)) for size in sizes}

    with open(os.path.join(assets, "icon.png"), "wb") as f:
        f.write(pngs[256])
    with open(os.path.join(assets, "icon.ico"), "wb") as f:
        f.write(ico_bytes([(s, pngs[s]) for s in sizes]))
    with open(os.path.join(HERE, "version_info.txt"), "w", encoding="utf-8") as f:
        f.write(VERSION_TEMPLATE.format(major=major, minor=minor,
                                        patch=patch, version=version))

    print(f"Generated assets for v{version}: assets/icon.png, "
          f"assets/icon.ico, version_info.txt")


if __name__ == "__main__":
    main()
