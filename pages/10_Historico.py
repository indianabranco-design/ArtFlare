import streamlit as st

# Sidebar (import robusto com fallback)
from pathlib import Path
import sys
from typing import List

def _get_show_sidebar():
    # 1) tentativa direta
    try:
        from app.sidebar import show_sidebar  # type: ignore
        return show_sidebar
    except Exception:
        pass
    # 2) adicionar raiz do projeto e tentar novamente
    try:
        ROOT = Path(__file__).resolve().parents[1]
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from app.sidebar import show_sidebar  # type: ignore
        return show_sidebar
    except Exception:
        # 3) fallback no-op para não rebentar a página
        def _noop():
            return None
        return _noop

show_sidebar = _get_show_sidebar()
show_sidebar()

# Conteúdo da página Histórico
st.title("Histórico")

tabs = st.tabs(["Histórico de Cálculos", "Movimentos de Stock", "Importadores"])

BASE_DIR = Path(__file__).parent

def _run_first_that_exists(candidates: List[str], tab_title: str):
    for name in candidates:
        path = BASE_DIR / name
        if path.exists():
            try:
                code = path.read_text(encoding="utf-8")
                exec(compile(code, str(path), "exec"), globals())
            except Exception as e:
                st.error(f"Erro ao carregar '{name}': {e}")
            return
    st.warning(f"Não encontrei nenhuma página para '{tab_title}'. Verifique: {', '.join(candidates)}")

with tabs[0]:
    _run_first_that_exists([
        "_10a_Historico_Calculos.py",
        "10a_Historico_Calculos.py",
        "a_Historico_Calculos.py",
        "Historico_Calculos.py",
    ], "Histórico de Cálculos")

with tabs[1]:
    _run_first_that_exists([
        "_10b_Movimentos_Stock.py",
        "10b_Movimentos_Stock.py",
        "b_Movimentos_Stock.py",
        "Movimentos_Stock.py",
    ], "Movimentos de Stock")

with tabs[2]:
    st.markdown("**Ferramentas de importação**")
    sub1, sub2 = st.tabs(["Importador", "Importar Orçamentos (Arquivo)"])

    with sub1:
        _run_first_that_exists([
            "_10c_Importador.py",
            "10c_Importador.py",
            "Importador.py",
            "Importadores.py",
        ], "Importador")

    with sub2:
        _run_first_that_exists([
            "_10d_Importar_Orcamentos_Arquivo.py",
            "10d_Importar_Orcamentos_Arquivo.py",
            "Importar_Orcamentos_Arquivo.py",
            "Importar_Orcamentos.py",
        ], "Importar Orçamentos (Arquivo)")