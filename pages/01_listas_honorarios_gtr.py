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
st.set_page_config(page_title="Extração de Honorários", page_icon="💶", layout="wide")

sheet_url = st.session_state.get('sheet_url')
if not sheet_url:
    st.warning("⚠️ Configuração em falta na Home (Link da Planilha).")
    st.stop()

# ---------------------------------------------------------------------------
# PARSING DIRETO (sem IA)
#
# ESTRUTURA DO PDF (Mapa de Honorários - Detalhe):
#
# Pág. 1: sumário por grupo (ignorada)
# Págs. 2+: linhas de detalhe, uma por ato:
#   "DD-MM-YY <processo><nome> <Serviço> <cod_ent> <entidade> <cod_acto><procedimento> [%] [NrK] <qtd> <valor>"
#
# Colunas extraídas (por ordem):
#   Data | Processo | Nome | Valor | Procedimento | Entidade | Data Extração | PDF Origem
# ---------------------------------------------------------------------------

# Serviços conhecidos — do mais longo para o mais curto (evita matches parciais)
_SERVICOS = [
    'Bloco Operatorio Tejo',
    'Cir. Plástica E Reconstru',
    'Ginecologia Obstetricia',
    'Otorrinolaringologia',
    'Neuro-Cirurgia',
    'Cirurgia Vascular',
    'Cirurgia Torácica',
    'Cirurgia Geral',
    'Gastroenterologia',
    'Anestesiologia',
    'Oftalmologia',
    'Ortopedia',
    'Angiografia',
    'Urologia',
    'CPRE',
]
_SERVICOS.sort(key=len, reverse=True)

# Mapa para nome canónico independente de maiúsculas no PDF
_SERVICO_CANON = {s.lower(): s for s in _SERVICOS}

# Separador nome → serviço: case-insensitive, serviço seguido de dígito (código entidade)
RE_SERVICO = re.compile(
    r'\s*(' + '|'.join(re.escape(s) for s in _SERVICOS) + r')(?=\s*\d)',
    re.IGNORECASE
)

# Linha de dados principal
RE_LINHA = re.compile(
    r'^(\d{2}-\d{2}-\d{2})\s+'   # data DD-MM-YY
    r'(\d+)'                       # processo (só dígitos, colado ao nome)
    r'(.+?)\s+'                    # nome + serviço + entidade + procedimento
    r'-?\d+\s+'                    # quantidade (pode ser negativa em extornos)
    r'(-?[\d,]+\.\d{2})$'         # valor (ex: 50.00 ou -121.41 ou 1,125.20)
)

# Cabeçalhos de secção de grupo
RE_GRUPO = re.compile(
    r'^(Anestesia|Angiografia[^,]|CPRE|Cirurgias Oftalmologia|Cirurgias|'
    r'Consultas|Exames Bloco)$'
)

# Linhas de cabeçalho/rodapé a ignorar
# "Hospital" ancorado ao início para não apanhar entidades como "Hospital Garcia De Orta"
RE_IGNORAR = re.compile(
    r'^Hospital |Mapa de Honor|PS_PA_009|Utilizador:|Pág\.\s*(por|:)?\s*\d|'
    r'Data:\s*\d{4}|Hora:\s*\d|Ano:\s*\d|Prestador de Serviços|'
    r'Código fornecedor|1M - Processamento|Datas (Activ|Factur)|'
    r'Valores do Período|^Data\s+Doente|Total (do Período|Geral|Valor)'
)


def extrair_entidade_proc(resto: str) -> tuple[str, str]:
    """
    Dado o texto após o serviço, extrai entidade pagadora e início do procedimento.

    Formato do resto: " <cod_ent> <entidade...> <cod_acto><procedimento> [% NrK]"

    O cod_acto é sempre 5+ dígitos colados ao início do procedimento.
    Alguns códigos têm sufixo de letras maiúsculas (PT, T) que fazem parte do código.
    """
    resto = resto.strip()
    partes = resto.split(None, 1)
    if len(partes) < 2:
        return "", ""

    sem_cod_ent = partes[1]  # remove o código numérico da entidade (1ª palavra)

    # Localiza cod_acto: 5+ dígitos colados ao procedimento
    m = re.search(r'\d{5,}', sem_cod_ent)
    if not m:
        return sem_cod_ent.strip(), ""

    entidade   = sem_cod_ent[:m.start()].strip()
    apos_digitos = sem_cod_ent[m.end():]

    # Elimina sufixo de código (PT ou T) quando colado ao procedimento
    sufixo = re.match(r'^(PT|T)(?=[A-Za-zÀ-ÿ])', apos_digitos)
    if sufixo:
        apos_digitos = apos_digitos[sufixo.end():]

    proc_raw = apos_digitos.strip()

    # Remove cauda: "% valor NrK" — ex: "90.00 -57" ou "90.00 66" ou só "60.00"
    proc = re.sub(r'\s+\d+\.\d{2}\s+-?\d+\s*$', '', proc_raw).strip()
    proc = re.sub(r'\s+\d+\.\d{2}\s*$', '', proc).strip()
    # Remove " -" final de linhas truncadas pelo PDF
    proc = re.sub(r'\s+-\s*$', '', proc).strip()

    return entidade, proc


def parsear_pagina(texto: str, grupo_atual: str) -> tuple[list, str]:
    """Parseia uma página e devolve (lista_registos, grupo_atual)."""
    registos = []

    for linha in texto.split('\n'):
        linha = linha.strip()
        if not linha or RE_IGNORAR.search(linha):
            continue

        # Detecta mudança de grupo
        mg = RE_GRUPO.match(linha)
        if mg:
            grupo_atual = mg.group(1).strip()
            continue

        # Linha de dados
        m = RE_LINHA.match(linha)
        if not m:
            continue

        data_raw  = m.group(1)   # DD-MM-YY
        processo  = m.group(2)   # só dígitos
        meio      = m.group(3).strip()
        valor_raw = m.group(4)

        # Separa nome do serviço (case-insensitive, cobre "UROLOGIA" e "Urologia")
        ms = RE_SERVICO.search(meio)
        nome  = meio[:ms.start()].strip() if ms else meio.strip()
        resto = meio[ms.end():]           if ms else ""

        # Extrai entidade e procedimento
        entidade, procedimento = extrair_entidade_proc(resto)

        # Formata data: DD-MM-YY → DD-MM-YYYY (com zero-padding no dia e mês)
        p = data_raw.split('-')
        data_fmt = f"{p[0].zfill(2)}-{p[1].zfill(2)}-20{p[2]}"

        # Formata valor: "1,125.20" → "1125,20" | "-50.00" → "-50,00"
        valor = valor_raw.replace(',', '').replace('.', ',')

        registos.append({
            "data":         data_fmt,
            "processo":     processo,
            "nome":         nome.upper(),
            "valor":        valor,
            "procedimento": procedimento,
            "entidade":     entidade,
        })

    return registos, grupo_atual


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

    NOME_FOLHA = 'Honorários'
    CABECALHO  = [["Data", "Processo", "Nome do Doente", "Valor (€)",
                   "Procedimento", "Entidade", "Gravado Em", "Origem PDF"]]
    try:
        worksheet = sh.worksheet(NOME_FOLHA)
    except Exception:
        worksheet = sh.add_worksheet(title=NOME_FOLHA, rows="10000", cols="15")
        worksheet.update(range_name="C1", values=CABECALHO)

except Exception as e:
    st.error(f"❌ Erro de ligação ao Google Sheets: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# INTERFACE E PROCESSAMENTO
# ---------------------------------------------------------------------------
st.title("💶 Extração de Honorários")
st.info(
    "Extrai todas as linhas dos PDFs **Mapa de Honorários - Detalhe** para o Google Sheets.  \n"
    "Sem deduplicação — todas as linhas são gravadas, incluindo extornos (valores negativos)."
)

uploads = st.file_uploader(
    "Carregue os PDFs de Honorários", type=['pdf', 'PDF'], accept_multiple_files=True
)

if uploads and st.button("🚀 Iniciar Processamento"):
    data_hoje = datetime.now().strftime("%d-%m-%Y %H:%M")
    status_msg = st.empty()
    progresso  = st.progress(0)

    for idx_pdf, pdf_file in enumerate(uploads):
        todas_linhas = []
        grupo_atual  = ""

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

                registos, grupo_atual = parsear_pagina(texto, grupo_atual)

                for r in registos:
                    todas_linhas.append([
                        r["data"], r["processo"], r["nome"],
                        r["valor"], r["procedimento"], r["entidade"],
                        data_hoje, pdf_file.name
                    ])

        # Diagnóstico por PDF
        st.write(f"**{pdf_file.name}** — {len(todas_linhas)} linhas extraídas")

        if todas_linhas:
            # Gravação em lotes de 500 a partir da primeira linha livre na coluna C
            for i in range(0, len(todas_linhas), 500):
                lote = todas_linhas[i:i+500]
                worksheet.append_rows(
                    lote,
                    value_input_option="USER_ENTERED",
                    table_range="C1"
                )
                if len(todas_linhas) > 500:
                    time.sleep(1)
            st.toast(f"✅ {len(todas_linhas)} linhas gravadas de {pdf_file.name}")
        else:
            # Diagnóstico se nada extraído
            with pdfplumber.open(pdf_file) as pdf:
                txt_p2 = pdf.pages[1].extract_text() if len(pdf.pages) > 1 else ""
            st.warning("⚠️ Nenhum registo encontrado. Primeiras linhas da pág. 2:")
            st.code(txt_p2[:1500] if txt_p2 else "(vazio)")

        progresso.progress((idx_pdf + 1) / len(uploads))

    status_msg.success("✨ Processamento concluído!")
