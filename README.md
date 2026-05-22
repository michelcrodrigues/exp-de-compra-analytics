# Analytics Dashboard — GA4 + GitHub Pages + Claude.ai

Dashboard de métricas do Google Analytics 4, atualizado automaticamente todo dia via GitHub Actions,
com insights gerados manualmente via Claude.ai (plano Team, sem custo adicional de API).

---

## Arquitetura

```
Google Analytics 4
       │
       │  GA4 Data API (gratuito)
       ▼
GitHub Actions (cron diário às 08h BRT)
       │
       │  Python script → data.json
       ▼
GitHub Pages  ←  index.html lê data.json
       │
       └──  Insights  ←  Claude.ai (manual, plano Team)
```

**Custo total: R$ 0** (além do plano Team que você já tem)

---

## Passo a passo completo

### ETAPA 1 — Criar o repositório no GitHub

1. Acesse [github.com](https://github.com) e clique em **New repository**
2. Preencha:
   - **Repository name:** `analytics-dashboard` (ou o nome que preferir)
   - **Visibility:** Private (recomendado) ou Public
   - Marque **Add a README file**
3. Clique em **Create repository**

---

### ETAPA 2 — Subir os arquivos do projeto

No repositório criado, suba os seguintes arquivos (arraste e solte ou use git):

```
analytics-dashboard/
├── .github/
│   └── workflows/
│       └── update-data.yml
├── scripts/
│   └── fetch_ga4.py
├── index.html
└── data.json
```

Para subir via interface do GitHub:
1. Clique em **Add file → Upload files**
2. Arraste todos os arquivos respeitando a estrutura de pastas
3. Clique em **Commit changes**

Para criar as pastas `.github/workflows/` pela interface:
1. Clique em **Add file → Create new file**
2. No campo de nome, digite `.github/workflows/update-data.yml`
3. Cole o conteúdo do arquivo e confirme

---

### ETAPA 3 — Criar a conta de serviço no Google Cloud

O script precisa de uma conta de serviço para autenticar na GA4 API.

#### 3.1 — Criar projeto no Google Cloud

1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. No topo, clique no seletor de projetos → **New Project**
3. Nome: `analytics-dashboard` → **Create**

#### 3.2 — Ativar a GA4 Data API

1. No menu lateral, vá em **APIs & Services → Library**
2. Pesquise por `Google Analytics Data API`
3. Clique no resultado → **Enable**

#### 3.3 — Criar a conta de serviço

1. Vá em **APIs & Services → Credentials**
2. Clique em **Create Credentials → Service account**
3. Preencha:
   - **Service account name:** `ga4-dashboard`
   - **Service account ID:** será preenchido automaticamente
4. Clique em **Create and Continue** → **Done** (sem precisar adicionar roles)

#### 3.4 — Gerar a chave JSON

1. Na lista de contas de serviço, clique na que você acabou de criar
2. Vá na aba **Keys**
3. Clique em **Add Key → Create new key**
4. Selecione **JSON** → **Create**
5. O arquivo `.json` será baixado automaticamente — **guarde-o com segurança**

---

### ETAPA 4 — Dar acesso ao Google Analytics

1. Acesse [analytics.google.com](https://analytics.google.com)
2. Clique no ícone de engrenagem (Admin) no canto inferior esquerdo
3. Na coluna **Property**, clique em **Property Access Management**
4. Clique no botão **+** (Add users)
5. No campo de e-mail, cole o e-mail da conta de serviço
   - Ele termina com `@<projeto>.iam.gserviceaccount.com`
   - Está visível na tela de detalhes da conta no Google Cloud Console
6. Selecione a role **Viewer** (leitura é suficiente)
7. Clique em **Add**

#### 4.1 — Pegar o Property ID

1. No Google Analytics, vá em **Admin → Property Settings**
2. Copie o **Property ID** (número de 9 dígitos, ex: `123456789`)

---

### ETAPA 5 — Configurar os Secrets no GitHub

Os secrets guardam as credenciais de forma segura — nunca ficam expostos no código.

1. No repositório do GitHub, vá em **Settings → Secrets and variables → Actions**
2. Clique em **New repository secret** e crie **dois secrets**:

#### Secret 1: `GA4_PROPERTY_ID`
- **Name:** `GA4_PROPERTY_ID`
- **Value:** o número do Property ID copiado no passo 4.1 (ex: `123456789`)

#### Secret 2: `GA4_CREDENTIALS_JSON`
- **Name:** `GA4_CREDENTIALS_JSON`
- **Value:** o conteúdo completo do arquivo JSON baixado no passo 3.4
  - Abra o arquivo em um editor de texto
  - Selecione tudo (Ctrl+A) e copie
  - Cole no campo Value

---

### ETAPA 6 — Ajustar os paths do funil

No arquivo `scripts/fetch_ga4.py`, localize a variável `FUNNEL_STEPS` (linha ~85)
e substitua pelos paths reais do seu funil:

```python
FUNNEL_STEPS = [
    {"name": "Página Inicial",  "path": "/"},
    {"name": "Produto / Lista", "path": "/produtos"},     # ← ajuste
    {"name": "Carrinho",        "path": "/carrinho"},     # ← ajuste
    {"name": "Checkout",        "path": "/checkout"},     # ← ajuste
    {"name": "Confirmação",     "path": "/obrigado"},     # ← ajuste
]
```

Para descobrir os paths corretos, acesse o GA4 → **Reports → Pages and screens**
e veja os caminhos das páginas do seu funil.

---

### ETAPA 7 — Ativar o GitHub Pages

1. No repositório, vá em **Settings → Pages**
2. Em **Source**, selecione **Deploy from a branch**
3. Em **Branch**, selecione `main` e a pasta `/ (root)`
4. Clique em **Save**
5. Após alguns minutos, o dashboard estará disponível em:
   `https://<seu-usuario>.github.io/<nome-do-repositorio>/`

---

### ETAPA 8 — Testar o pipeline manualmente

Antes de esperar o cron do dia seguinte, rode o workflow manualmente:

1. No repositório, vá em **Actions**
2. No menu lateral, clique em **Atualizar Dados GA4**
3. Clique em **Run workflow → Run workflow**
4. Aguarde ~2 minutos e verifique se o job passou (ícone verde)
5. Se passou, o `data.json` na raiz do repo terá sido atualizado com os dados reais
6. Acesse a URL do GitHub Pages para ver o dashboard

Se der erro, clique no job com falha → expanda os steps → o log mostrará o que aconteceu.

---

### ETAPA 9 — Gerar insights com o Claude.ai

O dashboard tem uma aba **Insights IA** com um prompt pronto.

**Fluxo:**

1. Acesse o GitHub Pages e vá na aba **Insights IA**
2. Clique em **Copiar prompt para Claude.ai**
3. Abra o [Claude.ai](https://claude.ai) no plano Team
4. Cole o prompt numa nova conversa
5. Adicione o conteúdo do `data.json` no final do prompt
   - O arquivo está em: `github.com/<usuario>/<repo>/blob/main/data.json`
6. Peça os insights ao Claude
7. O Claude retornará um array JSON como este:

```json
[
  {
    "title": "Tráfego orgânico cresceu 23% na semana",
    "body": "Houve um pico de sessões orgânicas entre dias 10-15. Verifique quais páginas ganharam ranking e replique o padrão de conteúdo.",
    "type": "positive",
    "generated_at": "2024-01-15"
  },
  {
    "title": "Alto abandono no checkout (67%)",
    "body": "Mais de dois terços dos usuários abandonam na etapa de checkout. Considere simplificar o formulário ou adicionar mais opções de pagamento.",
    "type": "warning",
    "generated_at": "2024-01-15"
  }
]
```

8. Abra o `data.json` no GitHub (botão **Edit** → ícone de lápis)
9. Substitua o conteúdo do campo `"insights": [...]` pelo array gerado
10. Clique em **Commit changes**
11. O dashboard na aba Insights IA mostrará os novos insights imediatamente

---

## Frequência de atualização

| O que | Quando | Como |
|---|---|---|
| Dados GA4 | Todo dia às 08h BRT | Automático via GitHub Actions |
| Insights | Quando o time quiser | Manual via Claude.ai + edição do data.json |

Para mudar o horário do cron, edite a linha no `update-data.yml`:
```yaml
- cron: '0 11 * * *'  # UTC — 11h UTC = 08h BRT
```

---

## Problemas comuns

**Erro: `google.api_core.exceptions.PermissionDenied`**
→ A conta de serviço não tem acesso à propriedade do GA4. Refaça o passo 4.

**Erro: `KeyError: GA4_PROPERTY_ID`**
→ O secret não foi criado corretamente. Verifique em Settings → Secrets.

**O `data.json` não foi atualizado após o job rodar**
→ Verifique se o repositório tem permissão de escrita para o Actions:
Settings → Actions → General → Workflow permissions → **Read and write permissions**

**Dashboard mostra dados zerados**
→ O `data.json` ainda está com os dados iniciais. Rode o workflow manualmente (passo 8).

---

## Estrutura do data.json

```jsonc
{
  "updated_at": "2024-01-15T11:00:00Z",   // timestamp da última atualização
  "period": "últimos 30 dias",
  "totals": { /* KPIs gerais */ },
  "daily":   [ /* sessões/usuários/conversões por dia */ ],
  "pages":   [ /* top 10 páginas */ ],
  "sources": [ /* top 15 origens */ ],
  "channels":[ /* por canal */ ],
  "funnel":  [ /* etapas do funil com drop rate */ ],
  "devices": [ /* por dispositivo */ ],
  "insights":[ /* gerado manualmente via Claude.ai */ ]
}
```
