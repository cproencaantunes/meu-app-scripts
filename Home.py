import streamlit as st
import time

# Configuração da página - DEVE ser a primeira linha
st.set_page_config(page_title="Hub de Extração Pro", page_icon="🏥", layout="wide")

# --- LÓGICA DE AUTENTICAÇÃO ROBUSTA ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

def login():
    st.title("🔐 Acesso Restrito")
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        with st.form("login_form", clear_on_submit=False):
            user_input = st.text_input("Utilizador")
            pass_input = st.text_input("Password", type="password")
            submit = st.form_submit_button("Entrar")
            
            if submit:
                allowed_users = st.secrets.get("users", {})
                # Verificação direta nos Secrets
                if user_input in allowed_users and str(allowed_users[user_input]) == pass_input:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = user_input
                    st.success("Autenticado com sucesso!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Utilizador ou Password incorretos")

# --- CONTROLO DE FLUXO ---
if not st.session_state["authenticated"]:
    login()
    st.stop() # FORÇA o Streamlit a parar aqui e não ler mais nada abaixo

# --- TUDO O QUE ESTÁ ABAIXO SÓ CORRE SE O LOGIN FOR FEITO ---

st.title(f"🏥 Bem-vindo, Dr. {st.session_state['username']}")

with st.sidebar:
    st.header("⚙️ Configuração")
    st.session_state['sheet_url'] = st.text_input(
        "Link da Planilha Google", 
        value=st.session_state.get('sheet_url', ''),
        placeholder="Cole o link aqui..."
    )
    st.divider()
    if st.button("🚪 Sair"):
        st.session_state["authenticated"] = False
        st.rerun()

st.info("Utilize o menu lateral para selecionar a ferramenta pretendida.")

# Cards visuais
col1, col2 = st.columns(2)
with col1:
    st.markdown("### 💰 Honorários\nProcessamento de pagamentos.")
with col2:
    st.markdown("### 🔬 Técnicas e Exames\nGastro e Medicina da Dor.")
