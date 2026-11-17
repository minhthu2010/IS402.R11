"""
Gop tat ca file results/*_raw_*.csv -> bang p50/p95 + toc do MB/s + bieu do.

    python summarize.py --in results

Tao ra:
  results/summary.csv        (dua vao bao cao / Power BI)
  results/summary.md         (bang copy vao Word)
  results/chart_<...>.png    (bieu do p50 voi thanh p95)
"""
import argparse
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def p(q):
    def f(s):
        return s.quantile(q)
    f.__name__ = f"p{int(q * 100)}"
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="results")
    args = ap.parse_args()
    d = Path(args.inp)

    frames = [pd.read_csv(x) for x in sorted(d.glob("*_raw_*.csv")) if x.stat().st_size > 0]
    if not frames:
        raise SystemExit("Khong co file *_raw_*.csv")
    df = pd.concat(frames, ignore_index=True)
    if "size_label" not in df:
        df["size_label"] = ""
    if "size_bytes" not in df:
        df["size_bytes"] = 0
    df["size_label"] = df["size_label"].fillna("")
    df["size_bytes"] = df["size_bytes"].fillna(0)

    keys = ["client", "region", "op", "size_label", "size_bytes"]
    total = df.groupby(keys).size().rename("n_total")
    ok = df[df["ok"] == 1].copy()
    ok["ms"] = ok["seconds"] * 1000
    g = ok.groupby(keys)["ms"].agg(["count", p(0.5), p(0.95), "mean", "min", "max"])
    g = g.join(total).reset_index()
    g = g.rename(columns={"count": "n_ok", "p50": "p50_ms", "p95": "p95_ms",
                          "mean": "mean_ms", "min": "min_ms", "max": "max_ms"})
    # Toc do chi co y nghia voi file >= 1 MB
    big = g["op"].isin(["upload", "download"]) & (g["size_bytes"] >= 1024**2)
    g["MBps_at_p50"] = float("nan")
    g.loc[big, "MBps_at_p50"] = (g.loc[big, "size_bytes"] / 1024**2) / (g.loc[big, "p50_ms"] / 1000)
    g = g.round(2)
    g.to_csv(d / "summary.csv", index=False)

    cols = ["client", "region", "op", "size_label", "n_ok", "n_total",
            "p50_ms", "p95_ms", "MBps_at_p50"]
    (d / "summary.md").write_text(g[cols].to_markdown(index=False), encoding="utf-8")
    print(g[cols].to_string(index=False))

    # Bieu do: moi (client, op, size) mot hinh, cot = p50, vach = p95
    for (client, op, size), sub in g.groupby(["client", "op", "size_label"]):
        sub = sub.sort_values("p50_ms")
        fig, ax = plt.subplots(figsize=(6, 3.2))
        ax.bar(sub["region"], sub["p50_ms"], color="#4C72B0", label="p50")
        ax.scatter(sub["region"], sub["p95_ms"], color="#C44E52", marker="_", s=600,
                   linewidths=2.5, label="p95", zorder=3)
        title = f"{op} {size}".strip()
        ax.set_title(f"{title} – đo từ {client}")
        ax.set_ylabel("ms")
        ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1, 1))
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        name = f"chart_{client}_{op}_{size or 'x'}.png".replace("/", "-")
        fig.savefig(d / name, dpi=150)
        plt.close(fig)
    print(f"Da ghi {d/'summary.csv'}, {d/'summary.md'} va bieu do PNG")


if __name__ == "__main__":
    main()
