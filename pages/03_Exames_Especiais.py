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
# Regex genéricos: funcionam com qualquer prefixo de processo (CCC/, HCIS/, etc.)
# e qualquer nome de especialidade (GASTROENTEROLO, CIRURGIA, MEDICINA, etc.)
#
# ESTRUTURA DO PDF:
# Linha com data:  "2021-05-17 Equipa Cirurgica 2 CCC/245230 JOSE... GASTROENTEROLO6051 Anestesia... 1 N/N"
# Linha sem data:  "CCC/344423 ANABELA... GASTROENTEROLO17009901 Colonoscopia... 1 N/N"
# Cabeçalho (ignorado): "Data: 2026-02-17", "Hospital ...", "Pág. 1/52", etc.
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
    r'Pág\.\s*\d'
)

# Linha COM data de ato
RE_COM_DATA = re.compile(
    r'^(\d{4}-\d{2}-\d{2})\s+'   # data do ato YYYY-MM-DD
    r'.+?\s+'                      # nome do grupo (qualquer texto)
    r'\d+\s+'                      # total do grupo
    r'([A-Z]+/\d+)\s+'            # processo (CCC/245230, HCIS/123, etc.)
    r'(.+?)'                       # nome do doente
    r'GASTROENTEROLO\s*'           # separador de especialidade (fixo)
    r'(\w+)\s+'                    # código do ato
    r'(.+?)\s+'                    # descrição do procedimento
    r'\d+\s+[A-Z]/[A-Z]$'         # qtd e fact — âncora final
)

# Linha SEM data
RE_SEM_DATA = re.compile(
    r'^([A-Z]+/\d+)\s+'   # processo (qualquer prefixo)
    r'(.+?)'               # nome do doente
    r'GASTROENTEROLO\s*'   # separador de especialidade (fixo)
    r'(\w+)\s+'            # código do ato
    r'(.+?)\s+'            # descrição do procedimento
    r'\d+\s+[A-Z]/[A-Z]$' # âncora final
)


def extrair_registos_pagina(texto: str, ultima_data: str):
    """
    Parseia uma página e devolve (lista_registos, última_data_de_ato).
    A data propaga-se apenas entre registos de ato — nunca do cabeçalho.
    """
    registos = []

    for linha in texto.split('\n'):
        linha = linha.strip()
        if not linha or RE_IGNORAR.search(linha):
            continue

        m = RE_COM_DATA.match(linha)
        if m:
            ultima_data = m.group(1)
            # grupos: 1=data, 2=processo, 3=nome, 4=codigo, 5=procedimento
            registos.append({
                "data": ultima_data,
                "processo": m.group(2),
                "nome": m.group(3).strip(),
                "codigo": m.group(4),
                "procedimento": m.group(5).strip()
            })
            continue

        m2 = RE_SEM_DATA.match(linha)
        if m2:
            registos.append({
                "data": ultima_data,
                "processo": m2.group(1),
                "nome": m2.group(2).strip(),
                "codigo": m2.group(3),
                "procedimento": m2.group(4).strip()
            })

    return registos, ultima_data


def formatar_data_pt(data_iso: str) -> str:
    """YYYY-MM-DD → DD-MM-YYYY com zero padding garantido (ex: 05-06-2021)"""
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

    NOME_FOLHA = 'Procedimentos'
    try:
        worksheet = sh.worksheet(NOME_FOLHA)
    except Exception:
        worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="10000", cols="10")
        worksheet.update(
            range_name="C1",
            values=[["Data", "Processo", "Nome do Doente", "Código", "Procedimento", "Gravado Em", "Origem PDF"]]
        )
except Exception as e:
    st.error(f"❌ Erro de ligação ao Google Sheets: {e}")
    st.stop()


# ---------------------------------------------------------------------------
# INTERFACE E PROCESSAMENTO
# ---------------------------------------------------------------------------
st.title("🛠️ Extração de Procedimentos")
st.info(
    "**Método:** Parsing direto (sem IA) — extrai 100% dos registos sem truncagem.  \n"
    "A data de impressão do cabeçalho é ignorada automaticamente."
)

uploads = st.file_uploader(
    "Carregue os PDFs", type=['pdf'], accept_multiple_files=True
)

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
        total_extraido = 0
        total_duplicado = 0

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

                registos, ultima_data = extrair_registos_pagina(texto, ultima_data)
                total_extraido += len(registos)

                for r in registos:
                    data_fmt = formatar_data_pt(r["data"])
                    nome = r["nome"].upper()
                    codigo = r["codigo"]
                    proc = r["procedimento"]
                    processo = re.sub(r'\D', '', r["processo"])  # só dígitos

                    chave = f"{data_fmt}_{processo}"
                    if chave not in chaves_existentes:
                        novas_linhas.append([
                            data_fmt, processo, nome, codigo, proc,
                            data_hoje, pdf_file.name
                        ])
                        chaves_existentes.add(chave)
                    else:
                        total_duplicado += 1

        # Diagnóstico sempre visível
        st.write(
            f"**{pdf_file.name}** — extraídos: {total_extraido} | "
            f"novos: {len(novas_linhas)} | duplicados ignorados: {total_duplicado}"
        )

        # Se extraiu zero, mostra as primeiras linhas brutas para diagnóstico
        if total_extraido == 0:
            with pdfplumber.open(pdf_file) as pdf:
                txt_p1 = pdf.pages[0].extract_text() or ""
            st.warning("⚠️ Nenhum registo encontrado. Primeiras linhas do PDF:")
            st.code(txt_p1[:1500])

        # Gravação em lotes de 500
        if novas_linhas:
            for i in range(0, len(novas_linhas), 500):
                lote = novas_linhas[i:i+500]
                worksheet.append_rows(
                    lote,
                    value_input_option="USER_ENTERED",
                    table_range="C1"
                )
                if len(novas_linhas) > 500:
                    time.sleep(1)
            st.toast(f"✅ {len(novas_linhas)} linhas gravadas de {pdf_file.name}")
        else:
            st.toast(f"ℹ️ Nenhuma linha nova em {pdf_file.name}")

        progresso.progress((idx_pdf + 1) / len(uploads))

    status_msg.success("✨ Processamento concluído!")
    st.balloons()
