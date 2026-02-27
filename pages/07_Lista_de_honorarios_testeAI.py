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
st.set_page_config(page_title="Lista de Honorários", page_icon="💰", layout="wide")

master_api_key = st.secrets.get("GEMINI_API_KEY")
sheet_url = st.session_state.get('sheet_url')

if not master_api_key:
    st.error("❌ Erro Crítico: GEMINI_API_KEY não configurada nos Secrets.")
    st.stop()

if not sheet_url:
    st.warning("⚠️ Configuração em falta! Por favor, insira o link da sua planilha na página Home (🏠).")
    st.stop()

# --- 2. FUNÇÕES DE SUPORTE ---

def extrair_id_planilha(url):
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else url

def formatar_data(data_str):
    data_str = str(data_str).strip()
    if not data_str or "DD-MM-YYYY" in data_str.upper():
        return None
    match = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', data_str)
    if match:
        d, m, a = match.groups()
        if len(a) == 2: a = "20" + a
        return f"{d.zfill(2)}-{m.zfill(2)}-{a}"
    return None

def extrair_dados_ia(texto_pagina, model):
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

def reparar_json_truncado(raw):
    """
    Tenta reparar JSON truncado/mal formado de várias formas.
    Devolve o objeto Python ou None.
    """
    # 1. Tentativa directa
    try:
        return json.loads(raw)
    except:
        pass

    # 2. Extrai bloco entre primeira { e última }
    try:
        start = raw.index('{')
        end = raw.rindex('}')
        return json.loads(raw[start:end+1])
    except:
        pass

    # 3. Tenta extrair só a lista de registos (ignora total_esperado)
    try:
        match = re.search(r'"todos_os_registos"\s*:\s*(\[.*?\])\s*[,}]', raw, re.DOTALL)
        if match:
            lista = json.loads(match.group(1))
            return {"total_esperado": len(lista), "todos_os_registos": lista}
    except:
        pass

    # 4. Extrai registos individuais com regex mesmo com JSON partido
    try:
        registos = []
        for m in re.finditer(
            r'\{\s*"data"\s*:\s*"([^"]*?)"\s*,\s*"id"\s*:\s*"([^"]*?)"\s*,\s*"nome"\s*:\s*"([^"]*?)"\s*,\s*"valor"\s*:\s*([\d.]+)',
            raw
        ):
            registos.append({
                "data": m.group(1),
                "id": m.group(2),
                "nome": m.group(3),
                "valor": float(m.group(4))
            })
        if registos:
            return {"total_esperado": len(registos), "todos_os_registos": registos}
    except:
        pass

    return None


def verificar_chunk(texto_chunk, model):
    """Verifica um chunk de texto e devolve lista de registos encontrados."""
    prompt = """Analisa este excerto de um PDF de honorários CUF.
Lista TODOS os registos de honorários que encontrares (data, ID utente, nome, valor).
Responde APENAS com uma lista JSON, sem texto adicional, sem markdown:
[{"data":"DD-MM-YYYY","id":"ID","nome":"NOME","valor":0.00}]
Se não houver registos, responde com: []"""
    try:
        response = model.generate_content(
            f"{prompt}\n\nTEXTO:\n{texto_chunk}",
            generation_config={"temperature": 0.0, "max_output_tokens": 8192}
        )
        raw = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return []
    except:
        return []


def contar_registos_esperados_ia(texto_completo_pdf, model):
    """
    Estratégia em 2 passos:
    1. Divide o texto em chunks manejáveis e pede à IA para listar registos de cada chunk.
    2. Agrega tudo, deduplica por ID e devolve o total esperado.
    """
    CHUNK_SIZE = 12000  # caracteres por chunk — seguro para o contexto do modelo
    chunks = []
    texto = texto_completo_pdf.strip()
    for i in range(0, len(texto), CHUNK_SIZE):
        chunk = texto[i:i+CHUNK_SIZE]
        if chunk.strip():
            chunks.append(chunk)

    todos_registos_raw = []
    erros_chunks = 0

    for chunk in chunks:
        resultado = verificar_chunk(chunk, model)
        if isinstance(resultado, list):
            todos_registos_raw.extend(resultado)
        else:
            erros_chunks += 1

    if not todos_registos_raw and erros_chunks == len(chunks):
        return None, [], "IA não conseguiu processar nenhum chunk do texto."

    # Deduplica por ID (mantém o primeiro encontrado)
    vistos = set()
    todos_registos = []
    termos_ignorar = ["PROENÇA ANTUNES", "UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO", "FIM DA LISTAGEM"]
    for r in todos_registos_raw:
        id_limpo = re.sub(r'\D', '', str(r.get('id', '')))
        nome_raw = str(r.get('nome', '')).strip().upper()
        e_lixo = any(t in nome_raw for t in termos_ignorar)
        if id_limpo and not e_lixo and len(nome_raw) > 3 and id_limpo not in vistos:
            vistos.add(id_limpo)
            r['id'] = id_limpo
            todos_registos.append(r)

    total_esperado = len(todos_registos)
    return total_esperado, todos_registos, None

def encontrar_em_falta(extraidos, todos_esperados):
    """
    Compara os registos extraídos com os esperados pela IA de verificação.
    Retorna lista de registos em falta (presentes nos esperados mas não nos extraídos).
    """
    ids_extraidos = set(re.sub(r'\D', '', str(r[1])) for r in extraidos if r[1])
    em_falta = []
    for r in todos_esperados:
        id_esperado = re.sub(r'\D', '', str(r.get('id', '')))
        if id_esperado and id_esperado not in ids_extraidos:
            em_falta.append(r)
    return em_falta


# --- 3. CONEXÃO ---
try:
    genai.configure(api_key=master_api_key)
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(extrair_id_planilha(sheet_url))
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Erro de Conexão: {e}")
    st.stop()

# --- 4. INTERFACE ---
st.title("💰 Processador de Honorários")
st.info("O sistema escreve a partir da Coluna B, preservando fórmulas na Coluna A.")

arquivos_pdf = st.file_uploader("Carregue os PDFs de Honorários", type=['pdf'], accept_multiple_files=True)

# Guardamos o estado do processamento na sessão
if "resultado_processamento" not in st.session_state:
    st.session_state.resultado_processamento = None

if arquivos_pdf and st.button("🚀 Iniciar Processamento e Verificação"):
    todas_as_linhas_final = []
    texto_completo_todos_pdfs = ""
    data_exec = datetime.now().strftime("%d-%m-%Y %H:%M")
    termos_ignorar = ["PROENÇA ANTUNES", "UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO", "FIM DA LISTAGEM"]

    progresso = st.progress(0)
    status_info = st.empty()

    # ----- FASE 1: EXTRAÇÃO -----
    status_info.info("📖 Fase 1/2 — A extrair dados dos PDFs...")

    for idx, pdf_file in enumerate(arquivos_pdf):
        status_info.info(f"📖 A ler: {pdf_file.name} ({idx+1}/{len(arquivos_pdf)})")
        ultima_data_valida = ""
        texto_pdf_atual = ""

        with pdfplumber.open(pdf_file) as pdf:
            for i, pagina in enumerate(pdf.pages):
                if i == 0:
                    continue

                texto = pagina.extract_text(layout=True)
                if not texto:
                    continue

                texto_pdf_atual += f"\n--- Página {i+1} ---\n{texto}"
                dados_ia = extrair_dados_ia(texto, model)

                for d in dados_ia:
                    dt = formatar_data(d.get('data', ''))
                    if dt:
                        ultima_data_valida = dt
                    else:
                        dt = ultima_data_valida

                    id_limpo = re.sub(r'\D', '', str(d.get('id', '')))
                    nome_raw = str(d.get('nome', '')).strip().upper()
                    e_lixo = any(termo in nome_raw for termo in termos_ignorar)

                    if id_limpo and not e_lixo and len(nome_raw) > 3:
                        todas_as_linhas_final.append([
                            dt,
                            id_limpo,
                            nome_raw,
                            d.get('valor', 0.0),
                            data_exec,
                            pdf_file.name
                        ])

        texto_completo_todos_pdfs += f"\n\n=== FICHEIRO: {pdf_file.name} ===\n{texto_pdf_atual}"
        progresso.progress((idx + 1) / len(arquivos_pdf))

    # ----- FASE 2: VERIFICAÇÃO COM IA (por chunks) -----
    CHUNK_SIZE = 12000
    n_chunks = max(1, len(texto_completo_todos_pdfs) // CHUNK_SIZE + 1)
    status_info.info(f"🔍 Fase 2/2 — A verificar com IA ({n_chunks} blocos de texto)...")
    progresso.progress(0)

    total_esperado, todos_esperados, erro_verificacao = contar_registos_esperados_ia(
        texto_completo_todos_pdfs, model
    )
    total_extraido = len(todas_as_linhas_final)

    em_falta = []
    if todos_esperados:
        em_falta = encontrar_em_falta(todas_as_linhas_final, todos_esperados)

    progresso.progress(1.0)
    status_info.empty()

    # Guardamos tudo na sessão
    st.session_state.resultado_processamento = {
        "linhas": todas_as_linhas_final,
        "total_extraido": total_extraido,
        "total_esperado": total_esperado,
        "em_falta": em_falta,
        "erro_verificacao": erro_verificacao,
        "dados_atuais_len": len(worksheet.get_all_values()),
    }

# ----- EXIBIÇÃO DO RELATÓRIO DE VERIFICAÇÃO -----
res = st.session_state.resultado_processamento

if res:
    total_extraido = res["total_extraido"]
    total_esperado = res["total_esperado"]
    em_falta = res["em_falta"]
    erro_verificacao = res["erro_verificacao"]
    todas_as_linhas_final = res["linhas"]

    st.markdown("---")
    st.subheader("📋 Relatório de Verificação")

    if erro_verificacao:
        st.warning(f"⚠️ Não foi possível completar a verificação automática: {erro_verificacao}")
        st.info(f"Total de registos extraídos: **{total_extraido}**")
        exportar_disponivel = True  # Permitimos exportar mesmo sem verificação
        aviso_verificacao = True
    elif total_esperado is None:
        st.warning("⚠️ A IA de verificação não conseguiu determinar o total esperado.")
        exportar_disponivel = True
        aviso_verificacao = True
    else:
        coincide = (total_extraido == total_esperado) and (len(em_falta) == 0)

        if coincide:
            st.success(
                f"✅ **Verificação aprovada!** "
                f"Foram extraídos **{total_extraido}** de **{total_esperado}** registos. "
                f"Todos os dados foram processados corretamente."
            )
            exportar_disponivel = True
            aviso_verificacao = False
        else:
            st.error(
                f"❌ **Atenção: discrepância detetada!** "
                f"Foram extraídos **{total_extraido}** de **{total_esperado}** registos esperados."
            )
            exportar_disponivel = False
            aviso_verificacao = True

            if em_falta:
                st.markdown(f"#### 🔍 Registos em falta ({len(em_falta)}):")
                cols = st.columns([1.5, 2, 4, 1.5])
                cols[0].markdown("**Data**")
                cols[1].markdown("**ID Utente**")
                cols[2].markdown("**Nome**")
                cols[3].markdown("**Valor**")
                st.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
                for r in em_falta:
                    cols = st.columns([1.5, 2, 4, 1.5])
                    cols[0].write(r.get("data", "—"))
                    cols[1].write(r.get("id", "—"))
                    cols[2].write(str(r.get("nome", "—")).upper())
                    cols[3].write(f"{r.get('valor', 0.0):.2f} €")

            st.markdown("---")
            st.markdown(
                "Pode exportar mesmo assim, mas os dados podem estar incompletos. "
                "Reveja os registos em falta antes de continuar."
            )

    # ----- PRÉ-VISUALIZAÇÃO DOS DADOS EXTRAÍDOS -----
    if todas_as_linhas_final:
        with st.expander(f"👁️ Pré-visualizar {total_extraido} registos extraídos"):
            import pandas as pd
            df = pd.DataFrame(
                todas_as_linhas_final,
                columns=["Data", "ID Utente", "Nome", "Valor (€)", "Data Execução", "Ficheiro"]
            )
            st.dataframe(df, use_container_width=True)

    # ----- BOTÕES DE EXPORTAÇÃO -----
    st.markdown("---")
    col1, col2 = st.columns([1, 3])

    with col1:
        if exportar_disponivel:
            exportar = st.button("✅ Exportar para Google Sheets", type="primary")
        else:
            exportar_mesmo_assim = st.button(
                "⚠️ Exportar mesmo assim",
                help="Os dados podem estar incompletos. Use apenas se tiver a certeza.",
                type="secondary"
            )
            exportar = exportar_mesmo_assim if "exportar_mesmo_assim" in dir() else False

    with col2:
        if not exportar_disponivel:
            st.warning("🔒 O botão de exportação normal está bloqueado devido à discrepância. Pode usar 'Exportar mesmo assim' sob sua responsabilidade.")

    # ----- EXECUÇÃO DA EXPORTAÇÃO -----
    exportar_flag = False
    if exportar_disponivel and "exportar" in dir() and exportar:
        exportar_flag = True
    elif not exportar_disponivel and "exportar_mesmo_assim" in dir() and exportar_mesmo_assim:
        exportar_flag = True

    if exportar_flag:
        if not todas_as_linhas_final:
            st.warning("⚠️ Nenhum dado válido para exportar.")
        else:
            try:
                proxima_linha = res["dados_atuais_len"] + 1
                worksheet.update(
                    range_name=f"B{proxima_linha}",
                    values=todas_as_linhas_final
                )
                st.success(f"✅ {len(todas_as_linhas_final)} linhas gravadas com sucesso na Coluna B!")
                # Limpa o estado após exportação bem-sucedida
                st.session_state.resultado_processamento = None
                st.balloons()
            except Exception as e:
                st.error(f"❌ Erro ao gravar na planilha: {e}")
