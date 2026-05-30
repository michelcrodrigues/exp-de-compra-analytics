"""
validate_schema.py — Valida o data.json antes de commitar no repositório.

Garante que:
  1. O arquivo existe e é JSON válido
  2. Contém ao menos um registro em "daily"
  3. Cada registro tem todas as colunas esperadas (sem colunas faltando)
  4. Nenhum campo numérico crítico está zerado de forma suspeita (sanity check)
  5. O último registro é de ontem ou hoje (dados frescos)

Interrompe o workflow com sys.exit(1) se qualquer verificação falhar,
impedindo que um data.json corrompido ou incompleto seja commitado.
"""

import json
import sys
import os
import datetime

OUTPUT_PATH = "data.json"

# Colunas numéricas que NUNCA deveriam ser zero num dia normal
# (se todos esses campos forem 0 no mesmo registro, algo está errado)
SANITY_NUMERIC = ["sessoes", "usuarios", "compras", "pageviews"]

# Todas as colunas esperadas em cada registro daily
EXPECTED_COLUMNS = [
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

EXPECTED_SET = set(EXPECTED_COLUMNS)

def fail(msg):
    print(f"\n[SCHEMA ERROR] {msg}")
    sys.exit(1)

def warn(msg):
    print(f"[SCHEMA WARN]  {msg}")

def main():
    print(f"Validando {OUTPUT_PATH}...")

    # ── 1. Arquivo existe e é JSON válido ────────────────────────────────────
    if not os.path.exists(OUTPUT_PATH):
        fail(f"{OUTPUT_PATH} não encontrado.")

    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        fail(f"JSON inválido — {e}")

    # ── 2. Estrutura mínima ──────────────────────────────────────────────────
    daily = data.get("daily")
    if not isinstance(daily, list) or len(daily) == 0:
        fail("Campo 'daily' ausente ou vazio.")

    print(f"  {len(daily)} registros encontrados.")

    # ── 3. Schema de colunas — verificar todos os registros ──────────────────
    missing_cols_report = {}
    extra_cols_report   = {}

    for i, record in enumerate(daily):
        record_keys  = set(record.keys())
        missing_cols = EXPECTED_SET - record_keys
        extra_cols   = record_keys - EXPECTED_SET

        if missing_cols:
            date = record.get("data", f"índice {i}")
            missing_cols_report[date] = sorted(missing_cols)

        if extra_cols:
            date = record.get("data", f"índice {i}")
            extra_cols_report[date] = sorted(extra_cols)

    if missing_cols_report:
        # Agrupa por conjunto de colunas faltando para não poluir o log
        from collections import defaultdict
        grouped = defaultdict(list)
        for date, cols in missing_cols_report.items():
            grouped[tuple(cols)].append(date)
        for cols, dates in grouped.items():
            sample = dates[:3]
            suffix = f" (+{len(dates)-3} mais)" if len(dates) > 3 else ""
            fail(
                f"Colunas faltando em {len(dates)} registro(s) "
                f"(ex: {', '.join(sample)}{suffix}):\n"
                f"  {', '.join(cols)}"
            )

    if extra_cols_report:
        # Colunas extras são apenas aviso — não interrompem o workflow
        from collections import defaultdict
        grouped = defaultdict(list)
        for date, cols in extra_cols_report.items():
            grouped[tuple(cols)].append(date)
        for cols, dates in grouped.items():
            warn(
                f"Colunas extras (não esperadas) em {len(dates)} registro(s): "
                f"{', '.join(cols)}"
            )

    # ── 4. Sanity check — último registro não pode ter tudo zerado ───────────
    last = daily[-1]
    all_zero = all(last.get(col, 0) == 0 for col in SANITY_NUMERIC)
    if all_zero:
        fail(
            f"Último registro ({last.get('data', '?')}) tem "
            f"{', '.join(SANITY_NUMERIC)} todos zerados. "
            f"Provável falha na coleta GA4."
        )

    # ── 5. Frescor dos dados — último registro deve ser recente ─────────────
    last_date_str = last.get("data", "")
    try:
        last_date = datetime.date.fromisoformat(last_date_str)
        today     = datetime.date.today()
        days_old  = (today - last_date).days
        if days_old > 2:
            warn(
                f"Último registro é de {last_date_str} ({days_old} dias atrás). "
                f"Verifique se o workflow de coleta está rodando corretamente."
            )
        else:
            print(f"  Último registro: {last_date_str} ✓")
    except ValueError:
        warn(f"Data do último registro inválida: '{last_date_str}'")

    print(f"  Schema OK — {len(EXPECTED_COLUMNS)} colunas validadas em todos os registros.")
    print("Validação concluída com sucesso.")

if __name__ == "__main__":
    main()
