#!/usr/bin/env python3
"""Transcrever v1 - Transcricao standalone usando faster-whisper (CPU) ou Groq Whisper API."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def write_checkpoint(workdir: Path, step_num: int, step_id: str, step_name: str, data: dict | None = None):
    """Escreve checkpoint no mesmo formato do dublar_pro_v5.py, preservando dados anteriores."""
    cp_path = workdir / "dub_work" / "checkpoint.json"
    existing_data: dict = {}
    if cp_path.exists():
        try:
            existing_data = json.loads(cp_path.read_text()).get("data", {}) or {}
        except Exception:
            pass
    cp = {
        "last_step_num": step_num,
        "last_step": step_id,
        "last_step_name": step_name,
        "timestamp": time.time(),
        "data": {**existing_data, **(data or {})},
    }
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    cp_path.write_text(json.dumps(cp, indent=2))
    print(f"[checkpoint] etapa {step_num}: {step_name}", flush=True)


def download_input(input_val: str, workdir: Path) -> Path:
    """Baixa video/audio se for URL, ou retorna o path local."""
    if input_val.startswith("http"):
        print(f"[download] Baixando: {input_val}", flush=True)
        out_template = workdir / "dub_work" / "source.%(ext)s"
        cmd = [
            "yt-dlp",
            # Preferencia: melhor audio isolado -> melhor com acodec -> qualquer formato
            # acodec!=none garante que o arquivo tenha audio (evita video-only como bytevc1)
            "-f", "bestaudio[ext=m4a]/bestaudio/best[acodec!=none]/best",
            "--output", str(out_template),
            "--no-playlist",
            "--write-info-json",
            input_val,
        ]
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp falhou com codigo {result.returncode}")
        files = list((workdir / "dub_work").glob("source.*"))
        files = [f for f in files if f.suffix not in (".json", ".txt", ".part")]
        if not files:
            raise RuntimeError("yt-dlp nao gerou arquivo de saida")
        return sorted(files)[-1]
    else:
        p = Path(input_val)
        if not p.exists():
            raise FileNotFoundError(f"Arquivo nao encontrado: {input_val}")
        return p


def extract_audio(source: Path, workdir: Path) -> Path:
    """Extrai audio do video como WAV mono 16kHz."""
    print("[extraction] Extraindo audio...", flush=True)
    audio_path = workdir / "dub_work" / "audio.wav"

    # Tentar com -vn (descarta video, extrai audio)
    cmd = [
        "ffmpeg", "-y", "-i", str(source),
        "-ac", "1", "-ar", "16000", "-vn",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Fallback: arquivo pode ser audio puro (m4a, mp3, opus) sem stream de video
        # Nesse caso remover -vn e converter direto
        if "does not contain any stream" in result.stderr or "Invalid argument" in result.stderr:
            print("[extraction] Sem stream de video detectado, convertendo como audio puro...", flush=True)
            cmd2 = [
                "ffmpeg", "-y", "-i", str(source),
                "-ac", "1", "-ar", "16000",
                str(audio_path),
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            if result2.returncode != 0:
                raise RuntimeError(f"ffmpeg falhou (audio puro): {result2.stderr[-500:]}")
            return audio_path

        raise RuntimeError(f"ffmpeg falhou: {result.stderr[-500:]}")
    return audio_path


def transcribe_groq(audio_path: Path, model: str, src_lang: str | None) -> list[dict]:
    """Transcreve via Groq Whisper API."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY nao configurada. Defina no .env ou variavel de ambiente.")

    import urllib.request

    print(f"[transcription] Transcrevendo com Groq Whisper API ({model})...", flush=True)

    # Groq aceita arquivos ate 25MB. Se maior, precisamos dividir.
    file_size_mb = audio_path.stat().st_size / (1024 * 1024)
    if file_size_mb > 25:
        print(f"[transcription] Arquivo grande ({file_size_mb:.1f}MB), dividindo em partes...", flush=True)
        return _transcribe_groq_chunked(audio_path, model, src_lang, api_key)

    return _groq_transcribe_file(audio_path, model, src_lang, api_key)


def _groq_transcribe_file(audio_path: Path, model: str, src_lang: str | None, api_key: str) -> list[dict]:
    """Transcreve um arquivo via Groq API (max 25MB)."""
    import urllib.request
    import mimetypes

    url = "https://api.groq.com/openai/v1/audio/transcriptions"

    # Multipart form data
    boundary = f"----inemavox{int(time.time())}"
    body_parts = []

    # Campo: file
    content_type = mimetypes.guess_type(str(audio_path))[0] or "audio/wav"
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'.encode())
    body_parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    body_parts.append(audio_path.read_bytes())
    body_parts.append(b"\r\n")

    # Campo: model
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(b'Content-Disposition: form-data; name="model"\r\n\r\n')
    body_parts.append(f"{model}\r\n".encode())

    # Campo: response_format = verbose_json (para ter timestamps)
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(b'Content-Disposition: form-data; name="response_format"\r\n\r\n')
    body_parts.append(b"verbose_json\r\n")

    # Campo: language (opcional)
    if src_lang:
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(b'Content-Disposition: form-data; name="language"\r\n\r\n')
        body_parts.append(f"{src_lang}\r\n".encode())

    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    segments = []
    for seg in data.get("segments", []):
        segments.append({
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "text": seg["text"].strip(),
        })
        print(f"  [{seg['start']:.1f}s -> {seg['end']:.1f}s] {seg['text'].strip()}", flush=True)

    lang = data.get("language", "?")
    print(f"[transcription] {len(segments)} segmentos, idioma: {lang}", flush=True)
    return segments


def _transcribe_groq_chunked(audio_path: Path, model: str, src_lang: str | None, api_key: str) -> list[dict]:
    """Divide audio grande em partes de ~20min e transcreve cada uma via Groq."""
    chunk_duration = 1200  # 20 minutos
    # Obter duracao total
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio_path)],
        capture_output=True, text=True, timeout=10,
    )
    total_duration = float(probe.stdout.strip())
    all_segments = []
    offset = 0.0
    chunk_num = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        while offset < total_duration:
            chunk_num += 1
            chunk_path = Path(tmpdir) / f"chunk_{chunk_num:03d}.wav"
            cmd = [
                "ffmpeg", "-y", "-i", str(audio_path),
                "-ss", str(offset),
                "-t", str(chunk_duration),
                "-ac", "1", "-ar", "16000",
                str(chunk_path),
            ]
            subprocess.run(cmd, capture_output=True, text=True)
            print(f"[transcription] Processando parte {chunk_num} (offset {offset:.0f}s)...", flush=True)

            segments = _groq_transcribe_file(chunk_path, model, src_lang, api_key)
            # Ajustar timestamps com offset
            for seg in segments:
                seg["start"] = round(seg["start"] + offset, 3)
                seg["end"] = round(seg["end"] + offset, 3)
                all_segments.append(seg)

            offset += chunk_duration

    return all_segments


def transcribe_whisper_cpu(audio_path: Path, model: str, src_lang: str | None) -> list[dict]:
    """Transcreve com faster-whisper em CPU."""
    print(f"[transcription] Transcrevendo com faster-whisper CPU {model}...", flush=True)
    from faster_whisper import WhisperModel

    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segments_iter, info = wm.transcribe(
        str(audio_path),
        language=src_lang or None,
        vad_filter=True,
        condition_on_previous_text=False,   # evita loop de alucinacao entre chunks
        no_speech_threshold=0.6,            # descarta silencio/ruido antes de alucinar
        compression_ratio_threshold=2.0,    # detecta e descarta texto repetitivo
    )

    results = []
    for seg in segments_iter:
        results.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
        })
        print(f"  [{seg.start:.1f}s -> {seg.end:.1f}s] {seg.text.strip()}", flush=True)

    print(f"[transcription] {len(results)} segmentos, idioma: {info.language}", flush=True)
    return results


def transcribe_openai(audio_path: Path, model: str, src_lang: str | None) -> list[dict]:
    """Transcreve via OpenAI Whisper API."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY nao configurada.")

    import urllib.request

    print(f"[transcription] Transcrevendo com OpenAI Whisper API ({model})...", flush=True)

    url = "https://api.openai.com/v1/audio/transcriptions"
    boundary = f"----inemavox{int(time.time())}"
    body_parts = []

    content_type = "audio/wav"
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'.encode())
    body_parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    body_parts.append(audio_path.read_bytes())
    body_parts.append(b"\r\n")

    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(b'Content-Disposition: form-data; name="model"\r\n\r\n')
    body_parts.append(f"{model}\r\n".encode())

    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(b'Content-Disposition: form-data; name="response_format"\r\n\r\n')
    body_parts.append(b"verbose_json\r\n")

    if src_lang:
        body_parts.append(f"--{boundary}\r\n".encode())
        body_parts.append(b'Content-Disposition: form-data; name="language"\r\n\r\n')
        body_parts.append(f"{src_lang}\r\n".encode())

    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    segments = []
    for seg in data.get("segments", []):
        segments.append({
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "text": seg["text"].strip(),
        })
        print(f"  [{seg['start']:.1f}s -> {seg['end']:.1f}s] {seg['text'].strip()}", flush=True)

    lang = data.get("language", "?")
    print(f"[transcription] {len(segments)} segmentos, idioma: {lang}", flush=True)
    return segments


def seconds_to_srt_time(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    ms = int((s % 1) * 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def get_video_title(workdir: Path, input_val: str) -> str:
    """Tenta obter o titulo do video da info JSON do yt-dlp ou do nome do arquivo."""
    info_json = workdir / "dub_work" / "source.info.json"
    if info_json.exists():
        try:
            info = json.loads(info_json.read_text(encoding="utf-8"))
            return str(info.get("title", "") or "")
        except Exception:
            pass
    if not input_val.startswith("http"):
        return Path(input_val).stem
    return ""


def save_transcript_summary(segments: list[dict], outdir: Path, title: str = ""):
    """Salva um JSON com titulo e descricao (preview do texto) da transcricao."""
    full_text = " ".join(seg["text"] for seg in segments)
    description = full_text[:500].strip()
    if len(full_text) > 500:
        last_space = description.rfind(" ")
        if last_space > 0:
            description = description[:last_space] + "..."
    duration_s = segments[-1]["end"] if segments else 0
    summary = {
        "title": title,
        "description": description,
        "total_segments": len(segments),
        "duration_s": round(duration_s, 1),
    }
    (outdir / "transcript_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[summary] Resumo salvo: titulo='{title}'", flush=True)


def export_transcription(segments: list[dict], outdir: Path):
    """Exporta SRT, TXT e JSON."""
    print("[export] Exportando legendas...", flush=True)
    outdir.mkdir(parents=True, exist_ok=True)

    # SRT
    srt_lines = []
    for i, seg in enumerate(segments, 1):
        srt_lines.append(str(i))
        srt_lines.append(f"{seconds_to_srt_time(seg['start'])} --> {seconds_to_srt_time(seg['end'])}")
        srt_lines.append(seg["text"])
        srt_lines.append("")
    (outdir / "transcript.srt").write_text("\n".join(srt_lines), encoding="utf-8")

    # TXT
    txt = "\n".join(seg["text"] for seg in segments)
    (outdir / "transcript.txt").write_text(txt, encoding="utf-8")

    # JSON
    (outdir / "transcript.json").write_text(
        json.dumps(segments, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"[export] Arquivos salvos em {outdir}", flush=True)


# Engine default: usa GROQ_API_KEY se disponivel, senao whisper-cpu
def _default_engine() -> str:
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return "whisper-cpu"


def main():
    parser = argparse.ArgumentParser(description="Transcrever v1")
    parser.add_argument("--in", dest="input", required=True, help="URL ou caminho do arquivo")
    parser.add_argument("--outdir", required=True, help="Diretorio de saida para transcricoes")
    parser.add_argument("--engine", default=None, choices=["groq", "whisper-cpu", "openai"],
                        help="Engine de STT (default: groq se GROQ_API_KEY disponivel, senao whisper-cpu)")
    # Manter --asr para compatibilidade com jobs antigos (mapeia whisper -> whisper-cpu)
    parser.add_argument("--asr", default=None, choices=["whisper", "parakeet"],
                        help="(Legado) Use --engine em vez disso")
    parser.add_argument("--whisper-model", default="small", dest="whisper_model",
                        help="Modelo Whisper para CPU (tiny/small/medium) ou Groq (whisper-large-v3-turbo)")
    parser.add_argument("--groq-model", default="whisper-large-v3-turbo", dest="groq_model",
                        help="Modelo Groq Whisper (whisper-large-v3-turbo ou whisper-large-v3)")
    parser.add_argument("--src", default=None, help="Idioma de origem (auto-detect se vazio)")
    args = parser.parse_args()

    # Resolver engine: --engine tem prioridade, senao --asr legado, senao auto-detect
    if args.engine:
        engine = args.engine
    elif args.asr:
        engine = "whisper-cpu"  # parakeet e whisper legado mapeiam para whisper-cpu
    else:
        engine = _default_engine()

    outdir = Path(args.outdir)
    workdir = outdir.parent  # dub_work fica no pai de transcription/

    (workdir / "dub_work").mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        # Etapa 1: Download
        source = download_input(args.input, workdir)
        write_checkpoint(workdir, 1, "download", "Download")

        # Etapa 2: Extraction
        audio = extract_audio(source, workdir)
        _dur_s = 0
        try:
            _probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(audio)],
                capture_output=True, text=True, timeout=10,
            )
            _dur_s = round(float(_probe.stdout.strip()), 1)
        except Exception:
            pass
        _title = get_video_title(workdir, args.input)
        write_checkpoint(workdir, 2, "extraction", "Extracao de audio",
                         data={"video_duration_s": _dur_s, "video_title": _title})

        # Etapa 3: Transcription
        if engine == "groq":
            segments = transcribe_groq(audio, args.groq_model, args.src)
        elif engine == "openai":
            segments = transcribe_openai(audio, "whisper-1", args.src)
        else:  # whisper-cpu
            segments = transcribe_whisper_cpu(audio, args.whisper_model, args.src)
        write_checkpoint(workdir, 3, "transcription", "Transcricao")

        # Etapa 4: Export
        export_transcription(segments, outdir)
        title = get_video_title(workdir, args.input)
        save_transcript_summary(segments, outdir, title)
        write_checkpoint(workdir, 4, "export", "Exportando legendas")

        print("[done] Transcricao concluida com sucesso!", flush=True)
        sys.exit(0)

    except Exception as e:
        print(f"[error] {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
