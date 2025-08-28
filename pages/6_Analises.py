import streamlit as st
from sqlmodel import select
from app.db import get_session, Quote, QuoteItem, Client, Material, Service, Settings
from app.utils import Margins, price_with_tiered_margin
import pandas as pd
from datetime import datetime

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

st.title("📊 Análises")

with get_session() as s:
    cfg = s.exec(select(Settings)).first()
    if not cfg:
        st.warning("Defina Parâmetros primeiro.")
        cfg = Settings(); s.add(cfg); s.commit(); s.refresh(cfg)
    margins = Margins(cfg.margin_0_15, cfg.margin_16_30, cfg.margin_31_70, cfg.margin_71_plus)
    qs = s.exec(select(Quote).order_by(Quote.data_criacao)).all()
    items = s.exec(select(QuoteItem)).all()
    # calcular totais por orçamento
    totals = {}
    for q in qs:
        it = [i for i in items if i.quote_id==q.id]
        tot = 0.0
        for i in it:
            part = (i.preco_unitario_cliente*(i.percent_uso/100.0))*i.quantidade
            tot += max(0.0, price_with_tiered_margin(part, i.percent_uso, margins) - i.desconto_item)
        tot -= q.desconto_total
        tot += tot*(q.iva_percent/100.0)
        totals[q.id] = tot

    # taxa de aprovação (aprovados / enviados)
    enviados = [q for q in qs if q.estado in ["ENVIADO","APROVADO","EM_PRODUCAO","ENTREGUE","ARQUIVADO"]]
    aprovados = [q for q in qs if q.estado in ["APROVADO","EM_PRODUCAO","ENTREGUE","ARQUIVADO"]]
    taxa = (len(aprovados)/len(enviados)*100.0) if enviados else 0.0
    st.metric("Taxa de aprovação (%)", f"{taxa:.1f}%")

    # faturado por mês (considera ENTREGUE/ARQUIVADO como faturado)
    rows = []
    for q in qs:
        if q.estado in ["ENTREGUE","ARQUIVADO"]:
            rows.append({"mes": q.data_criacao.strftime("%Y-%m"), "total": totals.get(q.id, 0.0)})
    df_mes = pd.DataFrame(rows).groupby("mes")["total"].sum().reset_index()
    if not df_mes.empty:
        st.subheader("Faturado por mês")
        st.bar_chart(df_mes.set_index("mes"))

    # top clientes por total
    rows2 = []
    for q in qs:
        rows2.append({"cliente_id": q.cliente_id, "total": totals.get(q.id, 0.0)})
    df_cli = pd.DataFrame(rows2).groupby("cliente_id")["total"].sum().reset_index()
    if not df_cli.empty:
        # map names
        names = {c.id: c.nome for c in s.exec(select(Client)).all()}
        df_cli["Cliente"] = df_cli["cliente_id"].map(names)
        df_cli = df_cli.sort_values("total", ascending=False).head(10)
        st.subheader("Top clientes (por total)")
        st.bar_chart(df_cli.set_index("Cliente")["total"])
