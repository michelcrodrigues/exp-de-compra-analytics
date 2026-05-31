"""
validate_schema.py — Valida o data.json antes de commitar no repositório.

Garante que:
  1. O arquivo existe e é JSON válido
  2. Contém ao menos um registro em "daily"
  3. Cada registro tem todas as colunas esperadas (sem colunas faltando)
  4. Nenhum campo numérico crítico está zerado de forma suspeita (sanity check)
  5. O último registro é de ontem ou hoje (dados frescos)
  6. Arrays raiz 'experimentos' e 'resumo_mensal' existem
  7. Todos os insights têm campos obrigatórios, IDs válidos e únicos
  8. criterio_confirmacao obrigatório quando tipo_acao=testar e status!=nunca_testada

Interrompe o workflow com sys.exit(1) se qualquer verificação falhar,
impedindo que um data.json corrompido ou incompleto seja commitado.
"""

import json
import sys
import os
import re
import datetime
from collections import Counter, defaultdict

OUTPUT_PATH = "data.json"

SANITY_NUMERIC = ["sessoes", "usuarios", "compras", "pageviews"]

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

INS_ID_PATTERN = re.compile(r'^INS-\d{4}-\d{3}$')
EXP_ID_PATTERN = re.compile(r'^EXP-\d{4}-\d{3}$')
REQUIRED_INSIGHT_FIELDS = ['id', 'tipo_acao', 'status', 'revisao', 'experimento_id']


def fail(msg):
    print(f"\n[SCHEMA ERROR] {msg}")
    sys.exit(1)


def warn(msg):
    print(f"[SCHEMA WARN]  {msg}")


def main():
    print(f"Validando {OUTPUT_PATH}...")

    if not os.path.exists(OUTPUT_PATH):
        fail(f"{OUTPUT_PATH} não encontrado.")

    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        fail(f"JSON inválido — {e}")

    daily = data.get("daily")
    if not isinstance(daily, list) or len(daily) == 0:
        fail("Campo 'daily' ausente ou vazio.")

    print(f"  {len(daily)} registros encontrados.")

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
        grouped = defaultdict(list)
        for date, cols in extra_cols_report.items():
            grouped[tuple(cols)].append(date)
        for cols, dates in grouped.items():
            warn(
                f"Colunas extras (não esperadas) em {len(dates)} registro(s): "
                f"{', '.join(cols)}"
            )

    last = daily[-1]
    all_zero = all(last.get(col, 0) == 0 for col in SANITY_NUMERIC)
    if all_zero:
        fail(
            f"Último registro ({last.get('data', '?')}) tem "
            f"{', '.join(SANITY_NUMERIC)} todos zerados. "
            f"Provável falha na coleta GA4."
        )

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

    # ── 6. Arrays raiz do Loop de Aprendizado ────────────────────────────────
    if 'experimentos' not in data:
        fail("Chave 'experimentos' ausente no data.json. Execute scripts/migrate_insights.py.")
    if not isinstance(data['experimentos'], list):
        fail("Campo 'experimentos' deve ser um array.")
    if 'resumo_mensal' not in data:
        fail("Chave 'resumo_mensal' ausente no data.json. Execute scripts/migrate_insights.py.")
    if not isinstance(data['resumo_mensal'], list):
        fail("Campo 'resumo_mensal' deve ser um array.")

    # ── 7. Validar insights ──────────────────────────────────────────────────
    insights = data.get('insights', [])
    if isinstance(insights, list) and insights:
        all_insight_ids = []
        insight_errors = []

        for week in insights:
            for item in (week.get('items') or []):
                ins_id = item.get('id', '')

                missing = [f for f in REQUIRED_INSIGHT_FIELDS if f not in item]
                if missing:
                    insight_errors.append(
                        f"Insight '{ins_id or '?'}' sem campos obrigatórios: {', '.join(missing)}"
                    )

                if ins_id:
                    if not INS_ID_PATTERN.match(ins_id):
                        insight_errors.append(
                            f"ID de insight inválido: '{ins_id}' (esperado INS-YYYY-NNN)"
                        )
                    else:
                        all_insight_ids.append(ins_id)

                if (item.get('tipo_acao') == 'testar'
                        and item.get('status') not in ('nunca_testada', None)
                        and item.get('criterio_confirmacao') is None):
                    insight_errors.append(
                        f"Insight {ins_id}: tipo_acao='testar' e status='{item.get('status')}' "
                        f"mas criterio_confirmacao é null — preencha o critério."
                    )

        for err in insight_errors[:5]:
            fail(err)

        dupes = [id_ for id_, count in Counter(all_insight_ids).items() if count > 1]
        if dupes:
            fail(f"IDs de insight duplicados: {', '.join(dupes)}")

        total_insights = sum(len(w.get('items', [])) for w in insights)
        print(f"  {total_insights} insights validados (IDs únicos, campos obrigatórios OK).")

    for exp in data.get('experimentos', []):
        exp_id = exp.get('id', '')
        if exp_id and not EXP_ID_PATTERN.match(exp_id):
            fail(f"ID de experimento inválido: '{exp_id}' (esperado EXP-YYYY-NNN)")

    print(f"  Schema OK — {len(EXPECTED_COLUMNS)} colunas validadas em todos os registros.")
    print("Validação concluída com sucesso.")


if __name__ == "__main__":
    main()
