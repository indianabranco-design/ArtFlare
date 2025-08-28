# pages/0_Dashboard.py — Painel principal
from pathlib import Path
import re
import streamlit as st

st.set_page_config(page_title="📌 Painel", page_icon="📌", layout="wide")

# (Opcional) Mini sidebar, se existir
try:
    from app.sidebar import show_sidebar
    show_sidebar()
except Exception:
    pass

BASE = Path(__file__).resolve().parents[1]
PAGES = BASE / "pages"


# Util: encontra o primeiro ficheiro em /pages que combine com os prefixos (robusto)
_norm_rx = re.compile(r"[^a-z0-9]+", re.IGNORECASE)

def _normalize(s: str) -> str:
    return _norm_rx.sub("", str(s).lower())

def _strip_num_prefix(name: str) -> str:
    return re.sub(r"^\d+_", "", name)

def _find_page(*candidates: str) -> str | None:
    if not PAGES.exists():
        return None
    files = [p.name for p in PAGES.iterdir() if p.suffix == ".py" and not p.name.startswith("_")]
    if not files:
        return None

    # Primeira tentativa: match por startswith (como antes)
    for cand in candidates:
        for name in sorted(files):
            if name.startswith(cand):
                return f"pages/{name}"

    # Segunda tentativa: remover prefixo numérico do filename e tentar startswith
    for cand in candidates:
        for name in sorted(files):
            if _strip_num_prefix(name).startswith(cand):
                return f"pages/{name}"

    # Terceira tentativa: match "contém" com normalização (ignora underscores, maiúsculas, acentos removidos por aproximação)
    norm_cands = [_normalize(c) for c in candidates]
    for name in sorted(files):
        nname = _normalize(_strip_num_prefix(name))
        for nc in norm_cands:
            if nc and nc in nname:
                return f"pages/{name}"

    return None

has_page_link = hasattr(st, "page_link")

st.title("📌 Painel principal")
st.caption("Atalhos rápidos e visão geral do sistema.")

# (Opcional) KPIs rápidos — só se a BD estiver acessível
try:
    from datetime import date, timedelta
    from sqlmodel import select
    from app.db import get_session, Quote, Material

    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # segunda
    week_end = week_start + timedelta(days=6)
    tomorrow = today + timedelta(days=1)

    with get_session() as s:
        # Totais básicos
        q = Quote  # alias
        rasc = s.exec(select(Quote).where(Quote.estado == "RASCUNHO")).all()
        curso = s.exec(select(Quote).where((Quote.estado != "RASCUNHO") & (Quote.estado != "ARQUIVADO"))).all()
        arq = s.exec(select(Quote).where(Quote.estado == "ARQUIVADO")).all()

        total_rasc = len(rasc)
        total_curso = len(curso)
        total_arq = len(arq)

        # Entregas esta semana (qualquer estado que não seja ARQUIVADO)
        def _entrega_in_semana(o) -> bool:
            dt = getattr(o, "data_entrega_prevista", None) or getattr(o, "entrega", None)
            try:
                d = dt.date() if hasattr(dt, "date") else dt
            except Exception:
                d = None
            return (d is not None) and (week_start <= d <= week_end)

        entregas_semana = sum(1 for o in curso if _entrega_in_semana(o))

        # € aprovados por receber (€): soma de (total_final - pago) quando estado == APROVADO
        def _as_float(x):
            try:
                return float(x or 0)
            except Exception:
                return 0.0

        aprovados = [o for o in curso if getattr(o, "estado", "") == "APROVADO"]
        por_receber = 0.0
        for o in aprovados:
            total_final = _as_float(getattr(o, "total_final", getattr(o, "valor_total", 0)))
            pago = _as_float(getattr(o, "pago", getattr(o, "valor_pago", 0)))
            por_receber += max(0.0, total_final - pago)

        # € aprovados por faturar esta semana (aprovados cuja data_entrega_prevista está nesta semana)
        aprovados_faturar_semana = 0.0
        for o in aprovados:
            dt = getattr(o, "data_entrega_prevista", None) or getattr(o, "entrega", None)
            try:
                d = dt.date() if hasattr(dt, "date") else dt
            except Exception:
                d = None
            if (d is not None) and (week_start <= d <= week_end):
                total_final = _as_float(getattr(o, "total_final", getattr(o, "valor_total", 0)))
                pago = _as_float(getattr(o, "pago", getattr(o, "valor_pago", 0)))
                aprovados_faturar_semana += max(0.0, total_final - pago)

        # Orçamentos atrasados (entrega < hoje e não arquivado)
        def _is_atrasado(o) -> bool:
            dt = getattr(o, "data_entrega_prevista", None) or getattr(o, "entrega", None)
            try:
                d = dt.date() if hasattr(dt, "date") else dt
            except Exception:
                d = None
            return (d is not None) and (d < today)

        atrasados = sum(1 for o in curso if _is_atrasado(o))

        # Entregas hoje e amanhã
        def _entrega_na_data(o, target_date) -> bool:
            dt = getattr(o, "data_entrega_prevista", None) or getattr(o, "entrega", None)
            try:
                d = dt.date() if hasattr(dt, "date") else dt
            except Exception:
                d = None
            return (d is not None) and (d == target_date)

        entregas_hoje = sum(1 for o in curso if _entrega_na_data(o, today))
        entregas_amanha = sum(1 for o in curso if _entrega_na_data(o, tomorrow))

        # Stock baixo: materiais com quantidade <= qtd_minima
        mats = s.exec(select(Material)).all()
        low_stock = 0
        low_stock_mats = []
        for m in mats:
            qtd = _as_float(getattr(m, "quantidade", getattr(m, "stock_qty", 0)))
            min_q = _as_float(getattr(m, "qtd_minima", 0))
            if min_q > 0 and qtd <= min_q:
                low_stock += 1
                diff = qtd - min_q
                nome = getattr(m, "nome", getattr(m, "name", ""))
                low_stock_mats.append({"nome": nome, "quantidade": qtd, "qtd_minima": min_q, "diferenca": diff})

        # Ordenar top 5 por diferença (qtd - qtd_minima), do menor para o maior (mais negativo primeiro)
        low_stock_mats_sorted = sorted(low_stock_mats, key=lambda x: x["diferenca"])
        top5_low_stock = low_stock_mats_sorted[:5]

    st.markdown("---")
    st.subheader("📊 Visão rápida")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Rascunhos", total_rasc)
    m2.metric("Em curso", total_curso)
    m3.metric("Arquivados", total_arq)
    m4.metric("Entregas esta semana", entregas_semana)

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Aprovados por receber", f"€ {por_receber:,.2f}".replace(",", " ").replace(".", ","))
    m6.metric("Aprovados por faturar esta semana", f"€ {aprovados_faturar_semana:,.2f}".replace(",", " ").replace(".", ","))
    m7.metric("Atrasados", atrasados)
    m8.metric("Entregas hoje", entregas_hoje)

    m9, m10 = st.columns(2)
    m9.metric("Entregas amanhã", entregas_amanha)
    m10.metric("Materiais com stock baixo", low_stock)

    if top5_low_stock:
        st.markdown("#### 🧾 Materiais em stock baixo (top 5)")
        import pandas as pd
        df_low_stock = pd.DataFrame(top5_low_stock)
        # Mostrar apenas nome e quantidade
        df_low_stock_display = df_low_stock[["nome", "quantidade"]]
        st.table(df_low_stock_display)

except Exception:
    pass

# Helper para renderizar cartões

def card(col, title, prefixes, desc):
    with col:
        st.markdown(f"### {title}")
        target = _find_page(*prefixes)
        if target and has_page_link:
            st.page_link(target, label="Abrir", use_container_width=True)
        elif target:
            st.write(f"Abrir pelo menu lateral: `{target}`")
        else:
            st.warning("Página não encontrada. Verifica o nome do ficheiro em `pages/`.")
        st.caption(desc)
        st.divider()

# =======================
# 🔹 Gestão do Negócio
# =======================
st.subheader("📂 Gestão do Negócio")
c1, c2, c3 = st.columns(3)
card(c1, "🗂️ Planeamento", ("2_Planeamento", "Planeamento"), "Gestão de tarefas e estados")
card(c2, "👤 Clientes", ("Clientes",), "Lista e edição de clientes")
card(c3, "🧾 Orçamentos", ("1_Orcamentos", "Orcamentos", "Orcamentos_v5_backup"), "Criar e editar orçamentos")

c4, c5, c6 = st.columns(3)
card(c4, "🛠️ Serviços", ("6_Servicos", "Servicos"), "Serviços e custos")
card(c5, "📦 Stock", ("5_Stock", "Stock"), "Materiais, stock e preços")
card(c6, "📊 Análise", ("Analise", "Analises"), "Relatórios e métricas")

# =======================
# 🔹 Configuração
# =======================
st.subheader("⚙️ Configuração")
c7, c8 = st.columns(2)
card(c7, "⚙️ Parâmetros", ("9_Parametros", "Parametros"), "Margens, máquinas (Laser/UV), energia e tinta UV")
card(c8, "🗃️ Arquivo", ("3_Arquivo", "Arquivo"), "Orçamentos concluídos/arquivados")

# =======================
# 🔹 Ferramentas
# =======================
st.subheader("🧮 Ferramentas")
c9, = st.columns(1)
card(c9, "🧮 Cálculos", ("9_Calculos", "Calculos"), "Ferramentas e cálculos auxiliares")

st.markdown("---")

st.markdown("### 📜 Histórico")

# Ligações do grupo Histórico
hist_links = [
    ("Visão de Histórico", ("10_Historico", "Historico")),
    ("Histórico de Cálculos", ("Historico_Calculos",)),
    ("Movimentos de Stock", ("Movimentos_Stock",)),
    ("Importador", ("Importador",)),
    ("Importar Orçamentos (Arquivo)", ("Importar_Orcamentos", "Importar_Orcamentos_Arquivo")),
]
cols = st.columns(3)
for i, (label, prefs) in enumerate(hist_links):
    with cols[i % 3]:
        target = _find_page(*prefs)
        if target and has_page_link:
            st.page_link(target, label=label, use_container_width=True)
        elif target:
            st.write(f"➡️ {label}: `{target}`")
        else:
            st.caption(f"(indisponível) {label}")

st.markdown("---")
st.caption("💡 A ordem deste painel segue a mesma ordem da barra lateral. Renomeia ficheiros em `pages/` para ajustar.")