import streamlit as st

# Configuração da página
st.set_page_config(page_title="Guia de Início", page_icon="📖", layout="wide")

st.title("📖 Guia de Início - Sistema de Extração Pro")
st.markdown("---")

# --- SECÇÃO 1: PREPARAR A PLANILHA ---
st.header("1️⃣ Preparar a sua Planilha")
col_a, col_b = st.columns(2)

with col_a:
    st.markdown("### 📑 Passo 1: Criar a sua cópia")
    st.write("Clique no botão abaixo para abrir o modelo oficial e faça uma cópia para a sua conta Google Drive pessoal.")
    st.link_button("Abrir Template do Excel ↗️", "https://docs.google.com/spreadsheets/d/1oyWViB-jafKCGKLTMCDcY5xShMNgtWVUjTqmZfzWQMM/edit?gid=0#gid=0")

with col_b:
    st.markdown("### 🔑 Passo 2: Dar acesso ao sistema")
    st.write("Para que o sistema consiga escrever os dados, vá ao botão **Partilhar** da sua planilha e adicione este e-mail como **Editor**:")
    st.code("pdf-extractor@gen-lang-client-0404678969.iam.gserviceaccount.com", language="text")

st.markdown("---")

# --- SECÇÃO 2: ATIVAÇÃO ---
st.header("2️⃣ Ativar a Ligação")

st.markdown("### 🔗 Vincular no App")
st.write("Já não precisa de gerar chaves de inteligência artificial. O sistema utiliza agora uma ligação mestra de alta velocidade.")
st.info("Basta ir à página **🏠 Home** no menu lateral e colar o **Link da sua Planilha** (o URL completo da cópia que criou no Passo 1).")

# --- SECÇÃO 3: ONDE CARREGAR CADA RELATÓRIO ---
st.markdown("---")
st.header("3️⃣ Onde carregar os seus relatórios?")
st.write("Selecione a página correta no menu lateral de acordo com o tipo de ficheiro que deseja processar:")

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.info("### 💰 Honorários\nProcessamento de listagens de pagamentos recebidos.")

with c2:
    st.success("### 💉 Anestesiados\nExtração de atos anestésicos. O sistema evita automaticamente registos duplicados.")

with c3:
    st.warning("### 🧪 Especiais\nExames e atos técnicos específicos (ExamesEsp).")

with c4:
    st.error("### 👨‍⚕️ Consultas\nListagens diárias de consultas efetuadas.")

# --- SECÇÃO 4: REGRAS DE OURO ---
st.markdown("---")
st.header("💡 Regras de Ouro")

st.markdown("""
* **Fórmulas Pessoais:** Pode criar as suas fórmulas nas **Colunas A e B**. O sistema escreve sempre a partir da **Coluna C**, garantindo que não apaga os seus cálculos.
* **Privacidade:** Os dados são processados e enviados diretamente para a sua planilha. O sistema não armazena cópias dos seus PDFs.
* **Qualidade do PDF:** Utilize apenas PDFs originais (digitais). Documentos digitalizados (fotos/scans) podem comprometer a precisão da leitura.
* **Processamento:** Graças à sua subscrição, o sistema utiliza o motor **Gemini 2.0 Flash Tier 1**, permitindo processamentos muito mais rápidos e sem interrupções.
""")

st.markdown("---")
st.caption("Sistema de Apoio Clínico Profissional | v3.0 (2026)")
