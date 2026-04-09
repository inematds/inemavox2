"""Monitor de sistema - CPU, RAM, disco (GPU info opcional se disponivel)."""

import subprocess
import os
import shutil


def get_gpu_info() -> dict:
    """Retorna informacoes da GPU via nvidia-smi."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu,power.draw,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            return {
                "available": True,
                "name": parts[0] if len(parts) > 0 else "Unknown",
                "temperature_c": int(parts[1]) if len(parts) > 1 and parts[1] != "[N/A]" else None,
                "power_w": float(parts[2]) if len(parts) > 2 and parts[2] != "[N/A]" else None,
                "memory_used_mb": int(parts[3]) if len(parts) > 3 and parts[3] != "[N/A]" else None,
                "memory_total_mb": int(parts[4]) if len(parts) > 4 and parts[4] != "[N/A]" else None,
                "utilization_pct": int(parts[5]) if len(parts) > 5 and parts[5] != "[N/A]" else None,
            }
    except Exception:
        pass
    return {"available": False}


def get_gpu_processes() -> list:
    """Retorna processos usando a GPU."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            processes = []
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    processes.append({
                        "pid": int(parts[0]),
                        "name": parts[1],
                        "memory_mb": int(parts[2]) if parts[2] != "[N/A]" else None,
                    })
            return processes
    except Exception:
        pass
    return []


def get_cpu_info() -> dict:
    """Retorna informacoes de CPU."""
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        return {
            "cores": cpu_count,
            "load_1m": round(load1, 2),
            "load_5m": round(load5, 2),
            "load_15m": round(load15, 2),
            "usage_pct": round((load1 / cpu_count) * 100, 1),
        }
    except Exception:
        return {"cores": os.cpu_count(), "usage_pct": 0}


def get_memory_info() -> dict:
    """Retorna informacoes de memoria RAM."""
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:", "MemFree:", "SwapTotal:", "SwapFree:"):
                    info[parts[0].rstrip(":")] = int(parts[1]) // 1024  # KB to MB
            return {
                "total_mb": info.get("MemTotal", 0),
                "available_mb": info.get("MemAvailable", 0),
                "used_mb": info.get("MemTotal", 0) - info.get("MemAvailable", 0),
                "usage_pct": round(
                    (1 - info.get("MemAvailable", 0) / max(info.get("MemTotal", 1), 1)) * 100, 1
                ),
                "swap_total_mb": info.get("SwapTotal", 0),
                "swap_used_mb": info.get("SwapTotal", 0) - info.get("SwapFree", 0),
            }
    except Exception:
        return {"total_mb": 0, "available_mb": 0, "usage_pct": 0}


def get_disk_info(path: str = "/") -> dict:
    """Retorna informacoes de disco."""
    try:
        usage = shutil.disk_usage(path)
        return {
            "total_gb": round(usage.total / (1024**3), 1),
            "used_gb": round(usage.used / (1024**3), 1),
            "free_gb": round(usage.free / (1024**3), 1),
            "usage_pct": round(usage.used / usage.total * 100, 1),
        }
    except Exception:
        return {"total_gb": 0, "free_gb": 0, "usage_pct": 0}


def get_system_status() -> dict:
    """Retorna status completo do sistema."""
    return {
        "gpu": get_gpu_info(),
        "gpu_processes": get_gpu_processes(),
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "disk": get_disk_info(),
    }
