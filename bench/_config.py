"""Captures the run configuration that a number is meaningless without.

Every bench report embeds the dict returned by `run_config()` so a reader can
tell, from the report alone, whether a given number is comparable to another
run — same worker count, same host, same trial/warmup sizes.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path


def _cpu_model() -> str:
    try:
        return subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        try:
            out = Path("/proc/cpuinfo").read_text()
            for line in out.splitlines():
                if "model name" in line:
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return "unknown"


def _ram_gb() -> str:
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        return f"{int(out) / (1024**3):.1f} GiB"
    except Exception:
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return f"{kb / (1024**2):.1f} GiB"
        except Exception:
            pass
    return "unknown"


def _pkg_ver(name: str) -> str:
    try:
        return _pkg_version(name)
    except Exception:
        return "unknown"


def run_config(*, trials: int, warmup_n: int, n_per_trial: int, extra: dict | None = None) -> dict:
    """Host + harness config, pulled from the environment at runtime.

    Callers embed the return value verbatim in their report so any run is
    self-documenting: a reader never has to guess what conditions produced a
    number, and a second run can be checked against the same config.
    """
    cfg = {
        "host_arch": platform.machine(),
        "host_cpu": _cpu_model(),
        "host_ram": _ram_gb(),
        "os": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "httpx": _pkg_ver("httpx"),
        "asyncpg": _pkg_ver("asyncpg"),
        "gateway_workers": os.environ.get("GATEWAY_WORKERS", "1 (default, pinned in docker-compose)"),
        "trials": trials,
        "warmup_requests_per_trial": warmup_n,
        "requests_per_trial": n_per_trial,
    }
    if extra:
        cfg.update(extra)
    return cfg


def format_config(cfg: dict) -> str:
    lines = "\n".join(f"- {k}: {v}" for k, v in cfg.items())
    return f"### Run configuration\n{lines}\n"


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return var**0.5
