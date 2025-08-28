import os, io, json, base64, time, math, random
from math import ceil
from datetime import datetime

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

# Sidebar (import robusto)
try:
    from app.sidebar import show_sidebar
except Exception:
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.sidebar import show_sidebar
show_sidebar()

# Shapely para o modo avançado
try:
    from shapely.geometry import Polygon, box
    from shapely.affinity import rotate as shp_rotate, translate as shp_translate
    from shapely.ops import unary_union
    SHAPELY_OK = True
except Exception:
    SHAPELY_OK = False

HISTORICO_PATH = "data/historico_calculos.json"

# ---------------- Histórico ----------------
def carregar_historico():
    if os.path.exists(HISTORICO_PATH):
        with open(HISTORICO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def salvar_historico(h):
    with open(HISTORICO_PATH, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2)

# ----- Detetar peça: textura + polígono em coords do recorte -----
def detect_piece(image_rgba: Image.Image):
    rgb = image_rgba.convert("RGB")
    arr = np.array(rgb)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, th = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, None, None, None
    cnt = max(cnts, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(cnt)

    cropped = image_rgba.crop((x, y, x + w, y + h)).convert("RGBA")
    mask_full = np.zeros_like(th)
    cv2.drawContours(mask_full, [cnt], -1, 255, -1)
    mask_crop = Image.fromarray(mask_full).crop((x, y, x + w, y + h))
    cropped.putalpha(mask_crop)

    epsilon = 0.004 * cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, epsilon, True)
    pts = [(int(p[0][0]-x), int(p[0][1]-y)) for p in approx]
    if len(pts) < 3:
        return None, None, None, None
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return cropped, poly, (w, h), np.array(mask_crop) > 0

# ----- Renderização final com numeração -----
def render_layout(placements, sheet_w, sheet_h):
    canvas = Image.new("RGBA", (sheet_w, sheet_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for idx, p in enumerate(placements, start=1):
        canvas.paste(p["img"], (p["x"], p["y"]), p["img"])
        draw.text((p["x"] + 5, p["y"] + 5), str(idx), fill=(255, 0, 0), font=font)
    return canvas

# ================== MODO 1: Alinhamento ortogonal (sem encaixe) ==================
def orthogonal_pack(tex, sheet_w, sheet_h, gap_px):
    """Coloca peças em linhas/colunas usando apenas 0/90/180/270, sem tentar encaixar recortes."""
    angles = [0, 90, 180, 270]
    placements = []
    y = 0
    while y < sheet_h:
        x = 0
        linha_altura = 0
        while x < sheet_w:
            placed = False
            for ang in angles:
                t = tex.rotate(ang, expand=True)
                w, h = t.size
                if x + w <= sheet_w and y + h <= sheet_h:
                    placements.append({"x": x, "y": y, "img": t})
                    x += w + gap_px
                    linha_altura = max(linha_altura, h)
                    placed = True
                    break
            if not placed:
                # não cabe em x → salta para próxima linha
                break
        if linha_altura == 0:
            break
        y += linha_altura + gap_px

    # % de aproveitamento aproximada por bbox da textura
    area_total = sheet_w * sheet_h
    area_peca = tex.size[0] * tex.size[1]
    util = (len(placements) * area_peca / area_total * 100.0) if area_total else 0.0
    return placements, util

# ================== MODO 2: Nesting Avançado (Shapely) ==================
def candidate_positions(sheet_w, sheet_h, step):
    pts = [(x, y) for y in range(0, sheet_h, step) for x in range(0, sheet_w, step)]
    random.shuffle(pts)
    return pts

def advanced_nest_shapely(tex_base, poly_base, sheet_w, sheet_h, gap_px, angs,
                          time_limit_s=20, max_trials=60000):
    """
    - Roda polígono no mesmo centro do bitmap, com ângulo NEGATIVO (coords shapely vs imagem).
    - Mantém a ordem de 'angs' (se queres só 0/90/180/270, passa [0,90,180,270]).
    - Verificação geométrica (buffer folga) + verificação raster para zero sobreposição.
    """
    t0 = time.time()
    sheet_poly = box(0, 0, sheet_w, sheet_h)

    W0, H0 = tex_base.size
    center = (W0/2.0, H0/2.0)

    angle_variants = []
    for ang in angs:
        tex_rot = tex_base.rotate(ang, expand=True)
        poly_rot = shp_rotate(poly_base, -ang, origin=center, use_radians=False)
        minx, miny, maxx, maxy = poly_rot.bounds
        poly_rot_00 = shp_translate(poly_rot, xoff=-minx, yoff=-miny)
        w_rot = int(math.ceil(maxx - minx))
        h_rot = int(math.ceil(maxy - miny))
        alpha = np.array(tex_rot.split()[-1]) > 0
        angle_variants.append((ang, tex_rot, poly_rot_00, w_rot, h_rot, alpha))

    occ = np.zeros((sheet_h, sheet_w), dtype=np.uint8)
    placements = []
    union = None
    occ_area = 0.0

    base_step = max(2, min(W0, H0) // 6)
    trials = 0
    stuck = 0

    for (cx, cy) in candidate_positions(sheet_w, sheet_h, base_step):
        if time.time() - t0 > time_limit_s or trials > max_trials:
            break
        placed = False
        # TENTA ANGULOS NA ORDEM DADA (sem baralhar)
        for ang, tex_rot, poly_rot_00, w_rot, h_rot, alpha in angle_variants:
            trials += 1
            if cx + w_rot > sheet_w or cy + h_rot > sheet_h:
                continue
            placed_poly = shp_translate(poly_rot_00, xoff=cx, yoff=cy)
            placed_with_gap = placed_poly.buffer(gap_px, join_style=2)
            if union is not None and not placed_with_gap.disjoint(union):
                continue
            if not sheet_poly.contains(placed_with_gap):
                continue
            sub = occ[cy:cy+h_rot, cx:cx+w_rot]
            if sub.shape != (h_rot, w_rot) or np.any(sub[alpha] != 0):
                continue
            # OK
            sub[alpha] = 1
            union = placed_with_gap if union is None else unary_union([union, placed_with_gap])
            placements.append({"x": cx, "y": cy, "img": tex_rot})
            occ_area += placed_poly.area
            placed = True
            break
        if placed:
            stuck = 0
        else:
            stuck += 1
            if stuck >= 3:
                base_step = max(1, base_step // 2); stuck = 0

    area_total = float(sheet_w) * float(sheet_h)
    util = (occ_area / area_total * 100.0) if area_total else 0.0
    return placements, util

# ===================== UI =====================
st.title("📐 Cálculos — Alinhamento ortogonal / Nesting Avançado")

piece_file = st.file_uploader("Peça (PNG/JPG) — linhas escuras em fundo claro", type=["png","jpg","jpeg"])
dpi = st.slider("Precisão (pixels/cm) [render]", 10, 120, 40)

col_dims = st.columns(2)
material_w_cm = col_dims[0].number_input("Largura da chapa (cm)", 1.0, 1000.0, 60.0)
material_h_cm = col_dims[1].number_input("Altura da chapa (cm)", 1.0, 1000.0, 40.0)

c1, c2, c3 = st.columns(3)
piece_w_cm = c1.number_input("Largura da peça (cm)", 0.1, 500.0, 12.0)
piece_h_cm = c2.number_input("Altura da peça (cm)", 0.1, 500.0, 8.0)
angle_step = c3.selectbox("Ângulo (passo) p/ modo avançado", [5,10,15,20,30,45,90], index=2)

folga_material_cm = st.number_input("Folga do material (cm)", 0.0, 10.0, 0.5)
folga_peca_cm = st.number_input("Folga entre peças (cm)", 0.0, 10.0, 0.4)
qty_needed = st.number_input("Quantidade necessária", 0, 100000, 0)

modo = st.radio("Modo", ["Alinhamento ortogonal (sem encaixe)", "Nesting Avançado (Shapely)"], horizontal=True)
so_ortogonais = st.toggle("No modo avançado, usar só 0°/90°/180°/270°", value=False)
tempo_max = st.slider("Limite de tempo (s) [Shapely]", 5, 60, 20)

if piece_file:
    raw_piece = Image.open(piece_file).convert("RGBA")
    tex, poly, (pw, ph), _ = detect_piece(raw_piece)
    if tex is None:
        st.error("Não foi possível detetar o contorno. Aumente o contraste (linhas escuras).")
        st.stop()

    # redimensionar peça
    target_w_px = max(1, int(piece_w_cm * dpi))
    target_h_px = max(1, int(piece_h_cm * dpi))
    tex = tex.resize((target_w_px, target_h_px), Image.BICUBIC)

    # polígono nas mesmas coords do bitmap
    sx = target_w_px / max(1, pw)
    sy = target_h_px / max(1, ph)
    poly_scaled = Polygon([(x*sx, y*sy) for (x,y) in poly.exterior.coords])

    # chapa útil
    sheet_w_px = max(1, int((material_w_cm - 2 * folga_material_cm) * dpi))
    sheet_h_px = max(1, int((material_h_cm - 2 * folga_material_cm) * dpi))
    gap_px = max(0, int(folga_peca_cm * dpi))

    if modo.startswith("Alinhamento"):
        placements, util = orthogonal_pack(tex, sheet_w_px, sheet_h_px, gap_px)
    else:
        if not SHAPELY_OK:
            st.error("Falta 'shapely'. Adicione 'shapely>=2.0' ao requirements.txt e instale.")
            st.stop()
        if so_ortogonais:
            angs = [0, 90, 180, 270]
        else:
            angs = list(range(0, 360, int(angle_step)))
        placements, util = advanced_nest_shapely(
            tex, poly_scaled, sheet_w_px, sheet_h_px, gap_px,
            angs=angs, time_limit_s=int(tempo_max)
        )

    # render + métricas
    canvas = render_layout(placements, sheet_w_px, sheet_h_px)
    total = len(placements)
    st.image(canvas, caption=f"{total} peças | {util:.1f}% de aproveitamento", use_column_width=True)

    cA, cB, cC = st.columns(3)
    cA.metric("Peças por chapa", total)
    cB.metric("% Aproveitamento", f"{util:.1f}%")
    cC.metric("Chapas necessárias", ceil(qty_needed/total) if total>0 and qty_needed>0 else 0)

    # Exportar
    buf = io.BytesIO(); canvas.save(buf, format="PNG"); png_bytes = buf.getvalue()
    st.download_button("⬇️ Exportar PNG", data=png_bytes, file_name="layout_nesting.png", mime="image/png")
    b64 = base64.b64encode(png_bytes).decode()
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='{sheet_w_px}' height='{sheet_h_px}'><image href='data:image/png;base64,{b64}' width='{sheet_w_px}' height='{sheet_h_px}'/></svg>"
    st.download_button("⬇️ Exportar SVG", data=svg.encode(), file_name="layout_nesting.svg", mime="image/svg+xml")

    # Guardar histórico
    nota = st.text_input("Notas (opcional)")
    if st.button("💾 Guardar no histórico"):
        hist = carregar_historico()
        hist.append({
            "id": datetime.now().strftime("%Y%m%d%H%M%S"),
            "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "folga_material": float(folga_material_cm),
            "folga_peca": float(folga_peca_cm),
            "total_pecas": int(total),
            "aproveitamento": float(util),
            "sheet_w_cm": float(material_w_cm),
            "sheet_h_cm": float(material_h_cm),
            "piece_w_cm": float(piece_w_cm),
            "piece_h_cm": float(piece_h_cm),
            "dpi": int(dpi),
            "nota": nota,
            "imagem_base64": b64,
        })
        salvar_historico(hist)
        st.success("Guardado no histórico.")
else:
    st.info("Carregue a peça, escolha 'Alinhamento ortogonal' para grelha simples ou 'Nesting Avançado' para encaixe.")