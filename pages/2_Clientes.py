# pages/Clientes.py — usa db.sqlite (sqlmodel), sem dependência obrigatória de xlsxwriter
import io
from datetime import datetime, date

import pandas as pd
import streamlit as st
from sqlmodel import select, func

from app.db import get_session, Client, Quote  # modelos da tua aplicação

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

st.title("👥 Clientes")

# ============== helpers ==============
def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def fmt_dt(v):
    """Formata datetime/date para string (para Streamlit)."""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.isoformat()
    return str(v or "")

def next_numero_cliente(session) -> int:
    """Devolve o próximo número disponível."""
    try:
        max_n = session.exec(select(func.max(Client.numero_cliente))).one()
        return int(max_n or 0) + 1
    except Exception:
        all_ids = session.exec(select(Client)).all()
        if not all_ids:
            return 1
        return (max([getattr(c, "numero_cliente", 0) or 0 for c in all_ids]) + 1)

def cliente_to_dict(c):
    """Converte o modelo Client em dicionário para a grelha/exportação."""
    return {
        "id": c.id,
        "numero": getattr(c, "numero_cliente", None),
        "nome": getattr(c, "nome", ""),
        "morada": getattr(c, "morada", ""),
        "cidade": getattr(c, "cidade", ""),
        "codigo_postal": getattr(c, "codigo_postal", ""),
        "pais": getattr(c, "pais", ""),
        "contacto": getattr(c, "contacto", ""),
        "email": getattr(c, "email", ""),
        "nif_tva": getattr(c, "nif_tva", ""),
        "notas": getattr(c, "notas", ""),
        "created_at": fmt_dt(getattr(c, "created_at", None)),
        "updated_at": fmt_dt(getattr(c, "updated_at", None)),
    }

def export_buttons(df: pd.DataFrame, base_filename="clientes"):
    """Exporta CSV sempre; Excel só se existir openpyxl/xlsxwriter instalado."""
    # CSV (sempre)
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Exportar CSV",
        data=csv_bytes,
        file_name=f"{base_filename}.csv",
        mime="text/csv",
        key="dl_csv_clientes",
    )

    # Excel (opcional)
    engine = None
    try:
        import openpyxl  # noqa: F401
        engine = "openpyxl"
    except Exception:
        try:
            import xlsxwriter  # noqa: F401
            engine = "xlsxwriter"
        except Exception:
            engine = None

    if engine:
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine=engine) as w:
            df.to_excel(w, index=False, sheet_name="Clientes")
            w.close()
        st.download_button(
            "⬇️ Exportar Excel",
            data=out.getvalue(),
            file_name=f"{base_filename}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_xlsx_clientes",
        )
    else:
        st.caption("💡 Para exportar em Excel no futuro, podes instalar `openpyxl` ou `xlsxwriter`. Por agora, usa o CSV.")

def metrics_for_client(session, client_id: int):
    """N.º de orçamentos e total (tenta campos 'total' ou 'valor_total')."""
    try:
        qcount = session.exec(select(func.count(Quote.id)).where(Quote.cliente_id == client_id)).one()
    except Exception:
        qcount = 0
    total = 0.0
    try:
        tot = session.exec(select(func.sum(getattr(Quote, "total"))).where(Quote.cliente_id == client_id)).one()
        if tot is None:
            tot = session.exec(select(func.sum(getattr(Quote, "valor_total"))).where(Quote.cliente_id == client_id)).one()
        total = float(tot or 0.0)
    except Exception:
        total = 0.0
    return int(qcount or 0), float(total or 0.0)

# ============== carregar dados da BD ==============
with get_session() as s:
    clientes = s.exec(select(Client).order_by(Client.numero_cliente)).all()

df = pd.DataFrame([cliente_to_dict(c) for c in clientes])

# ============== filtros/topo ==============
top1, top2, top3, top4 = st.columns([2, 2, 2, 2])
with top1:
    q = st.text_input("🔎 Pesquisar (nome, email, NIF, país...)", "")
with top2:
    pais_filtro = st.text_input("Filtrar por país", "")
with top3:
    ordenar_por = st.selectbox("Ordenar por", ["numero", "nome", "pais", "created_at", "updated_at"], index=0)
with top4:
    sentido = st.radio("Sentido", ["Asc", "Desc"], horizontal=True, index=0)

flt = df.copy()
if q:
    ql = q.lower()
    mask = (
        flt["nome"].str.lower().str.contains(ql, na=False) |
        flt["email"].str.lower().str.contains(ql, na=False) |
        flt["nif_tva"].str.lower().str.contains(ql, na=False) |
        flt["pais"].str.lower().str.contains(ql, na=False) |
        flt["contacto"].str.lower().str.contains(ql, na=False) |
        flt["morada"].str.lower().str.contains(ql, na=False)
    )
    flt = flt[mask]
if pais_filtro:
    flt = flt[flt["pais"].str.lower() == pais_filtro.lower()]
asc = (sentido == "Asc")
flt = flt.sort_values(ordenar_por, ascending=asc)

st.subheader("Lista de clientes")
st.dataframe(flt.drop(columns=["created_at", "updated_at"]), use_container_width=True, height=360)
export_buttons(flt, base_filename="clientes")

st.markdown("---")

# ============== criar / editar ==============
st.subheader("Criar / Editar cliente")
modo = st.radio("Modo", ["Novo", "Editar / Apagar"], horizontal=True)

if modo == "Novo":
    with get_session() as s:
        default_num = next_numero_cliente(s)
    with st.form("frm_novo_cliente"):
        cA, cB, cC = st.columns(3)
        with cA:
            numero = st.number_input("Número do cliente", value=default_num, min_value=1, step=1)
            nome = st.text_input("Nome", "")
            pais = st.text_input("País", "")
        with cB:
            morada = st.text_input("Morada", "")
            cidade = st.text_input("Cidade", "")
            codigo_postal = st.text_input("Código Postal", "")
        with cC:
            contacto = st.text_input("Contacto", "")
            email = st.text_input("Email", "")
            nif_tva = st.text_input("NIF/TVA", "")
        notas = st.text_area("Notas", "")
        st.caption("Campos obrigatórios: Número, Nome, País, Contacto, Email, NIF/TVA.")
        ok = st.form_submit_button("➕ Adicionar")

        if ok:
            faltas = [k for k, v in [("numero", numero), ("nome", nome), ("pais", pais),
                                     ("contacto", contacto), ("email", email), ("nif_tva", nif_tva)]
                      if str(v).strip() == ""]
            if faltas:
                st.error("Faltam campos: " + ", ".join(faltas))
            else:
                with get_session() as s:
                    existe = s.exec(select(Client).where(Client.numero_cliente == int(numero))).first()
                    if existe:
                        st.error(f"Já existe o número {int(numero)}.")
                    else:
                        c = Client(
                            numero_cliente=int(numero),
                            nome=nome.strip(),
                            morada=morada.strip(),
                            cidade=cidade.strip(),
                            codigo_postal=codigo_postal.strip(),
                            pais=pais.strip(),
                            contacto=contacto.strip(),
                            email=email.strip(),
                            nif_tva=nif_tva.strip(),
                            notas=notas.strip(),
                            created_at=now_iso(),
                            updated_at=now_iso(),
                        )
                        s.add(c); s.commit()
                        st.success(f"Cliente #{int(numero)} criado.")
                        st.experimental_rerun()

else:
    if df.empty:
        st.info("Ainda não existem clientes.")
    else:
        sel_num = st.selectbox("Escolha o cliente pelo número",
                               options=list(df["numero"].astype(int)))
        with get_session() as s:
            cli = s.exec(select(Client).where(Client.numero_cliente == int(sel_num))).first()

        if not cli:
            st.warning("Cliente não encontrado na BD.")
        else:
            # métricas (n.º orçamentos e total)
            with get_session() as s:
                n_orc, total_gasto = metrics_for_client(s, cli.id)
            m1, m2, m3 = st.columns(3)
            m1.metric("N.º de orçamentos", n_orc)
            m2.metric("Total (€)", f"{total_gasto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
            m3.metric("Criado em", fmt_dt(getattr(cli, "created_at", None)) or "—")

            with st.form("frm_edit_cliente"):
                cA, cB, cC = st.columns(3)
                with cA:
                    numero = st.number_input("Número do cliente",
                                             value=int(getattr(cli, "numero_cliente", sel_num) or sel_num),
                                             min_value=1, step=1)
                    nome = st.text_input("Nome", getattr(cli, "nome", ""))
                    pais = st.text_input("País", getattr(cli, "pais", ""))
                with cB:
                    morada = st.text_input("Morada", getattr(cli, "morada", ""))
                    cidade = st.text_input("Cidade", getattr(cli, "cidade", ""))
                    codigo_postal = st.text_input("Código Postal", getattr(cli, "codigo_postal", ""))
                with cC:
                    contacto = st.text_input("Contacto", getattr(cli, "contacto", ""))
                    email = st.text_input("Email", getattr(cli, "email", ""))
                    nif_tva = st.text_input("NIF/TVA", getattr(cli, "nif_tva", ""))
                notas = st.text_area("Notas", getattr(cli, "notas", ""))

                b1, b2, b3 = st.columns(3)
                save_btn = b1.form_submit_button("💾 Guardar alterações")
                del_btn  = b2.form_submit_button("🗑️ Apagar cliente")
                cancel   = b3.form_submit_button("❌ Cancelar")

                if save_btn:
                    faltas = [k for k, v in [("numero", numero), ("nome", nome), ("pais", pais),
                                             ("contacto", contacto), ("email", email), ("nif_tva", nif_tva)]
                              if str(v).strip() == ""]
                    if faltas:
                        st.error("Faltam campos: " + ", ".join(faltas))
                    else:
                        with get_session() as s:
                            if int(numero) != int(cli.numero_cliente):
                                dup = s.exec(select(Client).where(Client.numero_cliente == int(numero))).first()
                                if dup:
                                    st.error(f"Já existe cliente com o número {int(numero)}.")
                                    st.stop()
                            c = s.get(Client, cli.id)
                            c.numero_cliente = int(numero)
                            c.nome = nome.strip()
                            c.morada = morada.strip()
                            c.cidade = cidade.strip()
                            c.codigo_postal = codigo_postal.strip()
                            c.pais = pais.strip()
                            c.contacto = contacto.strip()
                            c.email = email.strip()
                            c.nif_tva = nif_tva.strip()
                            c.notas = notas.strip()
                            if not getattr(c, "created_at", None):
                                c.created_at = now_iso()
                            c.updated_at = now_iso()
                            s.add(c); s.commit()
                            st.success("Cliente atualizado.")
                            st.experimental_rerun()

                if del_btn:
                    with get_session() as s:
                        has_quotes = s.exec(select(func.count(Quote.id)).where(Quote.cliente_id == cli.id)).one()
                        if has_quotes:
                            st.warning("Este cliente tem orçamentos associados. Apaga-os ou desassocia primeiro.")
                        else:
                            s.delete(s.get(Client, cli.id)); s.commit()
                            st.success("Cliente apagado.")
                            st.experimental_rerun()

                if cancel:
                    st.experimental_rerun()