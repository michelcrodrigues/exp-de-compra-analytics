"""
validate_schema.py â Valida o data.json (e insights.json se existir) antes de commitar.

Garante que:
  1. O arquivo existe e e JSON valido
  2. Contem ao menos um registro em "daily"
  3. Cada registro tem todas as colunas esperadas (sem colunas faltando)
  4. Nenhum campo numerico critico esta zerado de forma suspeita (sanity check)
  5. O ultimo registro e de ontem ou hoje (dados frescos)
  6. Arrays raiz 'experimentos' e 'resumo_mensal' existem
  7. Todos os insights tem campos obrigatorios, IDs validos e unicos
  8. criterio_confirmacao obrigatorio quando tipo_acao=testar e status!=nunca_testada
  9. Quando tipo_acao=testar e testavel=true, experimento_template nao pode ser null [fail]
  10. O ID em experimento_template.id deve ter o mesmo numero do INS-YYYY-NNN pai [fail]
  11. Campos individuais (evidencia, diagnostico, plano_acao, impacto, acompanhamento)
      devem existir em insights novos -- emite warn (nao fail) para manter compatibilidade.
"""

import json
import sys
import os
import re
import datetime
from collections import Counter, defaultdict

OUTPUT_PATH   = "data.json"
INSIGHTS_PATH = "insights.json"

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
    "compras_organico", "compras_direto", "compras_pago",
    "compras_social", "compras_email", "compras_referral", "compras_outros_canais",
    # Funil total — estrutura atualizada (8 etapas, na ordem do fluxo real)
    "funil_search", "funil_view_result_search", "funil_select_item",
    "funil_seat_selection", "funil_add_to_cart", "funil_login_checkout",
    "funil_begin_checkout", "funil_purchase",
    # Funil por dispositivo
    "funil_search_mobile", "funil_view_result_search_mobile", "funil_select_item_mobile",
    "funil_seat_selection_mobile", "funil_add_to_cart_mobile", "funil_login_checkout_mobile",
    "funil_begin_checkout_mobile", "funil_purchase_mobile",
    "funil_search_desktop", "funil_view_result_search_desktop", "funil_select_item_desktop",
    "funil_seat_selection_desktop", "funil_add_to_cart_desktop", "funil_login_checkout_desktop",
    "funil_begin_checkout_desktop", "funil_purchase_desktop",
    "funil_search_tablet", "funil_view_result_search_tablet", "funil_select_item_tablet",
    "funil_seat_selection_tablet", "funil_add_to_cart_tablet", "funil_login_checkout_tablet",
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
    # NPS
    "nps_respostas", "nps_promotores", "nps_neutros", "nps_detratores", "nps_score", "nps_nota_media",
    "nps_respostas_mobile", "nps_promotores_mobile", "nps_neutros_mobile", "nps_detratores_mobile", "nps_score_mobile", "nps_nota_media_mobile",
    "nps_respostas_desktop", "nps_promotores_desktop", "nps_neutros_desktop", "nps_detratores_desktop", "nps_score_desktop", "nps_nota_media_desktop",
]

EXPECTED_SET = set(EXPECTED_COLUMNS)

INS_ID_PATTERN     = re.compile(r'^INS-\d{4}-(\d{3})$')
INS_EXP_ID_PATTERN = re.compile(r'^INS-\d{4}-(\d{3})$')
EXP_ID_PATTERN     = re.compile(r'^EXP-\d{4}-\d{3}$')

REQUIRED_INSIGHT_FIELDS_LEGACY = ['id', 'tipo_acao', 'status', 'revisao', 'experimento_id']
INSIGHT_STRUCTURED_FIELDS      = ['evidencia', 'diagnostico', 'plano_acao', 'impacto', 'acompanhamento']
STRUCTURED_FIELDS_CUTOFF       = "2026-06-10"


def fail(msg):
    print(f"\n[SCHEMA ERROR] {msg}")
    sys.exit(1)


def warn(msg):
    print(f"[SCHEMA WARN]  {msg}")


def _validate_insight_items(weeks, source_label):
    all_ids = []
    errors  = []

    for week in weeks:
        for item in (week.get('items') or []):
            ins_id = item.get('id', '')

            missing = [f for f in REQUIRED_INSIGHT_FIELDS_LEGACY if f not in item]
            if missing:
                errors.append(
                    f"[{source_label}] Insight '{ins_id or '?'}' sem campos obrigatorios: "
                    f"{', '.join(missing)}"
                )

            ins_num = None
            if ins_id:
                m = INS_ID_PATTERN.match(ins_id)
                if not m:
                    errors.append(
                        f"[{source_label}] ID de insight invalido: '{ins_id}' "
                        f"(esperado INS-YYYY-NNN)"
                    )
                else:
                    ins_num = m.group(1)
                    all_ids.append(ins_id)

            if (item.get('tipo_acao') == 'testar'
                    and item.get('status') not in ('nunca_testada', None)
                    and item.get('criterio_confirmacao') is None):
                errors.append(
                    f"[{source_label}] Insight {ins_id}: tipo_acao='testar' e "
                    f"status='{item.get('status')}' mas criterio_confirmacao e null."
                )

            if item.get('tipo_acao') == 'testar' and item.get('testavel') is True:
                if item.get('experimento_template') is None:
                    errors.append(
                        f"[{source_label}] Insight {ins_id}: testavel=true mas "
                        f"experimento_template e null."
                    )
                else:
                    tmpl = item['experimento_template']
                    if not isinstance(tmpl, dict):
                        warn(
                            f"[{source_label}] Insight {ins_id}: experimento_template e uma "
                            f"string em vez de objeto (formato legado) -- esperado objeto com "
                            f"campo 'id'. Ignorando validacao de template."
                        )
                        tmpl = None
                    if tmpl is not None:
                        tmpl_id = tmpl.get('id', '')
                        m_exp   = INS_EXP_ID_PATTERN.match(tmpl_id) if tmpl_id else None
                        if not m_exp:
                            if not tmpl_id:
                                warn(
                                    f"[{source_label}] Insight {ins_id}: experimento_template.id "
                                    f"vazio (template incompleto -- esperado INS-YYYY-NNN)."
                                )
                            else:
                                errors.append(
                                    f"[{source_label}] Insight {ins_id}: experimento_template.id "
                                    f"'{tmpl_id}' invalido (esperado INS-YYYY-NNN)."
                                )
                        elif ins_num and m_exp.group(1) != ins_num:
                            errors.append(
                                f"[{source_label}] Insight {ins_id}: numero do "
                                f"experimento_template.id ({m_exp.group(1)}) diverge do "
                                f"numero do insight ({ins_num}). Devem ser iguais."
                            )

            item_date = item.get('data', '')
            is_new    = bool(item_date) and item_date >= STRUCTURED_FIELDS_CUTOFF
            if is_new:
                missing_struct = [f for f in INSIGHT_STRUCTURED_FIELDS if not item.get(f)]
                if missing_struct:
                    warn(
                        f"[{source_label}] Insight {ins_id} (data={item_date}): "
                        f"campos estruturados ausentes: {', '.join(missing_struct)}."
                    )

    return all_ids, errors


def main():
    print(f"Validando {OUTPUT_PATH}...")

    if not os.path.exists(OUTPUT_PATH):
        fail(f"{OUTPUT_PATH} nao encontrado.")

    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        fail(f"JSON invalido -- {e}")

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
            date = record.get("data", f"indice {i}")
            missing_cols_report[date] = sorted(missing_cols)

        if extra_cols:
            date = record.get("data", f"indice {i}")
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
                f"Colunas extras (nao esperadas) em {len(dates)} registro(s): "
                f"{', '.join(cols)}"
            )

    last     = daily[-1]
    all_zero = all(last.get(col, 0) == 0 for col in SANITY_NUMERIC)
    if all_zero:
        fail(
            f"Ultimo registro ({last.get('data', '?')}) tem "
            f"{', '.join(SANITY_NUMERIC)} todos zerados. "
            f"Provavel falha na coleta GA4."
        )

    last_date_str = last.get("data", "")
    try:
        last_date = datetime.date.fromisoformat(last_date_str)
        today     = datetime.date.today()
        days_old  = (today - last_date).days
        if days_old > 2:
            warn(
                f"Ultimo registro e de {last_date_str} ({days_old} dias atras). "
                f"Verifique se o workflow de coleta esta rodando corretamente."
            )
        else:
            print(f"  Ultimo registro: {last_date_str} ok")
    except ValueError:
        warn(f"Data do ultimo registro invalida: '{last_date_str}'")

    if 'experimentos' not in data:
        fail("Chave 'experimentos' ausente no data.json.")
    if not isinstance(data['experimentos'], list):
        fail("Campo 'experimentos' deve ser um array.")
    if 'resumo_mensal' not in data:
        fail("Chave 'resumo_mensal' ausente no data.json.")
    if not isinstance(data['resumo_mensal'], list):
        fail("Campo 'resumo_mensal' deve ser um array.")

    legacy_insights = data.get('insights', [])
    if isinstance(legacy_insights, list) and legacy_insights:
        ids, errors = _validate_insight_items(legacy_insights, "data.json")
        for err in errors[:5]:
            fail(err)
        dupes = [id_ for id_, count in Counter(ids).items() if count > 1]
        if dupes:
            fail(f"IDs de insight duplicados em data.json: {', '.join(dupes)}")
        total = sum(len(w.get('items', [])) for w in legacy_insights)
        print(f"  {total} insights (data.json) validados.")

    for exp in data.get('experimentos', []):
        exp_id = exp.get('id', '')
        if exp_id and not EXP_ID_PATTERN.match(exp_id):
            fail(f"ID de experimento invalido: '{exp_id}' (esperado EXP-YYYY-NNN)")
        for req in ['id', 'insight_id', 'titulo', 'status']:
            if not exp.get(req):
                warn(f"Experimento '{exp_id or '?'}' sem campo '{req}'.")

    print(f"  Schema OK -- {len(EXPECTED_COLUMNS)} colunas validadas em todos os registros.")

    if os.path.exists(INSIGHTS_PATH):
        print(f"\nValidando {INSIGHTS_PATH}...")
        try:
            with open(INSIGHTS_PATH, "r", encoding="utf-8") as f:
                ins_data = json.load(f)
        except json.JSONDecodeError as e:
            fail(f"insights.json -- JSON invalido: {e}")

        if 'insights' not in ins_data or not isinstance(ins_data['insights'], list):
            fail("insights.json: chave 'insights' ausente ou nao e array.")

        ins_weeks   = ins_data['insights']
        ids, errors = _validate_insight_items(ins_weeks, "insights.json")
        for err in errors[:5]:
            fail(err)

        dupes = [id_ for id_, count in Counter(ids).items() if count > 1]
        if dupes:
            fail(f"IDs de insight duplicados em insights.json: {', '.join(dupes)}")

        total = sum(len(w.get('items', [])) for w in ins_weeks)
        print(f"  {total} insights validados em {len(ins_weeks)} semana(s) ok")
    else:
        warn(f"{INSIGHTS_PATH} nao encontrado -- pulando validacao de insights.json.")

    print("\nValidacao concluida com sucesso.")


if __name__ == "__main__":
    main()
