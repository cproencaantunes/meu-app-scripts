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
st.set_page_config(page_title="Analisador CUF", page_icon="📄")
st.title("📄 Processador de Honorários (Versão Colab)")

try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
    
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    gc = gspread.authorize(creds)
except Exception as e:
    st.error(f"❌ Erro de Configuração: {e}")
    st.stop()

SPREADSHEET_ID = '1WMd12Ps24yJkOTCXfi3tIFJ2UqvI7u_NWQsdgoX82wQ'
NOME_FOLHA = 'pagos'

# --- 2. FUNÇÕES DE SUPORTE (ORIGINAIS DO COLAB) ---

def formatar_data(data_str):
    data_str = str(data_str).strip()
    if not data_str or "DD-MM-YYYY" in data_str.upper():
        return None
    match_iso = re.search(r'(\d{4})-(\d{2})-(\d{2})', data_str)
    if match_iso:
        return f"{match_iso.group(3)}-{match_iso.group(2)}-{match_iso.group(1)}"
    match_pt = re.search(r'\d{2}-\d{2}-\d{4}', data_str)
    return match_pt.group(0) if match_pt else None

def extrair_dados_ia(texto_pagina, model):
    # Prompt idêntico ao original do Colab
    prompt = "Extraia dados deste PDF CUF para este JSON: [{\"data\":\"DD-MM-YYYY\",\"id\":\"ID\",\"nome\":\"NOME\",\"valor\":0.00}]"
    try:
        response = model.generate_content(f"{prompt}\n\nTEXTO:\n{texto_pagina}")
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        return json.loads(match.group()) if match else []
    except:
        return []

# --- 3. INTERFACE E FLUXO DE PROCESSAMENTO ---

arquivos_pdf = st.file_uploader("Arraste os PDFs aqui", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("Iniciar Processamento"):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    todas_as_linhas_final = []
    data_hoje = datetime.now().strftime("%d-%m-%Y")

    # Termos originais do Colab
    termos_ignorar = ["PROENÇA ANTUNES", "UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO", "FIM DA LISTAGEM"]

    progresso = st.progress(0)
    
    for idx, pdf_file in enumerate(arquivos_pdf):
        st.write(f"📖 A analisar: {pdf_file.name}")
        ultima_data_valida = ""

        with pdfplumber.open(pdf_file) as pdf:
            for pagina in pdf.pages:
                # AJUSTE PARA MAC: extração de texto orientada por layout para evitar inversão
                texto = pagina.extract_text(layout=True) 
                if not texto: continue

                dados_ia = extrair_dados_ia(texto, model)

                for d in dados_ia:
                    # 1. Lógica de Data (Herança) - Original Colab
                    dt_extraida = formatar_data(d.get('data', ''))
                    if dt_extraida:
                        ultima_data_valida = dt_extraida
                    else:
                        dt_extraida = ultima_data_valida

                    # 2. Limpeza do ID - Original Colab
                    id_raw = str(d.get('id', '')).strip()
                    id_limpo = re.sub(r'\D', '', id_raw)

                    # 3. Limpeza do Nome - Original Colab
                    nome_raw = str(d.get('nome', '')).replace('\n', ' ').strip().upper()

                    # 4. Filtro de Validação - Original Colab
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

                time.sleep(1) 
        
        progresso.progress((idx + 1) / len(arquivos_pdf))

    # --- 4. GRAVAÇÃO NO GOOGLE SHEETS ---
    if todas_as_linhas_final:
        try:
            sh = gc.open_by_key(SPREADSHEET_ID)
            try:
                worksheet = sh.worksheet(NOME_FOLHA)
            except:
                worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="2000", cols="6")

            if not worksheet.get_all_values():
                worksheet.append_row(["Data", "ID", "Nome", "Valor", "Data Execução", "Ficheiro Origem"])

            worksheet.append_rows(todas_as_linhas_final)
            st.success(f"✅ CONCLUÍDO: {len(todas_as_linhas_final)} linhas escritas.")
            st.dataframe(todas_as_linhas_final)
        except Exception as e:
            st.error(f"Erro ao gravar: {e}")
    else:
        st.warning("❌ Nenhum dado válido encontrado.")