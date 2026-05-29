"""
export_data.py — Lê o Google Sheets e gera data.json para o dashboard.

Roda no GitHub Actions após o fetch_ga4.py, ou pode rodar separado.
O data.json é commitado no repositório e servido pelo GitHub Pages.

Secrets necessários:
  GA4_CREDENTIALS_JSON  → service account com acesso ao Sheets
  SPREADSHEET_ID        → ID da planilha
"""

import os
import json
import sys
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

SHEET_TAB_NAME = "analytics"
OUTPUT_PATH    = "data.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

def get_credentials():
    creds_info = json.loads(os.environ["GA4_CREDENTIALS_JSON"])
    return service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )

def read_sheet(sheets, spreadsheet_id):
    result = sheets.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{SHEET_TAB_NAME}",  # sem limites — lê a aba inteira
    ).execute()
    rows = result.get("values", [])
    if not rows:
        raise ValueError("Planilha vazia.")
    headers = rows[0]
    records = []
    for row in rows[1:]:
        # preencher colunas faltantes com None
        padded = row + [None] * (len(headers) - len(row))
        records.append(dict(zip(headers, padded)))
    return headers, records

def safe_float(v, default=0.0):
    try:
        # Normaliza vírgula decimal — Google Sheets locale pt-BR retorna '62,5'
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return default

def safe_int(v, default=0):
    try:
        # Normaliza vírgula decimal antes de converter
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return default

def build_data_json(records):
    """
    Transforma os registros da planilha em data.json estruturado para o dashboard.
    Mantém todos os dados brutos + agrega totais por período para os filtros.
    """
    # Ordenar por data
    records = sorted(records, key=lambda r: r.get("data", ""))

    # ── Dados diários brutos (para gráficos de linha e filtros) ──────────────
    daily = []
    for r in records:
        daily.append({
            "data":               r.get("data", ""),
            # Volume
            "sessoes":            safe_int(r.get("sessoes")),
            "usuarios":           safe_int(r.get("usuarios")),
            "novos_usuarios":     safe_int(r.get("novos_usuarios")),
            "pageviews":          safe_int(r.get("pageviews")),
            # Conversão
            "compras":            safe_int(r.get("compras")),
            "taxa_conversao_pct": safe_float(r.get("taxa_conversao_pct")),
            # Engajamento
            "taxa_rejeicao_pct":  safe_float(r.get("taxa_rejeicao_pct")),
            "duracao_media_seg":  safe_float(r.get("duracao_media_seg")),
            # Dispositivo
            "sessoes_mobile":     safe_int(r.get("sessoes_mobile")),
            "sessoes_desktop":    safe_int(r.get("sessoes_desktop")),
            "sessoes_tablet":     safe_int(r.get("sessoes_tablet")),
            "compras_mobile":     safe_int(r.get("compras_mobile")),
            "compras_desktop":    safe_int(r.get("compras_desktop")),
            "compras_tablet":     safe_int(r.get("compras_tablet")),
            # Canal
            "sessoes_organico":       safe_int(r.get("sessoes_organico")),
            "sessoes_direto":         safe_int(r.get("sessoes_direto")),
            "sessoes_pago":           safe_int(r.get("sessoes_pago")),
            "sessoes_social":         safe_int(r.get("sessoes_social")),
            "sessoes_email":          safe_int(r.get("sessoes_email")),
            "sessoes_referral":       safe_int(r.get("sessoes_referral")),
            "sessoes_outros_canais":  safe_int(r.get("sessoes_outros_canais")),
            # Funil
            "funil_search":         safe_int(r.get("funil_search")),
            "funil_select_item":    safe_int(r.get("funil_select_item")),
            "funil_add_to_cart":    safe_int(r.get("funil_add_to_cart")),
            "funil_begin_checkout": safe_int(r.get("funil_begin_checkout")),
            "funil_purchase":       safe_int(r.get("funil_purchase")),
            # Rotas
            "top_origem_1": r.get("top_origem_1") or "",
            "top_origem_1_sessoes": safe_int(r.get("top_origem_1_sessoes")),
            "top_origem_2": r.get("top_origem_2") or "",
            "top_origem_2_sessoes": safe_int(r.get("top_origem_2_sessoes")),
            "top_origem_3": r.get("top_origem_3") or "",
            "top_origem_3_sessoes": safe_int(r.get("top_origem_3_sessoes")),
            "top_origem_4": r.get("top_origem_4") or "",
            "top_origem_4_sessoes": safe_int(r.get("top_origem_4_sessoes")),
            "top_origem_5": r.get("top_origem_5") or "",
            "top_origem_5_sessoes": safe_int(r.get("top_origem_5_sessoes")),
            "top_destino_1": r.get("top_destino_1") or "",
            "top_destino_1_sessoes": safe_int(r.get("top_destino_1_sessoes")),
            "top_destino_2": r.get("top_destino_2") or "",
            "top_destino_2_sessoes": safe_int(r.get("top_destino_2_sessoes")),
            "top_destino_3": r.get("top_destino_3") or "",
            "top_destino_3_sessoes": safe_int(r.get("top_destino_3_sessoes")),
            "top_destino_4": r.get("top_destino_4") or "",
            "top_destino_4_sessoes": safe_int(r.get("top_destino_4_sessoes")),
            "top_destino_5": r.get("top_destino_5") or "",
            "top_destino_5_sessoes": safe_int(r.get("top_destino_5_sessoes")),
        })

    return {
        "gerado_em": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_dias": len(daily),
        "daily": daily,
        "insights": [],  # preenchido pelo Claude Cowork semanalmente
    }

def load_existing_insights():
    """Lê os insights já gravados no data.json para não apagá-los."""
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        insights = existing.get("insights", [])
        if insights:
            print(f"  Preservando {len(insights)} insight(s) existentes.")
        return insights
    except Exception:
        return []


def main():
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        print("ERRO: variável SPREADSHEET_ID não definida ou vazia.")
        sys.exit(1)

    print("Autenticando...")
    creds  = get_credentials()
    sheets = build("sheets", "v4", credentials=creds)

    print("Lendo planilha...")
    headers, records = read_sheet(sheets, spreadsheet_id)
    print(f"  {len(records)} linhas lidas, {len(headers)} colunas")

    # Preservar insights gerados pelo Claude Cowork
    existing_insights = load_existing_insights()

    print("Gerando data.json...")
    data = build_data_json(records)
    data["insights"] = existing_insights  # restaurar insights preservados

    # Validar que o JSON é serializável antes de gravar
    try:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"ERRO: falha ao serializar data.json — {e}")
        sys.exit(1)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(payload)

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"  data.json gerado: {size_kb:.1f} KB, {data['total_dias']} dias, {len(existing_insights)} insights")
    print("Concluído.")

if __name__ == "__main__":
    main()
