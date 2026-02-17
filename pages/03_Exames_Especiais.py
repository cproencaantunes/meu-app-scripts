import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="Exames Especiais", page_icon="🧪", layout="wide")

master_api_key = st.secrets.get("GEMINI_API_KEY")
sheet_url = st.session_state.get('sheet_url')

if not master_api_key or not sheet_url:
    st.error("❌ Erro: Configuração de API ou Planilha em falta na Home.")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data_universal(data_str):
    if not data_str: return None
    s = str(data_str).strip()
    # Captura grupos de números para evitar inversões
    partes = re.findall(r'\d+', s)
    if len(partes) == 3:
        p1, p2, p3 = partes
        if len(p1) == 4: # ISO
            ano, mes, dia = p1, p2, p3
        elif len(p3) == 4: # PT
            dia, mes, ano = p1, p2, p3
        else:
            dia, mes, ano = p1, p2, p3
            if len(ano) == 2: ano = "20" + ano
        return f"{dia.zfill(2)}-{mes.zfill(2)}-{ano}"
    return None

def extrair_dados_ia_com_retry(texto_pagina, model, max_retries=3):
    # INSTRUÇÃO CORRIGIDA: Ignorar data de geração/emissão do relatório
    prompt_sistema = """
    Analisa este relatório de exames CUF. 
    REGRA CRÍTICA: Extrai apenas a DATA DO EXAME/ATO. 
    NÃO extraias a data de emissão, data de impressão ou data que aparece isolada no topo/canto superior direito do relatório.
    
    JSON: [{"data": "DD-MM-YYYY", "processo": "...", "nome": "...", "procedimento": "..."}]
    """
    for i in range(max_retries):
        try:
            response = model.generate_content(prompt_sistema + "\n\nTEXTO:\n" + texto_pagina, 
                                            generation_config={"temperature": 0.0})
            match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
            return json.loads(match.group()) if match else []
        except Exception as e:
            if "429" in str(e):
                time.sleep((i + 1) * 2)
            else:
                return []
    return []

# --- 3. CONEXÃO ---
try:
    genai.configure(api_key=master_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    
    NOME_FOLHA = 'ExamesEsp'
    try:
        worksheet = sh.worksheet(NOME_FOLHA)
    except:
        worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="2000", cols="10")
        worksheet.update(range_name="C1", values=[["Data", "Processo", "Nome Completo", "Procedimento", "Data Execução", "Origem PDF"]])
except Exception as e:
    st.error(f"❌ Erro de Ligação: {e}")
    st.stop()

# --- 4. INTERFACE ---
st.title("🧪 Exames Especiais")
st.info("A extração ignora agora as datas de emissão no cabeçalho e foca-se na data do exame.")

arquivos_pdf = st.file_uploader("Upload PDFs de Exames Especiais", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Processar Especiais"):
    novas_linhas = []
    data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
    termos_lixo = ["PROENÇA", "CPANTUNES", "PÁGINA", "UTILIZADOR", "GHCE9050"]

    progresso = st.progress(0)
    status = st.empty()

    dados_atuais = worksheet.get_all_values()

    for idx, pdf_file in enumerate(arquivos_pdf):
        status.text(f"📖 A ler: {pdf_file.name}")
        data_corrente = ""

        with pdfplumber.open(pdf_file) as pdf:
            for pagina in pdf.pages:
                texto = pagina.extract_text()
                if not texto: continue

                dados_ia = extrair_dados_ia_com_retry(texto, model)

                for d in dados_ia:
                    nova_dt = formatar_data_universal(d.get('data', ''))
                    if nova_dt: data_corrente = nova_dt
                    
                    if not data_corrente: continue

                    nome = str(d.get('nome', '')).strip().upper()
                    if any(t in nome for t in termos_lixo) or len(nome) < 4:
                        continue

                    processo = re.sub(r'\D', '', str(d.get('processo', '')))
                    proc = str(d.get('procedimento', '')).strip().upper()

                    # Escrita na Coluna C (Data, Processo, Nome, Procedimento, Data Exec, Nome PDF)
                    novas_linhas.append([
                        data_corrente, # C
                        processo,      # D
                        nome,          # E
                        proc,          # F
                        data_hoje,     # G
                        pdf_file.name  # H
                    ])
        
        progresso.progress((idx + 1) / len(arquivos_pdf))

    status.empty()

    if novas_linhas:
        try:
            proxima_linha = len(dados_atuais) + 1
            worksheet.update(
                range_name=f"C{proxima_linha}", 
                values=novas_linhas,
                value_input_option="USER_ENTERED"
            )
            st.balloons()
            st.success(f"✅ {len(novas_linhas)} linhas gravadas com sucesso!")
            st.dataframe(novas_linhas)
        except Exception as e:
            st.error(f"❌ Erro ao gravar: {e}")
    else:
        st.warning("Nada extraído dos ficheiros.")
