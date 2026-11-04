"""Writes research/out/harness_perf.md (performance record; harness_validation.md is produced by research.validate only)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from research import common as C


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


def build_text() -> str:
    logs = C.CACHE / "logs"
    res = C.CACHE / "results"
    out = ["# Harness 效能紀錄", "", "本檔只由 `python -m research.perf` 產生；`harness_validation.md` 只由 `research.validate` 產生。", ""]
    # ---- p0_perf_15m_all
    out += ["## p0_perf_15m_all（15m 全期、全幣池，門檻 10:00）", ""]
    pm_path = res / "p0_perf_15m_all.json"
    perf_txt = (logs / "perf.log").read_text() if (logs / "perf.log").exists() else ""
    m = re.search(r"real\s+(\S+)", perf_txt)
    if pm_path.exists():
        pm = json.loads(pm_path.read_text())
        real = m.group(1) if m else "?"
        secs = None
        mm = re.match(r"(\d+)m([\d.]+)s", real)
        if mm:
            secs = int(mm.group(1)) * 60 + float(mm.group(2))
        verdict = "PASS" if secs is not None and secs < 600 else "FAIL"
        out += [
            f"- 成交 {pm['n_trades']} 筆，訊號 {pm['n_signals']}；run.py 內部耗時 {pm['elapsed_s']} 秒。",
            f"- perf.log 的 bash `real` = {real}（門檻 10:00）→ {verdict}。環境沒有 `/usr/bin/time`，所以用 bash `time`。",
            "- 階段 0 驗收者冷快取重量：47.8 秒（階段 0 驗收報告）。",
        ]
    else:
        out.append("- 結果檔不存在。")
    # ---- signals build
    out += ["", "## 訊號快取建置", ""]
    small = _lines(logs / "signals_build_small.log")
    full = _lines(logs / "signals_build.log")
    hdr = [ln for ln in small if ln.startswith("# build")]
    if hdr:
        out.append(f"- 小樣本（`signals_build_small.log`）：{hdr[-1][2:]}")
    for ln in small:
        if "elapsed=" in ln and not ln.startswith("#"):
            out.append(f"  - {ln}")
    est = [ln for ln in full if ln.startswith("# estimate-retro")]
    if est:
        out.append(f"- 推估總耗時（小樣本回推，公式見 phase1.md §5.1）：{est[-1][2:]}")
    else:
        out.append("- 推估總耗時：尚未寫入（執行 `python -m research.signals estimate-retro`）。")
    done = [ln for ln in full if ln.startswith("# done")]
    if done:
        out.append(f"- 實際總耗時（`signals_build.log`）：{done[-1][2:]}（log 時間含機器暫停期間，非純運算時間）。")
    # ---- augment / donchian
    out += ["", "## 階段 1 補件耗時", ""]
    for name, label in (("augment.log", "augment build"), ("donchian_build.log", "donchian build")):
        lines = _lines(logs / name)
        d = [ln for ln in lines if ln.startswith("# done")]
        out.append(f"- {label}：{d[-1][2:] if d else '無紀錄'}")
    # ---- experiments
    out += ["", "## 各實驗耗時（results/*.json 的 elapsed_s）", "", "| 實驗 | 訊號數 | 成交數 | elapsed_s |", "| --- | --- | --- | --- |"]
    for p in sorted(res.glob("*.json")):
        j = json.loads(p.read_text())
        out.append(f"| {p.stem} | {j.get('n_signals')} | {j.get('n_trades')} | {j.get('elapsed_s')} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="research.perf")
    p.add_argument("--out", default=str(C.OUT / "harness_perf.md"))
    a = p.parse_args(argv)
    Path(a.out).write_text(build_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
