import streamlit as st
from sqlmodel import select
from app.db import get_session, Quote, QuoteItem, Client, Material, Service, Settings
from app.utils import Margins, price_with_tiered_margin, add_border_to_item, money_input
from datetime import datetime, date, timedelta
from app.pdf_utils import gerar_pdf_orcamento

import app.utils  # ativa patch global de number_input (vírgula/ponto; sem saltos)

import os
import json

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

# =============================
#  ORÇAMENTOS — FLUXO SIMPLIFICADO
# =============================

st.title("💼 Orçamentos")

# Carrega configurações e margens
with get_session() as s:
    cfg = s.exec(select(Settings)).first()
    if not cfg:
        st.warning("Defina os Parâmetros primeiro (margens, IVA).")
        cfg = Settings(); s.add(cfg); s.commit(); s.refresh(cfg)

margins = Margins(cfg.margin_0_15, cfg.margin_16_30, cfg.margin_31_70, cfg.margin_71_plus)

# Estado da sessão
if 'current_quote_id' not in st.session_state:
    st.session_state['current_quote_id'] = None
if 'concept_image_path' not in st.session_state:
    st.session_state['concept_image_path'] = None

# ===== Helpers =====

def _load_quote(qid):
    if not qid:
        return None
    with get_session() as s:
        return s.get(Quote, qid)

def _load_items(qid):
    if not qid:
        return []
    with get_session() as s:
        return s.exec(select(QuoteItem).where(QuoteItem.quote_id==qid)).all()

def _client_label(c):
    try:
        return f"#{c.numero_cliente} — {c.nome}"
    except Exception:
        return c.nome


# ===== Cabeçalho do RASCUNHO =====
with get_session() as s:
    clients = s.exec(select(Client).order_by(Client.nome)).all()


c1, c2 = st.columns([1,1])
lingua = c1.selectbox("Língua do orçamento", ["PT","EN","FR"])
cliente = c2.selectbox("Cliente", clients, format_func=_client_label)

# Guardar seleção anterior para detetar alterações e oferecer atualização automática do cabeçalho
if 'prev_cliente_id' not in st.session_state:
    try:
        st.session_state['prev_cliente_id'] = cliente.id
    except Exception:
        st.session_state['prev_cliente_id'] = None
if 'prev_lingua' not in st.session_state:
    st.session_state['prev_lingua'] = lingua

# Track other header fields (defaults; will be set on auto-create/save)
if 'prev_descricao' not in st.session_state:
    st.session_state['prev_descricao'] = ""
if 'prev_data_entrega' not in st.session_state:
    st.session_state['prev_data_entrega'] = None
if 'prev_iva' not in st.session_state:
    st.session_state['prev_iva'] = float(cfg.vat_rate or 0.0)


# Info do cliente
with st.expander("Informação do cliente", expanded=True):
    st.write(f"**Nome:** {getattr(cliente,'nome','')}  ")
    st.write(f"**Nº cliente:** {getattr(cliente,'numero_cliente','')}  ")
    st.write(f"**Email:** {getattr(cliente,'email','')}  ")
    st.write(f"**Telefone:** {getattr(cliente,'telefone','')}  ")
    st.write(f"**Morada:** {getattr(cliente,'morada','')}  ")

descricao = st.text_area("Descrição (aparece no PDF)")
foto = st.file_uploader("FOTOGRAFIA CONCEPTUAL DO TRABALHO (opcional)", type=["png","jpg","jpeg"]) 
data_entrega = st.date_input("Data de entrega", value=date.today())
desc_percent = money_input("Desconto global (%)", key="hdr_desc_percent", default=0.0)
# clamp 0..99
try:
    desc_percent = max(0.0, min(99.0, float(desc_percent or 0.0)))
except Exception:
    desc_percent = 0.0

iva_input = money_input("IVA (%)", key="hdr_iva_percent", default=float(cfg.vat_rate or 0.0))
try:
    iva_input = max(0.0, min(99.0, float(iva_input or 0.0)))
except Exception:
    iva_input = float(cfg.vat_rate or 0.0)

# Se já houver rascunho, detetar alterações de cabeçalho e oferecer aplicação automática
try:
    changed_cliente = st.session_state.get('prev_cliente_id') != getattr(cliente, 'id', None)
    changed_lingua = st.session_state.get('prev_lingua') != lingua
    changed_desc = st.session_state.get('prev_descricao') != (descricao or "")
    changed_date = st.session_state.get('prev_data_entrega') != (data_entrega.isoformat() if isinstance(data_entrega, date) else str(data_entrega))
    changed_iva = float(st.session_state.get('prev_iva') or 0.0) != float(iva_input or 0.0)
    if st.session_state.get('current_quote_id') and (changed_cliente or changed_lingua or changed_desc or changed_date or changed_iva):
        with st.container():
            st.warning("Detetei alterações ao cabeçalho (Cliente/Língua/Descrição/Data/IVA). Queres aplicar ao rascunho agora?")
            ac1, ac2 = st.columns([1,1])
            if ac1.button("✅ Aplicar alterações ao cabeçalho", key="apply_hdr_auto_all"):
                with get_session() as s:
                    qtmp = s.get(Quote, st.session_state['current_quote_id'])
                    if qtmp:
                        try:
                            qtmp.cliente_id = getattr(cliente, 'id', qtmp.cliente_id)
                            qtmp.lingua = lingua
                            qtmp.descricao = descricao
                            qtmp.data_entrega_prevista = datetime.combine(data_entrega, datetime.min.time())
                            qtmp.iva_percent = float(iva_input)
                        except Exception:
                            pass
                        s.add(qtmp); s.commit()
                # Atualizar os trackers
                st.session_state['prev_cliente_id'] = getattr(cliente, 'id', None)
                st.session_state['prev_lingua'] = lingua
                st.session_state['prev_descricao'] = descricao or ""
                st.session_state['prev_data_entrega'] = (data_entrega.isoformat() if isinstance(data_entrega, date) else str(data_entrega))
                st.session_state['prev_iva'] = float(iva_input or 0.0)
                st.success("Cabeçalho atualizado com as novas alterações.")
                st.rerun()
            ac2.caption("Podes também ignorar e clicar mais tarde em ‘💾 Guardar cabeçalho’.")
except Exception:
    pass

# Criar rascunho ou guardar cabeçalho
colh = st.columns([1,1,2])
if st.session_state['current_quote_id'] is None:
    st.info("Ainda não há rascunho ativo. Podes começar já a adicionar itens; um rascunho será **criado automaticamente** ao adicionares o primeiro item. Ou clica em **Criar rascunho** para o fazer agora.")
    if st.button("➕ Criar rascunho agora"):
        with get_session() as s:
            q = Quote(
                cliente_id=cliente.id,
                lingua=lingua,
                descricao=descricao,
                iva_percent=float(iva_input),
                desconto_total=0.0,
                data_entrega_prevista=datetime.combine(data_entrega, datetime.min.time()),
                estado="RASCUNHO"
            )
            s.add(q); s.commit(); s.refresh(q)
            # Tenta guardar o desconto percentual e a imagem conceptual, caso o modelo permita
            try:
                q.desconto_percent = desc_percent
            except Exception:
                pass
            try:
                if foto is not None:
                    os.makedirs("assets/concepts", exist_ok=True)
                    fname = f"assets/concepts/quote_{q.id}_{int(datetime.utcnow().timestamp())}.png"
                    with open(fname, "wb") as f:
                        f.write(foto.read())
                    st.session_state['concept_image_path'] = fname
                    try:
                        q.concept_image_path = fname
                    except Exception:
                        pass
            except Exception:
                pass
            s.add(q); s.commit()
            # Trackers
            st.session_state['prev_cliente_id'] = getattr(cliente, 'id', None)
            st.session_state['prev_lingua'] = lingua
            st.session_state['prev_descricao'] = descricao or ""
            st.session_state['prev_data_entrega'] = (data_entrega.isoformat() if isinstance(data_entrega, date) else str(data_entrega))
            st.session_state['prev_iva'] = float(iva_input or 0.0)
            st.session_state['current_quote_id'] = q.id
        st.success("Rascunho criado. Já podes adicionar itens.")
        st.rerun()
else:
    q = _load_quote(st.session_state['current_quote_id'])
    if colh[0].button("💾 Guardar cabeçalho"):
        with get_session() as s:
            q = s.get(Quote, st.session_state['current_quote_id'])
            q.cliente_id = cliente.id
            q.lingua = lingua
            q.descricao = descricao
            q.data_entrega_prevista = datetime.combine(data_entrega, datetime.min.time())
            q.iva_percent = float(iva_input)
            try:
                q.desconto_percent = desc_percent
            except Exception:
                pass
            try:
                if foto is not None:
                    os.makedirs("assets/concepts", exist_ok=True)
                    fname = f"assets/concepts/quote_{q.id}_{int(datetime.utcnow().timestamp())}.png"
                    with open(fname, "wb") as f:
                        f.write(foto.read())
                    st.session_state['concept_image_path'] = fname
                    try:
                        q.concept_image_path = fname
                    except Exception:
                        pass
            except Exception:
                pass
            s.add(q); s.commit()
            # Atualizar trackers após guardar manualmente
            st.session_state['prev_cliente_id'] = getattr(cliente, 'id', None)
            st.session_state['prev_lingua'] = lingua
            st.session_state['prev_descricao'] = descricao or ""
            st.session_state['prev_data_entrega'] = (data_entrega.isoformat() if isinstance(data_entrega, date) else str(data_entrega))
            st.session_state['prev_iva'] = float(iva_input or 0.0)
            st.success("Cabeçalho guardado.")

    # Botão para iniciar um novo rascunho em branco
    if colh[1].button("🧹 Novo rascunho em branco"):
        st.session_state['current_quote_id'] = None
        st.session_state['concept_image_path'] = None
        st.rerun()
# ===== Total ao vivo (topo) =====
if st.session_state['current_quote_id']:
    items_live = _load_items(st.session_state['current_quote_id'])
    total_sem_iva = 0.0
    for it in items_live:
        # usar subtotal gravado se existir; caso contrário, calcular como antes
        if getattr(it, 'subtotal_cliente', None) is not None:
            val = float(it.subtotal_cliente)
        else:
            if it.unidade == "min":
                part = it.preco_unitario_cliente * it.quantidade
            else:
                part = (it.preco_unitario_cliente * (it.percent_uso/100.0)) * it.quantidade
            val = price_with_tiered_margin(part, it.percent_uso, margins) - (it.desconto_item or 0.0)
            # adicionar tinta UV ao total do cliente quando aplicável (sem margem extra)
            try:
                if getattr(it, 'tipo_item', '') == 'SERVICO' and (getattr(it, 'ink_ml', 0.0) or 0.0) > 0:
                    val += float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0) * float(getattr(it, 'ink_ml', 0.0) or 0.0)
            except Exception:
                pass
        total_sem_iva += max(0.0, val)
    desconto_global_val = total_sem_iva * (desc_percent/100.0)
    subtotal = total_sem_iva - desconto_global_val
    iva = subtotal * (q.iva_percent/100.0) if st.session_state['current_quote_id'] else 0.0
    total_final = subtotal + iva
    st.metric("Total do orçamento (€)", f"{total_final:.2f}")

st.divider()

# ===== Adicionar itens =====
st.subheader("Adicionar itens")

# Catálogo unificado (Materiais + Serviços)
with get_session() as s:
    mats = s.exec(select(Material)).all()
    svs = s.exec(select(Service)).all()

catalog = [("MATERIAL", m.id) for m in mats] + [("SERVICO", sv.id) for sv in svs]

def _label_for(opt):
    kind, oid = opt
    if kind == "MATERIAL":
        m = next(x for x in mats if x.id == oid)
        nm = (m.nome_pt or "");
        if lingua == 'EN' and (m.nome_en or ''): nm = m.nome_en
        if lingua == 'FR' and (m.nome_fr or ''): nm = m.nome_fr
        return f"[M] {m.code} — {nm} ({m.categoria})"
    else:
        sv = next(x for x in svs if x.id == oid)
        nm = (sv.nome_pt or "");
        if lingua == 'EN' and (sv.nome_en or ''): nm = sv.nome_en
        if lingua == 'FR' and (sv.nome_fr or ''): nm = sv.nome_fr
        return f"[S] {sv.code} — {nm} ({sv.categoria})"

# << alteração: pesquisar sem rascunho >>
sel = st.selectbox("Pesquisar por código", catalog, format_func=_label_for, disabled=False)

# << alteração: abrir formulário mesmo sem rascunho >>
if sel:
    kind, oid = sel
    obj = next((x for x in (mats if kind=="MATERIAL" else svs) if x.id==oid))
    # Detetar tipo de máquina para serviços (LASER/UV) e tinta UV (ml)
    service_machine = getattr(obj, 'machine_type', '') if kind == 'SERVICO' else '—'
    ink_ml_input = 0.0
    if kind == 'SERVICO' and service_machine == 'UV':
        ink_ml_input = money_input("Tinta consumida (ml)", key="ink_ml_input", default=0.0)
        try:
            ink_ml_input = max(0.0, float(ink_ml_input or 0.0))
        except Exception:
            ink_ml_input = 0.0
    # Unidade e nome na língua
    unidade_default = getattr(obj,'unidade', None) or ("cm²" if (getattr(obj,'largura_cm',0) * getattr(obj,'altura_cm',0) > 0) else ("min" if kind=="SERVICO" else "PC"))
    unidade_opts = ["cm²", "min", "PC"]
    try:
        idx_un = unidade_opts.index(unidade_default) if unidade_default in unidade_opts else 0
    except Exception:
        idx_un = 0
    unidade = st.selectbox("Unidade", unidade_opts, index=idx_un)

    # Dimensões e quantidade
    if unidade == "cm²":
        largura = money_input("Largura (cm)", key="largura_cm", default=0.0)
        altura = money_input("Altura (cm)", key="altura_cm", default=0.0)
        try:
            largura = max(0.0, float(largura or 0.0))
            altura = max(0.0, float(altura or 0.0))
        except Exception:
            largura, altura = 0.0, 0.0
        largura_i, altura_i = add_border_to_item(largura, altura)
        base_area = max(0.0, float(getattr(obj,'largura_cm',0)) * float(getattr(obj,'altura_cm',0)))
        used_area = largura_i * altura_i
        percent_uso = min(10000.0, (used_area/base_area*100.0) if base_area>0 and used_area>0 else 0.0)
    else:
        largura = 0.0; altura = 0.0; percent_uso = 100.0
    quantidade = money_input("Quantidade", key="quantidade", default=1.0)
    try:
        quantidade = max(1.0, float(quantidade or 1.0))
    except Exception:
        quantidade = 1.0

    # Preços base
    preco_unit = getattr(obj, 'preco_cliente_un', None) or getattr(obj, 'preco_cliente', 0.0)
    # Pré-visualização preço cliente
    part_val = (preco_unit*(percent_uso/100.0))*quantidade if unidade != 'min' else preco_unit*quantidade
    preco_cliente_prev = price_with_tiered_margin(part_val, percent_uso, margins)
    # adicionar custo de tinta UV ao subtotal do cliente (sem margem extra)
    tinta_extra_preview = 0.0
    if kind == 'SERVICO' and service_machine == 'UV':
        try:
            tinta_extra_preview = float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0) * float(ink_ml_input or 0.0)
        except Exception:
            tinta_extra_preview = 0.0
        preco_cliente_prev += tinta_extra_preview
    # Se a unidade for cm² e a área usada for 0, anula a pré-visualização do cliente
    if unidade == 'cm²' and ((largura_i * altura_i) <= 0):
        preco_cliente_prev = 0.0
    # Custo real
    if kind == "MATERIAL":
        custo_real_prev = (float(obj.preco_compra_un) * (percent_uso/100.0)) * quantidade
    else:
        # custo interno do serviço: minutos_por_unidade × custo_por_minuto × quantidade (+ extras + tinta UV quando aplicável)
        try:
            minutos_un = float(getattr(obj, 'minutos_por_unidade', 0.0) or 0.0)
        except Exception:
            minutos_un = 0.0
        try:
            cpm = float(getattr(obj, 'custo_por_minuto', 0.0) or 0.0)
        except Exception:
            cpm = 0.0
        scale = (percent_uso/100.0) if unidade != 'min' else 1.0
        base = cpm * minutos_un * float(quantidade or 0.0) * float(scale)
        tinta_line_prev = 0.0
        try:
            if service_machine == 'UV' and (ink_ml_input or 0.0) > 0:
                tinta_line_prev = float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0) * float(ink_ml_input or 0.0)
        except Exception:
            tinta_line_prev = 0.0
        custo_real_prev = base + float(getattr(obj, 'custo_extra', 0.0) or 0.0) + float(getattr(obj, 'custo_fornecedor', 0.0) or 0.0) + tinta_line_prev
        minutos_efetivos_prev = float(minutos_un) * float(quantidade or 0.0) * float(scale)

    # Pré-visualização detalhada de custos
    if unidade == 'cm²' and ((largura_i * altura_i) <= 0):
        st.warning('Indica Largura × Altura para calcular o valor por área.')
    if kind == 'MATERIAL':
        if service_machine == 'UV' and (ink_ml_input or 0) > 0:
            st.info(f"Pré-visualização — Subtotal cliente: €{preco_cliente_prev:.2f} (incl. tinta €{tinta_extra_preview:.2f}) | Custo compra (uso): €{custo_real_prev:.2f}")
        else:
            st.info(f"Pré-visualização — Subtotal cliente: €{preco_cliente_prev:.2f} | Custo compra (uso): €{custo_real_prev:.2f}")
    else:
        if service_machine == 'UV' and (ink_ml_input or 0) > 0:
            st.info(f"Pré-visualização — Subtotal cliente: €{preco_cliente_prev:.2f} (incl. tinta €{tinta_extra_preview:.2f}) | Custo (serviço): €{custo_real_prev:.2f} | Min ef.: {minutos_efetivos_prev:.2f}")
        else:
            st.info(f"Pré-visualização — Subtotal cliente: €{preco_cliente_prev:.2f} | Custo (serviço): €{custo_real_prev:.2f} | Min ef.: {minutos_efetivos_prev:.2f}")

    # Categoria e descrição (auto na língua)
    categoria_item = st.text_input("Categoria do item", getattr(obj, 'categoria', '') or '')
    nome_pt = getattr(obj,'nome_pt','')
    nome_en = getattr(obj,'nome_en','')
    nome_fr = getattr(obj,'nome_fr','')

    btcols = st.columns([1,2])
    # << alteração: permitir adicionar sem rascunho (com guarda cm²/L×A) e criar rascunho no click se faltar >>
    _qstate = _load_quote(st.session_state['current_quote_id']) if st.session_state.get('current_quote_id') else None
    _disable_add = (unidade == 'cm²' and ((largura_i * altura_i) <= 0)) or (_qstate is not None and _qstate.estado != 'RASCUNHO')
    if btcols[0].button("Adicionar ao orçamento", disabled=_disable_add):
        with get_session() as s:
            qid = st.session_state.get('current_quote_id')
            if not qid:
                q = Quote(
                    cliente_id=cliente.id,
                    lingua=lingua,
                    descricao=descricao,
                    iva_percent=float(iva_input),
                    desconto_total=0.0,
                    data_entrega_prevista=datetime.combine(data_entrega, datetime.min.time()),
                    estado="RASCUNHO"
                )
                s.add(q); s.commit(); s.refresh(q)
                st.session_state['prev_cliente_id'] = getattr(cliente, 'id', None)
                st.session_state['prev_lingua'] = lingua
                st.session_state['prev_descricao'] = descricao or ""
                st.session_state['prev_data_entrega'] = (data_entrega.isoformat() if isinstance(data_entrega, date) else str(data_entrega))
                st.session_state['prev_iva'] = float(iva_input or 0.0)
                st.session_state['current_quote_id'] = q.id
            else:
                q = s.get(Quote, qid)
            # custo de compra (snapshot) — apenas para materiais (para métricas de arquivo)
            unit_cost_snapshot = None
            try:
                if kind == 'MATERIAL':
                    unit_cost_snapshot = float(getattr(obj, 'preco_compra_un', None) or 0.0) or None
            except Exception:
                unit_cost_snapshot = None

            # snapshot de contexto (margens, máquina, energia, tinta UV, IVA)
            try:
                snap = {
                    "ts": datetime.utcnow().isoformat(),
                    "lingua": lingua,
                    "cliente_id": getattr(cliente, 'id', None),
                    "margins": {
                        "0_15": float(getattr(cfg, 'margin_0_15', 0) or 0),
                        "16_30": float(getattr(cfg, 'margin_16_30', 0) or 0),
                        "31_70": float(getattr(cfg, 'margin_31_70', 0) or 0),
                        "71_plus": float(getattr(cfg, 'margin_71_plus', 0) or 0),
                    },
                    "iva_percent": float(getattr(cfg, 'vat_rate', 0) or 0),
                    "machine_type": service_machine,
                    "uv_ink_price_eur_ml": float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0),
                    # parâmetros de energia/desgaste, se existirem no Settings
                    "laser": {
                        "energia_eur_kwh": float(getattr(cfg, 'laser_energy_eur_kwh', 0.0) or 0.0),
                        "desgaste_eur_min": float(getattr(cfg, 'laser_wear_eur_min', 0.0) or 0.0),
                        "lucro_sobre_maquina_percent": float(getattr(cfg, 'laser_profit_over_machine_percent', 0.0) or 0.0),
                    },
                    "uv": {
                        "energia_eur_kwh": float(getattr(cfg, 'uv_energy_eur_kwh', 0.0) or 0.0),
                        "desgaste_eur_min": float(getattr(cfg, 'uv_wear_eur_min', 0.0) or 0.0),
                        "lucro_sobre_maquina_percent": float(getattr(cfg, 'uv_profit_over_machine_percent', 0.0) or 0.0),
                        "tinta_eur_ml": float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0),
                    },
                }
                snapshot_json = json.dumps(snap)
            except Exception:
                snapshot_json = None

            qi = QuoteItem(
                quote_id=q.id,
                categoria_item=categoria_item,
                tipo_item=kind,
                ref_id=obj.id,
                code=getattr(obj,'code',''),
                nome_pt=nome_pt,
                nome_en=nome_en,
                nome_fr=nome_fr,
                unidade=unidade,
                largura_cm=largura,
                altura_cm=altura,
                quantidade=quantidade,
                preco_unitario_cliente=preco_unit,
                percent_uso=percent_uso,
                desconto_item=0.0,
                ink_ml=float(ink_ml_input or 0.0),
                preco_compra_unitario=unit_cost_snapshot,
                snapshot_json=snapshot_json,
            )
            # guardar o subtotal do cliente conforme pré-visualização
            try:
                qi.subtotal_cliente = float(preco_cliente_prev)
            except Exception:
                pass
            s.add(qi); s.commit()
            st.success("Item adicionado.")
            st.rerun()

st.divider()

# ===== Itens adicionados (agrupados por categoria) =====
if st.session_state['current_quote_id']:
    items = _load_items(st.session_state['current_quote_id'])
    # mapa de serviços para custos internos
    with get_session() as _s_srv:
        _all_srv = {sv.id: sv for sv in _s_srv.exec(select(Service)).all()}
    if not items:
        st.info("Ainda não há itens neste orçamento.")
    else:
        # Agrupar
        grupos = {}
        for it in items:
            grupos.setdefault(it.categoria_item or "—", []).append(it)

        total_sem_iva = 0.0
        total_mat_cost = 0.0  # custo compra (uso) total
        total_srv_cost = 0.0  # custo interno total de serviços
        q_live = _load_quote(st.session_state['current_quote_id'])
        for cat, lst in grupos.items():
            st.markdown(f"### {cat}")
            g_sub = 0.0
            g_mat = 0.0  # custo compra (uso) por categoria
            for it in lst:
                # subtotal da linha (preferir subtotal_cliente gravado)
                if getattr(it, 'subtotal_cliente', None) is not None:
                    val = float(it.subtotal_cliente)
                    tinta_extra_line = 0.0
                else:
                    if it.unidade == 'min':
                        part = it.preco_unitario_cliente * it.quantidade
                    else:
                        part = (it.preco_unitario_cliente*(it.percent_uso/100.0)) * it.quantidade
                    val = price_with_tiered_margin(part, it.percent_uso, margins) - (it.desconto_item or 0.0)
                    # Tinta UV (sem margem adicional)
                    tinta_extra_line = 0.0
                    try:
                        if (getattr(it, 'ink_ml', 0.0) or 0.0) > 0:
                            tinta_extra_line = float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0) * float(getattr(it, 'ink_ml', 0.0) or 0.0)
                            val += tinta_extra_line
                    except Exception:
                        tinta_extra_line = 0.0
                g_sub += max(0.0, val)
                # custo interno do serviço (min/un × custo/min × qtd) + extras + tinta UV
                service_internal_line = None
                if getattr(it, 'tipo_item', '') == 'SERVICO':
                    try:
                        _sv = _all_srv.get(it.ref_id)
                        minutos_un = float(getattr(_sv, 'minutos_por_unidade', 0.0) or 0.0) if _sv else 0.0
                        cpm = float(getattr(_sv, 'custo_por_minuto', 0.0) or 0.0) if _sv else 0.0
                        extra = float(getattr(_sv, 'custo_extra', 0.0) or 0.0) if _sv else 0.0
                        fornec = float(getattr(_sv, 'custo_fornecedor', 0.0) or 0.0) if _sv else 0.0
                        tinta_line = float(getattr(it, 'ink_ml', 0.0) or 0.0) * float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0)
                        scale = (float(getattr(it,'percent_uso',0.0) or 0.0)/100.0) if getattr(it,'unidade','min') != 'min' else 1.0
                        service_internal_line = (cpm * minutos_un * float(it.quantidade or 0.0) * float(scale)) + extra + fornec + tinta_line
                        minutes_effective_line = float(minutos_un) * float(it.quantidade or 0.0) * float(scale)
                        total_srv_cost += float(service_internal_line)
                    except Exception:
                        service_internal_line = None

                # custo de compra da percentagem usada (apenas materiais)
                custo_compra_uso_line = None
                try:
                    if (getattr(it, 'tipo_item', '') == 'MATERIAL') and (it.unidade != 'min'):
                        unit_cost_snap = getattr(it, 'preco_compra_unitario', None)
                        if unit_cost_snap is not None:
                            custo_compra_uso_line = float(unit_cost_snap) * (float(it.percent_uso or 0.0)/100.0) * float(it.quantidade or 0.0)
                except Exception:
                    custo_compra_uso_line = None
                if custo_compra_uso_line is not None:
                    g_mat += float(custo_compra_uso_line)

                # edição inline apenas em RASCUNHO
                if q_live and q_live.estado == 'RASCUNHO':
                    c1, c2, c3, c4, c5 = st.columns([3,1,1,1,1])
                    nome_visivel = it.nome_pt or it.nome_en or it.nome_fr or "(sem nome)"
                    extra_cost_txt = (f" | Custo compra (uso): €{custo_compra_uso_line:.2f}" if custo_compra_uso_line is not None else "")
                    if getattr(it, 'tipo_item', '') == 'SERVICO' and service_internal_line is not None:
                        extra_cost_txt = f" | Custo (serviço): €{float(service_internal_line):.2f}"
                        extra_cost_txt += f" | Min ef.: {float(minutes_effective_line):.2f}"
                    c1.markdown(
                        f"**{it.code} — {nome_visivel}**  \n"
                        f"{it.quantidade} × {it.unidade} | % uso: {it.percent_uso:.1f} | € un: {it.preco_unitario_cliente:.2f} | **Subtotal:** €{val:.2f}{extra_cost_txt}"
                    )
                    try:
                        if (getattr(it, 'ink_ml', 0.0) or 0.0) > 0:
                            st.caption(f"🖨️ Tinta UV: {float(getattr(it,'ink_ml',0.0)):.1f} ml")
                    except Exception:
                        pass
                    new_qtd = money_input("Qtd", key=f"q_{it.id}", default=float(it.quantidade or 0.0))
                    try:
                        new_qtd = max(0.0, float(new_qtd or 0.0))
                    except Exception:
                        new_qtd = float(it.quantidade or 0.0)

                    new_pct = money_input("% uso", key=f"p_{it.id}", default=float(it.percent_uso or 0.0))
                    try:
                        new_pct = max(0.0, float(new_pct or 0.0))
                    except Exception:
                        new_pct = float(it.percent_uso or 0.0)

                    new_desc = money_input("Desc €", key=f"d_{it.id}", default=float(it.desconto_item or 0.0))
                    try:
                        new_desc = max(0.0, float(new_desc or 0.0))
                    except Exception:
                        new_desc = float(it.desconto_item or 0.0)
                    btn_save, btn_del = c5.columns(2)
                    if btn_save.button("Guardar", key=f"save_{it.id}"):
                        with get_session() as s2:
                            it.quantidade = new_qtd
                            it.percent_uso = new_pct
                            it.desconto_item = new_desc
                            # atualizar subtotal_cliente após edição
                            try:
                                if it.unidade == 'min':
                                    part = float(it.preco_unitario_cliente or 0.0) * float(new_qtd or 0.0)
                                else:
                                    part = float(it.preco_unitario_cliente or 0.0) * (float(new_pct or 0.0)/100.0) * float(new_qtd or 0.0)
                                new_val = price_with_tiered_margin(part, float(new_pct or 0.0), margins) - float(new_desc or 0.0)
                                if float(getattr(it, 'ink_ml', 0.0) or 0.0) > 0:
                                    new_val += float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0) * float(getattr(it, 'ink_ml', 0.0) or 0.0)
                                it.subtotal_cliente = float(max(0.0, new_val))
                            except Exception:
                                pass
                            s2.add(it); s2.commit()
                        st.success("Item atualizado.")
                        st.rerun()
                    if btn_del.button("🗑", key=f"del_{it.id}"):
                        with get_session() as s2:
                            s2.delete(it); s2.commit()
                        st.warning("Item removido.")
                        st.rerun()
                else:
                    tinta_note = ""
                    try:
                        if (getattr(it, 'ink_ml', 0.0) or 0.0) > 0:
                            tinta_note = f" | Tinta UV: {float(getattr(it,'ink_ml',0.0)):.1f} ml"
                    except Exception:
                        tinta_note = ""
                    extra_cost_txt = (f" | Custo compra (uso): €{custo_compra_uso_line:.2f}" if custo_compra_uso_line is not None else "")
                    if getattr(it, 'tipo_item', '') == 'SERVICO' and service_internal_line is not None:
                        extra_cost_txt = f" | Custo (serviço): €{float(service_internal_line):.2f}"
                        extra_cost_txt += f" | Min ef.: {float(minutes_effective_line):.2f}"
                    st.write(
                        f"- {it.code} — {it.nome_pt or it.nome_en or it.nome_fr or '(sem nome)'} | "
                        f"{it.quantidade} × {it.unidade} | % uso: {it.percent_uso:.1f} | "
                        f"€ un: {it.preco_unitario_cliente:.2f} | Subtotal: €{val:.2f}{tinta_note}{extra_cost_txt}"
                    )
            total_sem_iva += g_sub
            st.markdown(f"**Subtotal categoria:** €{g_sub:.2f}")
            if g_mat > 0:
                st.caption(f"Custo compra (uso) da categoria: €{g_mat:.2f}")
            total_sem_iva += 0.0  # no-op for clarity
            total_mat_cost += g_mat
            st.divider()

        desconto_global_val = total_sem_iva * (desc_percent/100.0)
        subtotal = total_sem_iva - desconto_global_val
        iva = subtotal * ((_load_quote(st.session_state['current_quote_id']).iva_percent)/100.0)
        total_final = subtotal + iva
        c1, c2, c3 = st.columns(3)
        c1.metric("Subtotal (€ s/IVA)", f"{subtotal:.2f}")
        c2.metric("IVA (€)", f"{iva:.2f}")
        c3.metric("Total (€)", f"{total_final:.2f}")
        c4, c5, c6 = st.columns(3)
        c4.metric("Custo compra (materiais) (€)", f"{total_mat_cost:.2f}")
        c5.metric("Custo interno (serviços) (€)", f"{total_srv_cost:.2f}")
        c6.metric("Lucro estimado s/IVA (€)", f"{max(0.0, subtotal - (total_mat_cost + total_srv_cost)):.2f}")

        colf = st.columns([1,1,1,2])
        if colf[0].button("📦 Guardar rascunho e enviar para Planeamento"):
            with get_session() as s:
                q = s.get(Quote, st.session_state['current_quote_id'])
                q.estado = "PLANEAMENTO"
                # desconto_total e percentagem de desconto
                try:
                    q.desconto_total = total_sem_iva * (desc_percent/100.0)
                except Exception:
                    pass
                try:
                    q.desconto_percent = float(desc_percent)
                except Exception:
                    pass

                # Guardar totais agregados antes de mover para Planeamento
                try:
                    q.final_total_eur = float(total_final)
                except Exception:
                    pass
                try:
                    q.total_material_cost_eur = float(total_mat_cost)
                except Exception:
                    pass
                try:
                    # custo interno total (serviços)
                    q.total_service_internal_cost_eur = float(total_srv_cost)
                except Exception:
                    pass
                try:
                    # lucro estimado (sem IVA): subtotal - custos (mat + serv)
                    lucro_est = max(0.0, float(subtotal) - (float(total_mat_cost) + float(total_srv_cost)))
                    q.profit_eur = float(lucro_est)
                except Exception:
                    pass
                try:
                    # % gastos = custo_total / total_final
                    if float(total_final) > 0:
                        q.expense_percent = float((float(total_mat_cost) + float(total_srv_cost)) / float(total_final) * 100.0)
                except Exception:
                    pass

                s.add(q); s.commit()
                st.success("Rascunho guardado e movido para Planeamento (sem número, continua como rascunho no Planeamento).")
                st.rerun()

        # Duplicar orçamento atual como novo rascunho
        if colf[1].button("📄 Duplicar orçamento"):
            with get_session() as s:
                old = s.get(Quote, st.session_state['current_quote_id'])
                # criar novo orçamento em RASCUNHO com os mesmos dados de cabeçalho
                new_q = Quote(
                    cliente_id=old.cliente_id,
                    lingua=old.lingua,
                    descricao=old.descricao,
                    iva_percent=old.iva_percent,
                    desconto_total=old.desconto_total,
                    data_entrega_prevista=old.data_entrega_prevista,
                    estado="RASCUNHO"
                )
                # campos opcionais
                try:
                    new_q.desconto_percent = getattr(old, 'desconto_percent', 0.0)
                except Exception:
                    pass
                try:
                    new_q.concept_image_path = getattr(old, 'concept_image_path', None)
                except Exception:
                    pass
                s.add(new_q); s.commit(); s.refresh(new_q)

                # clonar itens
                old_items = s.exec(select(QuoteItem).where(QuoteItem.quote_id == old.id)).all()
                for it in old_items:
                    s.add(QuoteItem(
                        quote_id=new_q.id,
                        categoria_item=it.categoria_item,
                        tipo_item=it.tipo_item,
                        ref_id=it.ref_id,
                        code=it.code,
                        nome_pt=it.nome_pt,
                        nome_en=it.nome_en,
                        nome_fr=it.nome_fr,
                        unidade=it.unidade,
                        largura_cm=it.largura_cm,
                        altura_cm=it.altura_cm,
                        quantidade=it.quantidade,
                        preco_unitario_cliente=it.preco_unitario_cliente,
                        percent_uso=it.percent_uso,
                        desconto_item=it.desconto_item,
                        ink_ml=getattr(it, 'ink_ml', 0.0),
                        preco_compra_unitario=getattr(it, 'preco_compra_unitario', None),
                        snapshot_json=getattr(it, 'snapshot_json', None),
                        subtotal_cliente=getattr(it, 'subtotal_cliente', None),
                    ))
                s.commit()

            st.session_state['current_quote_id'] = new_q.id
            st.success("Orçamento duplicado como novo rascunho.")
            st.rerun()

        # Gerar PDF Cliente (download)
        if colf[2].button("🧾 Gerar PDF Cliente"):
            with get_session() as s:
                q = s.get(Quote, st.session_state['current_quote_id'])
                cli = s.get(Client, q.cliente_id)
                items_all = s.exec(select(QuoteItem).where(QuoteItem.quote_id == q.id)).all()
            pdf_bytes = gerar_pdf_orcamento(cfg, q, cli, items_all)
            st.download_button(
                "⬇️ Download PDF",
                data=pdf_bytes,
                file_name=f"orcamento_{q.numero or q.id}.pdf",
                mime="application/pdf"
            )