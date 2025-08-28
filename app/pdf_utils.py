from io import BytesIO
from datetime import timedelta
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.lib.units import mm
import os

# Pequena ajuda para margens (se estiveres a usar)
def price_with_tiered_margin(base_value: float, percent_uso: float, margins=None) -> float:
    # Se tiveres a função “real” noutro sítio, remove esta e faz import de lá.
    # Aqui deixo um passthrough para não partir nada.
    return float(base_value or 0.0)

def _get(o, name, default=None):
    # Lê atributo tanto em objetos SQLModel como em dicionários
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)

def gerar_pdf_orcamento(cfg, quote, cliente, itens, *, incluir_logo=True) -> bytes:
    """
    Gera o PDF do cliente (layout unificado para Orçamentos e Planeamento).
    - Oculta coluna 'Desc.' se não houver descontos.
    - Soma tinta UV (ml × preço €/ml) ao total da linha, sem margem extra.
    - Mostra logo/empresa, cliente, datas, descrição, itens e totais simples.

    Parâmetros:
      cfg: Settings (com company_name, address, vat, payment_instructions, uv_ink_price_eur_ml, etc.)
      quote: objeto Quote OU dicionário materializado
      cliente: objeto Client
      itens: lista de QuoteItem (objetos)
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 50

    def _footer():
        try:
            c.setFont("Helvetica", 8)
            c.setFillColorRGB(0.4,0.4,0.4)
            c.drawRightString(w-20*mm, 10*mm, f"Página {c.getPageNumber()}")
            c.setFillColorRGB(0,0,0)
        except Exception:
            pass

    # Header
    if incluir_logo and getattr(cfg, 'logo_path', None):
        try:
            c.drawImage(cfg.logo_path, 40, y-40, width=120, height=40, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(w-40, y, getattr(cfg, 'company_name', '') or '')
    y -= 18
    c.setFont("Helvetica", 9)
    c.drawRightString(w-40, y, getattr(cfg, 'company_address', '') or '')
    y -= 12
    c.drawRightString(w-40, y, f"NIF/TVA: {getattr(cfg,'company_vat','') or ''}")
    y -= 16
    c.setFillColorRGB(0.2,0.5,0.9); c.rect(40, y-6, w-80, 6, fill=1, stroke=0)
    c.setFillColorRGB(0,0,0); y -= 18

    numero_txt = _get(quote, 'numero') or '(Rascunho)'
    c.setFont("Helvetica-Bold", 14); c.drawString(40, y, f"Orçamento {numero_txt}"); y -= 16
    c.setFont("Helvetica", 10); c.drawString(40, y, f"Cliente: {getattr(cliente,'nome','')}"); y -= 14

    if getattr(cliente,'email',None):
        c.setFont("Helvetica", 9); c.drawString(40, y, f"Email: {getattr(cliente,'email','')}"); y -= 12
    if getattr(cliente,'telefone',None):
        c.setFont("Helvetica", 9); c.drawString(40, y, f"Telefone: {getattr(cliente,'telefone','')}"); y -= 12

    # Morada do cliente (se existir)
    try:
        if getattr(cliente, 'morada', None):
            c.setFont("Helvetica", 9)
            for ln in str(getattr(cliente, 'morada')).splitlines():
                c.drawString(40, y, ln[:110])
                y -= 12
    except Exception:
        pass

    c.setFont("Helvetica", 9)
    data_criacao = _get(quote, 'data_criacao')
    if data_criacao:
        try: c.drawString(40, y, f"Data: {data_criacao.date().isoformat()}")
        except Exception: c.drawString(40, y, f"Data: {data_criacao}")
        y -= 12

    data_entrega = _get(quote, 'data_entrega_prevista')
    if data_entrega:
        try: c.drawString(40, y, f"Entrega prevista: {data_entrega.date().isoformat()}")
        except Exception: c.drawString(40, y, f"Entrega prevista: {data_entrega}")
        y -= 14

    if _get(quote, 'descricao'):
        c.setFont("Helvetica", 10); c.drawString(40, y, "Descrição:"); y -= 12
        c.setFont("Helvetica", 9)
        for ln in (_get(quote, 'descricao') or '').splitlines():
            c.drawString(60, y, ln[:110]); y -= 12
            if y < 160:
                _footer(); c.showPage(); w, h = A4; y = h - 60
        y -= 6

    # Tabela de itens
    has_disc = any(((getattr(it,'desconto_item',0.0) or 0.0) > 0) for it in itens)
    header = ["Categoria","Nome","Código","Qtd","Un.","Total linha"] if not has_disc else ["Categoria","Nome","Código","Qtd","Un.","Desc.","Total linha"]
    data = [header]

    uv_price = float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0)
    lang = (_get(quote,'lingua','PT') or 'PT').upper()
    subtotal = 0.0

    for it in itens:
        nome_item = getattr(it,'nome_pt','') or ''
        if lang == 'EN' and (getattr(it,'nome_en','') or ''):
            nome_item = getattr(it,'nome_en')
        elif lang == 'FR' and (getattr(it,'nome_fr','') or ''):
            nome_item = getattr(it,'nome_fr')

        if it.unidade == 'min':
            part = float(getattr(it,'preco_unitario_cliente',0.0) or 0.0) * float(getattr(it,'quantidade',0.0) or 0.0)
        else:
            part = float(getattr(it,'preco_unitario_cliente',0.0) or 0.0) * (float(getattr(it,'percent_uso',0.0) or 0.0)/100.0) * float(getattr(it,'quantidade',0.0) or 0.0)

        tl = max(0.0, part - float(getattr(it,'desconto_item',0.0) or 0.0))

        tinta_ml = float(getattr(it,'ink_ml',0.0) or 0.0)
        if tinta_ml > 0:
            tl += uv_price * tinta_ml
            nome_item = f"{nome_item} (Tinta UV: {tinta_ml:.1f} ml)"

        subtotal += tl
        row = [getattr(it,'categoria_item','') or '', nome_item, getattr(it,'code','') or '',
               f"{float(getattr(it,'quantidade',0.0) or 0.0):.0f}", getattr(it,'unidade','') or '']
        if has_disc:
            row += [f"€{float(getattr(it,'desconto_item',0.0) or 0.0):.2f}"]
        row += [f"€{tl:.2f}"]
        data.append(row)

    colw = [85, 180, 70, 35, 35, 75] if not has_disc else [85, 160, 70, 35, 35, 70, 75]
    t = Table(data, colWidths=colw)
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#e8eef9')),
        ('GRID',(0,0),(-1,-1), 0.25, colors.grey),
        ('ALIGN',(3,1),(4,-1), 'CENTER'),
        ('ALIGN',(-1,1),(-1,-1), 'RIGHT'),
        ('FONT',(0,0),(-1,0), 'Helvetica-Bold'),
    ]))
    t.wrapOn(c, w-80, h)
    t.drawOn(c, 40, y-240)
    y -= 250

    # Subtotais simples
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(w-40, y, f"Subtotal (itens): €{subtotal:.2f}")
    y -= 16

    # Validade do orçamento (se existir cfg.quote_valid_days)
    try:
        if hasattr(cfg, 'quote_valid_days') and _get(quote, 'data_criacao'):
            validade_dias = int(getattr(cfg, 'quote_valid_days') or 0)
            if validade_dias > 0:
                validade_data = (_get(quote,'data_criacao').date() + timedelta(days=validade_dias)).isoformat()
                c.setFont("Helvetica", 9); c.drawString(40, y, f"Validade até: {validade_data}"); y -= 12
    except Exception:
        pass

    # Pagamento / IBAN
    pay = []
    iban = getattr(cfg,'company_bank_iban', None) or getattr(cfg,'company_iban', None)
    bic  = getattr(cfg,'company_bank_bic', None)  or getattr(cfg,'company_bic', None)
    if iban: pay.append(f"IBAN: {iban}")
    if bic:  pay.append(f"BIC: {bic}")
    if getattr(cfg,'payment_instructions', None):
        pay += [ln for ln in (cfg.payment_instructions or '').splitlines()]
    if pay:
        c.setFont("Helvetica", 9); c.drawString(40, y, "Pagamento:"); y -= 12
        for ln in pay:
            c.drawString(50, y, ln[:110]); y -= 12

    # Termos e condições
    if getattr(cfg,'terms_conditions', None):
        c.setFont("Helvetica", 9); c.drawString(40, y, "Termos e condições:"); y -= 12
        for ln in (cfg.terms_conditions or '').splitlines():
            c.drawString(40, y, ln[:120]); y -= 12
            if y < 60:
                _footer(); c.showPage(); y = h-60

    _footer(); c.showPage(); c.save()
    return buf.getvalue()