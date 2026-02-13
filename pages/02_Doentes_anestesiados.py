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
st.set_page_config(page_title="Doentes Anestesiados", page_icon="💉", layout="wide")

# Lemos a TUA chave mestra e o link do cliente (vindo da Home)
master_api_key = st.secrets.get("GEMINI_API_KEY")
sheet_url = st.session_state.get('sheet_url')

if not master_api_key:
    st.error("❌ Erro Crítico: GEMINI_API_KEY não encontrada nos Secrets.")
    st.stop()

if not sheet_url:
    st.warning("⚠️ Configuração em falta! Por favor, insira o link da sua planilha na página **Home (🏠)**.")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data(data_str):
    data_str = str(data_str).strip()
    if not data_str or "DD-MM-YYYY" in data_str.upper() or data_str.lower() == "none":
        return None
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', data_str)
    if match:
        return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    match_pt = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', data_str)
    if match_pt:
        d, m, a = match_pt.groups()
        if len(a) == 2: a = "20" + a
        return f"{d.zfill(2)}-{m.zfill(2)}-{a}"
    return None

def extrair_dados_ia_com_espera(texto_pagina, model, max_tentativas=3):
    prompt = """
    Analisa o texto médico CUF.
    REGRAS:
    1. DATA: Formato DD-MM-YYYY.
    2. NOME: Nome completo MAIÚSCULAS.
    3. PROCESSO: Apenas números.
    4. PROCEDIMENTO: Apenas a primeira linha do ato principal.
    JSON: [{"data": "DD-MM-YYYY", "processo": "123", "nome": "NOME", "procedimento": "PROC"}]
    """
    for i in range(max_tentativas):
        try:
            response = model.generate_content(
                f"{prompt}\n\nTEXTO:\n{texto_pagina}",
                generation_config={"temperature": 0.0}
            )
            match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
            return json.loads(match.group()) if match else []
        except Exception as e:
            if "429" in str(e):
                time.sleep((i + 1) * 2) # Tempo reduzido pois Tier 1 tem RPM maior
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
    
    NOME_FOLHA = 'Anestesiados'
    try:
        worksheet = sh.worksheet(NOME_FOLHA)
    except:
        worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="1000", cols="10")
        # Cabeçalho na Coluna C (para ignorar A e B)
        worksheet.update(range_name="C1", values=[["Data", "Processo", "Nome Completo", "Procedimento", "Data Execução", "Ficheiro"]])

except Exception as e:
    st.error(f"❌ Erro de Conexão: {e}")
    st.stop()

# --- 4. INTERFACE ---
st.title("💉 Doentes Anestesiados (Escrita na Coluna C)")
st.info("Utilizando motor Gemini Tier 1. A escrita preserva as fórmulas nas Colunas A e B.")

arquivos_pdf = st.file_uploader("Carregue os PDFs de Anestesia", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Iniciar Processamento"):
    
    st.info("A verificar registos existentes para evitar duplicados...")
    dados_atuais = worksheet.get_all_values()
    registos_existentes = set()
    
    # Verificação de duplicados (Coluna C=2, D=3, E=4 no índice do Python)
    if len(dados_atuais) > 1:
        for r in dados_atuais[1:]:
            if len(r) >= 5: 
                chave = f"{r[2]}_{r[3]}_{r[4]}" 
                registos_existentes.add(chave)

    novas_linhas = []
    data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
    progresso = st.progress(0)
    
    for idx, pdf_file in enumerate(arquivos_pdf):
        ultima_data_valida = ""
        with pdfplumber.open(pdf_file) as pdf:
            for i, pagina in enumerate(pdf.pages):
                texto = pagina.extract_text()
                if not texto: continue
                dados_ia = extrair_dados_ia_com_espera(texto, model)

                for d in dados_ia:
                    dt = formatar_data(d.get('data', ''))
                    if dt: ultima_data_valida = dt
                    else: dt = ultima_data_valida

                    processo = re.sub(r'\D', '', str(d.get('processo', '')))
                    nome = str(d.get('nome', '')).replace('\n', ' ').strip().upper()
                    proc_limpo = str(d.get('procedimento', '')).split('\n')[0].split(',')[0].strip()
                    
                    termos_lixo = ["PROENÇA", "UTILIZADOR", "PÁGINA", "GHCE", "LISTAGEM"]
                    e_lixo = any(t in nome for t in termos_lixo)

                    if len(nome) > 3 and dt and not e_lixo:
                        chave_unica = f"{dt}_{processo}_{nome}"
                        
                        if chave_unica not in registos_existentes:
                            # Lista inicia logo na Data (será mapeada para C)
                            novas_linhas.append([
                                dt,          
                                processo,    
                                nome,        
                                proc_limpo,  
                                data_hoje,   
                                pdf_file.name 
                            ])
                            registos_existentes.add(chave_unica)
        
        progresso.progress((idx + 1) / len(arquivos_pdf))

    if novas_linhas:
        try:
            proxima_linha = len(dados_atuais) + 1
            # ESCRITA FORÇADA NA COLUNA C
            worksheet.update(
                range_name=f"C{proxima_linha}", 
                values=novas_linhas
            )
            st.success(f"✅ {len(novas_linhas)} registos gravados diretamente na Coluna C.")
            st.dataframe(novas_linhas)
        except Exception as e:
            st.error(f"❌ Erro ao gravar dados: {e}")
    else:
        st.warning("Nenhum registo novo (não duplicado) encontrado.")
