# pages/Servicos.py
import io
import pandas as pd
import streamlit as st
from sqlmodel import select
from app.db import get_session, Service, Settings, Machine

# Import opcional: coluna machine_type em Service
try:
    from app.db import upgrade_services_machine_type  # type: ignore
except Exception:
    def upgrade_services_machine_type():
        return None

# Import opcional: coluna minutos_por_unidade em Service
try:
    from app.db import upgrade_services_minutes  # type: ignore
except Exception:
    def upgrade_services_minutes():
        return None

# Import opcional: coluna unidade em Service
try:
    from app.db import upgrade_services_unidade  # type: ignore
except Exception:
    def upgrade_services_unidade():
        return None

# Import opcional: coluna observacoes em Service
try:
    from app.db import upgrade_services_observacoes  # type: ignore
except Exception:
    def upgrade_services_observacoes():
        return None

# Import opcional: helper para custo/min da máquina
try:
    from app.db import machine_cost_per_min  # type: ignore
except Exception:
    def machine_cost_per_min(*args, **kwargs):
        return 0.0

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

# ---- Export helpers (sem dependências obrigatórias) ----
def export_buttons(df: pd.DataFrame, base_filename: str = "servicos"):
    # CSV (sempre)
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Exportar CSV",
        data=csv_bytes,
        file_name=f"{base_filename}.csv",
        mime="text/csv",
        key=f"dl_csv_{base_filename}",
    )
    # Excel (opcional, se engine existir)
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
            df.to_excel(w, index=False, sheet_name="Servicos")
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

st.title("🛠️ Serviços")

upgrade_services_machine_type()
upgrade_services_minutes()
upgrade_services_unidade()
upgrade_services_observacoes()

tab1, tab2, tab3 = st.tabs(["Lista", "Adicionar", "Editar"])

with get_session() as s:
    # === Recalcular custo/min a partir dos Parâmetros e sincronizar serviços (por tipo de máquina) ===
    cfg = s.exec(select(Settings)).first()

    # --- Dynamic machines from Parâmetros ---
    machine_options = []
    machine_cost_map = {}

    laser_cost = 0.0
    uv_cost = 0.0
    if cfg:
        # Preferir custos já calculados e guardados em Parâmetros
        try:
            laser_cost = float(getattr(cfg, 'service_cost_eur_per_min', 0.0) or 0.0)
        except Exception:
            laser_cost = 0.0
        try:
            uv_cost = float(getattr(cfg, 'uv_service_cost_eur_per_min', 0.0) or 0.0)
        except Exception:
            uv_cost = 0.0
        # Fallback: calcular se algum não existir
        if laser_cost <= 0.0:
            energia_pm = (getattr(cfg, 'machine_power_watts', 0.0) / 1000.0) * (1.0/60.0) * getattr(cfg, 'energy_cost_eur_kwh', 0.0)
            desgaste_pm = getattr(cfg, 'wear_cost_eur_per_min', 0.0)
            base_pm = energia_pm + desgaste_pm
            laser_cost = base_pm + base_pm * (getattr(cfg, 'energy_markup_percent', 0.0) / 100.0)
        if uv_cost <= 0.0:
            energia_uv = (getattr(cfg, 'uv_machine_power_watts', 0.0) / 1000.0) * (1.0/60.0) * getattr(cfg, 'energy_cost_eur_kwh', 0.0)
            base_uv = energia_uv + getattr(cfg, 'uv_wear_cost_eur_per_min', 0.0)
            uv_cost = base_uv + base_uv * (getattr(cfg, 'uv_markup_percent', 0.0) / 100.0)
        # Ler máquinas reais da BD (definidas em Parâmetros)
        try:
            machines_all = s.exec(select(Machine)).all()
            for m in machines_all:
                # nome visível
                name = getattr(m, 'name', None) or getattr(m, 'nome', None) or getattr(m, 'titulo', None) or f"Maquina {getattr(m,'id','')}"
                # custo por minuto calculado
                try:
                    cpm = float(machine_cost_per_min(m, cfg))
                except Exception:
                    cpm = float(getattr(m, 'custo_por_minuto', 0.0) or 0.0)
                if name and name not in machine_options:
                    machine_options.append(str(name))
                machine_cost_map[str(name)] = float(cpm)
        except Exception:
            pass

        # Atualizar todos os serviços conforme o tipo de máquina
        all_svs = s.exec(select(Service)).all()
        updated = 0
        for sv in all_svs:
            mtype = getattr(sv, 'machine_type', 'LASER')
            target = float(machine_cost_map.get(mtype, 0.0))
            old = float(getattr(sv, 'custo_por_minuto', 0.0) or 0.0)
            if target > 0.0 and abs(old - target) > 1e-6:
                sv.custo_por_minuto = float(target)
                s.add(sv)
                updated += 1
        if updated:
            s.commit()
            st.success(f"Custos por minuto atualizados em {updated} serviços.")
    else:
        st.warning("Defina primeiro os Parâmetros (⚙️) para calcular custo por minuto.")

    # ============== LISTA ==============
    with tab1:
        svs = s.exec(select(Service)).all()
        rows = [{
            "Código": x.code,
            "Nome (PT)": x.nome_pt,
            "Categoria": getattr(x, "categoria", ""),
            "Unidade": getattr(x, "unidade", ""),
            "Largura (cm)": getattr(x, "largura_cm", 0.0),
            "Altura (cm)": getattr(x, "altura_cm", 0.0),
            "Preço Cliente": getattr(x, "preco_cliente", 0.0),
            "Custo/min": getattr(x, "custo_por_minuto", 0.0),
            "Min/Un": getattr(x, "minutos_por_unidade", 0.0),
            "Máquina": getattr(x, "machine_type", "LASER"),
            "Sugestão (€/min)": float(machine_cost_map.get(getattr(x, "machine_type", ""), 0.0)),
            "Custo extra": getattr(x, "custo_extra", 0.0),
            "Custo fornecedor": getattr(x, "custo_fornecedor", 0.0),
            "Obs.": getattr(x, "observacoes", ""),
        } for x in svs]
        st.dataframe(rows, use_container_width=True)
        df = pd.DataFrame(rows)
        export_buttons(df, base_filename="servicos")

    # ============== ADICIONAR ==============
    with tab2:
        st.subheader("Adicionar serviço")
        code = st.text_input("Código", key="svc_add_code")
        nome_pt = st.text_input("Nome (PT)", key="svc_add_nome_pt")
        nome_en = st.text_input("Nome (EN)", key="svc_add_nome_en")
        nome_fr = st.text_input("Nome (FR)", key="svc_add_nome_fr")
        categoria = st.text_input("Categoria", key="svc_add_categoria")

        unidade_opts = ["min", "cm²", "PC"]
        unidade = st.selectbox("Unidade", unidade_opts, index=0, key="svc_add_unidade")

        largura = st.number_input("Largura (cm)", min_value=0.0, value=0.0, key="svc_add_largura")
        altura = st.number_input("Altura (cm)", min_value=0.0, value=0.0, key="svc_add_altura")

        preco_cliente = st.number_input("Preço ao cliente (por unidade)", min_value=0.0, value=0.0, key="svc_add_preco_cliente")
        # Escolha de máquina com opção "sem máquina"
        if machine_options:
            _opts = ["— sem máquina —"] + machine_options
            _idx = 0
            machine_choice = st.selectbox("Máquina", _opts, index=_idx, key="svc_add_machine")
            machine_type = "" if machine_choice == "— sem máquina —" else machine_choice
        else:
            st.warning("Defina máquinas nos Parâmetros para as poder selecionar aqui, ou deixe sem máquina.")
            machine_type = ""  # sem máquina
        suggested_cpm = float(machine_cost_map.get(machine_type, 0.0))
        custo_por_minuto = st.number_input("Custo por minuto (€/min)", min_value=0.0, value=float(suggested_cpm), format="%.4f", key="svc_add_cpm")
        st.caption((f"Sugestão pelos Parâmetros ({machine_type}): €{float(suggested_cpm):.4f} / min") if machine_type else "Sem máquina associada: custo/min sugerido = 0.0")

        # Novo: minutos por unidade (para custo interno no orçamento)
        minutos_por_unidade = st.number_input("Minutos por unidade (custo interno)", min_value=0.0, value=0.0, step=0.5, format="%.2f", key="svc_add_min_por_un")

        custo_extra = st.number_input("Custo extra (fixo)", min_value=0.0, value=0.0, key="svc_add_custo_extra")
        custo_fornecedor = st.number_input("Custo fornecedor", min_value=0.0, value=0.0, key="svc_add_custo_forn")

        observacoes = st.text_area("Observações", key="svc_add_obs")
        last_by = st.text_input("Última alteração por", key="svc_add_last")

        if st.button("➕ Adicionar serviço", key="svc_add_submit"):
            sv = Service(
                code=code,
                nome_pt=nome_pt, nome_en=nome_en, nome_fr=nome_fr,
                categoria=categoria,
                unidade=unidade,
                largura_cm=float(largura), altura_cm=float(altura),
                preco_cliente=float(preco_cliente),
                custo_por_minuto=float(custo_por_minuto),
                minutos_por_unidade=float(minutos_por_unidade),
                machine_type=machine_type,
                custo_extra=float(custo_extra),
                custo_fornecedor=float(custo_fornecedor),
                observacoes=observacoes,
                last_modified_by=last_by,
            )
            s.add(sv); s.commit()
            st.success("Serviço criado.")

    # ============== EDITAR ==============
    with tab3:
        st.subheader("Editar serviço")
        svs_all = s.exec(select(Service)).all()
        if not svs_all:
            st.info("Não existem serviços para editar.")
        else:
            q = st.text_input("🔎 Procurar (código ou nome)", key="svc_edit_search")
            if q:
                ql = q.strip().lower()
                svs = [x for x in svs_all if (x.code and ql in str(x.code).lower()) or (x.nome_pt and ql in str(x.nome_pt).lower())]
            else:
                svs = svs_all
            if not svs:
                st.warning("Sem resultados para a pesquisa.")
            else:
                df_edit = pd.DataFrame([
                    {"ID": x.id, "Código": x.code, "Nome": x.nome_pt, "Categoria": getattr(x, 'categoria',''),
                     "Unidade": getattr(x,'unidade',''), "Custo/min": getattr(x,'custo_por_minuto',0.0), "Máquina": getattr(x,'machine_type','LASER')}
                    for x in svs
                ])
                st.dataframe(df_edit, use_container_width=True, hide_index=True)

                sel_id = st.selectbox("Escolhe o serviço", df_edit["ID"].tolist(), key="svc_edit_select")
                sv_db = s.get(Service, sel_id)

                code = st.text_input("Código", value=(sv_db.code or ""), key=f"svc_edit_code_{sel_id}")
                nome_pt = st.text_input("Nome (PT)", value=(sv_db.nome_pt or ""), key=f"svc_edit_nome_pt_{sel_id}")
                nome_en = st.text_input("Nome (EN)", value=(sv_db.nome_en or ""), key=f"svc_edit_nome_en_{sel_id}")
                nome_fr = st.text_input("Nome (FR)", value=(sv_db.nome_fr or ""), key=f"svc_edit_nome_fr_{sel_id}")
                categoria = st.text_input("Categoria", value=(getattr(sv_db, 'categoria', '') or ""), key=f"svc_edit_categoria_{sel_id}")

                unidade_opts = ["min", "cm²", "PC"]
                unidade_sel = getattr(sv_db, 'unidade', 'min') or 'min'
                unidade_sel = 'cm²' if unidade_sel == 'cm2' else unidade_sel
                unidade = st.selectbox("Unidade", unidade_opts, index=unidade_opts.index(unidade_sel) if unidade_sel in unidade_opts else 0, key=f"svc_edit_unidade_{sel_id}")

                largura = st.number_input("Largura (cm)", min_value=0.0, value=float(getattr(sv_db, 'largura_cm', 0.0) or 0.0), key=f"svc_edit_largura_{sel_id}")
                altura = st.number_input("Altura (cm)", min_value=0.0, value=float(getattr(sv_db, 'altura_cm', 0.0) or 0.0), key=f"svc_edit_altura_{sel_id}")

                preco_cliente = st.number_input("Preço ao cliente (por unidade)", min_value=0.0, value=float(getattr(sv_db, 'preco_cliente', 0.0) or 0.0), key=f"svc_edit_preco_cliente_{sel_id}")
                current_mt = getattr(sv_db,'machine_type','')
                if machine_options:
                    _opts = ["— sem máquina —"] + machine_options
                    idx = _opts.index(current_mt) if current_mt in _opts else 0
                    machine_choice = st.selectbox("Máquina", _opts, index=idx, key=f"svc_edit_machine_{sel_id}")
                    machine_type = "" if machine_choice == "— sem máquina —" else machine_choice
                else:
                    machine_type = ""  # sem máquina
                suggested_cpm = float(machine_cost_map.get(machine_type, 0.0))
                current_cpm = float(getattr(sv_db, 'custo_por_minuto', 0.0) or 0.0)
                default_cpm = current_cpm if current_cpm > 0 else float(suggested_cpm)
                custo_por_minuto = st.number_input("Custo por minuto", min_value=0.0, value=default_cpm, format="%.4f", key=f"svc_edit_cpm_{sel_id}")
                st.caption(f"Sugestão pelos Parâmetros ({machine_type}): €{float(suggested_cpm):.4f} / min")

                minutos_por_unidade = st.number_input("Minutos por unidade (custo interno)", min_value=0.0, value=float(getattr(sv_db, 'minutos_por_unidade', 0.0) or 0.0), step=0.5, format="%.2f", key=f"svc_edit_min_por_un_{sel_id}")

                custo_extra = st.number_input("Custo extra (fixo)", min_value=0.0, value=float(getattr(sv_db, 'custo_extra', 0.0) or 0.0), key=f"svc_edit_custo_extra_{sel_id}")
                custo_fornecedor = st.number_input("Custo fornecedor", min_value=0.0, value=float(getattr(sv_db, 'custo_fornecedor', 0.0) or 0.0), key=f"svc_edit_custo_forn_{sel_id}")

                observacoes = st.text_area("Observações", value=(getattr(sv_db, 'observacoes', '') or ""), key=f"svc_edit_obs_{sel_id}")
                last_by = st.text_input("Última alteração por", value=(getattr(sv_db, 'last_modified_by', '') or ""), key=f"svc_edit_last_{sel_id}")

                c1, c2 = st.columns(2)
                if c1.button("💾 Guardar alterações", key=f"svc_edit_save_{sel_id}"):
                    sv_db = s.get(Service, sel_id)
                    if not sv_db:
                        st.error("Não foi possível carregar o serviço selecionado.")
                    else:
                        sv_db.code = code
                        sv_db.nome_pt = nome_pt
                        sv_db.nome_en = nome_en
                        sv_db.nome_fr = nome_fr
                        setattr(sv_db, 'categoria', categoria)
                        setattr(sv_db, 'unidade', unidade)
                        setattr(sv_db, 'largura_cm', float(largura))
                        setattr(sv_db, 'altura_cm', float(altura))
                        setattr(sv_db, 'preco_cliente', float(preco_cliente))
                        setattr(sv_db, 'custo_por_minuto', float(custo_por_minuto))
                        setattr(sv_db, 'minutos_por_unidade', float(minutos_por_unidade))
                        setattr(sv_db, 'machine_type', machine_type)
                        setattr(sv_db, 'custo_extra', float(custo_extra))
                        setattr(sv_db, 'custo_fornecedor', float(custo_fornecedor))
                        setattr(sv_db, 'observacoes', observacoes)
                        setattr(sv_db, 'last_modified_by', last_by)
                        s.add(sv_db); s.commit()
                        st.success("Serviço atualizado.")

                if c2.button("🗑️ Apagar serviço", key=f"svc_edit_delete_{sel_id}"):
                    obj = s.get(Service, sel_id)
                    if not obj:
                        st.error("Serviço não encontrado para apagar.")
                    else:
                        s.delete(obj); s.commit()
                        st.success("Serviço removido.")