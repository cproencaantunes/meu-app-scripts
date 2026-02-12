import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÕES INICIAIS E SEGURANÇA ---
st.set_page_config(page_title="Lista de Honorários", page_icon="💰", layout="wide")

# Recuperação de chaves da Home/Secrets
user_api_key = st.session_state.get('user_api_key')
sheet_url = st.session_state.get('sheet_url')

if not user_api_key or not sheet_url:
    st.warning("⚠️ Configuração em falta! Por favor, vá à página **Home (🏠)** e insira a sua API Key e o link da Planilha.")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE (Lógica do Colab Refinada) ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data(data_str):
    """Garante o formato DD-MM-YYYY e corrige anos com 2 dígitos."""
    data_str = str(data_str).strip()
    if not data_str or "DD-MM-YYYY" in data_str.upper():
        return None
    
    # Procura padrão de data (DD-MM-YY ou DD-MM-YYYY)
    match = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', data_str)
    if match:
        d, m, a = match.groups()
        if len(a) == 2:
            a = "20" + a
        return f"{d.zfill(2)}-{m.zfill(2)}-{a}"
    return None

def extrair_dados_ia(texto_pagina, model):
    """Prompt otimizado para extração estrita."""
    prompt = "Extraia dados deste PDF CUF para este JSON: [{\"data\":\"DD-MM-YYYY\",\"id\":\"ID\",\"nome\":\"NOME\",\"valor\":0.00}]"
    try:
        response = model.generate_content(
            f"{prompt}\n\nTEXTO:\n{texto_pagina}",
            generation_config={"temperature": 0.0}
        )
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        return json.loads(match.group()) if match else []
    except:
        return []

# --- 3. CONEXÃO ÀS APIS ---

try:
    genai.configure(api_key=user_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    worksheet = sh.get_worksheet(0) # Assume a primeira aba
except Exception as e:
    st.error(f"❌ Erro de Conexão: {e}")
    st.stop()

# --- 4. INTERFACE E PROCESSAMENTO ---

st.title("💰 Processador de Honorários")
st.markdown("Extração automática com salto de cabeçalhos e correção de datas.")

arquivos_pdf = st.file_uploader("Carregue os PDFs de Honorários", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Iniciar Processamento"):
    todas_as_linhas_final = []
    data_execucao = datetime.now().strftime("%d-%m-%Y %H:%M")
    termos_ignorar = ["PROENÇA ANTUNES", "UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO", "FIM DA LISTAGEM"]

    progresso = st.progress(0)
    status_info = st.empty()

    for idx, pdf_file in enumerate(arquivos_pdf):
        status_info.info(f"Analisando: `{pdf_file.name}`")
        ultima_data_valida = ""

        with pdfplumber.open(pdf_file) as pdf:
            for i, pagina in enumerate(pdf.pages):
                
                # --- REGRA: SALTAR A PRIMEIRA PÁGINA (CABEÇALHO) ---
                if i == 0:
                    continue 

                texto = pagina.extract_text(layout=True)
                if not texto: continue

                dados_ia = extrair_dados_ia(texto, model)

                for d in dados_ia:
                    # 1. Lógica de Data (Herança de linha)
                    dt_extraida = formatar_data(d.get('data', ''))
                    if dt_extraida:
                        ultima_data_valida = dt_extraida
                    else:
                        dt_extraida = ultima_data_valida

                    # 2. Limpeza do ID (Apenas números)
                    id_raw = str(d.get('id', '')).strip()
                    id_limpo = re.sub(r'\D', '', id_raw)

                    # 3. Limpeza do Nome
                    nome_raw = str(d.get('nome', '')).replace('\n', ' ').strip().upper()

                    # 4. Filtro de Validação
                    e_lixo = any(termo in nome_raw for termo in termos_ignorar)

                    if id_limpo and not e_lixo and len(nome_raw) > 3:
                        todas_as_linhas_final.append([
                            dt_extraida,
                            id_limpo,
                            nome_raw,
                            d.get('valor', 0.0),
                            data_execucao,
                            pdf_file.name
                        ])
        
        progresso.progress((idx + 1) / len(arquivos_pdf))
        time.sleep(1) # Rate limit para API gratuita

    # --- 5. GRAVAÇÃO FINAL ---
    if todas_as_linhas_final:
        try:
            worksheet.append_rows(todas_as_linhas_final)
            st.balloons()
            st.success(f"✅ Concluído! {len(todas_as_linhas_final)} linhas escritas na planilha.")
            st.dataframe(todas_as_linhas_final)
        except Exception as e:
            st.error(f"Erro ao gravar na planilha: {e}")
    else:
        st.warning("Nenhum dado válido encontrado nos PDFs (além das páginas de cabeçalho).")

status_info.empty()
