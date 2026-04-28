"""Run orchestration for project and deploy actions."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import threading

from app.db.database import Database, utc_now_iso

DEPLOY_COMMANDS = {
    "vercel": ["vercel", "--prod"],
    "netlify": ["netlify", "deploy", "--prod"],
    "fly": ["fly", "deploy"],
    "railway": ["railway", "up"],
}


class RunService:
    def __init__(self, db: Database, *, base_dir: Path | None = None):
        self.db = db
        self.base_dir = Path(base_dir or Path.cwd())
        self._coordinator_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._active_runs: set[int] = set()
        self._processes: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def list_runs(self, project_id: int | None = None) -> list[dict]:
        with self.db.connect() as conn:
            if project_id is None:
                rows = conn.execute(
                    """
                    SELECT ar.id, ar.project_id, p.display_name, ar.agent_type, ar.skill_name, ar.cwd, ar.command, ar.status,
                           ar.started_at, ar.finished_at, ar.output_summary, ar.artifact_dir, ar.log_path
                    FROM agent_runs ar
                    LEFT JOIN projects p ON p.id = ar.project_id
                    ORDER BY ar.started_at DESC, ar.id DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT ar.id, ar.project_id, p.display_name, ar.agent_type, ar.skill_name, ar.cwd, ar.command, ar.status,
                           ar.started_at, ar.finished_at, ar.output_summary, ar.artifact_dir, ar.log_path
                    FROM agent_runs ar
                    LEFT JOIN projects p ON p.id = ar.project_id
                    WHERE ar.project_id = ?
                    ORDER BY ar.started_at DESC, ar.id DESC
                    """
                    ,
                    (project_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_skills(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT name, source, description, supports_codex, supports_openclaw, requires_interaction
                FROM skill_definitions
                ORDER BY name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def queue_run(self, payload: dict) -> int:
        cwd = str(payload["cwd"])
        command = self.display_command(payload["agent_type"], payload["skill_name"], cwd)
        started_at = utc_now_iso()
        artifact_dir = self._artifact_dir(payload["project_id"], started_at)
        log_path = self._log_path(payload["project_id"], started_at)
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent_runs
                (project_id, agent_type, skill_name, cwd, command, status, started_at, artifact_dir, log_path)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    payload["project_id"],
                    payload["agent_type"],
                    payload["skill_name"],
                    cwd,
                    command,
                    started_at,
                    artifact_dir,
                    log_path,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def cancel_run(self, run_id: int) -> dict:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, status
                FROM agent_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Run not found")

            status = str(row["status"])
            if status in {"finished", "failed", "cancelled"}:
                raise ValueError(f"Run is already {status}")

            if status == "queued":
                conn.execute(
                    """
                    UPDATE agent_runs
                    SET status = 'cancelled', finished_at = ?, output_summary = ?
                    WHERE id = ?
                    """,
                    (utc_now_iso(), "run cancelled before start", run_id),
                )
                conn.commit()
                self._sync_deploy_snapshot_state(run_id, "cancelled")
                return {"run_id": run_id, "status": "cancelled"}

            conn.execute(
                """
                UPDATE agent_runs
                SET status = 'cancelling', output_summary = ?
                WHERE id = ?
                """,
                ("cancellation requested", run_id),
            )
            conn.commit()

        with self._lock:
            process = self._processes.get(run_id)
        if process is not None:
            process.terminate()
        return {"run_id": run_id, "status": "cancelling"}

    def get_run_log(self, run_id: int, max_bytes: int = 24000) -> dict:
        run = self._load_run(run_id)
        if run is None:
            raise ValueError("Run not found")

        log_path = self.base_dir / str(run["log_path"])
        if not log_path.exists():
            return {"run_id": run_id, "status": run.get("status"), "log_path": str(run["log_path"]), "content": ""}

        try:
            raw = log_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Unable to read log: {exc}") from exc

        content = raw[-max_bytes:]
        return {
            "run_id": run_id,
            "status": run.get("status"),
            "log_path": str(run["log_path"]),
            "content": content,
        }

    def start(self) -> None:
        if self._coordinator_thread and self._coordinator_thread.is_alive():
            return
        self._recover_incomplete_runs()
        self._stop_event.clear()
        self._coordinator_thread = threading.Thread(target=self._coordinator_loop, name="project-radar-runs", daemon=True)
        self._coordinator_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._coordinator_thread and self._coordinator_thread.is_alive():
            self._coordinator_thread.join(timeout=2)

    def display_command(self, agent_type: str, skill_name: str, cwd: str) -> str:
        args = self.command_args(agent_type, skill_name, cwd)
        return subprocess.list2cmdline(args)

    def command_args(self, agent_type: str, skill_name: str, cwd: str) -> list[str]:
        normalized_agent = str(agent_type).strip().lower()
        normalized_skill = str(skill_name).strip()

        if normalized_agent in {"codex", "openclaw"}:
            return self._agent_command_args(normalized_agent, normalized_skill, cwd)
        if normalized_agent == "deploy":
            return self._deploy_command_args(normalized_skill)
        raise ValueError(f"Unsupported agent type: {agent_type}")

    def _agent_command_args(self, agent_type: str, skill_name: str, cwd: str) -> list[str]:
        prompt = self._skill_prompt(skill_name)
        if agent_type == "openclaw":
            return ["openclaw", "--cwd", cwd, prompt]
        return ["codex", "--cwd", cwd, prompt]

    def _skill_prompt(self, skill_name: str) -> str:
        prompts = {
            "canary": "use gstack canary in this workspace and verify the deployed app health",
            "document-release": "use gstack document-release in this workspace and update the docs to match what just shipped",
            "investigate": "use gstack investigate in this workspace and root-cause the highest-severity current problem",
            "office-hours": "use gstack office-hours in this workspace and rethink the highest-value product direction",
            "plan-ceo-review": "use gstack plan-ceo-review in this workspace and sharpen the product scope and ambition",
            "plan-design-review": "use gstack plan-design-review in this workspace and critique the user experience direction",
            "plan-eng-review": "use gstack plan-eng-review in this workspace and lock in the engineering plan",
            "qa": "use gstack qa in this workspace and find and fix the highest-value defects",
            "qa-only": "use gstack qa-only in this workspace and report the highest-value defects without changing code",
            "review": "use gstack review in this workspace and review the current diff for bugs and regressions",
            "ship": "use gstack ship in this workspace and ship the current ready changes",
        }
        return prompts.get(skill_name, f"use gstack {skill_name} in this workspace and improve the highest-value next issue")

    def _deploy_command_args(self, skill_name: str) -> list[str]:
        if not skill_name.startswith("deploy:"):
            raise ValueError(f"Unsupported deploy skill: {skill_name}")
        provider = skill_name.split(":", 1)[1].strip().lower()
        command = DEPLOY_COMMANDS.get(provider)
        if command is None:
            raise ValueError(f"Unsupported deploy provider: {provider}")
        return list(command)

    def _artifact_dir(self, project_id: int, started_at: str) -> str:
        safe_stamp = started_at.replace(":", "-")
        return str(Path("storage") / "artifacts" / f"project-{project_id}" / safe_stamp)

    def _log_path(self, project_id: int, started_at: str) -> str:
        safe_stamp = started_at.replace(":", "-")
        return str(Path("storage") / "logs" / f"project-{project_id}-{safe_stamp}.log")

    def _coordinator_loop(self) -> None:
        while not self._stop_event.is_set():
            for run_id in self._queued_run_ids():
                with self._lock:
                    if run_id in self._active_runs:
                        continue
                    self._active_runs.add(run_id)
                worker = threading.Thread(target=self._execute_run, args=(run_id,), name=f"project-radar-run-{run_id}", daemon=True)
                worker.start()
            self._stop_event.wait(2)

    def _queued_run_ids(self) -> list[int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id
                FROM agent_runs
                WHERE status = 'queued'
                ORDER BY started_at ASC, id ASC
                """
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def _execute_run(self, run_id: int) -> None:
        try:
            run = self._load_run(run_id)
            if run is None:
                return
            log_path = self.base_dir / str(run["log_path"])
            artifact_dir = self.base_dir / str(run["artifact_dir"])
            log_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_dir.mkdir(parents=True, exist_ok=True)

            with self.db.connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE agent_runs
                    SET status = 'running'
                    WHERE id = ? AND status = 'queued'
                    """,
                    (run_id,),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    return

            command_args = self.command_args(str(run["agent_type"]), str(run["skill_name"]), str(run["cwd"]))
            command = subprocess.list2cmdline(command_args)
            executable = Path(command_args[0]).name
            missing_binary = shutil.which(executable) is None
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{utc_now_iso()}] starting run {run_id}\n")
                handle.write(f"cwd: {run['cwd']}\n")
                handle.write(f"command: {command}\n\n")
                handle.flush()

                if missing_binary:
                    handle.write(f"agent binary not found on PATH: {executable}\n")
                    summary = f"{executable} not found on PATH"
                    self._finish_run(run_id, status="failed", output_summary=summary)
                    return

                process = subprocess.Popen(
                    command_args,
                    cwd=str(run["cwd"]),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                with self._lock:
                    self._processes[run_id] = process

                output_lines: list[str] = []
                if process.stdout is not None:
                    for line in process.stdout:
                        handle.write(line)
                        handle.flush()
                        output_lines.append(line.rstrip())
                returncode = process.wait()

                with self._lock:
                    self._processes.pop(run_id, None)

                current_status = self._current_status(run_id)
                combined_output = "\n".join(line for line in output_lines if line)
                summary = self._build_summary(returncode, combined_output, None)
                status = "cancelled" if current_status == "cancelling" else ("finished" if returncode == 0 else "failed")
                self._finish_run(run_id, status=status, output_summary=summary)
        except Exception as exc:
            self._finish_run(run_id, status="failed", output_summary=f"run coordinator error: {exc}")
        finally:
            with self._lock:
                self._processes.pop(run_id, None)
            with self._lock:
                self._active_runs.discard(run_id)

    def _load_run(self, run_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, project_id, agent_type, skill_name, cwd, command, status, artifact_dir, log_path
                FROM agent_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def _finish_run(self, run_id: int, *, status: str, output_summary: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = ?, finished_at = ?, output_summary = ?
                WHERE id = ?
                """,
                (status, utc_now_iso(), output_summary[:500], run_id),
            )
            conn.commit()
        self._sync_deploy_snapshot_state(run_id, status)

    def _build_summary(self, returncode: int, stdout: str | None, stderr: str | None) -> str:
        if returncode < 0:
            return "run terminated"
        if returncode == 0:
            output = (stdout or "").strip()
            if output:
                return output.splitlines()[-1][:500]
            return "run completed successfully"
        err = (stderr or stdout or "").strip()
        if err:
            return err.splitlines()[-1][:500]
        return f"run failed with exit code {returncode}"

    def _recover_incomplete_runs(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = 'queued'
                WHERE status IN ('running', 'cancelling')
                """
            )
            conn.commit()

    def _current_status(self, run_id: int) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT status FROM agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return str(row["status"]) if row else None

    def _sync_deploy_snapshot_state(self, run_id: int, status: str) -> None:
        run = self._load_run(run_id)
        if run is None:
            return
        skill_name = str(run.get("skill_name") or "")
        if not skill_name.startswith("deploy:"):
            return

        provider = skill_name.split(":", 1)[1] or "unknown"
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE deploy_snapshots
                SET state = ?, updated_at = ?
                WHERE project_id = ? AND provider = ?
                """,
                (status, utc_now_iso(), int(run["project_id"]), provider),
            )
            conn.commit()
