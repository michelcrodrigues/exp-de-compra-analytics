"""
fetch_ga4_app.py — Coleta métricas diárias do GA4 do App e grava em data/history_app.ndjson.

Estrutura análoga ao fetch_ga4.py (site web). Mesmos eventos, mesmo schema —
a diferença é a property (App GA4) e a ausência de rotas (não aplicável ao app).

Modos de operação:
  HISTÓRICO — ativado por FORCE_HISTORICAL_APP=true ou arquivo vazio/inexistente
              coleta de 01/01/2025 até ontem, dia a dia
  DIÁRIO    — padrão; re-coleta sempre os últimos 3 dias (D-1, D-2, D-3)
              para corrigir late-arriving data do GA4 (dados se finalizam em ~72h)

Secrets necessários no GitHub Actions:
  GA4_CREDENTIALS_JSON     → conteúdo do JSON da service account (mesmo do site)
  GA4_APP_PROPERTY_ID      → 256859064

Variáveis opcionais:
  FORCE_HISTORICAL_APP=true  → força modo histórico independente do conteúdo do arquivo
  FORCE_REPROCESS_APP=true   → apaga history_app.ndjson e reprocessa tudo desde jan/2025

Property App GA4:
  Conta:              185942521
  Propriedade:        256859064
  Fluxo Android:      2216517767
  Fluxo iOS:          2216523540
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

GA4_APP_PROPERTY_ID = os.environ.get("GA4_APP_PROPERTY_ID", "256859064")
HISTORY_START       = datetime.date(2025, 1, 1)
HISTORY_FILE        = "data/history_app.ndjson"
CHECKPOINT_EVERY    = 30    # gravar no arquivo a cada N dias coletados
PAUSE_BETWEEN_DAYS  = 0.15  # segundos entre chamadas GA4 no modo histórico
MAX_RETRIES         = 3     # tentativas em caso de erro transitório da API
DAILY_REFRESH_DAYS  = 3     # dias recentes re-coletados no modo diário

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
]

# Schema do App — mesmo schema do site, sem colunas de rotas (top_origem/destino)
# O filtro de dispositivo no app distingue apenas android e ios (mapeados para
# mobile e desktop no schema para manter paridade visual).
COLUMNS = [
    "data",
    "sessoes", "usuarios", "novos_usuarios", "pageviews",
    "compras", "taxa_conversao_pct",
    "taxa_rejeicao_pct", "duracao_media_seg",
    # Dispositivo — android → mobile, ios → desktop, outros → tablet
    "sessoes_mobile", "sessoes_desktop", "sessoes_tablet",
    "compras_mobile", "compras_desktop", "compras_tablet",
    "usuarios_mobile", "usuarios_desktop", "usuarios_tablet",
    "novos_usuarios_mobile", "novos_usuarios_desktop", "novos_usuarios_tablet",
    "taxa_rejeicao_mobile", "taxa_rejeicao_desktop", "taxa_rejeicao_tablet",
    "duracao_media_mobile", "duracao_media_desktop", "duracao_media_tablet",
    # Canal — app não tem canal de aquisição da mesma forma; preenchemos com zeros
    # mas mantemos as colunas para paridade de schema com o site
    "sessoes_organico", "sessoes_direto", "sessoes_pago",
    "sessoes_social", "sessoes_email", "sessoes_referral", "sessoes_outros_canais",
    # Funil total
    "funil_search", "funil_select_item", "funil_add_to_cart",
    "funil_begin_checkout", "funil_purchase",
    # Funil por dispositivo
    "funil_search_mobile", "funil_select_item_mobile", "funil_add_to_cart_mobile",
    "funil_begin_checkout_mobile", "funil_purchase_mobile",
    "funil_search_desktop", "funil_select_item_desktop", "funil_add_to_cart_desktop",
    "funil_begin_checkout_desktop", "funil_purchase_desktop",
    "funil_search_tablet", "funil_select_item_tablet", "funil_add_to_cart_tablet",
    "funil_begin_checkout_tablet", "funil_purchase_tablet",
    # Rotas — não aplicável ao app; preenchidas com strings/zeros vazios
    # mas mantidas para paridade de schema com o validate_schema_app.py
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
    # NPS — total e por plataforma (android=mobile, ios=desktop)
    "nps_respostas", "nps_promotores", "nps_neutros", "nps_detratores", "nps_score", "nps_nota_media",
    "nps_respostas_mobile", "nps_promotores_mobile", "nps_neutros_mobile", "nps_detratores_mobile", "nps_score_mobile", "nps_nota_media_mobile",
    "nps_respostas_desktop", "nps_promotores_desktop", "nps_neutros_desktop", "nps_detratores_desktop", "nps_score_desktop", "nps_nota_media_desktop",
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
# history_app.ndjson — leitura e escrita
# ──────────────────────────────────────────────

def load_existing_dates():
    """Lê o history_app.ndjson e retorna conjunto de datas já gravadas."""
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
                    pass
    return dates


def append_records(records):
    """
    Appenda uma lista de dicts ao history_app.ndjson.
    Cria o arquivo (e o diretório data/) se não existir.
    """
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def reset_history_file():
    """Apaga o history_app.ndjson para FORCE_REPROCESS_APP."""
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
                .runReport(property=f"properties/{GA4_APP_PROPERTY_ID}", body=body)
                .execute()
            )
            return resp.get("rows", [])
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < MAX_RETRIES:
                wait = 2 ** attempt
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
# Mapeamento de plataforma → coluna de dispositivo
#
# No GA4 App, a dimensão operatingSystem retorna "Android", "iOS", etc.
# Mapeamos para o mesmo esquema de colunas do site:
#   android → mobile
#   ios     → desktop
#   outros  → tablet
# Isso preserva paridade de schema e permite que o dashboard
# exiba os filtros "Mobile (Android)" e "Desktop (iOS)" com label customizado.
# ──────────────────────────────────────────────

PLATFORM_MAP = {
    "android": "mobile",
    "ios":     "desktop",
}

def platform_to_dev(platform_str):
    return PLATFORM_MAP.get(platform_str.lower(), "tablet")

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
        m["taxa_rejeicao_pct"] = round(safe_float(v[4]["value"]) * 100, 2)
        m["duracao_media_seg"] = safe_float(v[5]["value"], 2)
        m["pageviews"]         = safe_int(v[6]["value"])
    else:
        for k in ["sessoes", "usuarios", "novos_usuarios", "compras",
                  "taxa_rejeicao_pct", "duracao_media_seg", "pageviews"]:
            m[k] = 0

    m["taxa_conversao_pct"] = calc_cr(m["compras"], m["sessoes"])

    # ── Report 2: métricas por plataforma (Android / iOS) ────────────────────
    for dev in ["mobile", "desktop", "tablet"]:
        m[f"sessoes_{dev}"]        = 0
        m[f"compras_{dev}"]        = 0
        m[f"usuarios_{dev}"]       = 0
        m[f"novos_usuarios_{dev}"] = 0
        m[f"taxa_rejeicao_{dev}"]  = 0.0
        m[f"duracao_media_{dev}"]  = 0.0

    rows = run_report(
        service, date_str,
        ["operatingSystem"],
        ["sessions", "transactions", "totalUsers", "newUsers",
         "bounceRate", "averageSessionDuration"],
    )
    for row in rows:
        platform = row["dimensionValues"][0]["value"]
        dev = platform_to_dev(platform)
        v = row["metricValues"]
        # Acumula caso múltiplas plataformas mapeiem para o mesmo bucket
        m[f"sessoes_{dev}"]        += safe_int(v[0]["value"])
        m[f"compras_{dev}"]        += safe_int(v[1]["value"])
        m[f"usuarios_{dev}"]       += safe_int(v[2]["value"])
        m[f"novos_usuarios_{dev}"] += safe_int(v[3]["value"])
        # bounceRate: média ponderada — usa o maior volume; simplificado com último
        m[f"taxa_rejeicao_{dev}"]   = round(safe_float(v[4]["value"]) * 100, 2)
        m[f"duracao_media_{dev}"]   = round(safe_float(v[5]["value"]), 2)

    # ── Report 3: canal de aquisição do app ──────────────────────────────────
    # No GA4 App, sessionDefaultChannelGroup funciona de forma similar ao web.
    channel_map = {
        "organic search":  "sessoes_organico",
        "direct":          "sessoes_direto",
        "paid search":     "sessoes_pago",
        "organic social":  "sessoes_social",
        "email":           "sessoes_email",
        "referral":        "sessoes_referral",
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

    # ── Report 4b: funil por plataforma ──────────────────────────────────────
    for dev in ["mobile", "desktop", "tablet"]:
        for e in funil_events:
            m[f"funil_{e}_{dev}"] = 0

    rows = run_report(
        service, date_str,
        ["eventName", "operatingSystem"],
        ["eventCount"],
        limit=100,
    )
    for row in rows:
        event    = row["dimensionValues"][0]["value"]
        platform = row["dimensionValues"][1]["value"]
        dev      = platform_to_dev(platform)
        if event in funil_events:
            m[f"funil_{event}_{dev}"] += safe_int(row["metricValues"][0]["value"])

    # ── Rotas — não aplicável ao app (preenchidas com vazio/zero) ────────────
    for i in range(1, 6):
        m[f"top_origem_{i}"]         = ""
        m[f"top_origem_{i}_sessoes"] = 0
        m[f"top_destino_{i}"]        = ""
        m[f"top_destino_{i}_sessoes"] = 0

    # ── Report 7: NPS por plataforma (Android / iOS) ──────────────────────────
    # Evento: nps_response | Dimensão customizada: nps_number (0-10)
    # Quebra: operatingSystem (Android → mobile, iOS → desktop, outros → tablet)
    # Classificação padrão NPS: promotores ≥ 9, neutros 7-8, detratores ≤ 6
    # _nps_soma* são acumuladores internos (score × count) para calcular média — não expostos no schema.
    for dev in ("", "_mobile", "_desktop"):
        m[f"nps_respostas{dev}"]  = 0
        m[f"nps_promotores{dev}"] = 0
        m[f"nps_neutros{dev}"]    = 0
        m[f"nps_detratores{dev}"] = 0
        m[f"nps_score{dev}"]      = 0.0
        m[f"nps_nota_media{dev}"] = 0.0
        m[f"_nps_soma{dev}"]      = 0  # acumulador interno

    rows = run_report(
        service, date_str,
        ["customEvent:nps_number", "operatingSystem"],
        ["eventCount"],
        limit=200,
    )
    for row in rows:
        raw_score = row["dimensionValues"][0]["value"]
        platform  = row["dimensionValues"][1]["value"]
        count     = safe_int(row["metricValues"][0]["value"])

        if raw_score in ("(not set)", "") or count == 0:
            continue

        try:
            score = int(float(raw_score))
        except (ValueError, TypeError):
            continue

        # Categoria NPS padrão
        if score >= 9:
            cat = "promotores"
        elif score >= 7:
            cat = "neutros"
        else:
            cat = "detratores"

        # Acumula total
        m["nps_respostas"] += count
        m[f"nps_{cat}"]    += count
        m["_nps_soma"]     += score * count  # para média ponderada

        # Acumula por plataforma usando o mesmo PLATFORM_MAP (android=mobile, ios=desktop)
        dev_key = PLATFORM_MAP.get(platform.lower())
        if dev_key in ("mobile", "desktop"):
            m[f"nps_respostas_{dev_key}"] += count
            m[f"nps_{cat}_{dev_key}"]     += count
            m[f"_nps_soma_{dev_key}"]     += score * count

    def calc_nps(prom, detr, resp):
        if resp > 0:
            return round((prom - detr) / resp * 100, 2)
        return 0.0

    def calc_media(soma, resp):
        if resp > 0:
            return round(soma / resp, 2)
        return 0.0

    m["nps_score"]         = calc_nps(m["nps_promotores"],         m["nps_detratores"],         m["nps_respostas"])
    m["nps_score_mobile"]  = calc_nps(m["nps_promotores_mobile"],  m["nps_detratores_mobile"],  m["nps_respostas_mobile"])
    m["nps_score_desktop"] = calc_nps(m["nps_promotores_desktop"], m["nps_detratores_desktop"], m["nps_respostas_desktop"])
    m["nps_nota_media"]         = calc_media(m["_nps_soma"],         m["nps_respostas"])
    m["nps_nota_media_mobile"]  = calc_media(m["_nps_soma_mobile"],  m["nps_respostas_mobile"])
    m["nps_nota_media_desktop"] = calc_media(m["_nps_soma_desktop"], m["nps_respostas_desktop"])

    # Remove acumuladores internos antes de retornar (não fazem parte do schema)
    for dev in ("", "_mobile", "_desktop"):
        m.pop(f"_nps_soma{dev}", None)

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
    force_historical = os.environ.get("FORCE_HISTORICAL_APP", "").lower() == "true"
    force_reprocess  = os.environ.get("FORCE_REPROCESS_APP", "").lower() == "true"
    today            = datetime.date.today()
    yesterday        = today - datetime.timedelta(days=1)

    print(f"GA4 App Property ID: {GA4_APP_PROPERTY_ID}")
    print("Autenticando...")
    creds       = get_credentials()
    ga4_service = get_ga4_service(creds)

    if force_reprocess:
        print("FORCE_REPROCESS_APP=true — apagando history_app.ndjson e reprocessando tudo.")
        reset_history_file()
        force_historical = True

    existing_dates = load_existing_dates()
    print(f"Datas já no history_app.ndjson: {len(existing_dates)}")

    historical_mode = force_historical or len(existing_dates) == 0

    if historical_mode:
        reason = "forçado via FORCE_HISTORICAL_APP=true" if force_historical else "arquivo vazio/inexistente"
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
        est_min    = round(total_days * (5 * 0.4 + PAUSE_BETWEEN_DAYS) / 60, 1)
        print(f"  {total_days} dias para coletar — estimativa: ~{est_min} min")

    else:
        dates_to_collect = []
        for lag in range(1, DAILY_REFRESH_DAYS + 1):
            d = today - datetime.timedelta(days=lag)
            if d >= HISTORY_START:
                dates_to_collect.append(d.strftime("%Y-%m-%d"))

        print(f"MODO DIÁRIO — re-coletando {len(dates_to_collect)} dia(s) recentes: {', '.join(dates_to_collect)}")

    if not dates_to_collect:
        print("Nenhuma data para coletar.")
        sys.exit(0)

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
                f"CR={m['taxa_conversao_pct']}%"
            )
        except Exception as e:
            errors.append((date_str, str(e)))
            print(f"ERRO: {e}")

        if historical_mode and len(batch) >= CHECKPOINT_EVERY:
            print(f"  Gravando checkpoint ({rows_added} dias acumulados)...")
            append_records(batch)
            batch = []
            time.sleep(1)

        if historical_mode:
            time.sleep(PAUSE_BETWEEN_DAYS)

    if batch:
        print(f"\nGravando {len(batch)} registro(s) em {HISTORY_FILE}...")
        append_records(batch)

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
