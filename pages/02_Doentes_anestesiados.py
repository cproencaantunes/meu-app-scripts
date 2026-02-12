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

user_api_key = st.session_state.get('user_api_key')
sheet_url = st.session_state.get('sheet_url')

if not user_api_key or not sheet_url:
    st.warning("⚠️ Configuração em falta! Vá à página **Home (🏠)** e configure as chaves.")
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
    Analisa o texto médico.
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
                time.sleep((i + 1) * 5)
            else:
                return []
    return []

# --- 3. CONEXÃO ---
try:
    genai.configure(api_key=user_api_key)
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
        # Cria cabeçalho começando na Coluna C (A e B vazias)
        worksheet.append_row(["", "", "Data", "Processo", "Nome Completo", "Procedimento", "Data Execução", "Ficheiro"])

except Exception as e:
    st.error(f"❌ Erro de Conexão: {e}")
    st.stop()

# --- 4. INTERFACE ---
st.title("💉 Doentes Anestesiados (Coluna C)")

arquivos_pdf = st.file_uploader("Carregue os PDFs", type=['pdf'], accept_multiple_files=True)

if arquivos_pdf and st.button("🚀 Iniciar Processamento"):
    
    # 1. Leitura de Duplicados (Ajustada para Coluna C)
    st.info("A verificar registos existentes...")
    dados_atuais = worksheet.get_all_values()
    registos_existentes = set()
    
    if len(dados_atuais) > 1:
        for r in dados_atuais[1:]:
            # Agora os dados estão nos índices 2, 3, 4 (Colunas C, D, E)
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
                # if i == 0: continue # Descomente se quiser pular a 1ª página
                
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
                            # AQUI ESTÁ A MUDANÇA: Duas strings vazias no início
                            novas_linhas.append([
                                "",          # Coluna A (Vazia)
                                "",          # Coluna B (Vazia)
                                dt,          # Coluna C
                                processo,    # Coluna D
                                nome,        # Coluna E
                                proc_limpo,  # Coluna F
                                data_hoje,   # Coluna G
                                pdf_file.name # Coluna H
                            ])
                            registos_existentes.add(chave_unica)
        
        progresso.progress((idx + 1) / len(arquivos_pdf))

    if novas_linhas:
        worksheet.append_rows(novas_linhas)
        st.success(f"✅ {len(novas_linhas)} registos gravados a partir da Coluna C.")
        st.dataframe(novas_linhas)
    else:
        st.warning("Nenhum registo novo encontrado.")
