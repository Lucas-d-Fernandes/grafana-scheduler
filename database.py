import json
import re
import secrets
import sqlite3
from collections import OrderedDict
from datetime import datetime, timedelta

from paths import data_path

DB_FILE = data_path("database.db")
VALID_JOB_TRIGGER_SOURCES = {"manual", "api", "scheduled"}
VALID_JOB_STATUSES = {"queued", "running", "success", "partial", "failed"}
DEFAULT_MAX_CONCURRENT_REPORTS = 5
MAX_CONCURRENT_REPORTS_LIMIT = 100
MIN_CONCURRENT_REPORTS_LIMIT = 1


def _now_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_max_concurrent_reports(value):
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = DEFAULT_MAX_CONCURRENT_REPORTS
    return max(MIN_CONCURRENT_REPORTS_LIMIT, min(MAX_CONCURRENT_REPORTS_LIMIT, normalized))


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _safe_sql_identifier(value):
    normalized = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise ValueError(f"Identificador SQL inválido: {value}")
    return normalized


def ensure_column(conn, table_name, column_name, definition):
    table_name = _safe_sql_identifier(table_name)
    column_name = _safe_sql_identifier(column_name)
    columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if not any(column["name"] == column_name for column in columns):
        normalized_definition = definition
        if "CURRENT_TIMESTAMP" in definition.upper():
            normalized_definition = definition.split("DEFAULT", 1)[0].strip()
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {normalized_definition}")
        if "CURRENT_TIMESTAMP" in definition.upper():
            update_sql = f"""
                UPDATE {table_name}
                SET {column_name} = COALESCE({column_name}, CURRENT_TIMESTAMP)
                """  # nosec B608
            conn.execute(update_sql)


def normalize_selected_targets(selected_targets):
    normalized = []
    seen_uids = set()

    for target in selected_targets or []:
        if not isinstance(target, dict):
            continue

        candidates = []
        if target.get("type") == "dashboard":
            candidates = [target]
        elif target.get("type") == "folder":
            candidates = target.get("dashboards") or []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            uid = str(candidate.get("uid") or "").strip()
            if not uid or uid in seen_uids:
                continue

            normalized.append(
                {
                    "type": "dashboard",
                    "uid": uid,
                    "title": str(candidate.get("title") or uid).strip(),
                    "url": str(candidate.get("url") or "").strip(),
                }
            )
            seen_uids.add(uid)

    return normalized[:1]


def normalize_schedule_targets_in_db(conn):
    rows = conn.execute("SELECT id, selected_targets_json FROM agendamentos").fetchall()
    for row in rows:
        raw_value = row["selected_targets_json"] or "[]"
        try:
            selected_targets = json.loads(raw_value)
        except Exception:
            selected_targets = []

        normalized_json = json.dumps(normalize_selected_targets(selected_targets), ensure_ascii=True)
        if normalized_json != raw_value:
            conn.execute(
                "UPDATE agendamentos SET selected_targets_json = ? WHERE id = ?",
                (normalized_json, row["id"]),
            )


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS grafana_servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            base_url TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            service_account_token TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agendamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL DEFAULT '',
            nome_cliente TEXT NOT NULL DEFAULT '',
            url_dashboard TEXT NOT NULL DEFAULT '',
            usuario_dashboard TEXT NOT NULL DEFAULT '',
            senha_dashboard TEXT NOT NULL DEFAULT '',
            periodo TEXT NOT NULL DEFAULT 'diario',
            detalhe_periodo TEXT DEFAULT '',
            horario TEXT NOT NULL DEFAULT '',
            aplicacao TEXT NOT NULL DEFAULT 'grafana',
            grafana_server_id INTEGER,
            selected_targets_json TEXT NOT NULL DEFAULT '[]',
            delivery_methods_json TEXT NOT NULL DEFAULT '[]',
            report_type TEXT NOT NULL DEFAULT 'resumido',
            report_subject TEXT NOT NULL DEFAULT '',
            report_intro TEXT NOT NULL DEFAULT '',
            report_footer TEXT NOT NULL DEFAULT '',
            report_ai_instruction TEXT NOT NULL DEFAULT '',
            ai_prompt_id INTEGER,
            report_template_id INTEGER,
            use_ai INTEGER NOT NULL DEFAULT 0,
            ai_provider TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (grafana_server_id) REFERENCES grafana_servers (id) ON DELETE SET NULL,
            FOREIGN KEY (ai_prompt_id) REFERENCES ai_prompts (id) ON DELETE SET NULL,
            FOREIGN KEY (report_template_id) REFERENCES report_templates (id) ON DELETE SET NULL
        )
        """
    )

    ensure_column(conn, "agendamentos", "grafana_server_id", "INTEGER")
    ensure_column(conn, "agendamentos", "selected_targets_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "agendamentos", "delivery_methods_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "agendamentos", "report_type", "TEXT NOT NULL DEFAULT 'resumido'")
    ensure_column(conn, "agendamentos", "report_subject", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "agendamentos", "report_intro", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "agendamentos", "report_footer", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "agendamentos", "report_ai_instruction", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "agendamentos", "ai_prompt_id", "INTEGER")
    ensure_column(conn, "agendamentos", "report_template_id", "INTEGER")
    ensure_column(conn, "agendamentos", "use_ai", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "agendamentos", "ai_provider", "TEXT DEFAULT ''")
    ensure_column(conn, "agendamentos", "created_at", "TEXT DEFAULT CURRENT_TIMESTAMP")
    conn.execute(
        """
        UPDATE agendamentos
        SET usuario_dashboard = '',
            senha_dashboard = ''
        WHERE grafana_server_id IS NOT NULL
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agendamento_destinatarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agendamento_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('email', 'telegram')),
            valor TEXT NOT NULL,
            label TEXT DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (agendamento_id) REFERENCES agendamentos (id) ON DELETE CASCADE
        )
        """
    )
    ensure_column(conn, "agendamento_destinatarios", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao_email (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            smtp_server TEXT NOT NULL DEFAULT '',
            smtp_port INTEGER NOT NULL DEFAULT 587,
            smtp_username TEXT NOT NULL DEFAULT '',
            smtp_password TEXT NOT NULL DEFAULT '',
            smtp_from_email TEXT NOT NULL DEFAULT '',
            smtp_use_tls INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao_telegram (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            bot_token TEXT NOT NULL DEFAULT '',
            selected_chats_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            bot_token TEXT NOT NULL DEFAULT '',
            selected_chats_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao_ia (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            provider TEXT NOT NULL DEFAULT 'openai',
            api_key TEXT NOT NULL DEFAULT '',
            endpoint TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS api_access_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            api_token TEXT NOT NULL DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao_execucao (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            max_concurrent_reports INTEGER NOT NULL DEFAULT 5,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS api_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            api_token TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS report_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            logo_base64 TEXT NOT NULL DEFAULT '',
            cover_base64 TEXT NOT NULL DEFAULT '',
            back_cover_base64 TEXT NOT NULL DEFAULT '',
            show_summary INTEGER NOT NULL DEFAULT 1,
            header_text TEXT NOT NULL DEFAULT '',
            primary_color TEXT NOT NULL DEFAULT '#f97316',
            secondary_color TEXT NOT NULL DEFAULT '#0f172a',
            font_family TEXT NOT NULL DEFAULT 'Helvetica',
            title_font_size INTEGER NOT NULL DEFAULT 20,
            body_font_size INTEGER NOT NULL DEFAULT 11,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute("INSERT OR IGNORE INTO configuracao_email (id) VALUES (1)")
    cursor.execute("INSERT OR IGNORE INTO configuracao_telegram (id) VALUES (1)")
    cursor.execute("INSERT OR IGNORE INTO configuracao_ia (id) VALUES (1)")
    cursor.execute("INSERT OR IGNORE INTO api_access_config (id) VALUES (1)")
    cursor.execute("INSERT OR IGNORE INTO configuracao_execucao (id) VALUES (1)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS report_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER,
            schedule_title TEXT NOT NULL DEFAULT '',
            customer_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK(status IN ('success', 'partial', 'failed')),
            summary TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            error_details TEXT NOT NULL DEFAULT '',
            error_image_base64 TEXT NOT NULL DEFAULT '',
            report_count INTEGER NOT NULL DEFAULT 0,
            sent_email_count INTEGER NOT NULL DEFAULT 0,
            sent_telegram_count INTEGER NOT NULL DEFAULT 0,
            duration_seconds REAL NOT NULL DEFAULT 0,
            delivery_methods_json TEXT NOT NULL DEFAULT '[]',
            attachment_paths_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (schedule_id) REFERENCES agendamentos (id) ON DELETE SET NULL
        )
        """
    )
    ensure_column(conn, "report_executions", "duration_seconds", "REAL NOT NULL DEFAULT 0")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS report_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            trigger_source TEXT NOT NULL CHECK(trigger_source IN ('manual', 'api', 'scheduled')),
            requested_by TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'success', 'partial', 'failed')) DEFAULT 'queued',
            dedupe_key TEXT NOT NULL DEFAULT '',
            worker_name TEXT NOT NULL DEFAULT '',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            finished_at TEXT,
            FOREIGN KEY (schedule_id) REFERENCES agendamentos (id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_report_jobs_status_created
        ON report_jobs (status, created_at, id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_report_jobs_schedule_status
        ON report_jobs (schedule_id, status, id)
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_report_jobs_active_unique
        ON report_jobs (schedule_id)
        WHERE status IN ('queued', 'running')
        """
    )

    legacy_telegram = cursor.execute("SELECT bot_token, selected_chats_json FROM configuracao_telegram WHERE id = 1").fetchone()
    legacy_count = cursor.execute("SELECT COUNT(*) AS total FROM telegram_bots").fetchone()["total"]
    if legacy_telegram and legacy_telegram["bot_token"] and legacy_count == 0:
        cursor.execute(
            """
            INSERT INTO telegram_bots (nome, bot_token, selected_chats_json)
            VALUES (?, ?, ?)
            """,
            ("Bot Telegram 1", legacy_telegram["bot_token"], legacy_telegram["selected_chats_json"]),
        )

    legacy_api_token = cursor.execute("SELECT api_token FROM api_access_config WHERE id = 1").fetchone()
    api_token_count = cursor.execute("SELECT COUNT(*) AS total FROM api_tokens").fetchone()["total"]
    if legacy_api_token and legacy_api_token["api_token"] and api_token_count == 0:
        cursor.execute(
            """
            INSERT INTO api_tokens (nome, api_token)
            VALUES (?, ?)
            """,
            ("Token Principal", legacy_api_token["api_token"]),
        )

    normalize_schedule_targets_in_db(conn)
    cleanup_report_execution_history(conn)
    cleanup_report_job_history(conn)
    conn.commit()
    conn.close()


def cleanup_report_execution_history(conn=None, days=30):
    owns_connection = conn is None
    if owns_connection:
        conn = get_connection()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM report_executions WHERE created_at < ?", (cutoff,))
    if owns_connection:
        conn.commit()
        conn.close()


def cleanup_report_job_history(conn=None, days=30):
    owns_connection = conn is None
    if owns_connection:
        conn = get_connection()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        DELETE FROM report_jobs
        WHERE finished_at IS NOT NULL
          AND finished_at < ?
        """,
        (cutoff,),
    )
    if owns_connection:
        conn.commit()
        conn.close()


def create_grafana_server(server_data):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO grafana_servers (nome, base_url, username, password, service_account_token)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            server_data["nome"],
            server_data["base_url"],
            server_data["username"],
            server_data["password"],
            server_data["service_account_token"],
        ),
    )
    server_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return server_id


def update_grafana_server(server_id, server_data):
    conn = get_connection()
    conn.execute(
        """
        UPDATE grafana_servers
        SET nome = ?,
            base_url = ?,
            username = ?,
            password = ?,
            service_account_token = ?
        WHERE id = ?
        """,
        (
            server_data["nome"],
            server_data["base_url"],
            server_data["username"],
            server_data["password"],
            server_data["service_account_token"],
            server_id,
        ),
    )
    conn.commit()
    conn.close()


def list_grafana_servers():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, nome, base_url, username, created_at
        FROM grafana_servers
        ORDER BY nome ASC, id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_grafana_server(server_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM grafana_servers WHERE id = ?", (server_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_grafana_server(server_id):
    conn = get_connection()
    conn.execute("DELETE FROM grafana_servers WHERE id = ?", (server_id,))
    conn.commit()
    conn.close()


def create_schedule(schedule_data, recipients):
    selected_targets = normalize_selected_targets(schedule_data["selected_targets"])
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO agendamentos (
            titulo,
            nome_cliente,
            url_dashboard,
            usuario_dashboard,
            senha_dashboard,
            periodo,
            detalhe_periodo,
            horario,
            aplicacao,
            grafana_server_id,
            selected_targets_json,
            delivery_methods_json,
            report_type,
            report_subject,
            report_intro,
            report_footer,
            report_ai_instruction,
            ai_prompt_id,
            report_template_id,
            use_ai,
            ai_provider
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            schedule_data["titulo"],
            schedule_data["nome_cliente"],
            schedule_data["url_dashboard"],
            schedule_data["usuario_dashboard"],
            schedule_data["senha_dashboard"],
            schedule_data["periodo"],
            schedule_data["detalhe_periodo"],
            schedule_data["horario"],
            schedule_data["aplicacao"],
            schedule_data["grafana_server_id"],
            json.dumps(selected_targets, ensure_ascii=True),
            json.dumps(schedule_data["delivery_methods"], ensure_ascii=True),
            schedule_data["report_type"],
            schedule_data.get("report_subject", ""),
            schedule_data.get("report_intro", ""),
            schedule_data.get("report_footer", ""),
            schedule_data.get("report_ai_instruction", ""),
            schedule_data.get("ai_prompt_id"),
            schedule_data.get("report_template_id"),
            1 if schedule_data["use_ai"] else 0,
            schedule_data["ai_provider"],
        ),
    )
    schedule_id = cursor.lastrowid

    for recipient in recipients:
        cursor.execute(
            """
            INSERT INTO agendamento_destinatarios (agendamento_id, tipo, valor, label, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                schedule_id,
                recipient["tipo"],
                recipient["valor"],
                recipient.get("label", ""),
                json.dumps(recipient.get("metadata", {}), ensure_ascii=True),
            ),
        )

    conn.commit()
    conn.close()
    return schedule_id


def update_schedule(schedule_id, schedule_data, recipients):
    selected_targets = normalize_selected_targets(schedule_data["selected_targets"])
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE agendamentos
        SET titulo = ?,
            nome_cliente = ?,
            url_dashboard = ?,
            usuario_dashboard = ?,
            senha_dashboard = ?,
            periodo = ?,
            detalhe_periodo = ?,
            horario = ?,
            aplicacao = ?,
            grafana_server_id = ?,
            selected_targets_json = ?,
            delivery_methods_json = ?,
            report_type = ?,
            report_subject = ?,
            report_intro = ?,
            report_footer = ?,
            report_ai_instruction = ?,
            ai_prompt_id = ?,
            report_template_id = ?,
            use_ai = ?,
            ai_provider = ?
        WHERE id = ?
        """,
        (
            schedule_data["titulo"],
            schedule_data["nome_cliente"],
            schedule_data["url_dashboard"],
            schedule_data["usuario_dashboard"],
            schedule_data["senha_dashboard"],
            schedule_data["periodo"],
            schedule_data["detalhe_periodo"],
            schedule_data["horario"],
            schedule_data["aplicacao"],
            schedule_data["grafana_server_id"],
            json.dumps(selected_targets, ensure_ascii=True),
            json.dumps(schedule_data["delivery_methods"], ensure_ascii=True),
            schedule_data["report_type"],
            schedule_data.get("report_subject", ""),
            schedule_data.get("report_intro", ""),
            schedule_data.get("report_footer", ""),
            schedule_data.get("report_ai_instruction", ""),
            schedule_data.get("ai_prompt_id"),
            schedule_data.get("report_template_id"),
            1 if schedule_data["use_ai"] else 0,
            schedule_data["ai_provider"],
            schedule_id,
        ),
    )
    cursor.execute("DELETE FROM agendamento_destinatarios WHERE agendamento_id = ?", (schedule_id,))
    for recipient in recipients:
        cursor.execute(
            """
            INSERT INTO agendamento_destinatarios (agendamento_id, tipo, valor, label, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                schedule_id,
                recipient["tipo"],
                recipient["valor"],
                recipient.get("label", ""),
                json.dumps(recipient.get("metadata", {}), ensure_ascii=True),
            ),
        )
    conn.commit()
    conn.close()


def _schedule_select_sql(where_clause="", order_clause="ORDER BY a.id DESC"):
    allowed_where_clauses = {"", "WHERE a.id = ?"}
    allowed_order_clauses = {"", "ORDER BY a.id DESC"}
    if where_clause not in allowed_where_clauses or order_clause not in allowed_order_clauses:
        raise ValueError("Cláusula SQL não permitida para consulta de agendamentos.")

    query = f"""
        SELECT a.id, a.titulo, a.nome_cliente,
               a.periodo, a.detalhe_periodo, a.horario, a.aplicacao, a.created_at,
               a.grafana_server_id, a.selected_targets_json, a.delivery_methods_json,
               a.report_type, a.report_subject, a.report_intro, a.report_footer,
               a.report_ai_instruction, a.ai_prompt_id, a.report_template_id, a.use_ai, a.ai_provider,
               gs.nome AS grafana_server_nome, rt.nome AS report_template_nome,
               ap.titulo AS ai_prompt_titulo, ap.prompt_text AS ai_prompt_text
        FROM agendamentos a
        LEFT JOIN grafana_servers gs ON gs.id = a.grafana_server_id
        LEFT JOIN ai_prompts ap ON ap.id = a.ai_prompt_id
        LEFT JOIN report_templates rt ON rt.id = a.report_template_id
        {where_clause}
        {order_clause}
    """  # nosec B608
    return query


def _hydrate_schedule(cursor, row):
    recipients = cursor.execute(
        """
        SELECT id, tipo, valor, label
        FROM agendamento_destinatarios
        WHERE agendamento_id = ?
        ORDER BY id ASC
        """,
        (row["id"],),
    ).fetchall()

    return {
        "id": row["id"],
        "titulo": row["titulo"],
        "nome_cliente": row["nome_cliente"],
        "periodo": row["periodo"],
        "detalhe_periodo": row["detalhe_periodo"],
        "horario": row["horario"],
        "aplicacao": row["aplicacao"],
        "created_at": row["created_at"],
        "grafana_server_id": row["grafana_server_id"],
        "grafana_server_nome": row["grafana_server_nome"],
        "selected_targets": normalize_selected_targets(json.loads(row["selected_targets_json"] or "[]")),
        "delivery_methods": json.loads(row["delivery_methods_json"] or "[]"),
        "report_type": row["report_type"],
        "report_subject": row["report_subject"],
        "report_intro": row["report_intro"],
        "report_footer": row["report_footer"],
        "report_ai_instruction": row["report_ai_instruction"],
        "ai_prompt_id": row["ai_prompt_id"],
        "ai_prompt_titulo": row["ai_prompt_titulo"],
        "ai_prompt_text": row["ai_prompt_text"] or "",
        "report_template_id": row["report_template_id"],
        "report_template_nome": row["report_template_nome"],
        "use_ai": bool(row["use_ai"]),
        "ai_provider": row["ai_provider"],
        "destinatarios": [dict(recipient) for recipient in recipients],
    }


def list_schedules():
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute(_schedule_select_sql()).fetchall()
    schedules = [_hydrate_schedule(cursor, row) for row in rows]
    conn.close()
    return schedules


def get_schedule(schedule_id):
    conn = get_connection()
    cursor = conn.cursor()
    row = cursor.execute(
        _schedule_select_sql("WHERE a.id = ?", order_clause=""),
        (schedule_id,),
    ).fetchone()
    schedule = _hydrate_schedule(cursor, row) if row else None
    conn.close()
    return schedule


def delete_schedule(schedule_id):
    conn = get_connection()
    conn.execute("DELETE FROM agendamentos WHERE id = ?", (schedule_id,))
    conn.commit()
    conn.close()


def update_schedule_report_config(schedule_id, report_data):
    conn = get_connection()
    conn.execute(
        """
        UPDATE agendamentos
        SET report_type = ?,
            report_subject = ?,
            report_intro = ?,
            report_footer = ?,
            report_ai_instruction = ?,
            ai_prompt_id = ?,
            report_template_id = ?,
            use_ai = ?,
            ai_provider = ?
        WHERE id = ?
        """,
        (
            report_data["report_type"],
            report_data.get("report_subject", ""),
            report_data.get("report_intro", ""),
            report_data.get("report_footer", ""),
            report_data.get("report_ai_instruction", ""),
            report_data.get("ai_prompt_id"),
            report_data.get("report_template_id"),
            1 if report_data.get("use_ai") else 0,
            report_data.get("ai_provider", ""),
            schedule_id,
        ),
    )
    conn.commit()
    conn.close()


def get_schedule_recipients(schedule_id):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, tipo, valor, label, metadata_json
        FROM agendamento_destinatarios
        WHERE agendamento_id = ?
        ORDER BY id ASC
        """,
        (schedule_id,),
    ).fetchall()
    conn.close()
    recipients = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.get("metadata_json") or "{}")
        recipients.append(item)
    return recipients


def create_report_execution(execution_data):
    conn = get_connection()
    cleanup_report_execution_history(conn)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO report_executions (
            schedule_id,
            schedule_title,
            customer_name,
            status,
            summary,
            error_message,
            error_details,
            error_image_base64,
            report_count,
            sent_email_count,
            sent_telegram_count,
            duration_seconds,
            delivery_methods_json,
            attachment_paths_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            execution_data.get("schedule_id"),
            execution_data.get("schedule_title", ""),
            execution_data.get("customer_name", ""),
            execution_data["status"],
            execution_data.get("summary", ""),
            execution_data.get("error_message", ""),
            execution_data.get("error_details", ""),
            execution_data.get("error_image_base64", ""),
            execution_data.get("report_count", 0),
            execution_data.get("sent_email_count", 0),
            execution_data.get("sent_telegram_count", 0),
            float(execution_data.get("duration_seconds", 0) or 0),
            json.dumps(execution_data.get("delivery_methods", []), ensure_ascii=True),
            json.dumps(execution_data.get("attachment_paths", []), ensure_ascii=True),
            execution_data.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ),
    )
    execution_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return execution_id


def enqueue_report_job(schedule_id, trigger_source, requested_by="", dedupe_key=""):
    if trigger_source not in VALID_JOB_TRIGGER_SOURCES:
        raise ValueError("Origem de job invalida.")

    schedule_id = int(schedule_id)
    dedupe_key = str(dedupe_key or "").strip()
    now = _now_timestamp()
    conn = get_connection()
    cleanup_report_job_history(conn)

    if dedupe_key:
        # Sem filtro de status: um job já concluído (success/partial/failed) com a mesma
        # dedupe_key ainda deve bloquear re-enfileiramento. O scheduler varre a cada 10s
        # dentro do mesmo minuto; sem isso, jobs rápidos seriam enviados mais de uma vez.
        existing = conn.execute(
            """
            SELECT id, status, created_at
            FROM report_jobs
            WHERE schedule_id = ?
              AND dedupe_key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (schedule_id, dedupe_key),
        ).fetchone()
    elif trigger_source in {"manual", "api"}:
        existing = conn.execute(
            """
            SELECT id, status, created_at
            FROM report_jobs
            WHERE schedule_id = ?
              AND status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (schedule_id,),
        ).fetchone()
    else:
        existing = None

    if existing:
        conn.close()
        return {
            "id": existing["id"],
            "status": existing["status"],
            "created": False,
            "created_at": existing["created_at"],
        }

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO report_jobs (
                schedule_id,
                trigger_source,
                requested_by,
                status,
                dedupe_key,
                created_at
            )
            VALUES (?, ?, ?, 'queued', ?, ?)
            """,
            (schedule_id, trigger_source, str(requested_by or "").strip(), dedupe_key, now),
        )
        job_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return {"id": job_id, "status": "queued", "created": True, "created_at": now}
    except sqlite3.IntegrityError:
        existing = conn.execute(
            """
            SELECT id, status, created_at
            FROM report_jobs
            WHERE schedule_id = ?
              AND status IN ('queued', 'running')
            ORDER BY id DESC
            LIMIT 1
            """,
            (schedule_id,),
        ).fetchone()
        conn.close()
        if existing:
            return {
                "id": existing["id"],
                "status": existing["status"],
                "created": False,
                "created_at": existing["created_at"],
            }
        raise


def reset_running_report_jobs():
    conn = get_connection()
    conn.execute(
        """
        UPDATE report_jobs
        SET status = 'queued',
            worker_name = '',
            started_at = NULL,
            finished_at = NULL,
            last_error = CASE
                WHEN trim(last_error) = '' THEN 'Job reenfileirado apos reinicio do worker.'
                ELSE last_error || ' | Job reenfileirado apos reinicio do worker.'
            END
        WHERE status = 'running'
        """
    )
    conn.commit()
    conn.close()


def purge_report_queue(reason="Fila cancelada manualmente."):
    conn = get_connection()
    queued_count = conn.execute(
        "SELECT COUNT(*) AS total FROM report_jobs WHERE status = 'queued'"
    ).fetchone()["total"]
    running_count = conn.execute(
        "SELECT COUNT(*) AS total FROM report_jobs WHERE status = 'running'"
    ).fetchone()["total"]

    conn.execute("DELETE FROM report_jobs WHERE status = 'queued'")
    conn.execute(
        """
        UPDATE report_jobs
        SET status = 'failed',
            last_error = ?,
            finished_at = ?
        WHERE status = 'running'
        """,
        (str(reason or "").strip(), _now_timestamp()),
    )
    conn.commit()
    conn.close()
    return {
        "queued_removed": int(queued_count or 0),
        "running_cancelled": int(running_count or 0),
    }


def claim_next_report_job(worker_name="scheduler"):
    conn = get_connection()
    cleanup_report_job_history(conn)
    row = conn.execute(
        """
        SELECT *
        FROM report_jobs
        WHERE status = 'queued'
        ORDER BY created_at ASC, id ASC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        conn.close()
        return None

    started_at = _now_timestamp()
    cursor = conn.execute(
        """
        UPDATE report_jobs
        SET status = 'running',
            worker_name = ?,
            started_at = ?,
            finished_at = NULL,
            attempt_count = attempt_count + 1
        WHERE id = ?
          AND status = 'queued'
        """,
        (worker_name, started_at, row["id"]),
    )
    if cursor.rowcount != 1:
        conn.commit()
        conn.close()
        return None

    claimed_row = conn.execute("SELECT * FROM report_jobs WHERE id = ?", (row["id"],)).fetchone()
    conn.commit()
    conn.close()
    return dict(claimed_row) if claimed_row else None


def finish_report_job(job_id, status, last_error=""):
    if status not in VALID_JOB_STATUSES - {"queued", "running"}:
        raise ValueError("Status final de job invalido.")

    conn = get_connection()
    cursor = conn.execute(
        """
        UPDATE report_jobs
        SET status = ?,
            last_error = ?,
            finished_at = ?
        WHERE id = ?
          AND status = 'running'
        """,
        (status, str(last_error or "").strip(), _now_timestamp(), job_id),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount == 1


def get_report_job(job_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM report_jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def should_abort_report_job(job_id):
    if not job_id:
        return False
    row = get_report_job(job_id)
    if not row:
        return True
    return row.get("status") != "running"


def get_report_execution(execution_id):
    conn = get_connection()
    cleanup_report_execution_history(conn)
    row = conn.execute("SELECT * FROM report_executions WHERE id = ?", (execution_id,)).fetchone()
    conn.commit()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["delivery_methods"] = json.loads(item["delivery_methods_json"] or "[]")
    item["attachment_paths"] = json.loads(item["attachment_paths_json"] or "[]")
    return item


def get_status_dashboard_data(days=30):
    conn = get_connection()
    cleanup_report_execution_history(conn)
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM report_executions
            WHERE created_at >= ?
            ORDER BY created_at DESC
            """,
            (cutoff,),
        ).fetchall()
    ]
    job_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, status, worker_name, created_at, started_at, finished_at
            FROM report_jobs
            WHERE COALESCE(started_at, created_at) >= ?
               OR (status = 'running' AND started_at IS NOT NULL)
            ORDER BY COALESCE(started_at, created_at) DESC, id DESC
            """,
            (cutoff,),
        ).fetchall()
    ]
    conn.commit()
    conn.close()

    for item in rows:
        item["delivery_methods"] = json.loads(item["delivery_methods_json"] or "[]")
        item["attachment_paths"] = json.loads(item["attachment_paths_json"] or "[]")
        item["duration_seconds"] = float(item.get("duration_seconds", 0) or 0)

    def _parse_job_timestamp(value):
        if not value:
            return None
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

    successful = [item for item in rows if item["status"] in {"success", "partial"}]
    failures = [item for item in rows if item["status"] == "failed"]
    total_executions = len(rows)

    now = datetime.now()

    def _parse_created_at(item):
        return datetime.strptime(item["created_at"], "%Y-%m-%d %H:%M:%S")

    def _count_sent_since(delta):
        threshold = now - delta
        return sum(1 for item in successful if _parse_created_at(item) >= threshold)

    def _percent(part, total):
        if not total:
            return 0.0
        return round((part / total) * 100, 1)

    def _format_duration(seconds):
        seconds = round(float(seconds or 0), 2)
        minutes, remaining = divmod(seconds, 60)
        hours, minutes = divmod(int(minutes), 60)
        if hours:
            return f"{hours}h {minutes}m {remaining:.1f}s"
        if minutes:
            return f"{minutes}m {remaining:.1f}s"
        return f"{seconds:.2f}s"

    daily = OrderedDict()
    weekly = OrderedDict()
    monthly = OrderedDict()
    failure_daily = OrderedDict()
    all_daily = OrderedDict()
    hourly = OrderedDict()
    failure_hourly = OrderedDict()
    all_hourly = OrderedDict()

    start_day = (now - timedelta(days=max(days - 1, 0))).date()
    for index in range(days):
        label = (start_day + timedelta(days=index)).strftime("%Y-%m-%d")
        daily[label] = 0
        failure_daily[label] = 0
        all_daily[label] = 0

    if days == 1:
        start_hour = (now - timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
        for index in range(24):
            hour_label = (start_hour + timedelta(hours=index)).strftime("%Y-%m-%d %H:00")
            hourly[hour_label] = 0
            failure_hourly[hour_label] = 0
            all_hourly[hour_label] = 0

    for item in reversed(rows):
        created_at = _parse_created_at(item)
        day_key = created_at.strftime("%Y-%m-%d")
        if day_key in all_daily:
            all_daily[day_key] = all_daily.get(day_key, 0) + 1
        if days == 1:
            hour_key = created_at.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:00")
            if hour_key in all_hourly:
                all_hourly[hour_key] = all_hourly.get(hour_key, 0) + 1

    for item in reversed(successful):
        created_at = _parse_created_at(item)
        day_key = created_at.strftime("%Y-%m-%d")
        week_start = (created_at - timedelta(days=created_at.weekday())).strftime("%Y-%m-%d")
        month_key = created_at.strftime("%Y-%m")
        daily[day_key] = daily.get(day_key, 0) + 1
        weekly[week_start] = weekly.get(week_start, 0) + 1
        monthly[month_key] = monthly.get(month_key, 0) + 1
        if days == 1:
            hour_key = created_at.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:00")
            if hour_key in hourly:
                hourly[hour_key] = hourly.get(hour_key, 0) + 1

    for item in reversed(failures):
        created_at = _parse_created_at(item)
        day_key = created_at.strftime("%Y-%m-%d")
        if day_key in failure_daily:
            failure_daily[day_key] = failure_daily.get(day_key, 0) + 1
        if days == 1:
            hour_key = created_at.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:00")
            if hour_key in failure_hourly:
                failure_hourly[hour_key] = failure_hourly.get(hour_key, 0) + 1

    if days == 1:
        timeseries_counts = [{"label": key, "count": value} for key, value in hourly.items()]
        timeseries_failure_counts = [{"label": key, "count": value} for key, value in failure_hourly.items()]
        timeseries_execution_counts = [{"label": key, "count": value} for key, value in all_hourly.items()]
        timeseries_unit = "hour"
        worker_usage_base = hourly
    else:
        timeseries_counts = [{"label": key, "count": value} for key, value in daily.items()]
        timeseries_failure_counts = [{"label": key, "count": value} for key, value in failure_daily.items()]
        timeseries_execution_counts = [{"label": key, "count": value} for key, value in all_daily.items()]
        timeseries_unit = "day"
        worker_usage_base = daily

    worker_usage = OrderedDict((label, 0) for label in worker_usage_base.keys())

    for job in job_rows:
        job_start = _parse_job_timestamp(job.get("started_at")) or _parse_job_timestamp(job.get("created_at"))
        if not job_start:
            continue
        job_end = _parse_job_timestamp(job.get("finished_at")) or now

        for label in worker_usage.keys():
            if timeseries_unit == "hour":
                bucket_start = datetime.strptime(label, "%Y-%m-%d %H:%M")
                bucket_end = bucket_start + timedelta(hours=1)
            else:
                bucket_start = datetime.strptime(label, "%Y-%m-%d")
                bucket_end = bucket_start + timedelta(days=1)

            if job_start < bucket_end and job_end >= bucket_start:
                worker_usage[label] = worker_usage.get(label, 0) + 1

    worker_usage_timeseries = [{"label": key, "count": value} for key, value in worker_usage.items()]
    worker_peak = max((item["count"] for item in worker_usage_timeseries), default=0)

    sent_last_24h = _count_sent_since(timedelta(hours=24))
    sent_last_7d = _count_sent_since(timedelta(days=7))
    sent_last_30d = _count_sent_since(timedelta(days=30))

    success_rate = _percent(len(successful), total_executions)
    failure_rate = _percent(len(failures), total_executions)

    email_volume = sum(int(item.get("sent_email_count", 0) or 0) for item in successful)
    telegram_volume = sum(int(item.get("sent_telegram_count", 0) or 0) for item in successful)
    total_delivery_volume = email_volume + telegram_volume

    email_execution_count = sum(1 for item in successful if int(item.get("sent_email_count", 0) or 0) > 0)
    telegram_execution_count = sum(1 for item in successful if int(item.get("sent_telegram_count", 0) or 0) > 0)
    both_execution_count = sum(
        1
        for item in successful
        if int(item.get("sent_email_count", 0) or 0) > 0 and int(item.get("sent_telegram_count", 0) or 0) > 0
    )
    slowest_reports = sorted(
        [item for item in rows if item.get("duration_seconds", 0) > 0],
        key=lambda item: item.get("duration_seconds", 0),
        reverse=True,
    )[:10]

    avg_duration_seconds = round(
        sum(item.get("duration_seconds", 0) for item in rows if item.get("duration_seconds", 0) > 0)
        / max(1, sum(1 for item in rows if item.get("duration_seconds", 0) > 0)),
        2,
    ) if any(item.get("duration_seconds", 0) > 0 for item in rows) else 0

    return {
        "report_rows": successful,
        "failure_rows": failures,
        "recent_reports": successful[:10],
        "recent_failures": failures[:10],
        "total_executions": total_executions,
        "total_reports": len(successful),
        "total_failures": len(failures),
        "timeseries_unit": timeseries_unit,
        "timeseries_counts": timeseries_counts,
        "timeseries_failure_counts": timeseries_failure_counts,
        "timeseries_execution_counts": timeseries_execution_counts,
        "worker_usage_timeseries": worker_usage_timeseries,
        "daily_counts": [{"label": key, "count": value} for key, value in daily.items()],
        "daily_failure_counts": [{"label": key, "count": value} for key, value in failure_daily.items()],
        "daily_execution_counts": [{"label": key, "count": value} for key, value in all_daily.items()],
        "weekly_counts": [{"label": key, "count": value} for key, value in weekly.items()],
        "monthly_counts": [{"label": key, "count": value} for key, value in monthly.items()],
        "window_metrics": {
            "sent_last_24h": sent_last_24h,
            "sent_last_7d": sent_last_7d,
            "sent_last_30d": sent_last_30d,
        },
        "status_metrics": {
            "success_count": len(successful),
            "failure_count": len(failures),
            "success_rate": success_rate,
            "failure_rate": failure_rate,
        },
        "delivery_metrics": {
            "email_volume": email_volume,
            "telegram_volume": telegram_volume,
            "total_volume": total_delivery_volume,
            "email_percentage": _percent(email_volume, total_delivery_volume),
            "telegram_percentage": _percent(telegram_volume, total_delivery_volume),
            "email_execution_count": email_execution_count,
            "telegram_execution_count": telegram_execution_count,
            "both_execution_count": both_execution_count,
        },
        "duration_metrics": {
            "average_seconds": avg_duration_seconds,
            "worker_peak": worker_peak,
        },
        "slowest_reports": [
            {
                "schedule_title": item["schedule_title"],
                "duration_seconds": round(float(item.get("duration_seconds", 0) or 0), 2),
                "duration_label": _format_duration(item.get("duration_seconds", 0)),
            }
            for item in slowest_reports
        ],
    }


def get_email_config():
    conn = get_connection()
    row = conn.execute("SELECT * FROM configuracao_email WHERE id = 1").fetchone()
    conn.close()
    return dict(row)


def get_execution_config():
    conn = get_connection()
    row = conn.execute("SELECT * FROM configuracao_execucao WHERE id = 1").fetchone()
    conn.close()
    config = dict(row)
    config["max_concurrent_reports"] = normalize_max_concurrent_reports(config.get("max_concurrent_reports", DEFAULT_MAX_CONCURRENT_REPORTS))
    return config


def list_api_tokens():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, nome, created_at, updated_at
        FROM api_tokens
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def create_api_token(nome, encrypted_token):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO api_tokens (nome, api_token)
        VALUES (?, ?)
        """,
        (nome, encrypted_token),
    )
    token_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return token_id


def delete_api_token(token_id):
    conn = get_connection()
    conn.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()


def find_api_token_by_plaintext(plaintext_token, decrypt_fn):
    if not plaintext_token:
        return None
    conn = get_connection()
    rows = conn.execute("SELECT * FROM api_tokens ORDER BY id DESC").fetchall()
    conn.close()
    for row in rows:
        item = dict(row)
        encrypted_token = item.get("api_token", "")
        try:
            if encrypted_token and decrypt_fn(encrypted_token) == plaintext_token:
                return item
        except Exception:
            continue
    return None


def list_ai_prompts():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT *
        FROM ai_prompts
        ORDER BY titulo ASC, id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_ai_prompt(prompt_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM ai_prompts WHERE id = ?", (prompt_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_ai_prompt(prompt_data, prompt_id=None):
    conn = get_connection()
    fields = (
        prompt_data["titulo"],
        prompt_data["prompt_text"],
    )
    if prompt_id:
        conn.execute(
            """
            UPDATE ai_prompts
            SET titulo = ?,
                prompt_text = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            fields + (prompt_id,),
        )
        saved_id = prompt_id
    else:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_prompts (titulo, prompt_text)
            VALUES (?, ?)
            """,
            fields,
        )
        saved_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return saved_id


def delete_ai_prompt(prompt_id):
    conn = get_connection()
    conn.execute("DELETE FROM ai_prompts WHERE id = ?", (prompt_id,))
    conn.commit()
    conn.close()


def list_report_templates():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT *
        FROM report_templates
        ORDER BY nome ASC, id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_report_template(template_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM report_templates WHERE id = ?", (template_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_report_template(template_data, template_id=None):
    conn = get_connection()
    fields = (
        template_data["nome"],
        template_data.get("logo_base64", ""),
        "",
        "",
        1 if template_data.get("show_summary", True) else 0,
        template_data.get("header_text", ""),
        template_data.get("primary_color", "#f97316"),
        template_data.get("secondary_color", "#0f172a"),
        template_data.get("font_family", "Helvetica"),
        int(template_data.get("title_font_size", 20)),
        int(template_data.get("body_font_size", 11)),
    )
    if template_id:
        conn.execute(
            """
            UPDATE report_templates
            SET nome = ?,
                logo_base64 = ?,
                cover_base64 = ?,
                back_cover_base64 = ?,
                show_summary = ?,
                header_text = ?,
                primary_color = ?,
                secondary_color = ?,
                font_family = ?,
                title_font_size = ?,
                body_font_size = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            fields + (template_id,),
        )
        saved_id = template_id
    else:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO report_templates (
                nome,
                logo_base64,
                cover_base64,
                back_cover_base64,
                show_summary,
                header_text,
                primary_color,
                secondary_color,
                font_family,
                title_font_size,
                body_font_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fields,
        )
        saved_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return saved_id


def delete_report_template(template_id):
    conn = get_connection()
    conn.execute("DELETE FROM report_templates WHERE id = ?", (template_id,))
    conn.commit()
    conn.close()


def save_execution_config(config):
    conn = get_connection()
    conn.execute(
        """
        UPDATE configuracao_execucao
        SET max_concurrent_reports = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (normalize_max_concurrent_reports(config.get("max_concurrent_reports")),),
    )
    conn.commit()
    conn.close()


def generate_api_token_value():
    return secrets.token_urlsafe(32)


def save_email_config(config):
    conn = get_connection()
    conn.execute(
        """
        UPDATE configuracao_email
        SET smtp_server = ?,
            smtp_port = ?,
            smtp_username = ?,
            smtp_password = ?,
            smtp_from_email = ?,
            smtp_use_tls = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (
            config["smtp_server"],
            config["smtp_port"],
            config["smtp_username"],
            config["smtp_password"],
            config["smtp_from_email"],
            config["smtp_use_tls"],
        ),
    )
    conn.commit()
    conn.close()


def list_telegram_bots():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, nome, bot_token, selected_chats_json, created_at, updated_at
        FROM telegram_bots
        ORDER BY id ASC
        """
    ).fetchall()
    conn.close()
    bots = []
    for row in rows:
        item = dict(row)
        item["selected_chats"] = json.loads(item["selected_chats_json"] or "[]")
        bots.append(item)
    return bots


def get_telegram_bot(bot_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM telegram_bots WHERE id = ?", (bot_id,)).fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["selected_chats"] = json.loads(item["selected_chats_json"] or "[]")
    return item


def save_telegram_bot(nome, bot_token, selected_chats, bot_id=None):
    conn = get_connection()
    if bot_id:
        conn.execute(
            """
            UPDATE telegram_bots
            SET nome = ?,
                bot_token = ?,
                selected_chats_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (nome, bot_token, json.dumps(selected_chats, ensure_ascii=True), bot_id),
        )
        saved_id = bot_id
    else:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO telegram_bots (nome, bot_token, selected_chats_json)
            VALUES (?, ?, ?)
            """,
            (nome, bot_token, json.dumps(selected_chats, ensure_ascii=True)),
        )
        saved_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return saved_id


def delete_telegram_bot(bot_id):
    conn = get_connection()
    conn.execute("DELETE FROM telegram_bots WHERE id = ?", (bot_id,))
    conn.commit()
    conn.close()


def get_ai_config():
    conn = get_connection()
    row = conn.execute("SELECT * FROM configuracao_ia WHERE id = 1").fetchone()
    conn.close()
    return dict(row)


def save_ai_config(config):
    conn = get_connection()
    conn.execute(
        """
        UPDATE configuracao_ia
        SET provider = ?,
            api_key = ?,
            endpoint = ?,
            model = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (
            config["provider"],
            config["api_key"],
            config["endpoint"],
            config["model"],
        ),
    )
    conn.commit()
    conn.close()


init_db()
