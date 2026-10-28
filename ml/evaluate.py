"""So sánh model, vẽ biểu đồ cho báo cáo, đánh giá model tốt nhất, ghi model_metrics vào Azure SQL.

Lấy model từ Azure ML (run mới nhất của mỗi loại model trong experiment dropout-models):
    python ml/evaluate.py --aml --data ml/data/students.csv --major-faculty ml/data/major_faculty.csv
Hoặc từ các thư mục train trên laptop (bước C5):
    python ml/evaluate.py --local out_logreg out_rf out_lgbm out_mlp --data ml/data/students.csv --major-faculty ml/data/major_faculty.csv
Thêm --sweep để vẽ biểu đồ theo tham số (experiment dropout-sweep, chỉ với --aml).
Thêm --sql để ghi model_metrics vào Azure SQL (đặt biến môi trường SQL_CONN = chuỗi kết nối ODBC TV1 đưa).

Kết quả ở ml/figures/: 10_so_sanh_model.png, 11_roc.png, 12_tham_so_*.png, 13_confusion.png,
14_shap_tong_quat.png, 15_giai_thich_1_sv.png; ml/figures/model_metrics.csv; ml/figures/ket_qua.md
"""
import argparse
import json
import os
import sys
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import (ConfusionMatrixDisplay, classification_report, confusion_matrix,  # noqa: E402
                             roc_auc_score, roc_curve)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))
from explain import LABELS_VI, contributions  # noqa: E402
from train import load_features, split_data  # noqa: E402

FIG = HERE / "figures"
NAMES = {"logreg": "Logistic Regression", "rf": "Random Forest", "lgbm": "LightGBM", "xgb": "XGBoost", "mlp": "MLP"}
SHOW = ["val_auc", "val_f1", "val_recall", "val_precision"]


# ---------------------------------------------------------------- lấy model
def load_dir(d):
    d = Path(d)
    d = d / "model" if (d / "model" / "model.pkl").exists() else d
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    return {"run_id": d.parent.name, "dir": d, "pipe": joblib.load(d / "model.pkl"), "meta": meta}


def mlflow_client():
    import mlflow
    from azure.ai.ml import MLClient
    from azure.identity import DefaultAzureCredential
    ml = MLClient.from_config(DefaultAzureCredential(), path=str(HERE / "config.json"))
    mlflow.set_tracking_uri(ml.workspaces.get(ml.workspace_name).mlflow_tracking_uri)
    return mlflow


def load_aml(dst):
    mlflow = mlflow_client()
    runs = mlflow.search_runs(experiment_names=["dropout-models"], filter_string="attributes.status = 'FINISHED'")
    runs = runs[runs["params.drop_term2"].astype(str) == "0"].sort_values("start_time", ascending=False)
    out = []
    for name, r in runs.groupby("tags.model_name", sort=False):
        rid = r.iloc[0]["run_id"]                       # run mới nhất của loại model này
        path = mlflow.artifacts.download_artifacts(run_id=rid, artifact_path="model", dst_path=str(dst / rid))
        m = load_dir(path)
        m["run_id"] = rid
        out.append(m)
        print(f"{name:7s} run {rid}")
    return out


# ---------------------------------------------------------------- biểu đồ
def plot_compare(models):
    rows = [{"model": NAMES.get(m["meta"]["model_name"], m["meta"]["model_name"]),
             **{k: m["meta"]["metrics"][k] for k in SHOW + ["train_seconds", "cv_auc_mean", "cv_auc_std"]}}
            for m in models]
    df = pd.DataFrame(rows).sort_values("val_auc", ascending=False)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.5), gridspec_kw={"width_ratios": [3, 1]})
    df.set_index("model")[SHOW].rename(columns=lambda c: c.replace("val_", "").upper()).plot.bar(ax=a1, rot=0, width=0.8)
    a1.set(ylim=(0, 1), ylabel="Giá trị trên tập validation", xlabel="",
           title="So sánh model: ROC-AUC, F1, recall, precision")
    a1.legend(ncols=4, loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False)
    for c in a1.containers:
        a1.bar_label(c, fmt="%.2f", fontsize=7)
    a2.barh(df["model"], df["train_seconds"], color="grey")
    a2.set(xlabel="Giây", title="Thời gian train")
    a2.invert_yaxis()
    fig.tight_layout()
    fig.savefig(FIG / "10_so_sanh_model.png", dpi=200, bbox_inches="tight")
    return df


def plot_roc(models, test):
    fig, ax = plt.subplots(figsize=(6, 6))
    for m in models:
        p = m["pipe"].predict_proba(test[m["meta"]["features"]])[:, 1]
        fpr, tpr, _ = roc_curve(test["dropout"], p)
        ax.plot(fpr, tpr, label=f"{NAMES.get(m['meta']['model_name'])} (AUC {roc_auc_score(test['dropout'], p):.3f})")
    ax.plot([0, 1], [0, 1], "--", c="grey", lw=1)
    ax.set(xlabel="Tỉ lệ báo nhầm (FPR)", ylabel="Tỉ lệ phát hiện đúng (recall / TPR)", title="Đường ROC trên tập test")
    ax.legend(loc="lower right")
    fig.savefig(FIG / "11_roc.png", dpi=200, bbox_inches="tight")


def plot_sweep():
    mlflow = mlflow_client()
    runs = mlflow.search_runs(experiment_names=["dropout-sweep"], filter_string="attributes.status = 'FINISHED'")
    runs = runs.dropna(subset=["metrics.val_auc"])
    params = [c for c in runs.columns if c.startswith("params.")
              and c.split(".", 1)[1] in ("n_estimators", "learning_rate", "num_leaves", "min_samples_leaf", "max_depth")
              and runs[c].nunique() > 1]
    fig, axes = plt.subplots(1, len(params), figsize=(4 * len(params), 3.8), sharey=True, squeeze=False)
    for ax, c in zip(axes[0], params):
        x = pd.to_numeric(runs[c])
        ax.scatter(x, runs["metrics.val_auc"], alpha=0.7)
        best = runs["metrics.val_auc"].idxmax()
        ax.scatter(x[best], runs.loc[best, "metrics.val_auc"], c="red", s=60, label="tốt nhất")
        ax.set(xlabel=c.split(".", 1)[1], title=c.split(".", 1)[1])
    axes[0][0].set_ylabel("ROC-AUC validation")
    axes[0][0].legend()
    fig.suptitle(f"Sweep {len(runs)} lần chạy: ROC-AUC theo từng tham số")
    fig.tight_layout()
    fig.savefig(FIG / "12_tham_so_sweep.png", dpi=200, bbox_inches="tight")
    best = runs.loc[runs["metrics.val_auc"].idxmax()]
    print("Tham số tốt nhất:", {c.split('.', 1)[1]: best[c] for c in params}, "val_auc", round(best["metrics.val_auc"], 4))
    runs[[*params, "metrics.val_auc", "metrics.val_recall", "run_id"]].sort_values(
        "metrics.val_auc", ascending=False).to_csv(FIG / "sweep_runs.csv", index=False)


def evaluate_best(best, test, train):
    feats, t = best["meta"]["features"], best["meta"]["threshold"]
    p = best["pipe"].predict_proba(test[feats])[:, 1]
    pred = (p >= t).astype(int)
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ConfusionMatrixDisplay(confusion_matrix(test["dropout"], pred),
                           display_labels=["Ở lại", "Bỏ học"]).plot(ax=ax, colorbar=False, cmap="Blues")
    ax.set(title=f"{NAMES.get(best['meta']['model_name'])}, ngưỡng {t:.2f}", xlabel="Dự đoán", ylabel="Thực tế")
    fig.savefig(FIG / "13_confusion.png", dpi=200, bbox_inches="tight")
    report = classification_report(test["dropout"], pred, target_names=["Ở lại", "Bỏ học"], digits=3)

    contrib = contributions(best["pipe"], test, feats, train)
    if contrib is None:
        print("Model này không hỗ trợ giải thích (MLP); chọn model cây hoặc LogReg để có SHAP.")
        return report
    imp = contrib.abs().mean().sort_values().tail(15)
    fig, ax = plt.subplots(figsize=(7, 5.5))
    ax.barh([LABELS_VI.get(f, f) for f in imp.index], imp.values)
    ax.set(xlabel="Mức ảnh hưởng trung bình |SHAP| (log-odds)", title="15 yếu tố ảnh hưởng nhiều nhất tới dự đoán bỏ học")
    fig.savefig(FIG / "14_shap_tong_quat.png", dpi=200, bbox_inches="tight")

    i = int(np.argmax(p))                                  # sinh viên rủi ro cao nhất trong tập test -> demo
    row = contrib.iloc[i].sort_values(key=abs).tail(10)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh([LABELS_VI.get(f, f) for f in row.index], row.values,
            color=["#c0392b" if v > 0 else "#2e86c1" for v in row.values])
    ax.axvline(0, c="black", lw=0.8)
    ax.set(xlabel="Đóng góp vào rủi ro (đỏ = tăng, xanh = giảm)",
           title=f"Vì sao SV {test['student_id'].iloc[i]} được dự đoán bỏ học (xác suất {p[i]:.0%})")
    fig.savefig(FIG / "15_giai_thich_1_sv.png", dpi=200, bbox_inches="tight")
    return report


def md_table(df):
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns)
    return head + "".join("\n| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False))


# ---------------------------------------------------------------- model_metrics
def metrics_rows(models):
    rows = []
    for m in models:
        params = json.dumps({k: v for k, v in m["meta"]["params"].items() if k != "model"}, ensure_ascii=False)[:400]
        for k, v in m["meta"]["metrics"].items():
            rows.append({"run_id": m["run_id"][:64], "model_name": m["meta"]["model_name"],
                         "params": params, "metric": k, "value": float(v)})
    return pd.DataFrame(rows)


def write_sql(df):
    import pyodbc
    conn = pyodbc.connect(os.environ["SQL_CONN"])
    cur = conn.cursor()
    cur.fast_executemany = True
    cur.executemany("INSERT INTO model_metrics (run_id, model_name, params, metric, value) VALUES (?, ?, ?, ?, ?)",
                    list(df[["run_id", "model_name", "params", "metric", "value"]].itertuples(index=False, name=None)))
    conn.commit()
    print(f"Đã ghi {len(df)} dòng vào model_metrics")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aml", action="store_true")
    ap.add_argument("--local", nargs="*", default=[])
    ap.add_argument("--data", required=True)
    ap.add_argument("--major-faculty", default=None)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--best", default=None, help="tên model chọn làm model cuối (mặc định: val_auc cao nhất)")
    ap.add_argument("--sql", action="store_true")
    a = ap.parse_args()
    FIG.mkdir(exist_ok=True)

    models = load_aml(HERE / "downloads") if a.aml else [load_dir(d) for d in a.local]
    if not models:
        raise SystemExit("Không có model nào: dùng --aml hoặc --local <thư mục>")
    train, _, test = split_data(load_features(a.data, a.major_faculty))

    table = plot_compare(models)
    plot_roc(models, test)
    if a.sweep:
        plot_sweep()
    best = (next(m for m in models if m["meta"]["model_name"] == a.best) if a.best
            else max(models, key=lambda m: m["meta"]["metrics"]["val_auc"]))
    report = evaluate_best(best, test, train)

    mm = metrics_rows(models)
    mm.to_csv(FIG / "model_metrics.csv", index=False)
    md = ["# Kết quả so sánh model", "", md_table(table.round(4)), "",
          f"Model chọn: **{NAMES.get(best['meta']['model_name'])}** (run `{best['run_id']}`), "
          f"ngưỡng {best['meta']['threshold']:.2f}", "", "```", report, "```"]
    (FIG / "ket_qua.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    if a.sql:
        write_sql(mm)


if __name__ == "__main__":
    main()
