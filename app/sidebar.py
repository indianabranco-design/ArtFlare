# app/sidebar.py — Sidebar personalizada + esconder navegação automática (com dev toggle e highlight ativo)
from pathlib import Path
import streamlit as st

# ---- Query params helpers (compat Streamlit versions) ----
def _get_query_params():
    try:
        return dict(st.query_params)
    except Exception:
        try:
            return dict(st.experimental_get_query_params())
        except Exception:
            return {}

params = _get_query_params()
devnav_raw = params.get("devnav", 0)
if isinstance(devnav_raw, list):
    devnav_raw = devnav_raw[0] if devnav_raw else 0
DEVNAV = str(devnav_raw).strip() in {"1", "true", "True"}

# --- CSS base (active link highlight) ---
_css_parts = [
    """
    <style>
      .active-link { font-weight: 700 !important; text-decoration: underline !important; }
      .thin-sep { margin: 0.25rem 0 0.5rem 0; border-top: 1px solid rgba(255,255,255,0.15); }
    </style>
    """
]

# --- Ocultar navegação nativa quando NÃO estiver em modo devnav ---
if not DEVNAV:
    _css_parts.append(
        """
        <style>
          /* Oculta a navegação automática (multipage) - cobre diferentes assinaturas */
          div[data-testid="stSidebarNav"],
          nav[data-testid="stSidebarNav"],
          [data-testid="stSidebarNav"] ul,
          section[data-testid="stSidebar"] nav,
          section[data-testid="stSidebar"] [role="navigation"],
          section[data-testid="stSidebar"] div:has(> nav[data-testid="stSidebarNav"]),
          section[data-testid="stSidebar"] div:has(> [data-testid="stSidebarNav"]) {
            display: none !important;
            visibility: hidden !important;
            height: 0 !important;
            overflow: hidden !important;
          }
        </style>
        """
    )

st.markdown("\n".join(_css_parts), unsafe_allow_html=True)

# --- Remoção via JS como fallback (caso o CSS não chegue) ---
if not DEVNAV:
    st.markdown(
        """
        <script>
        (function(){
          try {
            const roots = [document, parent.document];
            const selectors = [
              '[data-testid="stSidebarNav"]',
              'nav[data-testid="stSidebarNav"]',
              'section[data-testid="stSidebar"] nav',
              'section[data-testid="stSidebar"] [role="navigation"]',
              '[data-testid="stSidebarNavItems"]'
            ];
            roots.forEach(root => {
              selectors.forEach(sel => {
                root.querySelectorAll(sel).forEach(el => el.remove());
              });
            });
          } catch(e) { /* noop */ }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )

BASE = Path(__file__).resolve().parents[1]
PAGES = BASE / "pages"


def _find_page(*prefixes: str) -> str | None:
    """Devolve o primeiro ficheiro em /pages que começa por um dos prefixos dados."""
    if not PAGES.exists():
        return None
    files = [p.name for p in PAGES.iterdir() if p.suffix == ".py" and not p.name.startswith("__")]
    for pref in prefixes:
        for name in sorted(files):
            if name.startswith(pref):
                return f"pages/{name}"
    return None


def show_sidebar():
    with st.sidebar:
        st.title("📌 Navegação")

        # Mostrar um badge quando em modo devnav
        if DEVNAV:
            st.caption("🧪 Modo desenvolvimento: navegação nativa visível (remova `?devnav=1` para ocultar)")

        has_page_link = hasattr(st, "page_link")

        def link(label: str, rel: str | None):
            if not rel:
                st.caption(f"(indisponível) {label}")
            elif has_page_link:
                st.page_link(rel, label=label, use_container_width=True)
            else:
                st.write(f"➡️ {label} — `{rel}`")

        # Ordem principal
        link("🗂️ Planeamento", _find_page("1_Planeamento", "2_Planeamento", "Planeamento"))
        link("👤 Clientes", _find_page("2_Clientes", "Clientes"))
        link("🧾 Orçamentos", _find_page("3_Orcamentos", "Orcamentos", "Orcamentos_v5_backup"))
        link("🛠️ Serviços", _find_page("4_Servicos", "Servicos"))
        link("📦 Stock", _find_page("5_Stock", "Stock"))
        link("🧮 Cálculos", _find_page("9_Calculos", "Calculos"))
        link("📊 Análises", _find_page("6_Analise", "6_Analises", "Analise", "Analises"))
        link("⚙️ Parâmetros", _find_page("7_Parametros", "9_Parametros", "Parametros"))
        link("🗃️ Arquivo", _find_page("8_Arquivo", "3_Arquivo", "Arquivo"))

        st.markdown('<div class="thin-sep"></div>', unsafe_allow_html=True)
        st.markdown("### 📜 Histórico")
        link("Visão de Histórico", _find_page("10_Historico", "Historico"))
        # Subpáginas escondidas do multipage (ficheiros com prefixo _10x_)
        link("📊 Histórico de Cálculos", _find_page("_10a_Historico_Calculos", "10a_Historico_Calculos", "Historico_Calculos"))
        link("📦 Movimentos de Stock", _find_page("_10b_Movimentos_Stock", "10b_Movimentos_Stock", "Movimentos_Stock"))
        link("📥 Importador", _find_page("_10c_Importador", "10c_Importador", "Importador"))
        link("📥 Importar Orçamentos (Arquivo)", _find_page("_10d_Importar_Orcamentos_Arquivo", "10d_Importar_Orcamentos_Arquivo", "Importar_Orcamentos_Arquivo", "Importar_Orcamentos"))

        st.markdown("---")
        dash = _find_page("0_Dashboard")
        if dash:
            link("🏠 Painel", dash)
        st.caption("A navegação acima é personalizada; o menu automático foi ocultado.")

        # ---- Highlight da página ativa via JS (marca o link cujo href contém o parâmetro page atual) ----
        st.markdown(
            """
            <script>
            (function(){
              try {
                const params = new URLSearchParams(window.location.search);
                const cur = params.get('page');
                const sb = parent.document.querySelector('section[data-testid="stSidebar"]') || document;
                const anchors = sb.querySelectorAll('a');
                anchors.forEach(a => {
                  const href = a.getAttribute('href') || '';
                  if (cur) {
                    if (href.includes(cur)) { a.classList.add('active-link'); }
                  } else {
                    // Sem ?page= (ex.: app.py), tentamos destacar o Dashboard
                    if (/0_Dashboard\.py$/.test(href) || /Dashboard/i.test(a.textContent)) {
                      a.classList.add('active-link');
                    }
                  }
                });
              } catch(e) { /* noop */ }
            })();
            </script>
            """,
            unsafe_allow_html=True,
        )