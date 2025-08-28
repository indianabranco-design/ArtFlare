import streamlit as st
import pandas as pd
from sqlmodel import select
from app.db import get_session, Client, Material, Service

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

st.title("📥 Importador (Clientes / Materiais / Serviços)")

uploaded = st.file_uploader("Carregar ficheiro (CSV ou Excel)", type=["csv","xlsx","xls"])
tipo = st.selectbox("Tipo de dados", ["Clientes","Materiais","Serviços"])
if uploaded:
    if uploaded.name.endswith(".csv"):
        df = pd.read_csv(uploaded)
    else:
        df = pd.read_excel(uploaded)
    st.write("Pré-visualização:")
    st.dataframe(df.head(20), use_container_width=True)

    st.subheader("Mapeamento de colunas")
    cols = list(df.columns)
    mapping = {}
    if tipo=="Clientes":
        campos = ["numero_cliente","nome","morada","pais","contacto","email","nif_tva","notas"]
    elif tipo=="Materiais":
        campos = ["code","nome_pt","categoria","tipo","largura_cm","altura_cm","unidade","preco_compra_un","preco_cliente_un","fornecedor","quantidade","qtd_minima","observacoes"]
    else:
        campos = ["code","nome_pt","categoria","usa_area","usa_tempo","largura_cm","altura_cm","preco_cliente","custo_por_minuto","custo_extra","custo_fornecedor"]
    for c in campos:
        mapping[c] = st.selectbox(f"Coluna para '{c}'", ["(nenhuma)"]+cols, index=cols.index(c) + 1 if c in cols else 0)

    if st.button("🔎 Validar"):
        missing_required = []
        if tipo=="Clientes":
            for req in ["numero_cliente","nome"]: 
                if mapping.get(req)=="(nenhuma)": missing_required.append(req)
        elif tipo=="Materiais":
            for req in ["code","nome_pt"]: 
                if mapping.get(req)=="(nenhuma)": missing_required.append(req)
        else:
            for req in ["code","nome_pt"]: 
                if mapping.get(req)=="(nenhuma)": missing_required.append(req)
        if missing_required:
            st.error("Faltam campos obrigatórios: " + ", ".join(missing_required))
        else:
            st.success("Mapeamento parece válido.")

    if st.button("⬇️ Importar"):
        count=0
        with get_session() as s:
            for _, row in df.iterrows():
                def val(field):
                    col = mapping.get(field)
                    return None if not col or col=="(nenhuma)" else row[col]
                if tipo=="Clientes":
                    obj = Client(
                        numero_cliente=int(val("numero_cliente") or 0),
                        nome=str(val("nome") or ""),
                        morada=str(val("morada") or ""),
                        pais=str(val("pais") or ""),
                        contacto=str(val("contacto") or ""),
                        email=str(val("email") or ""),
                        nif_tva=str(val("nif_tva") or ""),
                        notas=str(val("notas") or ""))
                elif tipo=="Materiais":
                    obj = Material(
                        code=str(val("code") or ""),
                        nome_pt=str(val("nome_pt") or ""),
                        categoria=str(val("categoria") or ""),
                        tipo=str(val("tipo") or "AREA"),
                        largura_cm=float(val("largura_cm") or 0.0),
                        altura_cm=float(val("altura_cm") or 0.0),
                        unidade=str(val("unidade") or "cm2"),
                        preco_compra_un=float(val("preco_compra_un") or 0.0),
                        preco_cliente_un=float(val("preco_cliente_un") or 0.0),
                        fornecedor=str(val("fornecedor") or ""),
                        quantidade=float(val("quantidade") or 0.0),
                        qtd_minima=float(val("qtd_minima") or 0.0),
                        observacoes=str(val("observacoes") or ""))
                else:
                    obj = Service(
                        code=str(val("code") or ""),
                        nome_pt=str(val("nome_pt") or ""),
                        categoria=str(val("categoria") or ""),
                        usa_area=bool(val("usa_area")) if not pd.isna(val("usa_area")) else True,
                        usa_tempo=bool(val("usa_tempo")) if not pd.isna(val("usa_tempo")) else True,
                        largura_cm=float(val("largura_cm") or 0.0),
                        altura_cm=float(val("altura_cm") or 0.0),
                        preco_cliente=float(val("preco_cliente") or 0.0),
                        custo_por_minuto=float(val("custo_por_minuto") or 0.0),
                        custo_extra=float(val("custo_extra") or 0.0),
                        custo_fornecedor=float(val("custo_fornecedor") or 0.0))
                s.add(obj); count+=1
            s.commit()
        st.success(f"Importados {count} registos.")
