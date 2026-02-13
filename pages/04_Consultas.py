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
st.set_page_config(page_title="Extração de Consultas", page_icon="👨‍⚕️", layout="wide")

# Lemos a TUA chave mestra e o link do cliente (vindo da Home)
master_api_key = st.secrets.get("GEMINI_API_KEY")
sheet_url = st.session_state.get('sheet_url')

if not master_api_key or not sheet_url:
    st.warning("⚠️ Configuração em falta! Por favor, configure o Link na página **Home (🏠)**.")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data_universal(data_str):
    if not data_str: return None
    s = str(data_str).strip()
    # Tenta ISO (YYYY-MM-DD)
    match_iso = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if match_iso:
        return f"{match_iso.group(3)}-{match_iso.group(2)}-{match_iso.group(1)}"
    # Tenta PT (DD-MM-YYYY)
    match_pt = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', s)
    if match_pt:
        d, m, a = match_pt.groups()
        if len(a) == 2: a = "20" + a
        return f"{d.zfill(2)}-{m.zfill(2)}-{a}"
    return None

def extrair_dados_com_espera(texto_pagina, model, max_tentativas=3):
    prompt = """
    Atua como um extrator de listagens de CONSULTAS médicas CUF.
    Extrai apenas linhas que contenham DATA, PROCESSO e NOME do doente.
    Responde rigorosamente em JSON:
    [{"data": "DD-MM-YYYY", "processo": "123", "nome": "NOME COMPLETO"}]
    """
    for tentativa in range(max_tentativas):
        try:
            # Uso da Master Key para alto desempenho
            response = model.generate_content(prompt + "\n\nTEXTO:\n" + texto_pagina, 
                                            generation_config={"temperature": 0.0})
            match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
            return json.loads(match.group()) if match else []
        except Exception as e:
            if "429" in str(e):
                # Com Tier 1, o tempo de espera pode ser menor
                time.sleep((tentativa + 1) * 3)
            else:
                return []
    return []

# --- 3. LIGAÇÃO ÀS APIS ---
try:
    genai.configure(api_key=master_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    
    NOME_FOLHA = 'Consulta'
    try:
        worksheet = sh.worksheet(NOME_FOLHA)
    except:
        worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="5000", cols="10")
        # Cabeçalho inicia logo na Coluna C
        worksheet.update(range_name="C1", values=[["Data", "Processo (HCIS)", "Nome Completo", "Data Execução"]])
except Exception as e:
    st.error(f"❌ Erro de Conexão: {e}")
    st.stop()

# --- 4. INTERFACE E PROCESSAMENTO ---
st.title("👨‍⚕️ Processador de Consultas (Pro)")
st.info("Utilizando motor Gemini Professional. Escrita automática a partir da Coluna C.")

arquivos_pdf = st.file_uploader("Carregue os PDFs de Consultas", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Iniciar Processamento"):
    novas_linhas = []
    data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
    termos_lixo = ["PROENÇA", "UTILIZADOR", "PÁGINA", "GHCE"]

    progresso = st.progress(0)
    status_text = st.empty()

    # Obter dados atuais para mapear a próxima linha livre
    dados_atuais = worksheet.get_all_values()

    for idx, pdf_file in enumerate(arquivos_pdf):
        status_text.text(f"📖 A ler: {pdf_file.name}")
        
        with pdfplumber.open(pdf_file) as pdf:
            for i, pagina in enumerate(pdf.pages):
                texto = pagina.extract_text()
                if not texto: continue

                dados_ia = extrair_dados_com_espera(texto, model)

                for d in dados_ia:
                    dt = formatar_data_universal(d.get('data', ''))
                    proc = re.sub(r'\D', '', str(d.get('processo', '')))
                    nome = str(d.get('nome', '')).strip().upper()

                    if dt and proc and len(nome) > 3:
                        if not any(t in nome for t in termos_lixo):
                            # Inicia direto no conteúdo para Coluna C
                            novas_linhas.append([
                                dt,        # Coluna C
                                proc,      # Coluna D
                                nome,      # Coluna E
                                data_hoje  # Coluna F
                            ])
        
        progresso.progress((idx + 1) / len(arquivos_pdf))

    status_text.empty()

    if novas_linhas:
        try:
            proxima_linha = len(dados_atuais) + 1
            # Escrita direta na Coluna C para proteger fórmulas em A e B
            worksheet.update(
                range_name=f"C{proxima_linha}", 
                values=novas_linhas
            )
            st.balloons()
            st.success(f"✅ {len(novas_linhas)} consultas enviadas com sucesso!")
            st.dataframe(novas_linhas)
        except Exception as e:
            st.error(f"Erro ao gravar no Google Sheets: {e}")
    else:
        st.warning("Nenhum dado válido extraído. Verifique se o PDF é digital.")
