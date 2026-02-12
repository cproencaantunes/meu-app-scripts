import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÕES E AUTENTICAÇÃO ---
st.set_page_config(page_title="Processador CUF", layout="wide")

# Recuperar segredos do Streamlit
try:
    # Google Sheets
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    
    # Gemini
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception as e:
    st.error("❌ Erro nas chaves de segurança. Verifique os Secrets no Streamlit Cloud.")
    st.stop()

# Configurações da Planilha (Podes manter fixo ou usar st.session_state)
SPREADSHEET_ID = '1WMd12Ps24yJkOTCXfi3tIFJ2UqvI7u_NWQsdgoX82wQ'
NOME_FOLHA = 'pagos'

# --- 2. FUNÇÕES DE SUPORTE ---

def formatar_data(data_str):
    data_str = str(data_str).strip()
    if not data_str or "DD-MM-YYYY" in data_str.upper():
        return None
    
    # Regex para capturar DD-MM-YY ou DD-MM-YYYY
    match = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})', data_str)
    if match:
        d, m, a = match.groups()
        if len(a) == 2:
            a = "20" + a
        return f"{d.zfill(2)}-{m.zfill(2)}-{a}"
    return None

def extrair_dados_ia(texto_pagina, model):
    prompt = "Extraia dados deste PDF CUF para este JSON: [{\"data\":\"DD-MM-YYYY\",\"id\":\"ID\",\"nome\":\"NOME\",\"valor\":0.00}]"
    try:
        response = model.generate_content(f"{prompt}\n\nTEXTO:\n{texto_pagina}", generation_config={"temperature": 0.0})
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        return json.loads(match.group()) if match else []
    except:
        return []

# --- 3. INTERFACE STREAMLIT ---

st.title("🏥 Processador de PDFs CUF")
st.write("Carregue os seus relatórios para extração automática para o Google Sheets.")

# Upload de ficheiros
arquivos_pdf = st.file_uploader("Selecione os ficheiros PDF", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf:
    if st.button("🚀 Iniciar Processamento"):
        model = genai.GenerativeModel("models/gemini-2.0-flash")
        todas_as_linhas_final = []
        data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
        
        # Termos para ignorar (limpeza do cabeçalho)
        termos_ignorar = ["PROENÇA ANTUNES", "UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO", "FIM DA LISTAGEM"]

        barra_progresso = st.progress(0)
        status_text = st.empty()

        for idx, pdf_file in enumerate(arquivos_pdf):
            status_text.text(f"📖 A analisar: {pdf_file.name}")
            ultima_data_valida = ""

            with pdfplumber.open(pdf_file) as pdf:
                for pagina in pdf.pages:
                    # layout=True ajuda a manter a estrutura para a IA
                    texto = pagina.extract_text(layout=True)
                    if not texto: continue

                    dados_ia = extrair_dados_ia(texto, model)

                    for d in dados_ia:
                        # 1. Lógica de Data
                        dt_extraida = formatar_data(d.get('data', ''))
                        if dt_extraida:
                            ultima_data_valida = dt_extraida
                        else:
                            dt_extraida = ultima_data_valida

                        # 2. Limpeza do ID e Nome
                        id_raw = str(d.get('id', '')).strip()
                        id_limpo = re.sub(r'\D', '', id_raw)
                        nome_raw = str(d.get('nome', '')).replace('\n', ' ').strip().upper()

                        # 3. Filtros
                        e_lixo = any(termo in nome_raw for termo in termos_ignorar)

                        if id_limpo and not e_lixo and len(nome_raw) > 3:
                            todas_as_linhas_final.append([
                                dt_extraida,
                                id_limpo,
                                nome_raw,
                                d.get('valor', 0.0),
                                data_hoje,
                                pdf_file.name
                            ])
            
            barra_progresso.progress((idx + 1) / len(arquivos_pdf))
            time.sleep(1)

        # --- 4. GRAVAÇÃO NO GOOGLE SHEETS ---
        if todas_as_linhas_final:
            try:
                sh = gc.open_by_key(SPREADSHEET_ID)
                try:
                    worksheet = sh.worksheet(NOME_FOLHA)
                except:
                    worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="2000", cols="6")

                # Adiciona cabeçalho se estiver vazio
                if not worksheet.get_all_values():
                    worksheet.append_row(["Data", "ID", "Nome", "Valor", "Data Execução", "Ficheiro Origem"])

                worksheet.append_rows(todas_as_linhas_final)
                st.balloons()
                st.success(f"✅ CONCLUÍDO: {len(todas_as_linhas_final)} linhas escritas em '{NOME_FOLHA}'.")
                st.dataframe(todas_as_linhas_final)
            except Exception as e:
                st.error(f"Erro ao aceder à planilha: {e}")
        else:
            st.warning("❌ Nenhum dado válido encontrado nos PDFs.")
