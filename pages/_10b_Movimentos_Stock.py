# pages/Movimentos_Stock.py
import streamlit as st
import pandas as pd
from sqlmodel import select
from app.db import get_session, StockMovement, Material

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

st.title("📊 Movimentação de Stock — Histórico")

# Carregar movimentos
with get_session() as s:
    materiais = {m.code: m for m in s.exec(select(Material)).all()}
    movimentos = s.exec(select(StockMovement)).all()

if not movimentos:
    st.info("Ainda não existem movimentações de stock.")
else:
    rows = []
    for mv in movimentos:
        # alinhar com StockMovement(ts, code, qty_delta, unidade, note)
        mat = materiais.get(getattr(mv, 'code', ''))
        qty = float(getattr(mv, 'qty_delta', 0.0) or 0.0)
        tipo = "Saída" if qty < 0 else ("Entrada" if qty > 0 else "Ajuste")
        rows.append({
            "Data": getattr(mv, "ts", None),
            "Produto": getattr(mat, "nome_pt", "") if mat else "—",
            "Código": getattr(mv, "code", "") or (getattr(mat, "code", "") if mat else ""),
            "Quantidade": qty,
            "Un.": getattr(mv, "unidade", "") or (getattr(mat, "unidade", "") if mat else ""),
            "Tipo": tipo,
            "Orçamento": getattr(mv, "quote_id", None),
            "Observações": getattr(mv, "note", ""),
        })

    df = pd.DataFrame(rows)

    # Preparação: Data só com dia e ordenação descendente
    if not df.empty:
        try:
            df["Data"] = pd.to_datetime(df["Data"]).dt.date
        except Exception:
            pass
        df = df.sort_values("Data", ascending=False)

        # --------- Filtros interativos ---------
        with st.expander("Filtros", expanded=False):
            colf1, colf2, colf3 = st.columns([2, 2, 2])
            produtos = sorted({r["Produto"] for r in rows if r.get("Produto") and r.get("Produto") != "—"})
            tipos_opts = ["Entrada", "Saída", "Ajuste"]

            produto_sel = colf1.selectbox("Produto", ["(Todos)"] + produtos)
            tipos_sel = colf2.multiselect("Tipo de movimento", tipos_opts, default=tipos_opts)

            # Intervalo de datas
            try:
                dmin = df["Data"].min()
                dmax = df["Data"].max()
            except Exception:
                from datetime import date as _date
                dmin = dmax = _date.today()
            data_ini, data_fim = colf3.date_input("Intervalo de datas", value=(dmin, dmax))

            colf4, colf5 = st.columns([2, 1])
            codigo_q = colf4.text_input("Código contém", "")
            orcamento_id = colf5.number_input("Orçamento (#)", min_value=0, step=1, value=0)

        # Aplicar filtros ao dataframe
        df_f = df.copy()
        if produto_sel != "(Todos)":
            df_f = df_f[df_f["Produto"] == produto_sel]
        if tipos_sel:
            df_f = df_f[df_f["Tipo"].isin(tipos_sel)]
        # Datas
        try:
            if data_ini and data_fim:
                df_f = df_f[(pd.to_datetime(df_f["Data"]) >= pd.to_datetime(data_ini)) & (pd.to_datetime(df_f["Data"]) <= pd.to_datetime(data_fim))]
        except Exception:
            pass
        # Código
        if codigo_q:
            df_f = df_f[df_f["Código"].astype(str).str.contains(codigo_q, case=False, na=False)]
        # Orçamento
        if orcamento_id:
            df_f = df_f[df_f["Orçamento"] == int(orcamento_id)]

        # --------- Métricas (sobre filtrado) ---------
        total_entradas = float(df_f.loc[df_f["Quantidade"] > 0, "Quantidade"].sum()) if not df_f.empty else 0.0
        total_saidas = float(df_f.loc[df_f["Quantidade"] < 0, "Quantidade"].sum()) if not df_f.empty else 0.0
        saldo = float(df_f["Quantidade"].sum()) if not df_f.empty else 0.0
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Entradas", f"{total_entradas:.2f}")
        m2.metric("Total Saídas", f"{total_saidas:.2f}")
        m3.metric("Saldo", f"{saldo:.2f}")

        # Garantir coluna Orçamento numérica para formatação
        try:
            df_f["Orçamento"] = pd.to_numeric(df_f["Orçamento"], errors='coerce').astype('Int64')
        except Exception:
            pass

        st.dataframe(
            df_f,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Quantidade": st.column_config.NumberColumn(format="%.2f"),
                "Orçamento": st.column_config.NumberColumn(format="%d"),
            }
        )

        # Exportar CSV (filtrado)
        st.download_button(
            "⬇️ Exportar CSV (filtrado)",
            data=df_f.to_csv(index=False).encode("utf-8"),
            file_name="movimentos_stock_filtrado.csv",
            mime="text/csv"
        )
    else:
        # Dataframe vazio, mas manter estrutura
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Quantidade": st.column_config.NumberColumn(format="%.2f"),
                "Orçamento": st.column_config.NumberColumn(format="%d"),
            }
        )
        st.download_button(
            "⬇️ Exportar CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="movimentos_stock.csv",
            mime="text/csv"
        )