# pages/Planeamento.py
from datetime import datetime, date
import pandas as pd
import streamlit as st
from sqlmodel import select
from app.utils import money_input




from app.db import (
    get_session, Quote, Client, QuoteItem, Settings,
    upgrade_quotes_metrics, upgrade_quoteitem_snapshot,
    upgrade_quote_stock_flag, upgrade_stock_movements_table, apply_stock_on_archive
)

# helper para números (evita erros com strings tipo "€ 1.234,56")
def to_float0(v):
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except Exception:
            return 0.0
    try:
        s = str(v).strip().replace("€", "").replace("\u00a0", " ")
        s = s.replace(" ", "")
        s = s.replace(".", "").replace(",", ".")
        return float(s) if s else 0.0
    except Exception:
        return 0.0



# === Helpers de cálculo (alinhados com Orçamentos) ===
def _uv_price(cfg):
    try:
        return float(getattr(cfg, 'uv_ink_price_eur_ml', 0.0) or 0.0)
    except Exception:
        return 0.0

# tenta obter um "mínimo eficaz" do item, considerando vários nomes possíveis
_MIN_KEYS = (
    'min_ef', 'min_eficaz', 'min_ef_total', 'minimo_eficaz', 'minimo_eficaz_total',
    'min_eficacia', 'min_eficaz_eur', 'min_eficaz_valor'
)


def _get_minimo_eficaz(it):
    for k in _MIN_KEYS:
        if hasattr(it, k):
            try:
                v = getattr(it, k)
                if v is not None:
                    return float(v)
            except Exception:
                continue
    return None

# margem automática (procura em vários campos, item>settings)
def _get_markup_percent(it, cfg):
    # 1) margem definida no próprio item
    for name in (
        'margem_percent', 'markup_percent', 'margem', 'markup',
        'client_markup_percent', 'client_margin_percent'
    ):  # noqa: E231
        if hasattr(it, name) and getattr(it, name) is not None:
            try:
                return float(getattr(it, name) or 0.0)
            except Exception:
                pass
    # 2) regras por tipo
    is_service = (getattr(it, 'unidade', '') == 'min')
    cand = []
    if is_service:
        cand = [
            'margem_servico_percent', 'markup_servico_percent', 'service_markup_percent',
            'margem_servicos_percent', 'markup_servicos_percent'
        ]
    else:
        cand = [
            'margem_material_percent', 'markup_material_percent', 'material_markup_percent',
            'margem_padrao_percent', 'markup_padrao_percent', 'default_markup_percent'
        ]
    for name in cand:
        if cfg is not None and hasattr(cfg, name) and getattr(cfg, name) is not None:
            try:
                return float(getattr(cfg, name) or 0.0)
            except Exception:
                pass
    return 0.0

def item_total_cliente(it, cfg, lang="PT"):
    """
    Total do item para o cliente (mesma regra do PDF/Orçamentos):
    - preço unitário × %uso × qtd (ou × minutos se unidade == 'min')
    - – desconto por item
    - + tinta UV (ml × preço/ml)
    - aplica mínimo eficaz se existir
    - aplica margem automática se necessário
    - prefere subtotal gravado se existir
    """
    try:
        # 0) se já existir um subtotal gravado no item, usa-o
        for stored_name in ('subtotal_cliente', 'total_cliente', 'preco_total_cliente'):
            if hasattr(it, stored_name) and getattr(it, stored_name) is not None:
                return float(getattr(it, stored_name) or 0.0)

        is_service = (getattr(it, 'unidade', '') == 'min')
        uv     = _uv_price(cfg)
        ink_ml = to_float0(getattr(it, 'ink_ml', 0.0))

        if is_service:
            # Serviços: preço do cliente = minutos * custo_interno_min * (1 + margem)  [+ tinta UV]
            mins   = to_float0(getattr(it, 'minutos', getattr(it, 'quantidade', 0.0)))
            cin_m  = getattr(it, 'custo_interno_min', None)
            if cin_m is None:
                cin_m = getattr(it, 'preco_servico_min', None)  # fallback
            base_cost = to_float0(cin_m) * mins
            markup_pct = _get_markup_percent(it, cfg)
            total = base_cost * (1.0 + (markup_pct/100.0))
        else:
            # Materiais: preço unitário do cliente × %uso × qtd (já contém margem na maioria dos casos)
            base = (
                to_float0(getattr(it, 'preco_unitario_cliente', 0.0))
                * (to_float0(getattr(it, 'percent_uso', 0.0)) / 100.0)
                * to_float0(getattr(it, 'quantidade', 0.0))
            )
            # Se parecer um preço "de custo", aplica margem inferred
            inferred = base
            if inferred and inferred <= to_float0(getattr(it, 'preco_compra_unitario', getattr(it,'preco_compra_un', 0.0))) * to_float0(getattr(it,'quantidade',1.0)):
                inferred *= (1.0 + (_get_markup_percent(it, cfg)/100.0))
            total = inferred

        # desconto
        total = max(0.0, total - to_float0(getattr(it, 'desconto_item', 0.0)))
        # tinta UV
        if ink_ml > 0 and uv > 0:
            total += uv * ink_ml
        # mínimo eficaz
        mef = _get_minimo_eficaz(it)
        if mef is not None:
            total = max(total, float(mef))
        return float(total)
    except Exception:
        return 0.0

from app.pdf_utils import gerar_pdf_orcamento

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

st.title("🗂️ Planeamento — Orçamentos em curso")
# garantir que as colunas novas existem (migracoes leves)
upgrade_quotes_metrics()
upgrade_quoteitem_snapshot()
upgrade_quote_stock_flag()
upgrade_stock_movements_table()

# ---------- helpers ----------
STATES = ["RASCUNHO","ENVIADO","APROVADO","EM EXECUÇÃO","ENTREGUE","REJEITADO","EXPIRADO","ARQUIVADO"]

def fmt_dt(v):
    if isinstance(v, datetime): return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):     return v.isoformat()
    return str(v or "")

def get_total(o):
    src = o if isinstance(o, dict) else o.__dict__
    # 1) prefer valor final persistido (novo campo)
    try:
        v = (src.get('final_total_eur') if isinstance(src, dict) else getattr(o, 'final_total_eur'))
        if v is not None:
            return float(v or 0.0)
    except Exception:
        pass
    # 2) variantes legadas
    for fld in ("total", "valor_total", "total_final", "total_sem_iva", "total_final_eur"):
        try:
            val = src.get(fld) if isinstance(src, dict) else getattr(o, fld)
            if val is not None:
                return float(val or 0.0)
        except Exception:
            continue
    return 0.0

def set_if_exists(obj, field, value):
    if isinstance(obj, dict):
        if field in obj:
            obj[field] = value
            return True
        return False
    if hasattr(obj, field):
        setattr(obj, field, value)
        return True
    return False

def ensure_number_if_needed(session, quote, new_state):
    """If the target state is not RASCUNHO and the quote has no number yet,
    assign the next sequential number (YYNNNN). Works regardless of current state."""
    # Only act when moving *to* a non-draft state and no number yet
    if (new_state or "").upper() == "RASCUNHO":
        return
    if getattr(quote, "numero", None):
        return
    yy = datetime.utcnow().strftime("%y")
    existentes = session.exec(select(Quote).where(Quote.numero.like(f"{yy}%"))).all()
    last = 0
    for q in existentes:
        try:
            if q.numero and len(q.numero) >= 6:
                last = max(last, int(q.numero[2:]))
        except Exception:
            pass
    quote.numero = f"{yy}{last+1:04d}"

def validations_ready(o, total_val):
    """Return True only if ALL validation checkboxes exist AND are True,
    and payment is fully covered (pago_valor >= total_val). If any required
    field is missing, returns False (do not auto-archive)."""
    # required validation fields (besides payment)
    required = ["maquete_feita", "maquete_aprovada", "realizado", "entregue"]
    for fld in required:
        if not hasattr(o, fld):
            return False
        if not bool(getattr(o, fld)):
            return False
    # payment check (auto): needs pago_valor
    if hasattr(o, "pago_valor"):
        paid = float(getattr(o, "pago_valor") or 0.0)
        return paid >= float(total_val or 0.0) - 1e-6
    # if there is no pago_valor field, don't auto-archive
    return False

def days_to_due(o, today: date):
    d = getattr(o, "data_entrega_prevista", None)
    if not d: return None
    return (d.date() - today).days

def urgency_badge(days_remaining):
    if days_remaining is None: return ""
    if days_remaining < 0:     return "🔴 atrasado"
    if days_remaining <= 2:    return "🟡"
    return "🟢"


# ---------- carregar dados (materializar para evitar DetachedInstance) ----------
with get_session() as s:
    _rows = s.exec(select(Quote).where(Quote.estado != "ARQUIVADO")).all()
    # aplicar auto-fix de número para estados != RASCUNHO
    try:
        changed_any = False
        for q in _rows:
            est = (getattr(q, "estado", "") or "").upper()
            if est != "RASCUNHO" and not getattr(q, "numero", None):
                ensure_number_if_needed(s, q, est)
                s.add(q)
                changed_any = True
        if changed_any:
            s.commit()
    except Exception:
        pass

    # cache clientes (objetos ainda ligados à sessão, mas vamos só ler nome/número)
    clients_cache = {}
    for q in _rows:
        if q.cliente_id and q.cliente_id not in clients_cache:
            cobj = s.get(Client, q.cliente_id)
            clients_cache[q.cliente_id] = cobj

    # materializar orçamentos em dicionários simples
    qs_all = []
    for q in _rows:
        qs_all.append({
            'id': q.id,
            'numero': getattr(q, 'numero', None),
            'estado': getattr(q, 'estado', ''),
            'cliente_id': getattr(q, 'cliente_id', None),
            'data_criacao': getattr(q, 'data_criacao', None),
            'approved_at': getattr(q, 'approved_at', None),
            'descricao': getattr(q, 'descricao', ''),
            'lingua': getattr(q, 'lingua', 'PT'),
            'observacoes': getattr(q, 'observacoes', '') if hasattr(q, 'observacoes') else '',
            'data_entrega_prevista': getattr(q, 'data_entrega_prevista', None),
            'pago_valor': getattr(q, 'pago_valor', 0.0) if hasattr(q, 'pago_valor') else 0.0,
            'maquete_feita': getattr(q, 'maquete_feita', False) if hasattr(q, 'maquete_feita') else False,
            'maquete_aprovada': getattr(q, 'maquete_aprovada', False) if hasattr(q, 'maquete_aprovada') else False,
            'realizado': getattr(q, 'realizado', False) if hasattr(q, 'realizado') else False,
            'entregue': getattr(q, 'entregue', False) if hasattr(q, 'entregue') else False,
            # totais possíveis
            'total': getattr(q, 'total', None),
            'valor_total': getattr(q, 'valor_total', None),
            'total_final': getattr(q, 'total_final', None),
            'total_sem_iva': getattr(q, 'total_sem_iva', None),
            'final_total_eur': getattr(q, 'final_total_eur', None),
        })

# =======================
# TAB 1 — LISTA
# =======================
# filtros (persistentes)
colf = st.columns([2,2,2,2])
with colf[0]:
    estados_existentes = sorted(set([(q.get("estado", "") or "").upper() for q in qs_all]))
    if 'pl_estados' not in st.session_state:
        st.session_state['pl_estados'] = [e for e in estados_existentes if e != "RASCUNHO"]
    estado_filtro = st.multiselect("Estados", estados_existentes, default=st.session_state['pl_estados'], key="pl_estados")
with colf[1]:
    clientes_opts = ["(Todos)"] + [(f"#{getattr(clients_cache.get(q.get('cliente_id')),'numero_cliente','?')} — {getattr(clients_cache.get(q.get('cliente_id')),'nome','')}", q.get('cliente_id')) for q in qs_all]
    # remover duplicados mantendo ordem
    uniq = []
    seen = set()
    for x in clientes_opts:
        if x == "(Todos)":
            if x not in uniq: uniq.append(x)
            continue
        if x[1] not in seen:
            uniq.append(x); seen.add(x[1])
    if 'pl_cliente_id' not in st.session_state:
        st.session_state['pl_cliente_id'] = None
    # calcular índice com base no cliente_id persistido
    _index = 0
    if st.session_state['pl_cliente_id'] is not None:
        for i, x in enumerate(uniq):
            if isinstance(x, tuple) and x[1] == st.session_state['pl_cliente_id']:
                _index = i; break
    cliente_sel = st.selectbox(
        "Cliente",
        uniq,
        index=_index,
        format_func=lambda x: (x if isinstance(x, str) else x[0])
    )
    cliente_id_filtro = None if cliente_sel == "(Todos)" else cliente_sel[1]
    # guardar no estado
    st.session_state['pl_cliente_id'] = cliente_id_filtro
with colf[2]:
    if 'pl_search' not in st.session_state:
        st.session_state['pl_search'] = ""
    search = st.text_input("Pesquisar (descrição, nº, cliente)...", st.session_state['pl_search'], key="pl_search")
with colf[3]:
    if 'pl_ordenar' not in st.session_state:
        st.session_state['pl_ordenar'] = "Entrega (urgência)"
    ordenar = st.selectbox("Ordenar por", ["Entrega (urgência)","Data","Cliente","Número"], index=["Entrega (urgência)","Data","Cliente","Número"].index(st.session_state['pl_ordenar']), key="pl_ordenar")

today = date.today()
fqs = []
for o in qs_all:
    est = (o.get("estado", "") or "").upper()
    if estado_filtro and est not in estado_filtro: continue
    if cliente_id_filtro and o.get('cliente_id') != cliente_id_filtro: continue
    txt = f"{o.get('numero','')}".lower() + " " + (o.get('descricao','') or "").lower()
    cname = (getattr(clients_cache.get(o.get('cliente_id')),"nome","") or "").lower()
    if search and (search.lower() not in txt and search.lower() not in cname): continue
    fqs.append(o)

def sort_key(o):
    if ordenar.startswith("Entrega"):
        drem = days_to_due(o, today)
        key = (drem if drem is not None else 999999)
        return (key, o.get("numero", "") or "ZZZ")
    if ordenar == "Data":
        d = o.get("data_criacao", None)
        return (d or datetime.min)
    if ordenar == "Cliente":
        c = clients_cache.get(o.get('cliente_id'))
        return getattr(c, "nome", "")
    if ordenar == "Número":
        return o.get("numero", "") or "ZZZ"
    return 0
fqs.sort(key=sort_key)

# resumo
ativos_para_resumo = {"APROVADO","ENVIADO","EM_EXECUCAO","EM EXECUÇÃO","PRODUCAO","PRODUÇÃO","ACEITE","ACEITO"}
total_aprov, total_por_receber = 0.0, 0.0
for o in fqs:
    tot = get_total(o)
    if (o.get("estado","") or "").upper() in ativos_para_resumo:
        total_aprov += tot
    pago = float(o.get("pago_valor",0.0)) if "pago_valor" in o and o.get("pago_valor") is not None else 0.0
    total_por_receber += max(0.0, tot - pago)

m1,m2,m3 = st.columns(3)
m1.metric("Em curso", len(fqs))
m2.metric("Aprovado (estim.)", f"€ {total_aprov:,.2f}".replace(",", " ").replace(".", ",").replace(" ", "."))
m3.metric("Por receber (estim.)", f"€ {total_por_receber:,.2f}".replace(",", " ").replace(".", ",").replace(" ", "."))

st.divider()

with st.expander("🛠️ Reparar dados antigos (agregados e aprovação)"):
    st.caption("Recalcula totais agregados e datas de aprovação para orçamentos já existentes.")
    if st.button("Reparar agora"):
        fixed = 0
        with get_session() as sfix:
            qs = sfix.exec(select(Quote)).all()
            for oo in qs:
                try:
                    # final_total_eur: usa se existir, senão tenta cair para campos antigos
                    total_after = get_total(oo)
                    changed = False
                    if getattr(oo, 'final_total_eur', None) is None and total_after:
                        oo.final_total_eur = float(total_after); changed = True
                    # aprovação: se estado APROVADO e approved_at vazio, usar data_criacao (ou agora)
                    if (getattr(oo, 'estado','') or '').upper() == 'APROVADO' and getattr(oo, 'approved_at', None) is None:
                        base_dt = getattr(oo, 'data_criacao', None) or datetime.utcnow()
                        oo.approved_at = base_dt; changed = True
                    # custos e métricas se ARQUIVADO
                    if (getattr(oo, 'estado','') or '').upper() == 'ARQUIVADO':
                        itens = sfix.exec(select(QuoteItem).where(QuoteItem.quote_id == oo.id)).all()
                        # material
                        mat_cost = 0.0
                        for it in itens:
                            if getattr(it,'unidade','') == 'min':
                                continue
                            unit_cost = getattr(it,'preco_compra_unitario', getattr(it,'preco_compra_un', None))
                            if unit_cost is None:
                                continue
                            perc = to_float0(getattr(it,'percent_uso',0.0)) / 100.0
                            qty  = to_float0(getattr(it,'quantidade',0.0))
                            mat_cost += to_float0(unit_cost) * perc * qty
                        if getattr(oo,'total_material_cost_eur', None) is None and mat_cost > 0:
                            oo.total_material_cost_eur = float(mat_cost); changed = True
                        # serviços
                        srv_cost = 0.0
                        for it in itens:
                            if getattr(it,'unidade','') != 'min':
                                continue
                            mins = to_float0(getattr(it,'minutos', getattr(it,'quantidade',0.0)))
                            unit_srv = getattr(it,'custo_interno_min', getattr(it,'preco_servico_min', None))
                            if unit_srv is not None:
                                srv_cost += to_float0(unit_srv) * mins
                            else:
                                cit = getattr(it, 'custo_interno_total', None)
                                if cit is not None:
                                    srv_cost += to_float0(cit)
                        if getattr(oo,'total_service_internal_cost_eur', None) is None and srv_cost > 0:
                            oo.total_service_internal_cost_eur = float(srv_cost); changed = True
                        # consolidação
                        mat_now = to_float0(oo.total_material_cost_eur)
                        srv_now = to_float0(oo.total_service_internal_cost_eur)
                        tcost = mat_now + srv_now
                        if getattr(oo,'total_cost_eur', None) is None and tcost > 0:
                            oo.total_cost_eur = float(tcost); changed = True
                        if (oo.final_total_eur or 0.0) > 0 and getattr(oo,'expense_percent', None) is None:
                            oo.expense_percent = (tcost / float(oo.final_total_eur)) * 100.0; changed = True
                        if getattr(oo,'profit_eur', None) is None:
                            oo.profit_eur = max(0.0, float(oo.final_total_eur or 0.0) - tcost); changed = True
                except Exception:
                    # proteger execução em reparação em massa — ignora registos problemáticos e continua
                    pass
                if changed:
                    sfix.add(oo)
                    fixed += 1
            sfix.commit()
        st.success(f"Registos atualizados: {fixed}")
        st.rerun()

# tabela principal
rows = []
for o in fqs:
    cliente = clients_cache.get(o.get('cliente_id'))
    drem = days_to_due(o, today)
    badge = urgency_badge(drem)
    total = get_total(o)
    pago = float(o.get("pago_valor",0.0)) if "pago_valor" in o and o.get("pago_valor") is not None else 0.0
    falta = max(0.0, total - pago)
    draft_badge = "📝 SEM NÚMERO" if (not o.get('numero', None)) else ""
    ap_dt = o.get('approved_at')
    ap_str = ''
    try:
        ap_str = f"✅ {ap_dt.date().isoformat()}" if ap_dt else ''
    except Exception:
        ap_str = f"✅ {ap_dt}" if ap_dt else ''
    rows.append({
        "Nº": o.get("numero", None) or "—",
        "Data": (o.get("data_criacao").date().isoformat() if isinstance(o.get("data_criacao"), datetime) else (o.get("data_criacao").isoformat() if isinstance(o.get("data_criacao"), date) else "")),
        "Cliente": getattr(cliente,"nome","") if cliente else "",
        "Valor (€)": total,
        "Pago (€)": pago,
        "Por receber (€)": falta,
        "Descrição": o.get("descricao","") or "",
        "Observações": o.get("observacoes","") if "observacoes" in o else "",
        "Estado": o.get("estado",""),
        "Aprovado em": ap_str,
        "Entrega": (o.get("data_entrega_prevista").date().isoformat() if o.get("data_entrega_prevista") else ""),
        "⏱️ Prazo": badge,
        "Faltam (dias)": (None if drem is None else drem),
    })

df_view = pd.DataFrame(rows)
st.dataframe(
    df_view,
    use_container_width=True,
    height=360,
    hide_index=True,
    column_config={
        "Valor (€)": st.column_config.NumberColumn(format="€ %.2f"),
        "Pago (€)": st.column_config.NumberColumn(format="€ %.2f"),
        "Por receber (€)": st.column_config.NumberColumn(format="€ %.2f"),
        "Faltam (dias)": st.column_config.NumberColumn(format="%d"),
    }
)

st.markdown("—")
st.subheader("Atualizar orçamentos")

for o in fqs:
    cliente = clients_cache.get(o.get('cliente_id'))
    _badge = " 📝 SEM NÚMERO" if not o.get('numero', None) else ""
    numero_txt = o.get('numero', None) or '—'
    _apb = ''
    if o.get('approved_at'):
        try:
            _apb = f"  ✅ {o.get('approved_at').date().isoformat()}"
        except Exception:
            _apb = f"  ✅ {o.get('approved_at')}"
    with st.expander(f"#{numero_txt} — {getattr(cliente,'nome','')}  |  {o.get('estado','')}{_badge}{_apb}"):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            nova_data_ent = st.date_input(
                "Data de entrega",
                value=(o.get('data_entrega_prevista').date() if o.get("data_entrega_prevista", None) else date.today()),
                key=f"date_{o['id']}"
            )
            novas_obs = st.text_area(
                "Observações (internas)",
                value=(o.get("observacoes", "") if "observacoes" in o else ""),
                height=90,
                key=f"obs_{o['id']}"
            )
        with c2:
            estados = STATES
            idx = estados.index(o.get("estado", "")) if o.get("estado", "") in estados else 0
            novo_estado = st.selectbox("Estado", estados, index=idx, key=f"est_{o['id']}")
            st.caption("Validações")
            v1 = st.checkbox("Maquete feita",      value=bool(o.get("maquete_feita", False)),    key=f"v1_{o['id']}")
            v2 = st.checkbox("Maquete aprovada",   value=bool(o.get("maquete_aprovada", False)), key=f"v2_{o['id']}")
            v3 = st.checkbox("Trabalho realizado", value=bool(o.get("realizado", False)),         key=f"v3_{o['id']}")
            v4 = st.checkbox("Entregue",           value=bool(o.get("entregue", False)),          key=f"v4_{o['id']}")
        with c3:
            metodo = st.selectbox(
                "Método de pagamento",
                ["", "Numerário", "Transferência", "Moeda digital", "PayPal"],
                index=( ["", "Numerário", "Transferência", "Moeda digital", "PayPal"].index(o.get("pago_metodo", ""))
                        if o.get("pago_metodo") in ["", "Numerário", "Transferência", "Moeda digital", "PayPal"] else 0 ),
                key=f"met_{o['id']}"
            )
            pago_valor = money_input(
                "Pago (€)", key=f"val_{o['id']}", default=float(o.get("pago_valor", 0.0))
            )
            total_preview = get_total(o)
            pago_ok_auto = (pago_valor >= total_preview)
            st.checkbox(
                "Pago (auto)", value=pago_ok_auto, disabled=True,
                help="Marca automaticamente quando o valor pago for >= total do orçamento.",
                key=f"pago_auto_{o['id']}"
            )
            st.caption(" ")
            save = st.button("💾 Guardar", key=f"save_{o['id']}")
            arch = st.button("🗃️ Arquivar agora", key=f"arch_{o['id']}")
        ac1, ac2 = st.columns([1,1])
        if ac1.button("✏️ Abrir no Orçamentos", key=f"open_{o['id']}"):
            st.session_state['current_quote_id'] = o['id']
            try:
                st.switch_page("pages/Orcamentos_v5_backup.py")
            except Exception:
                st.info("Não consegui mudar de página automaticamente. Vai à página 'Orçamentos' no menu; o orçamento já está selecionado.")
                st.rerun()
        if ac2.button("🧾 Gerar PDF Cliente", key=f"pdf_{o['id']}"):
            with get_session() as spdf:
                cfg = spdf.exec(select(Settings)).first()
                cliente_full = clients_cache.get(o.get('cliente_id'))
                itens = spdf.exec(select(QuoteItem).where(QuoteItem.quote_id == o['id'])).all()
            pdf_bytes = gerar_pdf_orcamento(cfg, o, cliente_full, itens)
            st.download_button("⬇️ Download PDF", data=pdf_bytes, file_name=f"orcamento_{o.get('numero') or 'rascunho'}.pdf", mime="application/pdf", key=f"dl_{o['id']}")

        st.markdown("---")
        st.markdown("**Itens do orçamento (consulta)**")
        with get_session() as s_it:
            itens = s_it.exec(select(QuoteItem).where(QuoteItem.quote_id == o['id'])).all()
            cfg = s_it.exec(select(Settings)).first()
        if not itens:
            st.info("Este orçamento ainda não tem itens.")
        else:
            rows_it = []
            uv_price = _uv_price(cfg)
            lang = (o.get('lingua','PT') or 'PT').upper()
            total_estimado = 0.0
            for it in itens:
                # escolher nome pela língua
                nome_item = getattr(it, 'nome_pt', '') or ''
                if lang == 'EN' and (getattr(it,'nome_en', '') or ''):
                    nome_item = getattr(it, 'nome_en')
                elif lang == 'FR' and (getattr(it,'nome_fr', '') or ''):
                    nome_item = getattr(it, 'nome_fr')
                # subtotal alinhado com Orçamentos (mínimos + tinta UV)
                tl = item_total_cliente(it, cfg, lang)
                tinta_ml = float(getattr(it,'ink_ml',0.0) or 0.0)  # mantemos a coluna informativa
                total_estimado += tl
                rows_it.append({
                    "Categoria": getattr(it,'categoria_item','') or '',
                    "Código": getattr(it,'code','') or '',
                    "Nome": nome_item or (getattr(it,'nome_pt','') or ''),
                    "Qtd": float(getattr(it,'quantidade',0.0) or 0.0),
                    "Un.": getattr(it,'unidade','') or '',
                    "% uso": float(getattr(it,'percent_uso',0.0) or 0.0),
                    "Preço un (cliente)": float(getattr(it,'preco_unitario_cliente',0.0) or 0.0),
                    "Desc. (€)": float(getattr(it,'desconto_item',0.0) or 0.0),
                    "Tinta UV (ml)": tinta_ml,
                    "Subtotal (€)": tl,
                })
            st.dataframe(
                pd.DataFrame(rows_it),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Qtd": st.column_config.NumberColumn(format="%.0f"),
                    "% uso": st.column_config.NumberColumn(format="%.1f%%"),
                    "Preço un (cliente)": st.column_config.NumberColumn(format="€ %.4f"),
                    "Desc. (€)": st.column_config.NumberColumn(format="€ %.2f"),
                    "Tinta UV (ml)": st.column_config.NumberColumn(format="%.1f"),
                    "Subtotal (€)": st.column_config.NumberColumn(format="€ %.2f"),
                }
            )
            st.caption(f"Total estimado (itens): € {total_estimado:,.2f}".replace(","," ").replace(".",",").replace(" ","."))

        if save or arch:
            with get_session() as s:
                oo = s.get(Quote, o['id'])
                # Campos básicos
                if hasattr(oo, "observacoes"):
                    oo.observacoes = novas_obs
                if hasattr(oo, "data_entrega_prevista"):
                    oo.data_entrega_prevista = datetime.combine(nova_data_ent, datetime.min.time())
                # Novo estado (a partir do widget)
                novo_estado = st.session_state.get(f"est_{o['id']}") or o.get('estado')
                # Marcar aprovacao quando entra em APROVADO
                if (novo_estado or '').upper() == 'APROVADO' and getattr(oo, 'approved_at', None) is None:
                    oo.approved_at = datetime.utcnow()
                # Forçar arquivacao pelo botao
                if arch:
                    novo_estado = 'ARQUIVADO'
                # Atribuir numero se sair de rascunho sem numero
                ensure_number_if_needed(s, oo, novo_estado)
                oo.estado = novo_estado
                # Validacoes
                set_if_exists(oo, "maquete_feita", v1)
                set_if_exists(oo, "maquete_aprovada", v2)
                set_if_exists(oo, "realizado", v3)
                set_if_exists(oo, "entregue", v4)
                # Pagamento
                set_if_exists(oo, "pago_metodo", metodo)
                set_if_exists(oo, "pago_valor", float(pago_valor))
                # Pago ok auto
                total_after = get_total(oo)
                set_if_exists(oo, "pago_ok", float(getattr(oo, "pago_valor", 0.0)) >= float(total_after or 0.0) - 1e-6)
                # Auto arquivar se todas validacoes + pagamento ok
                if validations_ready(oo, total_after) and (getattr(oo, "estado", "") or "").upper() != "ARQUIVADO":
                    oo.estado = "ARQUIVADO"
                # Se arquivado, carimbar datas e calcular metricas
                if (oo.estado or '').upper() == 'ARQUIVADO':
                    now = datetime.utcnow()
                    if getattr(oo, 'completed_at', None) is None:
                        oo.completed_at = now
                    oo.archived_at = now
                    # Totais
                    oo.final_total_eur = float(total_after or 0.0)
                    # Calcular custos: material + serviços internos
                    try:
                        itens = s.exec(select(QuoteItem).where(QuoteItem.quote_id == oo.id)).all()
                        # 1) Custo de material
                        mat_cost = 0.0
                        for it in itens:
                            if getattr(it, 'unidade', '') == 'min':
                                continue  # serviços não entram no custo de material
                            unit_cost = getattr(it, 'preco_compra_unitario', None)
                            if unit_cost is None:
                                unit_cost = getattr(it, 'preco_compra_un', None)
                            if unit_cost is None:
                                continue
                            perc = float(getattr(it, 'percent_uso', 0.0) or 0.0) / 100.0
                            qty  = float(getattr(it, 'quantidade', 0.0) or 0.0)
                            mat_cost += to_float0(unit_cost) * perc * qty
                        oo.total_material_cost_eur = (mat_cost if mat_cost > 0 else None)

                        # 2) Custo interno de serviços (por minuto ou total)
                        srv_cost = 0.0
                        for it in itens:
                            if getattr(it, 'unidade', '') != 'min':
                                continue
                            # minutos: alguns modelos guardam em `minutos`, noutros em `quantidade`
                            mins = float(getattr(it, 'minutos', getattr(it, 'quantidade', 0.0)) or 0.0)
                            # custo por minuto conhecido (preferências por campo)
                            unit_srv = getattr(it, 'custo_interno_min', None)
                            if unit_srv is None:
                                unit_srv = getattr(it, 'preco_servico_min', None)
                            if unit_srv is not None:
                                srv_cost += to_float0(unit_srv) * mins
                                continue
                            # fallback: custo interno total diretamente no item, se existir
                            cit = getattr(it, 'custo_interno_total', None)
                            if cit is not None:
                                srv_cost += to_float0(cit)
                                continue
                            # último fallback: usar preço de compra unitário como custo por minuto (pouco comum)
                            unit_srv = getattr(it, 'preco_compra_unitario', getattr(it, 'preco_compra_un', None))
                            if unit_srv is not None:
                                srv_cost += to_float0(unit_srv) * mins
                        oo.total_service_internal_cost_eur = (srv_cost if srv_cost > 0 else None)

                        # 3) Consolidação + métricas
                        mat_now = to_float0(oo.total_material_cost_eur)
                        srv_now = to_float0(oo.total_service_internal_cost_eur)
                        tcost   = mat_now + srv_now
                        oo.total_cost_eur = (tcost if tcost > 0 else None)

                        if (oo.final_total_eur or 0.0) > 0:
                            oo.expense_percent = (tcost / float(oo.final_total_eur)) * 100.0
                        # lucro = total final - custos (material+serviços)
                        oo.profit_eur = float(oo.final_total_eur or 0.0) - tcost
                        if oo.profit_eur is not None and oo.profit_eur < 0:
                            oo.profit_eur = 0.0
                    except Exception:
                        pass
                    # Dias aprovacao -> conclusao
                    try:
                        if getattr(oo, 'approved_at', None) and getattr(oo, 'completed_at', None):
                            delta = oo.completed_at.date() - oo.approved_at.date()
                            oo.days_approval_to_completion = int(delta.days)
                    except Exception:
                        pass
                # Descontar stock uma única vez
                try:
                    if not getattr(oo, 'stock_discount_done', False):
                        apply_stock_on_archive(s, oo.id)
                        oo.stock_discount_done = True
                except Exception:
                    pass
                s.add(oo); s.commit()
            st.success("Orçamento atualizado.")
            st.rerun()