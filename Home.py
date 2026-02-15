import streamlit as st
import time

st.set_page_config(page_title="Hub de Extração Pro", page_icon="🏥", layout="wide")

# 1. Inicializar o estado de autenticação
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# 2. Função de Login isolada
def mostrar_login():
    # Este placeholder evita o erro de 'removeChild'
    placeholder = st.empty()
    
    with placeholder.container():
        st.title("🔐 Acesso Restrito")
        col1, col2, col3 = st.columns([1,2,1])
        
        with col2:
            with st.form("login_form"):
                user_input = st.text_input("Utilizador")
                pass_input = st.text_input("Password", type="password")
                if st.form_submit_button("Entrar"):
                    allowed_users = st.secrets.get("users", {})
                    
                    if user_input in allowed_users and str(allowed_users[user_input]) == pass_input:
                        st.session_state["authenticated"] = True
                        st.session_state["username"] = user_input
                        st.success("Autenticado! A carregar...")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Credenciais incorretas")

# 3. Lógica Principal
if not st.session_state["authenticated"]:
    mostrar_login()
    st.stop() # Bloqueia a execução do resto do ficheiro

# --- DAQUI PARA BAIXO: APENAS CONTEÚDO PÓS-LOGIN ---

st.title(f"🏥 Bem-vindo, Dr. {st.session_state['username']}")

with st.sidebar:
    st.header("⚙️ Configuração")
    st.session_state['sheet_url'] = st.text_input(
        "Link da Planilha Google", 
        value=st.session_state.get('sheet_url', ''),
        placeholder="Cole o link aqui..."
    )
    if st.button("🚪 Sair"):
        st.session_state["authenticated"] = False
        st.rerun()

st.success("✅ Sistema pronto. Selecione uma ferramenta no menu lateral.")
