import streamlit as st
import hashlib

def check_pw():
    pw = st.text_input("Password", type="password")
    if not pw:
        st.stop()
    ok = hashlib.sha256(pw.encode()).hexdigest() == st.secrets["APP_SHA256"]
    if not ok:
        st.error("Password errada")
        st.stop()

check_pw()
from app.db import init_db, automate_statuses

st.set_page_config(page_title="Gestão da Empresa", page_icon="🏢", layout="wide")
init_db()
automate_statuses()

# Sidebar (import robusto para aplicar CSS/JS global de navegação)
try:
    from app.sidebar import show_sidebar
except Exception:
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[0]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.sidebar import show_sidebar
show_sidebar()

st.title("🏢 Gestão da Empresa")

st.markdown("### Bem-vindo ao sistema de gestão da empresa!")
st.markdown("Use o menu lateral para navegar ou aceda diretamente ao painel principal:")

st.page_link("pages/0_Dashboard.py", label="📊 Ir para o Dashboard")
