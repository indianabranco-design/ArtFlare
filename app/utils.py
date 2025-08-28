from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, List
from math import floor, ceil
import numpy as np
from PIL import Image, ImageDraw
import io

try:
    import cairosvg
    HAS_CAIROSVG = True
except Exception:
    HAS_CAIROSVG = False

BORDER_ADD_CM_DEFAULT = 0.5

@dataclass
class Margins:
    m0_15: float = 0.50
    m16_30: float = 0.30
    m31_70: float = 0.25
    m71_plus: float = 0.0

def pick_margin(percent: float, margins: Margins) -> float:
    if percent <= 15: return margins.m0_15
    if percent <= 30: return margins.m16_30
    if percent <= 70: return margins.m31_70
    return margins.m71_plus

def price_with_tiered_margin(part_value: float, percent_used: float, margins: Margins) -> float:
    return max(0.0, part_value) * (1 + pick_margin(percent_used, margins))

def add_border_to_item(w_cm: float, h_cm: float, add_each_dim: float = BORDER_ADD_CM_DEFAULT) -> Tuple[float, float]:
    return (w_cm + add_each_dim, h_cm + add_each_dim)

def subtract_border_from_sheet(w_cm: float, h_cm: float, border_all_around: float = BORDER_ADD_CM_DEFAULT) -> Tuple[float, float]:
    return (max(0.0, w_cm - 2*border_all_around), max(0.0, h_cm - 2*border_all_around))

def rect_pack_count(sheet_w: float, sheet_h: float, item_w: float, item_h: float) -> int:
    if item_w<=0 or item_h<=0: return 0
    fit1 = floor(sheet_w // item_w) * floor(sheet_h // item_h)
    fit2 = floor(sheet_w // item_h) * floor(sheet_h // item_w)
    return max(fit1, fit2)

# --- Image helpers ---
def load_shape_from_upload(file_bytes: bytes, filename: str) -> Image.Image:
    name = filename.lower()
    if name.endswith((".png",".jpg",".jpeg")):
        im = Image.open(io.BytesIO(file_bytes)).convert("L")
        return im
    if name.endswith(".svg"):
        if not HAS_CAIROSVG:
            raise RuntimeError("CairoSVG não disponível. Instale as dependências e rode 'pip install cairosvg'.")
        png_bytes = cairosvg.svg2png(bytestring=file_bytes)
        im = Image.open(io.BytesIO(png_bytes)).convert("L")
        return im
    raise ValueError("Formato não suportado. Use PNG/JPG/SVG.")

def binarize_image(im: Image.Image, threshold: int = 200) -> Image.Image:
    if im.mode != "L":
        im = im.convert("L")
    arr = np.array(im)
    mask = (arr < threshold).astype(np.uint8) * 255
    return Image.fromarray(mask, mode="L")

# --- Greedy free-rotation nesting (angle sweep) ---
def greedy_nest(mask: Image.Image, sheet_w_cm: float, sheet_h_cm: float, dpi: int, gap_cm: float, border_cm: float, angle_step: int = 10, max_px: int = 900):
    # scale sheet
    sw_eff_cm, sh_eff_cm = subtract_border_from_sheet(sheet_w_cm, sheet_h_cm, border_cm)
    sw_px = max(1, int(sw_eff_cm * dpi))
    sh_px = max(1, int(sh_eff_cm * dpi))
    # limit resolution for performance
    scale_factor = 1.0
    if max(sw_px, sh_px) > max_px:
        scale_factor = max_px / max(sw_px, sh_px)
        sw_px = int(sw_px * scale_factor); sh_px = int(sh_px * scale_factor)
        dpi = int(dpi * scale_factor)

    gap_px = max(0, int(gap_cm * dpi))

    # bin canvas for occupancy
    occ = np.zeros((sh_px, sw_px), dtype=np.uint8)

    # normalize mask size by requested piece cm (caller must resize before)
    placements = []
    best_total = 0
    best_snapshot = None

    # Try angle sweep
    for ang in range(0, 360, angle_step):
        m = mask.rotate(ang, expand=True, fillcolor=0)
        m_arr = np.array(m) // 255  # 0/1
        mh, mw = m_arr.shape
        count = 0
        occ_copy = occ.copy()
        placements_tmp = []
        # step size: choose small stride for better fill vs speed
        step = max(1, int(max(mw, mh) * 0.2))
        for y in range(0, sh_px - mh + 1, step):
            for x in range(0, sw_px - mw + 1, step):
                # expand area by gap
                x0 = max(0, x - gap_px); y0 = max(0, y - gap_px)
                x1 = min(sw_px, x + mw + gap_px); y1 = min(sh_px, y + mh + gap_px)
                # check collision in area
                if np.any(occ_copy[y0:y1, x0:x1] != 0):
                    continue
                # place mask
                slice_view = occ_copy[y:y+mh, x:x+mw]
                if np.any(slice_view != 0):
                    continue
                # draw piece
                slice_view[:] = slice_view | m_arr
                # add gap border
                if gap_px>0:
                    occ_copy[y0:y1, x0:x1] = np.maximum(occ_copy[y0:y1, x0:x1], 1)
                placements_tmp.append({"x_px": x, "y_px": y, "angle": ang, "w": mw, "h": mh})
                count += 1
        if count > best_total:
            best_total = count
            best_snapshot = occ_copy
            best_placements = placements_tmp

    if best_snapshot is None:
        best_snapshot = occ
        best_placements = []

    # Create preview image (white background, colored pieces)
    preview = Image.new("RGB", (sw_px, sh_px), "white")
    # draw colored rectangles approximating placements (for speed)
    draw = ImageDraw.Draw(preview)
    rng_colors = [(255, 77, 77), (77, 166, 255), (77, 255, 166), (255, 166, 77), (180, 77, 255), (255, 226, 77)]
    for i, p in enumerate(best_placements):
        color = rng_colors[i % len(rng_colors)]
        # draw bounding box; faster than pasting rotated alpha
        draw.rectangle([p["x_px"], p["y_px"], p["x_px"]+p["w"]-1, p["y_px"]+p["h"]-1], outline=color, width=2)

    utilization = float(best_snapshot.sum())/(sw_px*sh_px) if (sw_px*sh_px)>0 else 0.0
    return preview, best_placements, best_total, utilization, (sw_px, sh_px), dpi, scale_factor

# ==========================
# Inputs numéricos robustos
# ==========================
import streamlit as st

def _parse_float_pt(raw: str, default: float = 0.0) -> float:
    """Converte strings com vírgula/ponto em float, tolerante a milhares.
    Exemplos aceites: "1.234,56", "1,234.56", "1234,56", "1234.56".
    """
    if raw is None:
        return float(default)
    s = str(raw).strip().replace("\u00a0", " ").replace(" ", "")
    # se tiver ponto e vírgula, assume milhares com ponto e decimal com vírgula
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return float(default)

def money_input(label: str, key: str, default: float = 0.0, help: str | None = None) -> float:
    """Campo monetário estável (sem saltos enquanto escreve) e compatível com vírgula.
    Usa text_input por baixo e sincroniza com st.session_state.
    """
    txt_key = f"{key}__txt"
    if txt_key not in st.session_state:
        st.session_state[txt_key] = f"{float(default):.2f}"
        st.session_state[key] = float(default)
    raw = st.text_input(label, st.session_state[txt_key], key=txt_key, help=help)
    val = _parse_float_pt(raw, st.session_state.get(key, default))
    st.session_state[key] = float(val)
    return float(val)
