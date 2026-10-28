"""T2.7 – đo job xử lý >4GB trên laptop (máy chủ truyền thống) để so với Synapse/ADF trên cloud.

Job giống truy vấn (3) trong synapse/03_benchmark.sql của TV1: xoay 12 cặp cột môn/điểm thành dạng dòng,
quy điểm chữ ra điểm số, tính GPA trung bình và tỉ lệ bỏ học theo khoa trên TOÀN BỘ dữ liệu mô phỏng.

Dữ liệu: chạy generate_data.py của TV1 trên laptop với tham số mặc định (seed 42) -> ra đúng bộ >4GB như trên lake:
    python data/generate_data.py --xlsx UnivData1.xlsx --out out
Đo:
    python ml/bench_laptop.py --folder out/synthetic/students --mode naive     # đọc hết vào RAM một lần (thường tràn RAM)
    python ml/bench_laptop.py --folder out/synthetic/students --mode chunked   # đọc từng file, chỉ các cột cần
Mỗi chế độ chạy 3 lần. Kết quả ghi thêm 1 dòng vào ml/figures/bench_laptop.csv.
"""
import argparse
import csv
import platform
import threading
import time
from pathlib import Path

import pandas as pd
import psutil

HERE = Path(__file__).resolve().parent
GRADE_COLS = [f"CORE_COURSE_GRADE_{i}_{t}" for t in "FS" for i in range(1, 7)]
POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}


class PeakMemory:
    """Đo RAM cao nhất của tiến trình (lấy mẫu mỗi 0,2 giây)."""
    def __init__(self):
        self.proc, self.peak, self._stop = psutil.Process(), 0, threading.Event()

    def __enter__(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, self.proc.memory_info().rss)
            time.sleep(0.2)

    def __exit__(self, *exc):
        self._stop.set()
        self.peak = max(self.peak, self.proc.memory_info().rss)


def partial_agg(df):
    """Tổng điểm, số môn có điểm theo ngành + số SV, số SV bỏ học theo ngành."""
    long = df.melt(id_vars=["STDNT_MAJOR"], value_vars=GRADE_COLS, value_name="grade").dropna(subset=["grade"])
    long["pts"] = long["grade"].map(POINTS)
    g = long.dropna(subset=["pts"]).groupby("STDNT_MAJOR")["pts"].agg(["sum", "count"])
    s = df.groupby("STDNT_MAJOR")["RETURNED_2ND_YR"].agg(students="size", returned="sum")
    return g.join(s, how="outer").fillna(0)


def finish(parts, major_faculty):
    t = pd.concat(parts).groupby(level=0).sum()
    t = t.join(major_faculty.set_index("major_name")[["faculty_name"]]).groupby("faculty_name").sum()
    t["gpa"] = t["sum"] / t["count"]
    t["dropout_rate"] = 1 - t["returned"] / t["students"]
    return t[["students", "gpa", "dropout_rate"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--mode", choices=["naive", "chunked"], default="chunked")
    ap.add_argument("--major-faculty", default=str(HERE / "src" / "major_faculty.csv"))
    a = ap.parse_args()
    files = sorted(Path(a.folder).glob("*.csv"))
    size_gb = sum(f.stat().st_size for f in files) / 2**30
    mf = pd.read_csv(a.major_faculty)
    print(f"{len(files)} file, {size_gb:.2f} GB, chế độ {a.mode}")

    status, rows = "ok", 0
    t0 = time.perf_counter()
    with PeakMemory() as mem:
        try:
            if a.mode == "naive":
                df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)    # mọi cột, một lần
                rows = len(df)
                result = finish([partial_agg(df)], mf)
            else:
                parts = []
                for f in files:
                    df = pd.read_csv(f, usecols=["STDNT_MAJOR", "RETURNED_2ND_YR", *GRADE_COLS])
                    rows += len(df)
                    parts.append(partial_agg(df))
                result = finish(parts, mf)
            print(result.round(3))
        except MemoryError:
            status = "MemoryError (tràn RAM)"
    seconds = time.perf_counter() - t0

    vm = psutil.virtual_memory()
    rec = {"mode": a.mode, "status": status, "files": len(files), "size_gb": round(size_gb, 2), "rows": rows,
           "seconds": round(seconds, 1), "peak_ram_gb": round(mem.peak / 2**30, 2),
           "machine": f"{platform.processor() or platform.machine()} | {psutil.cpu_count()} luồng | "
                      f"{vm.total / 2**30:.0f} GB RAM"}
    print(rec)
    out = HERE / "figures" / "bench_laptop.csv"
    out.parent.mkdir(exist_ok=True)
    new = not out.exists()
    with out.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rec))
        if new:
            w.writeheader()
        w.writerow(rec)


if __name__ == "__main__":
    main()
