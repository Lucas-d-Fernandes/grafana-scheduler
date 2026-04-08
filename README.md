# Grafana Scheduler

Aplicação web para agendar geração de relatórios a partir de dashboards do Grafana, com envio automático por e-mail e Telegram, suporte opcional a análise por IA e uma API embutida para métricas operacionais e disparo remoto.

## O que a aplicação faz

O Grafana Scheduler resolve um problema operacional simples e recorrente: transformar dashboards do Grafana em relatórios executivos ou técnicos, de forma programada, consistente e sem depender de execução manual.

Com ele é possível:

- cadastrar servidores Grafana e consultar catálogo de folders e dashboards pela API
- criar agendamentos recorrentes
- gerar relatórios resumidos ou detalhados
- enviar PDFs automaticamente por e-mail e/ou Telegram
- aplicar templates visuais personalizados ao PDF
- usar IA para enriquecer o relatório com análises contextuais
- acompanhar métricas operacionais, falhas e histórico de execução
- acionar envios imediatos pela interface ou pela API

## Principais fluxos

### 1. Configurar origem Grafana

Na tela `Configurações > Servidores Grafana`, você cadastra:

- nome do servidor
- URL do Grafana
- usuário
- senha
- token de conta de serviço

A aplicação usa essas credenciais para:

- consultar a API do Grafana
- descobrir folders e dashboards
- abrir o navegador automatizado e capturar dashboards/painéis

### 2. Configurar meios de envio

Na tela `Configurações > Aplicações de Envio`, você define os canais operacionais.

#### E-mail

Campos suportados:

- servidor SMTP
- porta
- usuário SMTP
- senha SMTP
- remetente
- uso de TLS/STARTTLS

#### Telegram

Recursos suportados:

- múltiplos bots
- nome amigável por bot
- busca de chats pela API do Telegram
- seleção de múltiplos chats por bot

### 3. Configurar IA

Na tela `Configurações > IA`, você configura:

- provedor
- API Key
- endpoint, quando aplicável
- modelo
- biblioteca de prompts reutilizáveis

Provedores suportados hoje:

- OpenAI
- Azure AI Foundry

### 4. Criar agendamentos

Na tela `Agendamentos`, o fluxo é organizado em etapas:

- identidade do agendamento
- origem Grafana
- periodicidade
- entrega
- relatório e IA

Cada agendamento pode:

- selecionar dashboards individuais
- selecionar folders inteiros
- enviar por e-mail, Telegram ou ambos
- usar relatório resumido ou detalhado
- usar template visual
- ativar ou não insights de IA

## Tipos de relatório

### Relatório resumido

Fluxo pensado para leitura rápida.

Inclui:

- captura da dashboard inteira
- página de resumo enxuta
- análise opcional quando IA estiver ativa

Não inclui:

- sumário
- estrutura painel a painel
- capa/contracapa editorial longa

### Relatório detalhado

Fluxo pensado para leitura analítica.

Inclui:

- consulta de metadados da dashboard
- leitura painel a painel
- captura individual dos painéis
- título, descrição, figura e análise por painel
- resumo final contextual, quando IA estiver ativa

Observações:

- painéis do tipo `text` são ignorados
- o sistema tenta recortar melhor painéis compactos para evitar imagens vazias ou excesso de fundo

## Meios de envio suportados

### E-mail

O envio por e-mail:

- usa SMTP configurado pelo usuário
- envia um HTML moderno e limpo no corpo do e-mail
- anexa os PDFs gerados
- não injeta a análise completa da IA no corpo do e-mail

### Telegram

O envio por Telegram:

- envia mensagem curta com contexto do agendamento
- anexa o PDF como documento
- suporta múltiplos bots e múltiplos chats

## Como a IA é usada

Quando habilitada no agendamento, a IA pode ser usada para:

- interpretar dashboards em modo resumido
- interpretar painéis individualmente em modo detalhado
- sugerir título para painel sem título
- produzir análise contextual com base em imagem + metadados úteis

Os metadados enviados para a IA são resumidos. A aplicação não envia o JSON bruto inteiro da dashboard; ela extrai apenas informações relevantes, como:

- título da dashboard
- descrição
- datasource
- título do painel
- descrição do painel
- contexto operacional do agendamento

## Biblioteca de prompts

A biblioteca de prompts fica embutida na tela de configuração de IA.

Cada prompt possui:

- título
- texto do prompt

Os prompts podem ser associados aos agendamentos e reutilizados entre análises.

## API embutida

A aplicação expõe uma API simples, protegida por token.

### Endpoints disponíveis

#### `GET /api/v1/metrics?days=1|7|30`

Retorna métricas agregadas da operação:

- volume de execuções
- sucesso e falha
- distribuição por canal
- série temporal

#### `GET /api/v1/relatorios/status?days=1|7|30`

Retorna tabela operacional simplificada dos relatórios executados.

#### `POST /api/v1/agendamentos/<id>/enviar`

Enfileira uma execução imediata do agendamento.

Importante:

- o endpoint não executa o relatório dentro da requisição HTTP
- ele apenas cria um job na fila
- o processamento é feito de forma assíncrona pelo scheduler

## Arquitetura resumida

A aplicação roda em dois serviços principais:

### `web`

Responsável por:

- interface web
- autenticação administrativa
- configuração
- API
- enqueue de jobs

### `scheduler`

Responsável por:

- detectar agendamentos vencidos
- enfileirar execuções automáticas
- consumir jobs da fila
- gerar relatórios
- enviar e-mail e Telegram

## Bibliotecas principais usadas

### Backend

- Flask
- Gunicorn
- Requests
- SQLite (`sqlite3`)

### Geração de relatório

- Pyppeteer
- ReportLab
- PyPDF (`pypdf`)
- BeautifulSoup (`bs4`)

### Infraestrutura

- Docker
- Docker Compose

## Estrutura de dados principal

Tabelas relevantes:

- `grafana_servers`
- `agendamentos`
- `agendamento_destinatarios`
- `configuracao_email`
- `telegram_bots`
- `configuracao_ia`
- `ai_prompts`
- `report_templates`
- `report_executions`
- `report_jobs`
- `api_tokens`

## Como executar localmente

### 1. Criar arquivo `.env`

Use [`.env.example`](./.env.example) como base.

### 2. Subir os containers

```bash
docker compose up --build -d
```

### 3. Acessar a aplicação

```text
http://localhost:5000
```

## Tutorial fácil para rodar em um servidor remoto

Este é o caminho mais simples para quem só quer colocar a aplicação no ar.

### Pré-requisitos

- um servidor Linux com Docker instalado
- acesso SSH ao servidor
- portas liberadas para a aplicação

### Passo 1. Copie o projeto para o servidor

Coloque os arquivos do projeto em um diretório como:

```bash
/opt/projeto
```

### Passo 2. Crie o arquivo `.env`

Exemplo mínimo:

```env
FLASK_SECRET_KEY=gere_um_valor_grande_e_aleatorio
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=
ADMIN_PASSWORD=defina_uma_senha_forte
SESSION_COOKIE_SECURE=0
TZ=America/Sao_Paulo
APP_DATA_DIR=/app/data
```

Observações:

- em ambiente com HTTPS, troque `SESSION_COOKIE_SECURE=0` para `1`
- prefira usar `ADMIN_PASSWORD_HASH` em vez de senha em texto puro

### Passo 3. Suba os serviços

```bash
cd /opt/projeto
docker compose up --build -d
```

### Passo 4. Verifique se os serviços estão ativos

```bash
docker compose ps
docker compose logs -f
```

### Passo 5. Acesse pelo navegador

```text
http://IP_DO_SERVIDOR:5000
```

### Passo 6. Faça a configuração inicial

Na interface:

1. cadastre os servidores Grafana
2. configure e-mail e/ou Telegram
3. configure IA, se desejar
4. crie um template de relatório, se necessário
5. crie seu primeiro agendamento

## Exemplo de uso da API

### Consultar métricas

```bash
curl -H "Authorization: Bearer SEU_TOKEN" \
  "http://localhost:5000/api/v1/metrics?days=7"
```

### Consultar status dos relatórios

```bash
curl -H "Authorization: Bearer SEU_TOKEN" \
  "http://localhost:5000/api/v1/relatorios/status?days=7"
```

### Enfileirar um envio imediato

```bash
curl -X POST \
  -H "Authorization: Bearer SEU_TOKEN" \
  "http://localhost:5000/api/v1/agendamentos/2/enviar"
```

## Licença e responsabilidade

Adapte este projeto ao seu ambiente antes de publicar em produção. Credenciais, tokens, política de retenção, proteção de rede e backup do volume de dados devem seguir a política da sua organização.
