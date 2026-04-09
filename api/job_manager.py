"""Gerenciador de Jobs - fila, subprocess, monitoramento, stats."""

import asyncio
import json
import os
import re
import signal
import subprocess
import time
import shutil
import sys
import uuid
from pathlib import Path
from typing import Optional

from api.stats_tracker import STAGES, estimate_remaining, record_job_complete, format_eta

JOBS_DIR = Path(os.environ.get("JOBS_DIR", "jobs"))
PIPELINE_SCRIPT = os.environ.get("PIPELINE_SCRIPT", "dublar_pro_v5.py")
PYTHON_BIN = os.environ.get("PYTHON_BIN", sys.executable or shutil.which("python3") or "python3")
PROJECT_DIR = Path(__file__).parent.parent.resolve()

# Stages para jobs de corte manual (3 etapas)
STAGES_CUT_MANUAL = [
    {"num": 1, "id": "download", "name": "Download", "icon": "⬇"},
    {"num": 2, "id": "cutting", "name": "Cortando clips", "icon": "✂"},
    {"num": 3, "id": "zip", "name": "Criando ZIP", "icon": "📦"},
]

# Stages para jobs de corte viral (6 etapas)
STAGES_CUT_VIRAL = [
    {"num": 1, "id": "download", "name": "Download", "icon": "⬇"},
    {"num": 2, "id": "extraction", "name": "Extracao de audio", "icon": "🔊"},
    {"num": 3, "id": "transcription", "name": "Transcricao", "icon": "📝"},
    {"num": 4, "id": "analysis", "name": "Analise viral", "icon": "🔥"},
    {"num": 5, "id": "cutting", "name": "Cortando clips", "icon": "✂"},
    {"num": 6, "id": "zip", "name": "Criando ZIP", "icon": "📦"},
]

# Stages para jobs de transcricao (4 etapas)
STAGES_TRANSCRIPTION = [
    {"num": 1, "id": "download", "name": "Download", "icon": "⬇"},
    {"num": 2, "id": "extraction", "name": "Extracao de audio", "icon": "🔊"},
    {"num": 3, "id": "transcription", "name": "Transcricao", "icon": "📝"},
    {"num": 4, "id": "export", "name": "Exportando legendas", "icon": "💾"},
]

# Stages para jobs de download (1 etapa)
STAGES_DOWNLOAD = [
    {"num": 1, "id": "download", "name": "Baixando video", "icon": "⬇"},
]

# Stages para jobs de TTS (1 etapa)
STAGES_TTS = [
    {"num": 1, "id": "generating", "name": "Gerando audio", "icon": "🔊"},
]

print(f"[JobManager] Modo: CPU | Python: {PYTHON_BIN}")


class Job:
    def __init__(self, job_id: str, config: dict):
        self.id = job_id
        self.config = config
        self.status = "queued"
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self.process: Optional[subprocess.Popen] = None
        self.workdir = JOBS_DIR / job_id
        self.error = None
        self.device = "cpu"
        self.stage_times: dict[str, float] = {}
        self._last_stage_num = 0
        self._last_stage_start = 0.0
        self._user_cancelled = False

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0
        end = self.finished_at or time.time()
        return end - self.started_at

    def _get_stages(self) -> list:
        """Retorna a lista de stages corretos baseado no tipo de job."""
        job_type = self.config.get("job_type", "dubbing")
        if job_type == "cutting":
            mode = self.config.get("mode", "manual")
            if mode in ("viral", "topics") and not self.config.get("split_equal"):
                return STAGES_CUT_VIRAL
            return STAGES_CUT_MANUAL
        elif job_type == "transcription":
            return STAGES_TRANSCRIPTION
        elif job_type == "download":
            return STAGES_DOWNLOAD
        elif job_type in ("tts_generate", "voice_clone"):
            return STAGES_TTS
        else:
            return STAGES

    def _recover_if_output_exists(self):
        """Se marcado como failed mas arquivos de saida existem, recuperar para completed."""
        if self.status != "failed":
            return
        job_type = self.config.get("job_type", "dubbing")
        if job_type == "transcription":
            td = self.workdir / "transcription"
            if td.exists() and any(td.glob("transcript.*")):
                self.status = "completed"
                self.error = None
        elif job_type == "cutting":
            cd = self.workdir / "clips"
            if cd.exists() and any(cd.glob("clip_*.mp4")):
                self.status = "completed"
                self.error = None
        elif job_type == "download":
            dd = self.workdir / "download"
            if dd.exists() and any(dd.glob("video.*")):
                self.status = "completed"
                self.error = None
        elif job_type in ("tts_generate", "voice_clone"):
            ao = self.workdir / "audio_out"
            if ao.exists() and any(ao.glob("generated.*")):
                self.status = "completed"
                self.error = None
        else:
            dd = self.workdir / "dublado"
            if dd.exists() and any(dd.glob("*.mp4")):
                self.status = "completed"
                self.error = None

    def to_dict(self) -> dict:
        self._recover_if_output_exists()
        checkpoint = self._read_checkpoint()
        progress = self._calc_progress(checkpoint)

        cp_data = checkpoint.get("data", {}) or {}
        video_title = cp_data.get("video_title", "") or ""
        video_duration_s = cp_data.get("video_duration_s", 0) or 0

        if not video_title or not video_duration_s:
            ts_path = self.workdir / "transcription" / "transcript_summary.json"
            if ts_path.exists():
                try:
                    ts = json.loads(ts_path.read_text())
                    if not video_title:
                        video_title = ts.get("title", "") or ""
                    if not video_duration_s:
                        video_duration_s = ts.get("duration_s", 0) or 0
                except Exception:
                    pass

        if not video_title:
            cfg_input = self.config.get("input") or self.config.get("url") or ""
            if cfg_input and not cfg_input.startswith("http"):
                video_title = Path(cfg_input).stem

        return {
            "id": self.id,
            "status": self.status,
            "config": self.config,
            "device": self.device,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(self.duration, 1),
            "error": self.error,
            "checkpoint": checkpoint,
            "progress": progress,
            "stage_times": self.stage_times,
            "video_title": video_title,
            "video_duration_s": video_duration_s,
        }

    def _read_checkpoint(self) -> dict:
        cp_path = self.workdir / "dub_work" / "checkpoint.json"
        if cp_path.exists():
            try:
                return json.loads(cp_path.read_text())
            except Exception:
                pass
        return {}

    def _calc_progress_simple(self, checkpoint: dict) -> dict:
        """Calculo de progresso simplificado para jobs nao-dubbing (sem ETA)."""
        stages = self._get_stages()
        current_step = checkpoint.get("last_step_num", 0)
        total = len(stages)
        percent = round((current_step / total) * 100) if total > 0 else 0

        if current_step != self._last_stage_num and current_step > 0:
            now = time.time()
            start_time = self._last_stage_start if self._last_stage_start > 0 else (self.started_at or now)
            elapsed = round(now - start_time, 1)

            stages_completed = current_step - self._last_stage_num
            if stages_completed > 0:
                per_stage = round(elapsed / stages_completed, 1)
                for i in range(self._last_stage_num, current_step):
                    if i < len(stages):
                        self.stage_times[stages[i]["id"]] = per_stage

            self._last_stage_num = current_step
            self._last_stage_start = now
        elif self._last_stage_num == 0 and self.started_at:
            self._last_stage_start = self.started_at

        current_stage_elapsed = round(time.time() - self._last_stage_start, 1) if self._last_stage_start > 0 else 0

        stages_info = []
        for stage in stages:
            snum = stage["num"]
            sid = stage["id"]
            if snum < current_step + 1:
                st = {**stage, "status": "done", "time": self.stage_times.get(sid)}
            elif snum == current_step + 1:
                st = {**stage, "status": "running", "elapsed": current_stage_elapsed}
                log_progress = self._parse_log_progress()
                if log_progress:
                    st["log_progress"] = log_progress
            else:
                st = {**stage, "status": "pending"}
            stages_info.append(st)

        stage_name = stages[current_step]["name"] if current_step < total else "Concluido"
        stage_id = stages[current_step]["id"] if current_step < total else "done"

        return {
            "current_stage": current_step,
            "next_stage": current_step + 1,
            "total_stages": total,
            "percent": percent,
            "stage_name": stage_name,
            "stage_id": stage_id,
            "stages": stages_info,
            "device": self.device,
            "eta_seconds": None,
            "eta_text": None,
            "eta_confidence": "low",
            "elapsed_s": round(self.duration, 1),
        }

    def _calc_progress(self, checkpoint: dict) -> dict:
        job_type = self.config.get("job_type", "dubbing")
        if job_type != "dubbing":
            return self._calc_progress_simple(checkpoint)

        current_step = checkpoint.get("last_step_num", 0)
        total = len(STAGES)
        percent = round((current_step / total) * 100) if total > 0 else 0

        if current_step != self._last_stage_num and current_step > 0:
            now = time.time()
            start_time = self._last_stage_start if self._last_stage_start > 0 else (self.started_at or now)
            elapsed = round(now - start_time, 1)

            stages_completed = current_step - self._last_stage_num
            if stages_completed > 0:
                per_stage = round(elapsed / stages_completed, 1)
                for i in range(self._last_stage_num, current_step):
                    if i < len(STAGES):
                        self.stage_times[STAGES[i]["id"]] = per_stage

            self._last_stage_num = current_step
            self._last_stage_start = now
        elif self._last_stage_num == 0 and self.started_at:
            self._last_stage_start = self.started_at

        eta = estimate_remaining(self.config, current_step, 0, self.device)
        eta_text = format_eta(eta["eta_seconds"]) if eta else "?"

        current_stage_elapsed = round(time.time() - self._last_stage_start, 1) if self._last_stage_start > 0 else 0

        cfg = self.config
        asr_engine = cfg.get("asr_engine", cfg.get("engine", "whisper-cpu"))
        asr_label = asr_engine
        if asr_engine in ("whisper", "whisper-cpu"):
            asr_label = f"whisper {cfg.get('whisper_model', 'small')}"
        elif asr_engine == "groq":
            asr_label = f"groq {cfg.get('groq_model', 'whisper-large-v3-turbo')}"

        trad_label = cfg.get("translation_engine", "m2m100")
        stage_tools = {
            "download": "yt-dlp",
            "extraction": "ffmpeg",
            "transcription": asr_label,
            "translation": trad_label,
            "split": "ffmpeg",
            "tts": cfg.get("tts_engine", "edge"),
            "sync": cfg.get("sync_mode", "smart"),
            "concat": "ffmpeg",
            "postprocess": "rubberband",
            "mux": "ffmpeg",
        }

        stages_info = []
        for stage in STAGES:
            snum = stage["num"]
            sid = stage["id"]
            tool = stage_tools.get(sid, "")
            if snum < current_step + 1:
                st = {**stage, "status": "done", "time": self.stage_times.get(sid), "tool": tool}
            elif snum == current_step + 1:
                st = {**stage, "status": "running", "elapsed": current_stage_elapsed, "tool": tool}
                log_progress = self._parse_log_progress()
                if log_progress:
                    st["log_progress"] = log_progress
            else:
                est = eta["stage_estimates"].get(sid, {}).get("est_seconds") if eta else None
                st = {**stage, "status": "pending", "estimate": est, "tool": tool}
            stages_info.append(st)

        return {
            "current_stage": current_step,
            "next_stage": current_step + 1,
            "total_stages": total,
            "percent": percent,
            "stage_name": STAGES[current_step]["name"] if current_step < total else "Concluido",
            "stage_id": STAGES[current_step]["id"] if current_step < total else "done",
            "stages": stages_info,
            "device": self.device,
            "eta_seconds": eta["eta_seconds"] if eta else None,
            "eta_text": eta_text,
            "eta_confidence": eta["confidence"] if eta else "low",
            "elapsed_s": round(self.duration, 1),
        }

    def _parse_log_progress(self) -> dict | None:
        """Extrai progresso do yt-dlp ou outras ferramentas do output.log."""
        log_path = self.workdir / "output.log"
        if not log_path.exists():
            return None
        try:
            with open(log_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                tail = f.read().decode("utf-8", errors="replace")
            match = re.search(
                r"\[download\]\s+([\d.]+)%\s+of\s+~?([\d.]+\S+)\s+at\s+([\d.]+\S+)\s+ETA\s+(\S+)",
                tail,
            )
            if match:
                return {
                    "type": "download",
                    "percent": float(match.group(1)),
                    "size": match.group(2),
                    "speed": match.group(3),
                    "eta": match.group(4),
                }
            if "[Merger]" in tail or "Merging formats" in tail:
                return {"type": "download", "percent": 99, "detail": "Mesclando audio+video..."}
        except Exception:
            pass
        return None

    def read_logs(self, last_n: int = 50) -> list:
        log_path = self.workdir / "output.log"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text().splitlines()
            return lines[-last_n:]
        except Exception:
            return []


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._subscribers: dict[str, list] = {}
        JOBS_DIR.mkdir(exist_ok=True)

    def start(self):
        self._load_existing_jobs()
        self._worker_task = asyncio.create_task(self._worker())

    def _load_existing_jobs(self):
        """Recarrega jobs existentes do disco (sobrevive a restarts/reloads)."""
        if not JOBS_DIR.exists():
            return
        loaded = 0
        for job_dir in sorted(JOBS_DIR.iterdir()):
            if not job_dir.is_dir():
                continue
            config_path = job_dir / "config.json"
            if not config_path.exists():
                continue
            job_id = job_dir.name
            existing = self.jobs.get(job_id)
            if existing and existing.status in ("completed", "running", "queued"):
                continue
            if existing and existing.status in ("failed", "cancelled"):
                existing_config = existing.config
                existing_type = existing_config.get("job_type", "dubbing")
                if existing_type == "cutting":
                    clips_dir = job_dir / "clips"
                    if clips_dir.exists() and any(clips_dir.glob("clip_*.mp4")):
                        existing.status = "completed"
                        existing.error = None
                elif existing_type == "transcription":
                    transcript_dir = job_dir / "transcription"
                    if transcript_dir.exists() and any(transcript_dir.glob("transcript.*")):
                        existing.status = "completed"
                        existing.error = None
                elif existing_type == "download":
                    dl_dir = job_dir / "download"
                    if dl_dir.exists() and any(dl_dir.glob("video.*")):
                        existing.status = "completed"
                        existing.error = None
                else:
                    dublado_dir = job_dir / "dublado"
                    if dublado_dir.exists() and any(dublado_dir.glob("*.mp4")):
                        existing.status = "completed"
                        existing.error = None
                continue
            try:
                config = json.loads(config_path.read_text())
                job = Job(job_id, config)
                job_type = config.get("job_type", "dubbing")

                job.created_at = config_path.stat().st_mtime
                times_path = job_dir / "stage_times.json"
                if times_path.exists():
                    try:
                        job.stage_times = json.loads(times_path.read_text())
                    except Exception:
                        pass
                checkpoint = job._read_checkpoint()
                if checkpoint.get("last_step_num"):
                    job._last_stage_num = checkpoint["last_step_num"]

                log_path = job_dir / "output.log"
                if log_path.exists():
                    log_stat = log_path.stat()
                    job.started_at = log_stat.st_mtime
                    if job.stage_times:
                        total_dur = sum(job.stage_times.values())
                        job.started_at = job.created_at
                        job.finished_at = job.created_at + total_dur

                if job_type == "cutting":
                    clips_dir = job_dir / "clips"
                    has_output = clips_dir.exists() and any(clips_dir.glob("clip_*.mp4"))
                elif job_type == "transcription":
                    transcript_dir = job_dir / "transcription"
                    has_output = transcript_dir.exists() and any(
                        transcript_dir.glob("transcript.*")
                    )
                elif job_type == "download":
                    dl_dir = job_dir / "download"
                    has_output = dl_dir.exists() and any(dl_dir.glob("video.*"))
                else:
                    dublado_dir = job_dir / "dublado"
                    has_output = dublado_dir.exists() and any(dublado_dir.glob("*.mp4"))

                if has_output:
                    job.status = "completed"
                elif log_path.exists():
                    log_text = log_path.read_text()
                    if "Traceback" in log_text or "Error" in log_text[-500:]:
                        job.status = "failed"
                        for line in reversed(log_text.splitlines()[-20:]):
                            if "error" in line.lower() or "exception" in line.lower():
                                job.error = line.strip()
                                break
                    elif checkpoint:
                        job.status = "failed"
                        job.error = f"Interrompido na etapa {checkpoint.get('last_step', '?')}"
                    else:
                        job.status = "failed"
                else:
                    job.status = "queued"
                self.jobs[job_id] = job
                loaded += 1
            except Exception as e:
                print(f"[JobManager] Erro ao carregar job {job_id}: {e}")
        if loaded:
            print(f"[JobManager] {loaded} jobs carregados do disco")

    async def _worker(self):
        while True:
            job_id = await self.queue.get()
            job = self.jobs.get(job_id)
            if job and job.status == "queued":
                await self._run_job(job)
            self.queue.task_done()

    async def create_job(self, config: dict) -> Job:
        job_id = str(uuid.uuid4())[:8]
        job = Job(job_id, config)
        job_type = config.get("job_type", "dubbing")

        job.workdir.mkdir(parents=True, exist_ok=True)
        (job.workdir / "dub_work").mkdir(exist_ok=True)

        if job_type == "cutting":
            (job.workdir / "clips").mkdir(exist_ok=True)
        elif job_type == "transcription":
            (job.workdir / "transcription").mkdir(exist_ok=True)
        elif job_type == "download":
            (job.workdir / "download").mkdir(exist_ok=True)
        elif job_type in ("tts_generate", "voice_clone"):
            (job.workdir / "audio_out").mkdir(exist_ok=True)
        else:
            (job.workdir / "dublado").mkdir(exist_ok=True)

        self.jobs[job_id] = job
        (job.workdir / "config.json").write_text(json.dumps(config, indent=2))

        await self.queue.put(job_id)
        await self._notify(job_id, {"event": "created", "job": job.to_dict()})
        return job

    async def _run_job(self, job: Job):
        job.status = "running"
        job.started_at = time.time()
        job._last_stage_start = job.started_at
        await self._notify(job.id, {"event": "started", "job": job.to_dict()})

        job_type = job.config.get("job_type", "dubbing")

        if job_type == "cutting":
            cmd = self._build_cut_command(job)
        elif job_type == "transcription":
            cmd = self._build_transcribe_command(job)
        elif job_type == "download":
            cmd = self._build_download_command(job)
        elif job_type in ("tts_generate", "voice_clone"):
            cmd = self._build_tts_command(job)
        else:
            cmd = self._build_dub_command(job)

        log_path = job.workdir / "output.log"

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            python_dir = os.path.dirname(PYTHON_BIN)
            if python_dir not in env.get("PATH", ""):
                env["PATH"] = python_dir + ":" + env.get("PATH", "")

            with open(log_path, "w") as log_file:
                job.process = subprocess.Popen(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    cwd=str(job.workdir),
                    env=env,
                )

                while job.process.poll() is None:
                    await asyncio.sleep(2)
                    await self._notify(job.id, {
                        "event": "progress",
                        "job": job.to_dict(),
                    })

                exit_code = job.process.returncode
                job.finished_at = time.time()

                checkpoint = job._read_checkpoint()
                job._calc_progress(checkpoint)

                stages = job._get_stages()
                if job._last_stage_num > 0 and job._last_stage_num <= len(stages):
                    last_sid = stages[job._last_stage_num - 1]["id"]
                    job.stage_times[last_sid] = round(job.finished_at - job._last_stage_start, 1)

                try:
                    times_path = job.workdir / "stage_times.json"
                    times_path.write_text(json.dumps(job.stage_times, indent=2))
                except Exception:
                    pass

                if exit_code == 0:
                    job.status = "completed"
                    if job_type == "dubbing":
                        record_job_complete(job.config, job.stage_times, job.duration, job.device)
                elif job._user_cancelled or exit_code == -signal.SIGTERM:
                    job.status = "cancelled"
                else:
                    job.status = "failed"
                    error_msg = f"Exit code: {exit_code}"
                    if exit_code == -signal.SIGKILL:
                        error_msg = f"Processo encerrado pelo sistema (SIGKILL, exit {exit_code}) — possivel OOM killer"
                    try:
                        lines = log_path.read_text().splitlines()
                        for line in reversed(lines[-20:]):
                            if "error" in line.lower() or "traceback" in line.lower() or "exception" in line.lower():
                                error_msg = line.strip()
                                break
                    except Exception:
                        pass
                    job.error = error_msg

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = time.time()

        await self._notify(job.id, {"event": "finished", "job": job.to_dict()})

    def _build_cut_command(self, job: Job) -> list:
        """Monta comando para corte de clips."""
        config = job.config
        script_path = str(PROJECT_DIR / "clipar_v1.py")
        cmd = [PYTHON_BIN, script_path]

        cmd.extend(["--in", config["input"]])
        cmd.extend(["--outdir", str(job.workdir.resolve() / "clips")])
        cmd.extend(["--mode", config.get("mode", "manual")])

        if config.get("mode") == "manual" and config.get("timestamps"):
            cmd.extend(["--timestamps", config["timestamps"]])
        elif config.get("mode") in ("viral", "topics"):
            if config.get("num_clips"):
                cmd.extend(["--num-clips", str(config["num_clips"])])
            if config.get("split_equal"):
                cmd.append("--split-equal")
            else:
                if config.get("min_duration"):
                    cmd.extend(["--min-duration", str(config["min_duration"])])
                if config.get("max_duration"):
                    cmd.extend(["--max-duration", str(config["max_duration"])])
                if config.get("whisper_model"):
                    cmd.extend(["--whisper-model", config["whisper_model"]])
                # LLM provider
                provider = config.get("llm_provider", "groq")
                cmd.extend(["--llm-provider", provider])
                if config.get("llm_model"):
                    cmd.extend(["--llm-model", config["llm_model"]])
                if config.get("llm_api_key"):
                    cmd.extend(["--llm-api-key", config["llm_api_key"]])
                if config.get("llm_base_url"):
                    cmd.extend(["--llm-base-url", config["llm_base_url"]])
                if config.get("system_prompt"):
                    cmd.extend(["--system-prompt", config["system_prompt"]])
                if config.get("user_prompt"):
                    cmd.extend(["--user-prompt", config["user_prompt"]])

        return cmd

    def _build_transcribe_command(self, job: Job) -> list:
        """Monta comando para transcricao."""
        config = job.config
        script_path = str(PROJECT_DIR / "transcrever_v1.py")
        cmd = [PYTHON_BIN, script_path]

        cmd.extend(["--in", config["input"]])
        cmd.extend(["--outdir", str(job.workdir.resolve() / "transcription")])

        # Engine de STT configuravel
        engine = config.get("stt_engine") or config.get("asr_engine", "whisper-cpu")
        # Mapear engines legadas
        if engine in ("whisper", "parakeet"):
            engine = "whisper-cpu"
        cmd.extend(["--engine", engine])

        if config.get("whisper_model"):
            cmd.extend(["--whisper-model", config["whisper_model"]])
        if config.get("groq_model"):
            cmd.extend(["--groq-model", config["groq_model"]])
        if config.get("src_lang"):
            cmd.extend(["--src", config["src_lang"]])

        return cmd

    def _build_download_command(self, job: Job) -> list:
        """Monta comando para download de video."""
        config = job.config
        script_path = str(PROJECT_DIR / "baixar_v1.py")

        cmd = [
            PYTHON_BIN, script_path,
            "--outdir", str(job.workdir.resolve() / "download"),
        ]

        if config.get("local_file"):
            cmd.extend(["--local-file", config["local_file"]])
        else:
            cmd.extend(["--url", config["url"]])

        if config.get("quality"):
            cmd.extend(["--quality", config["quality"]])

        return cmd

    def _build_tts_command(self, job: Job) -> list:
        """Monta comando para geracao de audio (TTS)."""
        config = job.config
        script_path = str(PROJECT_DIR / "tts_direct.py")
        outdir = str(job.workdir.resolve() / "audio_out")

        cmd = [
            PYTHON_BIN, script_path,
            "--text", config["text"],
            "--lang", config.get("lang", "pt"),
            "--engine", config.get("engine", "edge"),
            "--outdir", outdir,
        ]
        if config.get("voice"):
            cmd.extend(["--voice", config["voice"]])

        return cmd

    def _build_dub_command(self, job: Job) -> list:
        """Monta comando para pipeline de dublagem."""
        config = job.config
        cmd = [PYTHON_BIN, os.path.abspath(PIPELINE_SCRIPT)]

        cmd.extend(["--in", config["input"]])

        if config.get("src_lang"):
            cmd.extend(["--src", config["src_lang"]])
        cmd.extend(["--tgt", config.get("tgt_lang", "pt")])

        cmd.extend(["--outdir", str(job.workdir.resolve() / "dublado")])

        # ASR engine - mapear para novo formato
        asr = config.get("asr_engine", "whisper")
        cmd.extend(["--asr", asr])
        if config.get("whisper_model"):
            cmd.extend(["--whisper-model", config["whisper_model"]])

        tradutor = config.get("translation_engine", "m2m100")
        cmd.extend(["--tradutor", tradutor])
        if config.get("large_model"):
            cmd.append("--large-model")

        tts = config.get("tts_engine", "edge")
        cmd.extend(["--tts", tts])
        if config.get("voice"):
            cmd.extend(["--voice", config["voice"]])
        if config.get("tts_rate"):
            cmd.extend(["--rate", config["tts_rate"]])

        if config.get("sync_mode"):
            cmd.extend(["--sync", config["sync_mode"]])
        if config.get("maxstretch"):
            cmd.extend(["--maxstretch", str(config["maxstretch"])])
        if config.get("tolerance"):
            cmd.extend(["--tolerance", str(config["tolerance"])])
        if config.get("no_truncate"):
            cmd.append("--no-truncate")
        if config.get("use_rubberband") is False:
            cmd.append("--no-rubberband")

        if config.get("diarize"):
            cmd.append("--diarize")
            if config.get("num_speakers"):
                cmd.extend(["--num-speakers", str(config["num_speakers"])])
            if config.get("diarize_engine"):
                cmd.extend(["--diarize-engine", config["diarize_engine"]])

        if config.get("maxdur"):
            cmd.extend(["--maxdur", str(config["maxdur"])])
        if config.get("seed"):
            cmd.extend(["--seed", str(config["seed"])])

        if config.get("content_type") == "curso":
            cmd.extend(["--segment-max-words", "30", "--segment-pause", "0.5"])
        if config.get("content_type") == "curso" or config.get("summary"):
            cmd.append("--summary")

        return cmd

    async def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.process and job.process.poll() is None:
            job._user_cancelled = True
            job.process.terminate()
            try:
                job.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                job.process.kill()
            job.status = "cancelled"
            job.finished_at = time.time()
            await self._notify(job_id, {"event": "cancelled", "job": job.to_dict()})
            return True
        return False

    async def delete_job(self, job_id: str) -> bool:
        """Cancela (se rodando/na fila) e deleta arquivos + entrada do job."""
        job = self.jobs.get(job_id)
        if not job:
            return False
        if job.status == "running" and job.process and job.process.poll() is None:
            job.process.terminate()
            try:
                job.process.wait(timeout=5)
            except Exception:
                job.process.kill()
        job.status = "deleted"
        if job.workdir.exists():
            shutil.rmtree(job.workdir, ignore_errors=True)
        self.jobs.pop(job_id, None)
        return True

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def list_jobs(self) -> list:
        return [j.to_dict() for j in sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)]

    def subscribe(self, job_id: str, ws):
        if job_id not in self._subscribers:
            self._subscribers[job_id] = []
        self._subscribers[job_id].append(ws)

    def unsubscribe(self, job_id: str, ws):
        if job_id in self._subscribers:
            self._subscribers[job_id] = [w for w in self._subscribers[job_id] if w != ws]

    async def _notify(self, job_id: str, data: dict):
        subscribers = self._subscribers.get(job_id, [])
        dead = []
        for ws in subscribers:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unsubscribe(job_id, ws)
