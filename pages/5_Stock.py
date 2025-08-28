import streamlit as st
from sqlmodel import select
from app.db import get_session, Material, Settings
# Import opcional: migração leve para a tabela de materiais
try:
    from app.db import upgrade_materials_table  # type: ignore
except Exception:
    def upgrade_materials_table():
        # no-op se não existir no app.db
        return None
import pandas as pd
import io

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


# Garantir coluna de controlo (usar margens dos Parâmetros)
try:
    upgrade_materials_table()
except Exception:
    pass

# Export helpers
def export_buttons(df: pd.DataFrame, base_filename: str = "stock"):
    """Exporta CSV sempre; Excel só se houver engine instalada (openpyxl/xlsxwriter)."""
    # CSV (sempre)
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Exportar CSV",
        data=csv_bytes,
        file_name=f"{base_filename}.csv",
        mime="text/csv",
        key=f"dl_csv_{base_filename}",
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
            df.to_excel(w, index=False, sheet_name="Dados")
            w.close()
        st.download_button(
            "⬇️ Exportar Excel",
            data=out.getvalue(),
            file_name=f"{base_filename}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_xlsx_{base_filename}",
        )
    else:
        st.caption("💡 Para Excel, instala `openpyxl` ou `xlsxwriter`. Por agora usa o CSV.")

st.title("📦 Stock de Materiais")

tab1, tab2, tab3 = st.tabs(["Lista", "Adicionar", "Editar"])

with get_session() as s:
    # === Recalcular preços ao público para materiais com margens padrão ===
    cfg = s.exec(select(Settings)).first()
    if cfg:
        default_margin_full = float(getattr(cfg, 'margin_71_plus', 0.0) or 0.0)
        mats_all = s.exec(select(Material)).all()
        updated = 0
        for m in mats_all:
            try:
                if getattr(m, 'use_param_margins', True) and (m.preco_compra_un or 0.0) > 0:
                    suggested = float(m.preco_compra_un) * (1.0 + default_margin_full)
                    # atualiza sempre que houver diferença relevante
                    if abs(float(m.preco_cliente_un or 0.0) - suggested) > 1e-6:
                        m.preco_cliente_un = round(suggested, 4)
                        s.add(m)
                        updated += 1
            except Exception:
                pass
        if updated:
            s.commit()
            st.success(f"Preços atualizados por Parâmetros em {updated} materiais.")

    with tab1:
        # --- Recalcular agora (apenas os com Parâmetros) ---
        st.subheader("Atualização manual")
        rc1, rc2 = st.columns([1,2])
        confirm_recalc = rc1.checkbox("Tenho a certeza", key="recalc_stock_confirm")
        if rc2.button("🔁 Recalcular agora (apenas os com Parâmetros)"):
            if not cfg:
                st.warning("Define primeiro as margens nos Parâmetros.")
            elif not confirm_recalc:
                st.warning("Marca 'Tenho a certeza' para proceder.")
            else:
                try:
                    default_margin_full = float(getattr(cfg, 'margin_71_plus', 0.0) or 0.0)
                    mats_all2 = s.exec(select(Material)).all()
                    updated2 = 0
                    for m2 in mats_all2:
                        try:
                            if getattr(m2, 'use_param_margins', True) and (m2.preco_compra_un or 0.0) > 0:
                                suggested2 = float(m2.preco_compra_un) * (1.0 + default_margin_full)
                                if abs(float(m2.preco_cliente_un or 0.0) - suggested2) > 1e-6:
                                    m2.preco_cliente_un = round(suggested2, 4)
                                    s.add(m2)
                                    updated2 += 1
                        except Exception:
                            pass
                    if updated2:
                        s.commit()
                        st.success(f"Recalculado com Parâmetros em {updated2} materiais.")
                    else:
                        st.info("Nenhum material precisava de atualização.")
                except Exception as e:
                    st.error(f"Falha ao recalcular: {e}")

        mats = s.exec(select(Material)).all()
        rows = [{
            "Código": m.code, "Nome (PT)": m.nome_pt, "Categoria": m.categoria, "Tipo": m.tipo,
            "Unidade": m.unidade, "Qtd": m.quantidade, "Mínimo": m.qtd_minima,
            "Preço Cliente (un)": m.preco_cliente_un,
            "Preço sugerido (Parâmetros)": (float(m.preco_compra_un or 0.0) * (1.0 + float(getattr(cfg, 'margin_71_plus', 0.0) or 0.0))) if cfg else None,
            "Usa margens (Parâmetros)": ("Sim" if getattr(m, 'use_param_margins', True) else "Não"),
        } for m in mats]
        st.dataframe(rows, use_container_width=True)
        df = pd.DataFrame(rows)
        export_buttons(df, base_filename="stock")

    # ============ TAB 2 — ADICIONAR ============
    with tab2:
        st.subheader("Adicionar material")
        code = st.text_input("Código", key="add_codigo")
        nome_pt = st.text_input("Nome (PT)", key="add_nome_pt")
        nome_en = st.text_input("Nome (EN)", key="add_nome_en")
        nome_fr = st.text_input("Nome (FR)", key="add_nome_fr")
        categoria = st.text_input("Categoria", key="add_categoria")
        tipo = st.selectbox("Tipo", ["AREA","PC"], index=0, key="add_tipo")
        largura = st.number_input("Largura (cm)", min_value=0.0, value=0.0, key="add_largura")
        altura = st.number_input("Altura (cm)", min_value=0.0, value=0.0, key="add_altura")
        unidade = st.selectbox("Unidade", ["cm2","PC"], index=0, key="add_unidade")
        preco_compra = st.number_input("Preço de compra (un)", min_value=0.0, value=0.0, key="add_preco_compra")
        margin_71 = float(getattr(cfg, 'margin_71_plus', 0.0) or 0.0) if cfg else 0.0
        suggested_value = (preco_compra * (1.0 + margin_71)) if preco_compra > 0 else 0.0
        preco_cliente = st.number_input("Preço ao cliente (un)", min_value=0.0, value=suggested_value, format="%.4f", key="add_preco_cliente")
        st.caption(f"Sugerido pelos Parâmetros: €{suggested_value:.4f}")
        use_param = st.checkbox("Usar margens padrão (Parâmetros)", value=True, key="add_use_param")
        st.caption("Se ativo, o preço ao cliente pode ser atualizado automaticamente quando mudares as margens nos Parâmetros.")
        fornecedor = st.text_input("Fornecedor", key="add_fornecedor")
        qtd = st.number_input("Quantidade em stock", min_value=0.0, value=0.0, key="add_qtd")
        qtd_min = st.number_input("Quantidade mínima", min_value=0.0, value=0.0, key="add_qtd_min")
        observacoes = st.text_area("Observações", key="add_observacoes")
        last_by = st.text_input("Última alteração por", key="add_last_by")
        if st.button("➕ Adicionar", key="add_submit"):
            m = Material(
                code=code, nome_pt=nome_pt, nome_en=nome_en, nome_fr=nome_fr,
                categoria=categoria, tipo=tipo,
                largura_cm=float(largura), altura_cm=float(altura), unidade=unidade,
                preco_compra_un=float(preco_compra), preco_cliente_un=float(preco_cliente),
                use_param_margins=bool(use_param),
                fornecedor=fornecedor, quantidade=float(qtd), qtd_minima=float(qtd_min),
                observacoes=observacoes, last_modified_by=last_by,
            )
            s.add(m); s.commit()
            st.success("Material criado.")

    # ============ TAB 3 — EDITAR ============
    with tab3:
        st.subheader("Editar material")
        mats = s.exec(select(Material)).all()
        if not mats:
            st.info("Não existem materiais para editar.")
        else:
            # Pesquisa rápida
            q = st.text_input("🔎 Procurar (código ou nome)", key="stock_edit_search")
            if q:
                ql = q.strip().lower()
                mats_f = [m for m in mats if (m.code and ql in str(m.code).lower()) or (m.nome_pt and ql in str(m.nome_pt).lower())]
            else:
                mats_f = mats

            if not mats_f:
                st.warning("Sem resultados para a pesquisa.")
                st.stop()

            # Lista para consulta rápida (filtrada)
            df_edit = pd.DataFrame([{
                "ID": m.id, "Código": m.code, "Nome": m.nome_pt,
                "Categoria": m.categoria, "Qtd": m.quantidade,
            } for m in mats_f])
            st.dataframe(df_edit, use_container_width=True, hide_index=True)

            sel_id = st.selectbox("Escolhe o material", df_edit["ID"].tolist())
            sel_db = s.get(Material, sel_id)

            code = st.text_input("Código", value=(sel_db.code or ""), key=f"edit_codigo_{sel_id}")
            nome_pt = st.text_input("Nome (PT)", value=(sel_db.nome_pt or ""), key=f"edit_nome_pt_{sel_id}")
            nome_en = st.text_input("Nome (EN)", value=(sel_db.nome_en or ""), key=f"edit_nome_en_{sel_id}")
            nome_fr = st.text_input("Nome (FR)", value=(sel_db.nome_fr or ""), key=f"edit_nome_fr_{sel_id}")
            categoria = st.text_input("Categoria", value=(sel_db.categoria or ""), key=f"edit_categoria_{sel_id}")
            tipo = st.selectbox("Tipo", ["AREA","PC"], index=(0 if sel_db.tipo=="AREA" else 1), key=f"edit_tipo_{sel_id}")
            largura = st.number_input("Largura (cm)", min_value=0.0, value=float(sel_db.largura_cm or 0.0), key=f"edit_largura_{sel_id}")
            altura = st.number_input("Altura (cm)", min_value=0.0, value=float(sel_db.altura_cm or 0.0), key=f"edit_altura_{sel_id}")
            unidade = st.selectbox("Unidade", ["cm2","PC"], index=(0 if sel_db.unidade=="cm2" else 1), key=f"edit_unidade_{sel_id}")
            preco_compra = st.number_input("Preço de compra (un)", min_value=0.0, value=float(sel_db.preco_compra_un or 0.0), key=f"edit_preco_compra_{sel_id}")
            margin_71 = float(getattr(cfg, 'margin_71_plus', 0.0) or 0.0) if cfg else 0.0
            base_compra = float(sel_db.preco_compra_un or 0.0)
            current_cliente = float(sel_db.preco_cliente_un or 0.0)
            suggested_value = base_compra * (1.0 + margin_71) if base_compra > 0 else 0.0
            default_preco_cliente = current_cliente if current_cliente > 0 else suggested_value
            preco_cliente = st.number_input("Preço ao cliente (un)", min_value=0.0, value=default_preco_cliente, format="%.4f", key=f"edit_preco_cliente_{sel_id}")
            st.caption(f"Sugerido pelos Parâmetros: €{suggested_value:.4f}")
            use_param = st.checkbox("Usar margens padrão (Parâmetros)", value=bool(getattr(sel_db, 'use_param_margins', True)), key=f"edit_use_param_{sel_id}")
            st.caption("Se ativo, o preço ao cliente pode ser atualizado automaticamente quando mudares as margens nos Parâmetros.")
            fornecedor = st.text_input("Fornecedor", value=(sel_db.fornecedor or ""), key=f"edit_fornecedor_{sel_id}")
            qtd = st.number_input("Quantidade em stock", min_value=0.0, value=float(sel_db.quantidade or 0.0), key=f"edit_qtd_{sel_id}")
            qtd_min = st.number_input("Quantidade mínima", min_value=0.0, value=float(sel_db.qtd_minima or 0.0), key=f"edit_qtd_min_{sel_id}")
            observacoes = st.text_area("Observações", value=(sel_db.observacoes or ""), key=f"edit_observacoes_{sel_id}")
            last_by = st.text_input("Última alteração por", value=(sel_db.last_modified_by or ""), key=f"edit_last_by_{sel_id}")

            c1, c2 = st.columns(2)
            if c1.button("💾 Guardar alterações", key=f"edit_save_{sel_id}"):
                sel_db = s.get(Material, sel_id)
                if not sel_db:
                    st.error("Não foi possível carregar o material selecionado.")
                else:
                    sel_db.code = code
                    sel_db.nome_pt = nome_pt
                    sel_db.nome_en = nome_en
                    sel_db.nome_fr = nome_fr
                    sel_db.categoria = categoria
                    sel_db.tipo = tipo
                    sel_db.largura_cm = float(largura)
                    sel_db.altura_cm = float(altura)
                    sel_db.unidade = unidade
                    sel_db.preco_compra_un = float(preco_compra)
                    sel_db.preco_cliente_un = float(preco_cliente)
                    sel_db.use_param_margins = bool(use_param)
                    sel_db.fornecedor = fornecedor
                    sel_db.quantidade = float(qtd)
                    sel_db.qtd_minima = float(qtd_min)
                    sel_db.observacoes = observacoes
                    sel_db.last_modified_by = last_by
                    s.add(sel_db); s.commit()
                    st.success("Material atualizado.")
            if c2.button("🗑️ Apagar material", key=f"edit_delete_{sel_id}"):
                obj = s.get(Material, sel_id)
                if not obj:
                    st.error("Material não encontrado para apagar.")
                else:
                    s.delete(obj); s.commit()
                    st.success("Material removido.")
