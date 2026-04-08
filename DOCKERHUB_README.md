# Grafana Scheduler

Aplicacao para gerar relatorios a partir de dashboards do Grafana e entregar automaticamente por e-mail e Telegram.

## O que faz

- cadastra servidores Grafana
- seleciona dashboards para envio
- agenda relatorios recorrentes
- gera PDFs resumidos ou detalhados
- envia por e-mail e Telegram
- expoe metricas e operacoes por API

## Arquitetura simplificada

A imagem roda em dois containers:

### `web`

- interface web
- autenticacao administrativa
- configuracoes
- API

### `scheduler`

- fila de execucao
- geracao de relatorios
- envio por e-mail e Telegram

Os dados persistentes ficam em um volume dedicado.

## Como executar

### 1. Crie um diretorio de trabalho

```bash
mkdir -p /opt/grafana-scheduler
cd /opt/grafana-scheduler
```

### 2. Crie o arquivo `.env`

Crie o arquivo abaixo no mesmo diretorio do `docker-compose.yml`:

```bash
/opt/grafana-scheduler/.env
```

Exemplo:

```env
FLASK_SECRET_KEY=troque-este-valor-por-uma-chave-grande-e-aleatoria
ADMIN_USERNAME=admin
ADMIN_PASSWORD=defina-uma-senha-forte-aqui
SESSION_COOKIE_SECURE=0
TZ=America/Sao_Paulo
```

O login da interface sera:

- usuario: valor de `ADMIN_USERNAME`
- senha: valor de `ADMIN_PASSWORD`

Se houver HTTPS na borda, troque `SESSION_COOKIE_SECURE=0` por `1`.

### 3. Crie o arquivo `docker-compose.yml`

```yaml
services:
  web:
    image: luc4sd3s0uz4/grafana_scheduler:2026.04.08
    env_file:
      - .env
    ports:
      - "5000:5000"
    volumes:
      - app_data:/app/data
    shm_size: "1gb"
    restart: unless-stopped

  scheduler:
    image: luc4sd3s0uz4/grafana_scheduler:2026.04.08
    command: ["python", "clock.py"]
    env_file:
      - .env
    volumes:
      - app_data:/app/data
    shm_size: "1gb"
    restart: unless-stopped

volumes:
  app_data:
```

### 4. Suba os containers

```bash
docker compose up -d
```

### 5. Acesse a aplicacao

```text
http://IP_DO_SERVIDOR:5000
```

## Tags disponiveis

- `latest`
- `2026.04.08`
