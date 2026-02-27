import streamlit as st
import google.generativeai as genai
import gspread
import json
import re
import io
import pdfplumber
from collections import Counter
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
    """Extração principal — usada na Fase 1."""
    prompt = 'Extraia dados deste PDF CUF para este JSON: [{"data":"DD-MM-YYYY","id":"ID","nome":"NOME","valor":0.00}]'
    try:
        response = model.generate_content(
            f"{prompt}\n\nTEXTO:\n{texto_pagina}",
            generation_config={"temperature": 0.0}
        )
        match = re.search(r'\[\s*\{.*\}\s*\]', response.text, re.DOTALL)
        return json.loads(match.group()) if match else []
    except:
        return []


# ── VERIFICAÇÃO: lê o total DECLARADO no próprio PDF ─────────────────────────

def _extrair_texto_extremos(pdf_bytes_list):
    texto = ""
    for nome, conteudo in pdf_bytes_list:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            indices = sorted(set([0, len(pdf.pages) - 1]))
            for i in indices:
                t = pdf.pages[i].extract_text() or ""
                texto += f"\n[{nome} — pág. {i+1}]\n{t}\n"
    return texto

def _regex_total(texto):
    padroes = [
        r'n[oº°]\.?\s*(?:de\s+)?registos\s*[:\-]\s*(\d+)',
        r'total\s+(?:de\s+)?registos\s*[:\-]\s*(\d+)',
        r'total\s+(?:de\s+)?linhas\s*[:\-]\s*(\d+)',
        r'total\s*[:\-]\s*(\d+)\s*registos',
        r'\b(\d{2,4})\s+registos\b',
        r'\blinhas\s*[:\-]\s*(\d+)',
        r'\bcount\s*[:\-]\s*(\d+)',
    ]
    candidatos = []
    for padrao in padroes:
        for m in re.finditer(padrao, texto.lower()):
            val = int(m.group(1))
            if 1 < val < 100000:
                candidatos.append(val)
    return Counter(candidatos).most_common(1)[0][0] if candidatos else None

def _ia_total(texto_extremos, model):
    prompt = (
        "Lê este texto de PDFs de honorários CUF (primeiras e últimas páginas).\n"
        "Encontra o número TOTAL DE REGISTOS declarado ('Total', 'Nº Registos', 'Nº de linhas', etc.).\n"
        "Responde APENAS com o número inteiro. Se não encontrares, responde: null"
    )
    try:
        response = model.generate_content(
            f"{prompt}\n\nTEXTO:\n{texto_extremos}",
            generation_config={"temperature": 0.0, "max_output_tokens": 20}
        )
        raw = response.text.strip()
        if "null" in raw.lower():
            return None
        numeros = re.findall(r'\d+', raw)
        return int(numeros[0]) if numeros else None
    except:
        return None

def obter_total_esperado(pdf_bytes_list, model):
    texto_extremos = _extrair_texto_extremos(pdf_bytes_list)
    total = _regex_total(texto_extremos)
    if total:
        return total, "rodapé/cabeçalho do PDF (detecção automática)"
    total = _ia_total(texto_extremos, model)
    if total:
        return total, "rodapé/cabeçalho do PDF (leitura por IA)"
    return None, None


# ── FASE 3: CAÇA AOS REGISTOS EM FALTA ──────────────────────────────────────

TERMOS_IGNORAR = ["PROENÇA ANTUNES", "UTILIZADOR", "PÁGINA", "LISTAGEM", "RELATÓRIO", "FIM DA LISTAGEM"]

def extrair_todos_ids_do_pdf(pdf_bytes_list, model, status_placeholder, progresso_placeholder):
    """
    Relê TODAS as páginas de todos os PDFs e extrai todos os registos,
    usando uma abordagem mais agressiva (sem pular a página 0).
    Devolve dict {id: {data, id, nome, valor, pagina, ficheiro}}.
    """
    todos = {}
    total_paginas = sum(
        len(pdfplumber.open(io.BytesIO(c)).pages) for _, c in pdf_bytes_list
    )
    pagina_atual = 0

    for nome_ficheiro, conteudo in pdf_bytes_list:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            ultima_data = ""
            for i, pagina in enumerate(pdf.pages):
                pagina_atual += 1
                progresso_placeholder.progress(pagina_atual / total_paginas)
                status_placeholder.info(f"🔎 A re-analisar: {nome_ficheiro} — pág. {i+1}/{len(pdf.pages)}")

                texto = pagina.extract_text(layout=True)
                if not texto:
                    continue

                dados = extrair_dados_ia(texto, model)
                for d in dados:
                    dt = formatar_data(d.get('data', ''))
                    if dt:
                        ultima_data = dt
                    else:
                        dt = ultima_data

                    id_limpo = re.sub(r'\D', '', str(d.get('id', '')))
                    nome_raw = str(d.get('nome', '')).strip().upper()
                    e_lixo = any(t in nome_raw for t in TERMOS_IGNORAR)

                    if id_limpo and not e_lixo and len(nome_raw) > 3:
                        if id_limpo not in todos:   # primeiro encontrado ganha
                            todos[id_limpo] = {
                                "data": dt,
                                "id": id_limpo,
                                "nome": nome_raw,
                                "valor": d.get('valor', 0.0),
                                "pagina": i + 1,
                                "ficheiro": nome_ficheiro,
                            }
    return todos

def encontrar_em_falta(ids_extraidos_set, todos_do_pdf):
    """
    Compara o set de IDs já extraídos com o universo completo do PDF.
    Devolve lista de registos presentes no PDF mas ausentes na extração principal.
    """
    return [
        r for id_key, r in todos_do_pdf.items()
        if id_key not in ids_extraidos_set
    ]


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

if "resultado_processamento" not in st.session_state:
    st.session_state.resultado_processamento = None
if "pdf_bytes_cache" not in st.session_state:
    st.session_state.pdf_bytes_cache = None
if "registos_em_falta" not in st.session_state:
    st.session_state.registos_em_falta = None
if "investigacao_feita" not in st.session_state:
    st.session_state.investigacao_feita = False

if arquivos_pdf and st.button("🚀 Iniciar Processamento e Verificação"):
    # Reset investigação anterior
    st.session_state.registos_em_falta = None
    st.session_state.investigacao_feita = False

    todas_as_linhas_final = []
    pdf_bytes_list = []
    data_exec = datetime.now().strftime("%d-%m-%Y %H:%M")

    progresso = st.progress(0)
    status_info = st.empty()

    # ── FASE 1: EXTRAÇÃO ─────────────────────────────────────────────────────
    for idx, pdf_file in enumerate(arquivos_pdf):
        status_info.info(f"📖 Fase 1/2 — A ler: {pdf_file.name} ({idx+1}/{len(arquivos_pdf)})")
        ultima_data_valida = ""

        conteudo_bytes = pdf_file.read()
        pdf_bytes_list.append((pdf_file.name, conteudo_bytes))

        with pdfplumber.open(io.BytesIO(conteudo_bytes)) as pdf:
            for i, pagina in enumerate(pdf.pages):
                if i == 0:
                    continue
                texto = pagina.extract_text(layout=True)
                if not texto:
                    continue
                dados_ia = extrair_dados_ia(texto, model)
                for d in dados_ia:
                    dt = formatar_data(d.get('data', ''))
                    if dt:
                        ultima_data_valida = dt
                    else:
                        dt = ultima_data_valida
                    id_limpo = re.sub(r'\D', '', str(d.get('id', '')))
                    nome_raw = str(d.get('nome', '')).strip().upper()
                    e_lixo = any(t in nome_raw for t in TERMOS_IGNORAR)
                    if id_limpo and not e_lixo and len(nome_raw) > 3:
                        todas_as_linhas_final.append([
                            dt, id_limpo, nome_raw,
                            d.get('valor', 0.0), data_exec, pdf_file.name
                        ])

        progresso.progress((idx + 1) / len(arquivos_pdf))

    total_extraido = len(todas_as_linhas_final)

    # ── FASE 2: VERIFICAÇÃO ──────────────────────────────────────────────────
    status_info.info("🔍 Fase 2/2 — A ler total declarado no PDF...")
    progresso.progress(0)
    total_esperado, metodo_verificacao = obter_total_esperado(pdf_bytes_list, model)
    progresso.progress(1.0)
    status_info.empty()

    # Guarda tudo em sessão (incluindo bytes dos PDFs para eventual Fase 3)
    st.session_state.pdf_bytes_cache = pdf_bytes_list
    st.session_state.resultado_processamento = {
        "linhas": todas_as_linhas_final,
        "total_extraido": total_extraido,
        "total_esperado": total_esperado,
        "metodo_verificacao": metodo_verificacao,
        "dados_atuais_len": len(worksheet.get_all_values()),
    }

# ── RELATÓRIO ────────────────────────────────────────────────────────────────
res = st.session_state.resultado_processamento

if res:
    total_extraido        = res["total_extraido"]
    total_esperado        = res["total_esperado"]
    metodo                = res["metodo_verificacao"]
    todas_as_linhas_final = res["linhas"]
    ids_extraidos         = set(re.sub(r'\D', '', str(r[1])) for r in todas_as_linhas_final)

    st.markdown("---")
    st.subheader("📋 Relatório de Verificação")

    if total_esperado is None:
        st.warning(
            f"⚠️ Não foi possível encontrar um total declarado no PDF. "
            f"Foram extraídos **{total_extraido}** registos. "
            "A exportação está disponível mas não foi possível validar automaticamente."
        )
        exportar_disponivel = True
        ha_discrepancia = False

    elif total_extraido == total_esperado:
        st.success(
            f"✅ **Verificação aprovada!** "
            f"Extraídos **{total_extraido}** de **{total_esperado}** registos ({metodo})."
        )
        exportar_disponivel = True
        ha_discrepancia = False

    else:
        diferenca = total_extraido - total_esperado
        sinal = "a mais" if diferenca > 0 else "a menos"
        st.error(
            f"❌ **Discrepância detetada!** "
            f"Extraídos: **{total_extraido}** | Declarados: **{total_esperado}** ({metodo}). "
            f"Diferença: **{abs(diferenca)} registo(s) {sinal}**."
        )
        if diferenca > 0:
            st.info("💡 Mais registos do que o declarado — possíveis duplicados. Verifique a pré-visualização.")
        else:
            st.info("💡 Menos registos do que o declarado — possível OCR incompleto em algumas páginas.")

        exportar_disponivel = False
        ha_discrepancia = True

    # ── INVESTIGAÇÃO DE REGISTOS EM FALTA ────────────────────────────────────
    if ha_discrepancia and total_extraido < total_esperado:
        st.markdown("---")

        if not st.session_state.investigacao_feita:
            if st.button("🔎 Investigar registos em falta", type="primary"):
                prog_inv = st.progress(0)
                status_inv = st.empty()

                todos_do_pdf = extrair_todos_ids_do_pdf(
                    st.session_state.pdf_bytes_cache,
                    model,
                    status_inv,
                    prog_inv
                )
                em_falta = encontrar_em_falta(ids_extraidos, todos_do_pdf)

                prog_inv.progress(1.0)
                status_inv.empty()

                st.session_state.registos_em_falta = em_falta
                st.session_state.investigacao_feita = True
                st.rerun()

        if st.session_state.investigacao_feita:
            em_falta = st.session_state.registos_em_falta

            if not em_falta:
                st.warning(
                    "⚠️ A re-análise completa do PDF não encontrou registos adicionais. "
                    "A diferença pode dever-se a registos com formatação que a IA não conseguiu interpretar, "
                    "ou ao total declarado no PDF incluir linhas de cabeçalho/rodapé."
                )
            else:
                st.error(f"🔍 Foram encontrados **{len(em_falta)} registo(s) em falta**:")

                import pandas as pd
                df_falta = pd.DataFrame(em_falta)
                df_falta = df_falta.rename(columns={
                    "data": "Data", "id": "ID Utente", "nome": "Nome",
                    "valor": "Valor (€)", "pagina": "Página", "ficheiro": "Ficheiro"
                })
                st.dataframe(df_falta, use_container_width=True)

                # Opção de adicionar os registos em falta à extração
                st.markdown("**O que deseja fazer com os registos em falta?**")
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("➕ Adicionar à lista e exportar tudo", type="primary"):
                        data_exec = datetime.now().strftime("%d-%m-%Y %H:%M")
                        for r in em_falta:
                            todas_as_linhas_final.append([
                                r["data"], r["id"], r["nome"],
                                r["valor"], data_exec, r["ficheiro"]
                            ])
                        res["linhas"] = todas_as_linhas_final
                        res["total_extraido"] = len(todas_as_linhas_final)
                        st.session_state.resultado_processamento = res
                        st.session_state.investigacao_feita = False
                        st.session_state.registos_em_falta = None
                        st.rerun()
                with col_b:
                    if st.button("⏭️ Ignorar e exportar só o que foi extraído", type="secondary"):
                        exportar_disponivel = True   # desbloqueia exportação manual
                        st.session_state.investigacao_feita = False

    # ── PRÉ-VISUALIZAÇÃO ─────────────────────────────────────────────────────
    if todas_as_linhas_final:
        import pandas as pd
        with st.expander(f"👁️ Pré-visualizar {len(todas_as_linhas_final)} registos extraídos"):
            df = pd.DataFrame(
                todas_as_linhas_final,
                columns=["Data", "ID Utente", "Nome", "Valor (€)", "Data Execução", "Ficheiro"]
            )
            st.dataframe(df, use_container_width=True)

    # ── BOTÕES DE EXPORTAÇÃO ─────────────────────────────────────────────────
    st.markdown("---")
    col1, col2 = st.columns([1, 3])

    with col1:
        if exportar_disponivel:
            btn_exportar = st.button("✅ Exportar para Google Sheets", type="primary")
            btn_mesmo_assim = False
        else:
            btn_exportar = False
            btn_mesmo_assim = st.button(
                "⚠️ Exportar mesmo assim",
                help="Discrepância não resolvida. Use apenas se tiver a certeza.",
                type="secondary"
            )

    with col2:
        if not exportar_disponivel:
            st.warning(
                "🔒 Exportação bloqueada. Use **'🔎 Investigar registos em falta'** acima, "
                "ou **'Exportar mesmo assim'** sob sua responsabilidade."
            )

    # ── EXECUÇÃO ─────────────────────────────────────────────────────────────
    if btn_exportar or btn_mesmo_assim:
        if not todas_as_linhas_final:
            st.warning("⚠️ Nenhum dado válido para exportar.")
        else:
            try:
                proxima_linha = res["dados_atuais_len"] + 1
                worksheet.update(
                    range_name=f"B{proxima_linha}",
                    values=todas_as_linhas_final
                )
                st.success(f"✅ {len(todas_as_linhas_final)} linhas gravadas na Coluna B com sucesso!")
                st.session_state.resultado_processamento = None
                st.session_state.pdf_bytes_cache = None
                st.session_state.registos_em_falta = None
                st.session_state.investigacao_feita = False
                st.balloons()
            except Exception as e:
                st.error(f"❌ Erro ao gravar na planilha: {e}")
