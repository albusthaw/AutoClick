#!/usr/bin/env python3
"""Visual template matching for AutoClicker (numpy only).

Locates a small template image inside a larger screenshot using normalized
cross-correlation, searching over a range of scales so the target is still
found after the window (and therefore the rendered content) is resized.

This is what makes clicking robust inside remote-desktop windows (Horizon,
Citrix, RDP): those clients letterbox / scale / pan the remote image inside
their window, so a fixed percentage of the window no longer maps to the same
remote pixel after a resize. Matching by appearance sidesteps the unknown
coordinate transform entirely.

Only numpy is required. If the best match is below the confidence threshold,
callers should NOT click — skipping is always preferable to a misclick.
"""

import numpy as np

# Scales tried relative to the captured template size. Values < 1 find the
# target when the window has been shrunk (content rendered smaller); values
# > 1 when it has been enlarged.
DEFAULT_SCALES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6)
DEFAULT_THRESHOLD = 0.80


def to_gray(rgb):
    """(H, W, 3|4) uint8 -> (H, W) float32 luminance."""
    a = np.asarray(rgb)
    if a.ndim == 2:
        return a.astype(np.float32)
    b = a[:, :, 0].astype(np.float32)
    g = a[:, :, 1].astype(np.float32)
    r = a[:, :, 2].astype(np.float32)
    return 0.299 * r + 0.587 * g + 0.114 * b


def resize_bilinear(img, new_h, new_w):
    """Bilinear resize of a 2-D float array (no external deps)."""
    h, w = img.shape
    new_h, new_w = max(int(new_h), 1), max(int(new_w), 1)
    if (new_h, new_w) == (h, w):
        return img.astype(np.float32, copy=False)
    ys = (np.arange(new_h) + 0.5) * (h / new_h) - 0.5
    xs = (np.arange(new_w) + 0.5) * (w / new_w) - 0.5
    ys = np.clip(ys, 0, h - 1)
    xs = np.clip(xs, 0, w - 1)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    y1 = np.minimum(y0 + 1, h - 1)
    x1 = np.minimum(x0 + 1, w - 1)
    wy = (ys - y0)[:, None]
    wx = (xs - x0)[None, :]
    top = img[y0][:, x0] * (1 - wx) + img[y0][:, x1] * wx
    bot = img[y1][:, x0] * (1 - wx) + img[y1][:, x1] * wx
    return (top * (1 - wy) + bot * wy).astype(np.float32)


def _integral(a):
    return np.pad(np.cumsum(np.cumsum(a, axis=0), axis=1), ((1, 0), (1, 0)))


def _window_sum(ii, H, W, h, w):
    return (ii[h:H + 1, w:W + 1] - ii[0:H - h + 1, w:W + 1]
            - ii[h:H + 1, 0:W - w + 1] + ii[0:H - h + 1, 0:W - w + 1])


def normxcorr2(image, templ):
    """Normalized cross-correlation map over valid positions, or None.

    Returns an array of shape (H-h+1, W-w+1) with values in roughly [-1, 1];
    each entry is the NCC of the template against that top-left position.
    """
    image = np.asarray(image, dtype=np.float32)
    templ = np.asarray(templ, dtype=np.float32)
    H, W = image.shape
    h, w = templ.shape
    if h > H or w > W:
        return None
    t = templ - templ.mean()
    t_ss = float(np.sum(t * t))
    if t_ss < 1e-6:
        return None   # featureless template — nothing distinctive to match

    sz0, sz1 = H + h - 1, W + w - 1
    f_img = np.fft.rfft2(image, s=(sz0, sz1))
    f_t = np.fft.rfft2(t[::-1, ::-1], s=(sz0, sz1))
    corr = np.fft.irfft2(f_img * f_t, s=(sz0, sz1))
    num = corr[h - 1:H, w - 1:W]           # sum((I - localmean) * t), since sum(t)=0

    ii = _integral(image)
    ii2 = _integral(image * image)
    n = h * w
    s1 = _window_sum(ii, H, W, h, w)
    s2 = _window_sum(ii2, H, W, h, w)
    var = s2 - (s1 * s1) / n
    denom = np.sqrt(np.clip(var, 0, None) * t_ss)

    out = np.zeros_like(num, dtype=np.float32)
    np.divide(num, denom, out=out, where=denom > 1e-6)
    return out


def find(screenshot_gray, template_gray, scales=DEFAULT_SCALES):
    """Best match of template within screenshot across scales.

    Returns dict {score, cx, cy, scale, w, h} where (cx, cy) is the CENTER of
    the matched region in screenshot pixel coordinates, or None if nothing
    could be evaluated (e.g. template larger than image at every scale).
    """
    image = np.asarray(screenshot_gray, dtype=np.float32)
    templ0 = np.asarray(template_gray, dtype=np.float32)
    H, W = image.shape
    th0, tw0 = templ0.shape

    best = None
    for scale in scales:
        th, tw = max(int(round(th0 * scale)), 4), max(int(round(tw0 * scale)), 4)
        if th > H or tw > W:
            continue
        templ = resize_bilinear(templ0, th, tw) if scale != 1.0 else templ0
        ncc = normxcorr2(image, templ)
        if ncc is None or ncc.size == 0:
            continue
        idx = int(np.argmax(ncc))
        y, x = np.unravel_index(idx, ncc.shape)
        score = float(ncc[y, x])
        if best is None or score > best["score"]:
            best = {"score": score, "cx": x + tw / 2.0, "cy": y + th / 2.0,
                    "scale": scale, "w": tw, "h": th}
    return best
