#!/usr/bin/env python3
"""
migrate_insights.py — Migração de schema para Loop de Aprendizado v1

Campos adicionados em cada item de insight:
  - id: INS-YYYY-NNN (YYYY = ano da semana, NNN = sequencial global do mais antigo)
  - tipo_acao: "monitorar" (default para insights antigos)
  - criterio_confirmacao: null
  - status: "nunca_testada"
  - experimento_id: null
  - revisao: null

Campos adicionados na raiz do data.json:
  - experimentos: []
  - resumo_mensal: []
"""
import json
import re
import os
import sys

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data.json')


def main():
    if not os.path.exists(DATA_PATH):
        print(f"Erro: {DATA_PATH} nao encontrado.")
        sys.exit(1)

    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    added_root = []
    if 'experimentos' not in data:
        data['experimentos'] = []
        added_root.append('experimentos')
    if 'resumo_mensal' not in data:
        data['resumo_mensal'] = []
        added_root.append('resumo_mensal')
    if added_root:
        print(f"  Chaves raiz adicionadas: {', '.join(added_root)}")

    insights = data.get('insights', [])
    if not insights:
        print("Nenhum insight encontrado. Nada a migrar.")
    else:
        pattern = re.compile(r'INS-\d{4}-(\d{3})')
        nums = [int(m.group(1)) for w in insights for item in w.get('items', [])
                if (m := pattern.match(item.get('id', '')))]
        next_num = max(nums) + 1 if nums else 1

        weeks_sorted = sorted(insights, key=lambda w: w.get('semana', ''))

        total_migrated = 0
        for week in weeks_sorted:
            semana = week.get('semana', '2026')
            year = semana[:4] if semana else '2026'

            for item in week.get('items', []):
                changed = False
                if not item.get('id'):
                    item['id'] = f'INS-{year}-{next_num:03d}'
                    next_num += 1
                    changed = True
                if 'tipo_acao' not in item:
                    item['tipo_acao'] = 'monitorar'
                    changed = True
                if 'criterio_confirmacao' not in item:
                    item['criterio_confirmacao'] = None
                    changed = True
                if 'status' not in item:
                    item['status'] = 'nunca_testada'
                    changed = True
                if 'experimento_id' not in item:
                    item['experimento_id'] = None
                    changed = True
                if 'revisao' not in item:
                    item['revisao'] = None
                    changed = True
                if changed:
                    total_migrated += 1

        total_items = sum(len(w.get('items', [])) for w in insights)
        print(f"  {total_items} insights no total, {total_migrated} atualizados.")

    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Migracao concluida.")
    print(f"   experimentos: {len(data['experimentos'])}, resumo_mensal: {len(data['resumo_mensal'])}")


if __name__ == '__main__':
    main()
