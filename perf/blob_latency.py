"""
T4.7 - Do latency doc/ghi Azure Blob Storage giua nhieu region.

Cach chay (vi du tu may o HCMC):
    python blob_latency.py --config targets.json --client hcmc --reps 30

Tu VM tren Azure:
    python blob_latency.py --config targets.json --client vm-southeastasia --reps 30

Connection string KHONG dat trong code. Dat qua bien moi truong
(ten bien khai bao trong targets.json, vd CONN_EASTASIA).

Ket qua: ghi tung phep do vao results/blob_raw_<client>_<thoigian>.csv
(ghi ngay sau moi lan do, dung giua chung van giu duoc du lieu).
"""
import argparse
import csv
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from azure.storage.blob import BlobServiceClient

# Kich thuoc mac dinh. 1 KB do "do tre thuan" (RTT), cac file lon do thong luong.
DEFAULT_SIZES = {"1kb": 1024, "1mb": 1024**2, "10mb": 10 * 1024**2, "50mb": 50 * 1024**2}


def parse_sizes(text: str) -> dict:
    """Nhan '1kb,1mb' hoac so byte. PowerShell tu doi 1kb,1mb (khong co nhay) thanh
    1024 1048576, nen ca hai dang deu duoc chap nhan."""
    by_bytes = {v: k for k, v in DEFAULT_SIZES.items()}
    out = {}
    for tok in text.replace(",", " ").split():
        tok = tok.strip().lower()
        if tok in DEFAULT_SIZES:
            out[tok] = DEFAULT_SIZES[tok]
        elif tok.isdigit() and int(tok) in by_bytes:
            out[by_bytes[int(tok)]] = int(tok)
        else:
            raise SystemExit(f"Kich thuoc khong hop le: {tok}. Dung: 1kb, 1mb, 10mb, 50mb")
    return out


def make_test_files(folder: Path, sizes: dict) -> dict:
    """Tao file ngau nhien (khong nen duoc) mot lan, dung lai cho moi region."""
    folder.mkdir(exist_ok=True)
    data = {}
    for label, n in sizes.items():
        p = folder / f"test_{label}.bin"
        if not p.exists() or p.stat().st_size != n:
            p.write_bytes(os.urandom(n))
        data[label] = p.read_bytes()
    return data


def build_clients(cfg: dict, concurrency: int):
    targets = []
    for t in cfg["targets"]:
        conn = os.environ.get(t["conn_env"])
        if not conn:
            raise SystemExit(f"Thieu bien moi truong {t['conn_env']} cho {t['name']}")
        svc = BlobServiceClient.from_connection_string(
            conn,
            # Cung mot cau hinh chia block cho moi region de so sanh cong bang
            max_single_put_size=4 * 1024**2,
            max_block_size=4 * 1024**2,
            max_single_get_size=4 * 1024**2,
            max_chunk_get_size=4 * 1024**2,
        )
        cc = svc.get_container_client(t["container"])
        if not cc.exists():
            cc.create_container()
        targets.append({"name": t["name"], "region": t["region"], "cc": cc})
    return targets


def timed(fn):
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="targets.json")
    ap.add_argument("--client", required=True, help="Nhan noi do, vd hcmc, vm-southeastasia")
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=2, help="So lan chay khoi dong, khong ghi")
    ap.add_argument("--sizes", default="1kb,1mb,10mb,50mb")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    sizes = parse_sizes(args.sizes)
    payloads = make_test_files(Path("testfiles"), sizes)
    targets = build_clients(cfg, args.concurrency)

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = out_dir / f"blob_raw_{args.client}_{stamp}.csv"
    fields = ["timestamp_utc", "client", "target", "region", "op", "size_label",
              "size_bytes", "rep", "seconds", "ok", "error"]
    f = open(out_path, "w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()

    def one_round(rep, record):
        # Xao tron thu tu region moi vong de khong region nao luon bi do luc mang yeu
        order = targets[:]
        random.shuffle(order)
        for label, data in payloads.items():
            for t in order:
                bc = t["cc"].get_blob_client(f"{args.client}/test_{label}.bin")
                ops = [
                    ("upload", lambda: bc.upload_blob(data, overwrite=True,
                                                     max_concurrency=args.concurrency)),
                    ("download", lambda: bc.download_blob(max_concurrency=args.concurrency).readall()),
                ]
                if label == "1kb":
                    # Phep goi nhe nhat: chi doc metadata -> gan voi RTT mang
                    ops.append(("head", lambda: bc.get_blob_properties()))
                for op, fn in ops:
                    row = {"timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "client": args.client, "target": t["name"], "region": t["region"],
                           "op": op, "size_label": label, "size_bytes": len(data), "rep": rep}
                    try:
                        row["seconds"] = round(timed(fn), 6)
                        row["ok"] = 1
                        row["error"] = ""
                    except Exception as e:  # ghi loi lai, khong dung ca bai do
                        row["seconds"] = ""
                        row["ok"] = 0
                        row["error"] = str(e)[:200]
                    if record:
                        w.writerow(row)
                        f.flush()

    print(f"Warm-up {args.warmup} vong...")
    for i in range(args.warmup):
        one_round(-1, record=False)
    for rep in range(1, args.reps + 1):
        t0 = time.perf_counter()
        one_round(rep, record=True)
        print(f"Vong {rep}/{args.reps} xong ({time.perf_counter() - t0:.1f}s)")
    f.close()
    print(f"Da ghi: {out_path}")


if __name__ == "__main__":
    main()
