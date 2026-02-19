import streamlit as st
import gspread
import re
import pdfplumber
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# CONFIGURAÇÕES INICIAIS
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Extração de Procedimentos", page_icon="🛠️", layout="wide")

sheet_url = st.session_state.get('sheet_url')
if not sheet_url:
    st.warning("⚠️ Configuração em falta na Home (Link da Planilha).")
    st.stop()

# ---------------------------------------------------------------------------
# PARSING DIRETO (sem IA)
#
# ESTRUTURA DO PDF (Pneumologia / Psiquiatria):
#
# Linha COM data e grupo:
#   "2021-09-24 Serviços Especiais Psiquiatria 8 HCIS/1809239 DIOGO MANUEL ALVES DA C PSIQUIATRIA 4000002 Electroconvulsivoterapia Modificada Com Anestes 1 N/S"
#
# Linha SEM data (continuação do grupo):
#   "HCIS/929761 ALICE MARIA NEVES RAMOS PSIQUIATRIA 4000002 Electroconvulsivoterapia Modificada Com Anestes 1 S/S"
#
# Campos:
#   processo   = HCIS/\d+  (ou CCC/\d+, etc.)
#   nome       = texto entre processo e especialidade
#   especialidade = PSIQUIATRIA | PNEUMOLOGIA | GASTROENTEROLO | CIRURGIA | ...
#   codigo     = número após especialidade (ex: 4000002, 50019903, 99880166)
#   procedimento = texto até ao par qtd + Fact (ex: "1 N/S")
# ---------------------------------------------------------------------------

RE_IGNORAR = re.compile(
    r'Data:\s*\d{4}|'
    r'Hora:\s*\d|'
    r'Hospital |'
    r'Exames Realizados|'
    r'Utilizador:|'
    r'GHC[A-Z]\d+|'
    r'Período entre|'
    r'Interveniente:|'
    r'^Data\s+Grupo\s+Total|'
    r'Pág\.?\s*\d|'
    r'Fim da Listagem'
)

# Especialidades conhecidas — adicione mais se necessário
ESPECIALIDADES = (
    r'PSIQUIATRIA|PNEUMOLOGIA|GASTROENTEROLO|CIRURGIA|MEDICINA|'
    r'ORTOPEDIA|CARDIOLOGIA|NEUROLOGIA|UROLOGIA|GINECOLOGIA|'
    r'OFTALMOLOGIA|DERMATOLOGIA|PEDIATRIA|ONCOLOGIA|RADIOLOGIA|'
    r'ANESTESIOLOGIA|ENDOSCOPIA|REUMATOLOGIA|NEFROLOGIA|'
    r'HEMATOLOGIA|IMUNOLOGIA|INFECIOLOGIA|OTORRINOLARINGO'
)

# Linha COM data de ato
# Grupos: 1=data, 2=grupo_nome, 3=total_grupo, 4=processo, 5=nome, 6=especialidade, 7=codigo, 8=procedimento
RE_COM_DATA = re.compile(
    r'^(\d{4}-\d{2}-\d{2})\s+'             # 1: data YYYY-MM-DD
    r'(.+?)\s+'                             # 2: nome do grupo (qualquer texto)
    r'(\d+)\s+'                             # 3: total do grupo
    r'([A-Z]+/\d+)\s+'                      # 4: processo (HCIS/123, CCC/456)
    r'(.+?)\s+'                             # 5: nome do doente
    r'(' + ESPECIALIDADES + r')\s*'         # 6: especialidade
    r'(\w+)\s+'                             # 7: código do ato
    r'(.+?)\s+'                             # 8: descrição do procedimento
    r'\d+\s+[A-Z]/[A-Z]$'                  # qtd e fact — âncora final
)

# Linha SEM data (continuação de grupo)
# Grupos: 1=processo, 2=nome, 3=especialidade, 4=codigo, 5=procedimento
RE_SEM_DATA = re.compile(
    r'^([A-Z]+/\d+)\s+'                    # 1: processo
    r'(.+?)\s+'                             # 2: nome do doente
    r'(' + ESPECIALIDADES + r')\s*'         # 3: especialidade
    r'(\w+)\s+'                             # 4: código do ato
    r'(.+?)\s+'                             # 5: descrição do procedimento
    r'\d+\s+[A-Z]/[A-Z]$'                  # âncora final
)


def extrair_registos_pagina(texto: str, ultima_data: str, ultimo_grupo: str):
    """
    Parseia uma página e devolve (lista_registos, última_data, último_grupo).
    """
    registos = []

    for linha in texto.split('\n'):
        linha = linha.strip()
        if not linha or RE_IGNORAR.search(linha):
            continue

        m = RE_COM_DATA.match(linha)
        if m:
            ultima_data = m.group(1)
            ultimo_grupo = m.group(2).strip()
            registos.append({
                "data": ultima_data,
                "grupo": ultimo_grupo,
                "processo": m.group(4),
                "nome": m.group(5).strip(),
                "especialidade": m.group(6).strip(),
                "codigo": m.group(7),
                "procedimento": m.group(8).strip()
            })
            continue

        m2 = RE_SEM_DATA.match(linha)
        if m2:
            registos.append({
                "data": ultima_data,
                "grupo": ultimo_grupo,
                "processo": m2.group(1),
                "nome": m2.group(2).strip(),
                "especialidade": m2.group(3).strip(),
                "codigo": m2.group(4),
                "procedimento": m2.group(5).strip()
            })

    return registos, ultima_data, ultimo_grupo


def formatar_data_pt(data_iso: str) -> str:
    """YYYY-MM-DD → DD-MM-YYYY"""
    if not data_iso:
        return ""
    p = re.findall(r'\d+', data_iso)
    if len(p) == 3 and len(p[0]) == 4:
        ano, mes, dia = p[0], p[1].zfill(2), p[2].zfill(2)
        return f"{dia}-{mes}-{ano}"
    return data_iso


# ---------------------------------------------------------------------------
# CONEXÃO GOOGLE SHEETS
# ---------------------------------------------------------------------------
try:
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scope
    )
    gc = gspread.authorize(creds)
    sheet_id = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url).group(1)
    sh = gc.open_by_key(sheet_id)

    NOME_FOLHA = 'ExamesEsp'
    try:
        worksheet = sh.worksheet(NOME_FOLHA)
    except Exception:
        worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="10000", cols="10")
        worksheet.update(
            range_name="A1",
            values=[["Data", "Processo", "Nome do Doente", "Especialidade",
                     "Código", "Procedimento", "Grupo", "Gravado Em", "Origem PDF"]]
        )
except Exception as e:
    st.error(f"❌ Erro de ligação ao Google Sheets: {e}")
    st.stop()


# ---------------------------------------------------------------------------
# INTERFACE E PROCESSAMENTO
# ---------------------------------------------------------------------------
st.title("🛠️ Extração de Procedimentos — Pneumologia / Psiquiatria")
st.info(
    "**Método:** Parsing direto (sem IA).  \n"
    "Suporta especialidades: Psiquiatria, Pneumologia, Gastroenterologia, Cirurgia, e outras.  \n"
    "A data de impressão do cabeçalho é ignorada automaticamente."
)

uploads = st.file_uploader(
    "Carregue os PDFs", type=['pdf'], accept_multiple_files=True
)

# Opção de diagnóstico
modo_diagnostico = st.checkbox("🔍 Modo diagnóstico (mostra linhas brutas que não foram reconhecidas)", value=False)

if uploads and st.button("🚀 Iniciar Processamento"):
    dados_existentes = worksheet.get_all_values()
    chaves_existentes = {
        f"{r[0]}_{r[1]}"
        for r in dados_existentes[1:] if len(r) > 1
    }

    data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
    status_msg = st.empty()
    progresso = st.progress(0)

    for idx_pdf, pdf_file in enumerate(uploads):
        novas_linhas = []
        ultima_data = ""
        ultimo_grupo = ""
        total_extraido = 0
        total_duplicado = 0
        linhas_nao_reconhecidas = []

        with pdfplumber.open(pdf_file) as pdf:
            total_pags = len(pdf.pages)

            for p_idx, pagina in enumerate(pdf.pages):
                status_msg.info(
                    f"📄 PDF {idx_pdf+1}/{len(uploads)} | "
                    f"Página {p_idx+1}/{total_pags} — {pdf_file.name}"
                )

                texto = pagina.extract_text()
                if not texto:
                    continue

                registos, ultima_data, ultimo_grupo = extrair_registos_pagina(
                    texto, ultima_data, ultimo_grupo
                )
                total_extraido += len(registos)

                # Diagnóstico: linhas não reconhecidas
                if modo_diagnostico:
                    for linha in texto.split('\n'):
                        linha = linha.strip()
                        if not linha or RE_IGNORAR.search(linha):
                            continue
                        if not RE_COM_DATA.match(linha) and not RE_SEM_DATA.match(linha):
                            linhas_nao_reconhecidas.append(f"[Pág {p_idx+1}] {linha}")

                for r in registos:
                    data_fmt = formatar_data_pt(r["data"])
                    nome = r["nome"].upper()
                    especialidade = r["especialidade"]
                    codigo = r["codigo"]
                    proc = r["procedimento"]
                    grupo = r["grupo"]
                    processo = re.sub(r'\D', '', r["processo"])  # só dígitos

                    chave = f"{data_fmt}_{processo}"
                    if chave not in chaves_existentes:
                        novas_linhas.append([
                            data_fmt, processo, nome, especialidade,
                            codigo, proc, grupo, data_hoje, pdf_file.name
                        ])
                        chaves_existentes.add(chave)
                    else:
                        total_duplicado += 1

        # Resumo do PDF
        st.write(
            f"**{pdf_file.name}** — extraídos: {total_extraido} | "
            f"novos: {len(novas_linhas)} | duplicados ignorados: {total_duplicado}"
        )

        # Se extraiu zero, mostra diagnóstico automático
        if total_extraido == 0:
            with pdfplumber.open(pdf_file) as pdf:
                txt_p1 = pdf.pages[0].extract_text() or ""
            st.warning("⚠️ Nenhum registo encontrado. Primeiras linhas do PDF (para diagnóstico):")
            st.code(txt_p1[:2000])

        # Modo diagnóstico: linhas não reconhecidas
        if modo_diagnostico and linhas_nao_reconhecidas:
            with st.expander(f"🔍 Linhas não reconhecidas em {pdf_file.name} ({len(linhas_nao_reconhecidas)})"):
                st.code('\n'.join(linhas_nao_reconhecidas[:100]))

        # Gravação em lotes de 500
        if novas_linhas:
            for i in range(0, len(novas_linhas), 500):
                lote = novas_linhas[i:i+500]
                worksheet.append_rows(
                    lote,
                    value_input_option="USER_ENTERED",
                    table_range="A1"
                )
                if len(novas_linhas) > 500:
                    time.sleep(1)
            st.toast(f"✅ {len(novas_linhas)} linhas gravadas de {pdf_file.name}")
        else:
            st.toast(f"ℹ️ Nenhuma linha nova em {pdf_file.name}")

        progresso.progress((idx_pdf + 1) / len(uploads))

    status_msg.success("✨ Processamento concluído!")
    st.balloons()
