import streamlit as st

st.set_page_config(page_title="Hub de Extração Pro", page_icon="🏥", layout="wide")

# --- LÓGICA DE AUTENTICAÇÃO ---
def check_login():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.title("🔐 Acesso Restrito - Central de Documentos")
        
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            with st.form("login_form"):
                user = st.text_input("Utilizador")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Entrar na Plataforma"):
                    allowed_users = st.secrets.get("users", {})
                    # Verifica se o utilizador existe e a pass coincide
                    if user in allowed_users and str(allowed_users[user]) == password:
                        st.session_state["authenticated"] = True
                        st.session_state["username"] = user
                        st.rerun()
                    else:
                        st.error("❌ Credenciais incorretas.")
        return False
    return True

# --- CONTEÚDO SÓ APARECE SE LOGADO ---
if check_login():
    st.title("🏥 Central de Processamento de Documentos")

    with st.sidebar:
        st.header("⚙️ Configuração")
        st.session_state['sheet_url'] = st.text_input(
            "Link da Planilha Google", 
            value=st.session_state.get('sheet_url', ''),
            placeholder="https://docs.google.com/spreadsheets/d/..."
        )

        if "gcp_service_account" in st.secrets:
            st.divider()
            st.markdown("### 🔑 Autorização")
            st.write("Partilhe a sua planilha como **'Editor'** com:")
            st.code(st.secrets["gcp_service_account"]["client_email"], language="text")
            
        st.divider()
        if st.button("🚪 Sair"):
            st.session_state["authenticated"] = False
            st.rerun()

    # Conteúdo Principal
    st.markdown("---")
    st.markdown(f"### 👋 Bem-vindo, Dr. {st.session_state['username']}")
    
    # Cards de Ferramentas Ativas
    col1, col2 = st.columns(2)
    with col1:
        st.info("💰 **Honorários**\n\nProcessamento de listagens de pagamentos.")
    with col2:
        st.success("🔬 **Técnicas e Exames**\n\nEspecial para Gastro e Dor (Múltiplos atos).")

    st.markdown("""
    ### 💡 Como funciona?
    1.  Configure o link da sua planilha à esquerda.
    2.  Selecione a ferramenta no menu lateral.
    3.  O sistema extrai os dados e usa a **Coluna C como Chave Única** para o seu VLOOKUP.
    """)

    if not st.session_state.get('sheet_url'):
        st.warning("👈 Introduza o link da sua planilha na barra lateral para ativar o sistema.")
