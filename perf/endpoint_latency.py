"""
T4.7 - Do thoi gian goi Azure ML managed online endpoint o nhieu region.

    python endpoint_latency.py --config endpoints.json --client hcmc --reps 30

endpoints.json khai bao URL scoring, ten bien moi truong chua key,
va file request mau (lay tu API contract cua TV3).
Key KHONG dat trong code: set bien moi truong, vd KEY_EP_REGION1.
"""
import argparse
import csv
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="endpoints.json")
    ap.add_argument("--client", required=True)
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    eps = []
    for e in cfg["endpoints"]:
        key = os.environ.get(e["key_env"])
        if not key:
            raise SystemExit(f"Thieu bien moi truong {e['key_env']} cho {e['name']}")
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        if e.get("deployment"):
            headers["azureml-model-deployment"] = e["deployment"]
        body = Path(e["request_file"]).read_bytes()
        s = requests.Session()  # giu ket noi (keep-alive) nhu web/Function thuc te
        eps.append({**e, "headers": headers, "body": body, "session": s})

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"endpoint_raw_{args.client}_{datetime.now():%Y%m%d_%H%M}.csv"
    fields = ["timestamp_utc", "client", "target", "region", "op", "rep",
              "seconds", "status", "ok", "error"]
    f = open(out_path, "w", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()

    def call(ep):
        t0 = time.perf_counter()
        r = ep["session"].post(ep["url"], data=ep["body"], headers=ep["headers"],
                               timeout=args.timeout)
        body = r.content
        sec = time.perf_counter() - t0
        # score.py tra loi {"error": ...} voi ma 200 khi du lieu sai -> khong tinh la thanh cong
        if r.status_code == 200 and b'"error"' in body[:200]:
            return sec, "200-error"
        return sec, r.status_code

    print(f"Warm-up {args.warmup} lan moi endpoint...")
    for _ in range(args.warmup):
        for ep in eps:
            try:
                sec, code = call(ep)
                print(f"  {ep['name']}: status {code}, {sec*1000:.0f} ms")
            except Exception as e:
                print(f"  warm-up loi {ep['name']}: {e}")

    for rep in range(1, args.reps + 1):
        order = eps[:]
        random.shuffle(order)
        for ep in order:
            row = {"timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "client": args.client, "target": ep["name"], "region": ep["region"],
                   "op": "score", "rep": rep}
            try:
                sec, code = call(ep)
                row.update(seconds=round(sec, 6), status=code, ok=int(code == 200), error="")
            except Exception as e:
                row.update(seconds="", status="", ok=0, error=str(e)[:200])
            w.writerow(row)
            f.flush()
        print(f"Vong {rep}/{args.reps} xong")
    f.close()
    print(f"Da ghi: {out_path}")


if __name__ == "__main__":
    main()
