import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from paths import data_path
from report_runner import log_message, run_schedule
from database import (
    claim_next_report_job,
    enqueue_report_job,
    finish_report_job,
    get_execution_config,
    get_schedule,
    MAX_CONCURRENT_REPORTS_LIMIT,
    reset_running_report_jobs,
)


DB_FILE = data_path("database.db")
SCHEDULE_SCAN_INTERVAL_SECONDS = 10
QUEUE_IDLE_INTERVAL_SECONDS = 2
WORKER_NAME = "scheduler"

DIAS_SEMANA_PT = {
    "monday": "segunda",
    "tuesday": "terca",
    "wednesday": "quarta",
    "thursday": "quinta",
    "friday": "sexta",
    "saturday": "sabado",
    "sunday": "domingo",
}


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_due_schedules(conn, now):
    hora_atual = now.strftime("%H:%M")
    dia_semana = DIAS_SEMANA_PT[now.strftime("%A").lower()]
    dia_mes = str(int(now.strftime("%d")))

    rows = conn.execute(
        """
        SELECT *
        FROM agendamentos
        WHERE horario = ?
          AND (
            periodo = 'diario'
            OR (periodo = 'semanal' AND detalhe_periodo = ?)
            OR (periodo = 'mensal' AND detalhe_periodo = ?)
          )
        ORDER BY id ASC
        """,
        (hora_atual, dia_semana, dia_mes),
    ).fetchall()

    schedules = []
    for row in rows:
        item = dict(row)
        item["selected_targets"] = json.loads(item.get("selected_targets_json") or "[]")
        item["delivery_methods"] = json.loads(item.get("delivery_methods_json") or "[]")
        item["use_ai"] = bool(item.get("use_ai"))
        schedules.append(item)
    return schedules


def enqueue_due_schedules():
    while True:
        now = datetime.now()
        conn = get_connection()
        try:
            due_schedules = get_due_schedules(conn, now)
        finally:
            conn.close()

        current_key = now.strftime("%Y-%m-%d %H:%M")
        for schedule in due_schedules:
            try:
                job = enqueue_report_job(
                    schedule_id=schedule["id"],
                    trigger_source="scheduled",
                    requested_by="scheduler",
                    dedupe_key=current_key,
                )
                if job["created"]:
                    log_message(
                        f"Agendamento {schedule['id']} - {schedule['titulo']} enfileirado para execucao automatica (job {job['id']})."
                    )
            except Exception as exc:
                log_message(f"Falha ao enfileirar agendamento {schedule['id']}: {exc}")

        time.sleep(SCHEDULE_SCAN_INTERVAL_SECONDS)


def process_report_jobs():
    reset_running_report_jobs()
    log_message("Fila de relatorios inicializada.")

    def run_job(job):
        schedule = get_schedule(job["schedule_id"])
        if not schedule:
            message = f"Agendamento {job['schedule_id']} nao encontrado para o job {job['id']}."
            finish_report_job(job["id"], "failed", message)
            log_message(message)
            return

        try:
            log_message(
                f"Processando job {job['id']} do agendamento {schedule['id']} - {schedule['titulo']} "
                f"(origem={job['trigger_source']}, tentativa={job['attempt_count']}, worker={job['worker_name']})."
            )
            result = run_schedule(schedule, job_id=job["id"]) or {}
            status = result.get("status", "success")
            finish_report_job(job["id"], status, "")
            log_message(f"Job {job['id']} concluido com status {status}.")
        except Exception as exc:
            finish_report_job(job["id"], "failed", str(exc))
            log_message(f"Job {job['id']} falhou: {exc}")

    active_futures = {}
    last_logged_limit = None

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REPORTS_LIMIT, thread_name_prefix="report-worker") as executor:
        while True:
            for future, future_job in list(active_futures.items()):
                if not future.done():
                    continue
                try:
                    future.result()
                except Exception as exc:
                    log_message(f"Worker do job {future_job['id']} encerrou com erro inesperado: {exc}")
                finally:
                    active_futures.pop(future, None)

            execution_config = get_execution_config()
            max_concurrent_reports = int(execution_config.get("max_concurrent_reports", MAX_CONCURRENT_REPORTS_LIMIT) or MAX_CONCURRENT_REPORTS_LIMIT)

            if max_concurrent_reports != last_logged_limit:
                log_message(f"Limite de relatorios simultaneos ajustado para {max_concurrent_reports}.")
                last_logged_limit = max_concurrent_reports

            available_slots = max(0, max_concurrent_reports - len(active_futures))
            claimed_any = False

            for slot in range(available_slots):
                worker_name = f"{WORKER_NAME}-{slot + 1}"
                job = claim_next_report_job(worker_name=worker_name)
                if not job:
                    break
                claimed_any = True
                future = executor.submit(run_job, job)
                active_futures[future] = job

            if not claimed_any and not active_futures:
                time.sleep(QUEUE_IDLE_INTERVAL_SECONDS)
            else:
                time.sleep(0.5)


def check_schedules():
    enqueue_thread = threading.Thread(target=enqueue_due_schedules, name="due-schedule-enqueuer", daemon=True)
    enqueue_thread.start()
    process_report_jobs()


if __name__ == "__main__":
    try:
        check_schedules()
    except KeyboardInterrupt:
        log_message("Agendador encerrado pelo usuario.")
