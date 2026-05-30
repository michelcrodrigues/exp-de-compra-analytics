"""
fetch_ga4.py — Coleta métricas diárias do GA4 e grava em data/history.ndjson.

Substituição do Google Sheets por arquivo ndjson local no repositório.
Cada linha do ndjson é um JSON completo representando um dia de dados.

Modos de operação:
  HISTÓRICO — ativado por FORCE_HISTORICAL=true ou arquivo vazio/inexistente
              coleta de 01/01/2025 até ontem, dia a dia
  DIÁRIO    — padrão; coleta só o dia anterior

Secrets necessários no GitHub Actions:
  GA4_CREDENTIALS_JSON   → conteúdo do JSON da service account

Variáveis opcionais:
  FORCE_HISTORICAL=true  → força modo histórico independente do conteúdo do arquivo
  FORCE_REPROCESS=true   → apaga history.ndjson e reprocessa tudo desde jan/2025

A service account precisa ter acesso de leitura ao GA4.
E-mail: ga4-dashboard-github@analytics-dashboard-497114.iam.gserviceaccount.com
"""

import os
import json
import datetime
import sys
import time

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ──────────────────────────────────────────────
# Configurações
# ──────────────────────────────────────────────

GA4_PROPERTY_ID    = "326912205"
HISTORY_START      = datetime.date(2025, 1, 1)
HISTORY_FILE       = "data/history.ndjson"
CHECKPOINT_EVERY   = 30    # gravar no arquivo a cada N dias coletados
PAUSE_BETWEEN_DAYS = 0.15  # segundos entre chamadas GA4 no modo histórico
MAX_RETRIES        = 3     # tentativas em caso de erro transitório da API

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
]

# Colunas esperadas — usadas pelo validate_schema.py
# Ordem não importa aqui, mas serve como contrato entre os scripts
COLUMNS = [
    "data",
    "sessoes", "usuarios", "novos_usuarios", "pageviews",
    "compras", "taxa_conversao_pct",
    "taxa_rejeicao_pct", "duracao_media_seg",
    "sessoes_mobile", "sessoes_desktop", "sessoes_tablet",
    "compras_mobile", "compras_desktop", "compras_tablet",
    "usuarios_mobile", "usuarios_desktop", "usuarios_tablet",
    "novos_usuarios_mobile", "novos_usuarios_desktop", "novos_usuarios_tablet",
    "taxa_rejeicao_mobile", "taxa_rejeicao_desktop", "taxa_rejeicao_tablet",
    "duracao_media_mobile", "duracao_media_desktop", "duracao_media_tablet",
    "sessoes_organico", "sessoes_direto", "sessoes_pago",
    "sessoes_social", "sessoes_email", "sessoes_referral", "sessoes_outros_canais",
    "funil_search", "funil_select_item", "funil_add_to_cart",
    "funil_begin_checkout", "funil_purchase",
    "funil_search_mobile", "funil_select_item_mobile", "funil_add_to_cart_mobile",
    "funil_begin_checkout_mobile", "funil_purchase_mobile",
    "funil_search_desktop", "funil_select_item_desktop", "funil_add_to_cart_desktop",
    "funil_begin_checkout_desktop", "funil_purchase_desktop",
    "funil_search_tablet", "funil_select_item_tablet", "funil_add_to_cart_tablet",
    "funil_begin_checkout_tablet", "funil_purchase_tablet",
    "top_origem_1", "top_origem_1_sessoes",
    "top_origem_2", "top_origem_2_sessoes",
    "top_origem_3", "top_origem_3_sessoes",
    "top_origem_4", "top_origem_4_sessoes",
    "top_origem_5", "top_origem_5_sessoes",
    "top_destino_1", "top_destino_1_sessoes",
    "top_destino_2", "top_destino_2_sessoes",
    "top_destino_3", "top_destino_3_sessoes",
    "top_destino_4", "top_destino_4_sessoes",
    "top_destino_5", "top_destino_5_sessoes",
]

# ──────────────────────────────────────────────
# Autenticação
# ──────────────────────────────────────────────

def get_credentials():
    creds_info = json.loads(os.environ["GA4_CREDENTIALS_JSON"])
    return service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )

# ──────────────────────────────────────────────
# history.ndjson — leitura e escrita
# ──────────────────────────────────────────────

def load_existing_dates():
    """Lê o history.ndjson e retorna conjunto de datas já gravadas."""
    if not os.path.exists(HISTORY_FILE):
        return set()
    dates = set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    record = json.loads(line)
                    if record.get("data"):
                        dates.add(record["data"])
                except json.JSONDecodeError:
                    pass  # linha corrompida — ignora e continua
    return dates


def append_records(records):
    """
    Appenda uma lista de dicts ao history.ndjson.
    Cria o arquivo (e o diretório data/) se não existir.
    """
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def reset_history_file():
    """Apaga o history.ndjson para FORCE_REPROCESS."""
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
        print(f"  {HISTORY_FILE} removido.")
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)

# ──────────────────────────────────────────────
# GA4 — helpers
# ──────────────────────────────────────────────

def get_ga4_service(creds):
    return build("analyticsdata", "v1beta", credentials=creds)


def run_report(service, date_str, dimensions, metrics, limit=10):
    """
    Executa um RunReport com retry automático em erros transitórios (429, 500, 503).
    """
    body = {
        "dateRanges": [{"startDate": date_str, "endDate": date_str}],
        "dimensions": [{"name": d} for d in dimensions],
        "metrics":    [{"name": m} for m in metrics],
        "limit":      limit,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = (
                service.properties()
                .runReport(property=f"properties/{GA4_PROPERTY_ID}", body=body)
                .execute()
            )
            return resp.get("rows", [])
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < MAX_RETRIES:
                wait = 2 ** attempt  # 2s, 4s, 8s
                print(f"    API error {e.resp.status} — aguardando {wait}s (tentativa {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
            else:
                raise
    return []


def safe_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def safe_float(value, decimals=4):
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return 0.0


def calc_cr(compras, sessoes):
    if sessoes > 0:
        return round(compras / sessoes * 100, 4)
    return 0.0

# ──────────────────────────────────────────────
# GA4 — coleta de métricas por dia
# ──────────────────────────────────────────────

def collect_metrics(service, date_str):
    m = {}

    # ── Report 1: métricas gerais (sem dimensão) ─────────────────────────────
    rows = run_report(
        service, date_str, [],
        ["sessions", "totalUsers", "newUsers", "transactions",
         "bounceRate", "averageSessionDuration", "screenPageViews"],
    )
    if rows:
        v = rows[0]["metricValues"]
        m["sessoes"]           = safe_int(v[0]["value"])
        m["usuarios"]          = safe_int(v[1]["value"])
        m["novos_usuarios"]    = safe_int(v[2]["value"])
        m["compras"]           = safe_int(v[3]["value"])
        # bounceRate vem como decimal (0–1) — converter para percentual
        m["taxa_rejeicao_pct"] = round(safe_float(v[4]["value"]) * 100, 2)
        m["duracao_media_seg"] = safe_float(v[5]["value"], 2)
        m["pageviews"]         = safe_int(v[6]["value"])
    else:
        for k in ["sessoes", "usuarios", "novos_usuarios", "compras",
                  "taxa_rejeicao_pct", "duracao_media_seg", "pageviews"]:
            m[k] = 0

    # CR calculado manualmente — não usar sessionConversionRate do GA4
    m["taxa_conversao_pct"] = calc_cr(m["compras"], m["sessoes"])

    # ── Report 2: métricas completas por dispositivo ──────────────────────────
    for dev in ["mobile", "desktop", "tablet"]:
        m[f"sessoes_{dev}"]        = 0
        m[f"compras_{dev}"]        = 0
        m[f"usuarios_{dev}"]       = 0
        m[f"novos_usuarios_{dev}"] = 0
        m[f"taxa_rejeicao_{dev}"]  = 0.0
        m[f"duracao_media_{dev}"]  = 0.0

    rows = run_report(
        service, date_str,
        ["deviceCategory"],
        ["sessions", "transactions", "totalUsers", "newUsers",
         "bounceRate", "averageSessionDuration"],
    )
    for row in rows:
        dev = row["dimensionValues"][0]["value"].lower()
        if dev in ("mobile", "desktop", "tablet"):
            v = row["metricValues"]
            m[f"sessoes_{dev}"]        = safe_int(v[0]["value"])
            m[f"compras_{dev}"]        = safe_int(v[1]["value"])
            m[f"usuarios_{dev}"]       = safe_int(v[2]["value"])
            m[f"novos_usuarios_{dev}"] = safe_int(v[3]["value"])
            # bounceRate vem como decimal (0–1) → converter para percentual
            m[f"taxa_rejeicao_{dev}"]  = round(safe_float(v[4]["value"]) * 100, 2)
            m[f"duracao_media_{dev}"]  = round(safe_float(v[5]["value"]), 2)

    # ── Report 3: sessões por canal ──────────────────────────────────────────
    channel_map = {
        "organic search": "sessoes_organico",
        "direct":         "sessoes_direto",
        "paid search":    "sessoes_pago",
        "organic social": "sessoes_social",
        "email":          "sessoes_email",
        "referral":       "sessoes_referral",
    }
    for k in channel_map.values():
        m[k] = 0
    m["sessoes_outros_canais"] = 0

    rows = run_report(
        service, date_str,
        ["sessionDefaultChannelGroup"],
        ["sessions"],
        limit=20,
    )
    for row in rows:
        channel = row["dimensionValues"][0]["value"].lower()
        val     = safe_int(row["metricValues"][0]["value"])
        if channel in channel_map:
            m[channel_map[channel]] = val
        else:
            m["sessoes_outros_canais"] += val

    # ── Report 4a: funil de eventos total ────────────────────────────────────
    funil_events = ["search", "select_item", "add_to_cart", "begin_checkout", "purchase"]
    funil_map = {e: f"funil_{e}" for e in funil_events}
    for k in funil_map.values():
        m[k] = 0

    rows = run_report(
        service, date_str,
        ["eventName"],
        ["eventCount"],
        limit=50,
    )
    for row in rows:
        event = row["dimensionValues"][0]["value"]
        if event in funil_map:
            m[funil_map[event]] = safe_int(row["metricValues"][0]["value"])

    # ── Report 4b: funil por dispositivo ─────────────────────────────────────
    for dev in ["mobile", "desktop", "tablet"]:
        for e in funil_events:
            m[f"funil_{e}_{dev}"] = 0

    rows = run_report(
        service, date_str,
        ["eventName", "deviceCategory"],
        ["eventCount"],
        limit=100,
    )
    for row in rows:
        event = row["dimensionValues"][0]["value"]
        dev   = row["dimensionValues"][1]["value"].lower()
        if event in funil_events and dev in ("mobile", "desktop", "tablet"):
            m[f"funil_{event}_{dev}"] = safe_int(row["metricValues"][0]["value"])

    # ── Report 5: top 5 origens ──────────────────────────────────────────────
    for i in range(1, 6):
        m[f"top_origem_{i}"]         = ""
        m[f"top_origem_{i}_sessoes"] = 0

    rows = run_report(
        service, date_str,
        ["customEvent:originCity"],
        ["sessions"],
        limit=5,
    )
    for i, row in enumerate(rows, 1):
        city = row["dimensionValues"][0]["value"]
        if city and city != "(not set)":
            m[f"top_origem_{i}"]         = city
            m[f"top_origem_{i}_sessoes"] = safe_int(row["metricValues"][0]["value"])

    # ── Report 6: top 5 destinos ─────────────────────────────────────────────
    for i in range(1, 6):
        m[f"top_destino_{i}"]         = ""
        m[f"top_destino_{i}_sessoes"] = 0

    rows = run_report(
        service, date_str,
        ["customEvent:destinationCity"],
        ["sessions"],
        limit=5,
    )
    for i, row in enumerate(rows, 1):
        city = row["dimensionValues"][0]["value"]
        if city and city != "(not set)":
            m[f"top_destino_{i}"]         = city
            m[f"top_destino_{i}_sessoes"] = safe_int(row["metricValues"][0]["value"])

    return m


def metrics_to_record(date_str, m):
    """Converte dict de métricas para dict ordenado na ordem de COLUMNS."""
    record = {"data": date_str}
    for col in COLUMNS[1:]:
        record[col] = m.get(col, "" if col.startswith("top_") and not col.endswith("_sessoes") else 0)
    return record

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    force_historical = os.environ.get("FORCE_HISTORICAL", "").lower() == "true"
    force_reprocess  = os.environ.get("FORCE_REPROCESS", "").lower() == "true"
    yesterday        = datetime.date.today() - datetime.timedelta(days=1)

    print("Autenticando...")
    creds       = get_credentials()
    ga4_service = get_ga4_service(creds)

    # ── FORCE_REPROCESS: apaga o arquivo e começa do zero ────────────────────
    if force_reprocess:
        print("FORCE_REPROCESS=true — apagando history.ndjson e reprocessando tudo.")
        reset_history_file()
        force_historical = True  # implica modo histórico

    existing_dates = load_existing_dates()
    print(f"Datas já no history.ndjson: {len(existing_dates)}")

    # ── Modo de operação ─────────────────────────────────────────────────────
    historical_mode = force_historical or len(existing_dates) == 0

    if historical_mode:
        reason = "forçado via FORCE_HISTORICAL=true" if force_historical else "arquivo vazio/inexistente"
        print(f"MODO HISTÓRICO — {reason}")
        print(f"  Coletando de {HISTORY_START} até {yesterday}")

        dates_to_collect = []
        current = HISTORY_START
        while current <= yesterday:
            date_str = current.strftime("%Y-%m-%d")
            if date_str not in existing_dates:
                dates_to_collect.append(date_str)
            current += datetime.timedelta(days=1)

        total_days = len(dates_to_collect)
        est_min    = round(total_days * (6 * 0.4 + PAUSE_BETWEEN_DAYS) / 60, 1)
        print(f"  {total_days} dias para coletar — estimativa: ~{est_min} min")

    else:
        date_str = yesterday.strftime("%Y-%m-%d")
        if date_str in existing_dates:
            print(f"MODO DIÁRIO — {date_str} já existe. Nada a fazer.")
            sys.exit(0)
        print(f"MODO DIÁRIO — coletando {date_str}")
        dates_to_collect = [date_str]

    if not dates_to_collect:
        print("Nenhuma data nova para coletar.")
        sys.exit(0)

    # ── Coleta e gravação ────────────────────────────────────────────────────
    total      = len(dates_to_collect)
    batch      = []
    rows_added = 0
    errors     = []

    for i, date_str in enumerate(dates_to_collect, 1):
        print(f"  [{i}/{total}] {date_str}...", end=" ", flush=True)
        try:
            m = collect_metrics(ga4_service, date_str)
            batch.append(metrics_to_record(date_str, m))
            rows_added += 1
            print(
                f"sessoes={m['sessoes']:,} "
                f"compras={m['compras']:,} "
                f"CR={m['taxa_conversao_pct']}% "
                f"bounce={m['taxa_rejeicao_pct']}%"
            )
        except Exception as e:
            errors.append((date_str, str(e)))
            print(f"ERRO: {e}")

        # Checkpoint a cada CHECKPOINT_EVERY dias (anti-timeout / perda de dados)
        if historical_mode and len(batch) >= CHECKPOINT_EVERY:
            print(f"  Gravando checkpoint ({rows_added} dias acumulados)...")
            append_records(batch)
            batch = []
            time.sleep(1)

        if historical_mode:
            time.sleep(PAUSE_BETWEEN_DAYS)

    # ── Gravar restante ──────────────────────────────────────────────────────
    if batch:
        print(f"\nGravando {len(batch)} registro(s) finais em {HISTORY_FILE}...")
        append_records(batch)

    # ── Relatório final ──────────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"Registros adicionados : {rows_added}")
    print(f"Erros                 : {len(errors)}")
    if errors:
        print("Datas com erro:")
        for date_str, err in errors:
            print(f"  {date_str}: {err}")
    print("Concluído.")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
