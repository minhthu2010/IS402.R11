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
import os
import warnings
# joblib cố đếm lõi CPU vật lý bằng lệnh "wmic" mà Windows 11 đã bỏ, rồi in cảnh báo dài (không ảnh hưởng kết quả).
# Khai sẵn số lõi = 1/2 số luồng (thường đúng bằng số lõi vật lý) để joblib bỏ qua bước đếm đó.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(max(1, (os.cpu_count() or 2) // 2)))
warnings.filterwarnings("ignore", message="Could not find the number of physical cores")
import argparse
import json
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
SHOW = ["cv_auc", "cv_recall", "cv_precision", "cv_f1", "cv_accuracy"]


def save(fig, name):
    """Lưu hình vào ml/figures. Windows khóa file đang mở ở chương trình khác (trình xem ảnh, VS Code...),
    khi đó lưu sang tên khác thay vì dừng cả chương trình."""
    path = FIG / name
    try:
        fig.savefig(path, dpi=200, bbox_inches="tight")
    except OSError:
        alt = path.with_name(f"{path.stem}_moi{path.suffix}")
        fig.savefig(alt, dpi=200, bbox_inches="tight")
        print(f"Không ghi đè được {path.name} (file đang mở ở chương trình khác?) -> đã lưu thành {alt.name}")
    plt.close(fig)


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
    keep = runs["params.drop_term2"].astype(str) == "0"
    if "params.drop_sensitive" in runs:          # bản chính thức: không dùng xuất thân, giới tính
        keep &= runs["params.drop_sensitive"].astype(str).isin(["1", "nan", "None"])
    runs = runs[keep].sort_values("start_time", ascending=False)
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
def plot_compare(models, test):
    """Cột trái: metric cross-validation (5 fold trên tập dev) của từng model + mốc "đoán tất cả ở lại"."""
    rows = [{"model": NAMES.get(m["meta"]["model_name"], m["meta"]["model_name"])
             + ("" if m["meta"].get("drop_sensitive", False) else " (+xuất thân, giới tính)"),
             **{k: m["meta"]["metrics"][k] for k in SHOW + ["cv_auc_std", "test_auc", "train_seconds"]}}
            for m in models]
    df = pd.DataFrame(rows).sort_values("cv_auc", ascending=False)
    base_acc = max(test["dropout"].mean(), 1 - test["dropout"].mean())
    base = pd.DataFrame([{"model": "Đoán tất cả ở lại", "cv_auc": 0.5, "cv_recall": 0.0, "cv_precision": 0.0,
                          "cv_f1": 0.0, "cv_accuracy": base_acc}])
    plot = pd.concat([df, base], ignore_index=True).set_index("model")[SHOW]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 4.8), gridspec_kw={"width_ratios": [3.2, 1]})
    plot.rename(columns=lambda c: c.replace("cv_", "").upper()).plot.bar(ax=a1, rot=0, width=0.85)
    a1.set(ylim=(0, 1.05), ylabel="Cross-validation 5 fold (tập dev)", xlabel="",
           title="So sánh model: ROC-AUC, recall, precision, F1, accuracy (lớp dương = bỏ học)")
    a1.legend(ncols=5, loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False)
    for c in a1.containers:
        a1.bar_label(c, fmt="%.2f", fontsize=7)
    a2.barh(df["model"], df["train_seconds"], color="grey")
    a2.set(xlabel="Giây", title="Thời gian train (toàn bộ dev)")
    a2.invert_yaxis()
    fig.tight_layout()
    save(fig, "10_so_sanh_model.png")
    return pd.concat([df, base], ignore_index=True)


def plot_roc(models, test):
    fig, ax = plt.subplots(figsize=(6, 6))
    for m in models:
        p = m["pipe"].predict_proba(test[m["meta"]["features"]])[:, 1]
        fpr, tpr, _ = roc_curve(test["dropout"], p)
        ax.plot(fpr, tpr, label=f"{NAMES.get(m['meta']['model_name'])} (AUC {roc_auc_score(test['dropout'], p):.3f})")
    ax.plot([0, 1], [0, 1], "--", c="grey", lw=1)
    ax.set(xlabel="Tỉ lệ báo nhầm (FPR)", ylabel="Tỉ lệ phát hiện đúng (recall / TPR)", title="Đường ROC trên tập test")
    ax.legend(loc="lower right")
    save(fig, "11_roc.png")


def plot_sweep():
    mlflow = mlflow_client()
    runs = mlflow.search_runs(experiment_names=["dropout-sweep"], filter_string="attributes.status = 'FINISHED'")
    runs = runs.dropna(subset=["metrics.cv_auc"])
    params = [c for c in runs.columns if c.startswith("params.")
              and c.split(".", 1)[1] in ("n_estimators", "learning_rate", "num_leaves", "min_samples_leaf", "max_depth")
              and runs[c].nunique() > 1]
    fig, axes = plt.subplots(1, len(params), figsize=(4 * len(params), 3.8), sharey=True, squeeze=False)
    for ax, c in zip(axes[0], params):
        x = pd.to_numeric(runs[c])
        ax.scatter(x, runs["metrics.cv_auc"], alpha=0.7)
        best = runs["metrics.cv_auc"].idxmax()
        ax.scatter(x[best], runs.loc[best, "metrics.cv_auc"], c="red", s=60, label="tốt nhất")
        ax.set(xlabel=c.split(".", 1)[1], title=c.split(".", 1)[1])
    axes[0][0].set_ylabel("ROC-AUC cross-validation")
    axes[0][0].legend()
    fig.suptitle(f"Sweep {len(runs)} lần chạy: ROC-AUC theo từng tham số")
    fig.tight_layout()
    save(fig, "12_tham_so_sweep.png")
    best = runs.loc[runs["metrics.cv_auc"].idxmax()]
    print("Tham số tốt nhất:", {c.split('.', 1)[1]: best[c] for c in params}, "cv_auc", round(best["metrics.cv_auc"], 4))
    runs[[*params, "metrics.cv_auc", "metrics.cv_recall", "run_id"]].sort_values(
        "metrics.cv_auc", ascending=False).to_csv(FIG / "sweep_runs.csv", index=False)


def evaluate_best(best, test, dev):
    feats, t = best["meta"]["features"], best["meta"]["threshold"]
    p = best["pipe"].predict_proba(test[feats])[:, 1]
    pred = (p >= t).astype(int)
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ConfusionMatrixDisplay(confusion_matrix(test["dropout"], pred),
                           display_labels=["Ở lại", "Bỏ học"]).plot(ax=ax, colorbar=False, cmap="Blues")
    ax.set(title=f"{NAMES.get(best['meta']['model_name'])}, ngưỡng {t:.2f}", xlabel="Dự đoán", ylabel="Thực tế")
    save(fig, "13_confusion.png")
    report = classification_report(test["dropout"], pred, target_names=["Ở lại", "Bỏ học"], digits=3)

    contrib = contributions(best["pipe"], test, feats, dev)
    if contrib is None:
        print("Model này không hỗ trợ giải thích (MLP); chọn model cây hoặc LogReg để có SHAP.")
        return report
    imp = contrib.abs().mean().sort_values().tail(15)
    fig, ax = plt.subplots(figsize=(7, 5.5))
    ax.barh([LABELS_VI.get(f, f) for f in imp.index], imp.values)
    ax.set(xlabel="Mức ảnh hưởng trung bình |SHAP| (log-odds)", title="15 yếu tố ảnh hưởng nhiều nhất tới dự đoán bỏ học")
    save(fig, "14_shap_tong_quat.png")

    # Demo: sinh viên rủi ro cao nhất trong số CÓ đăng ký HK2 (nếu chọn người không đăng ký HK2 thì
    # một yếu tố chiếm gần hết, ai cũng đoán được; người có HK2 cho thấy model dựa vào GPA, tín chỉ, tài chính)
    pool = np.flatnonzero(test["has_second_term"].to_numpy() == 1) if "has_second_term" in feats else np.arange(len(p))
    i = int(pool[np.argmax(p[pool])]) if len(pool) else int(np.argmax(p))
    row = contrib.iloc[i].sort_values(key=abs).tail(10)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh([LABELS_VI.get(f, f) for f in row.index], row.values,
            color=["#c0392b" if v > 0 else "#2e86c1" for v in row.values])
    ax.axvline(0, c="black", lw=0.8)
    ax.set(xlabel="Đóng góp vào rủi ro (đỏ = tăng, xanh = giảm)",
           title=f"Vì sao SV {test['student_id'].iloc[i]} được dự đoán bỏ học (xác suất {p[i]:.0%})")
    save(fig, "15_giai_thich_1_sv.png")
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
    ap.add_argument("--best", default=None, help="tên model chọn làm model cuối (mặc định: cv_auc cao nhất)")
    ap.add_argument("--sql", action="store_true")
    a = ap.parse_args()
    FIG.mkdir(exist_ok=True)

    models = load_aml(HERE / "downloads") if a.aml else [load_dir(d) for d in a.local]
    if not models:
        raise SystemExit("Không có model nào: dùng --aml hoặc --local <thư mục>")
    dev, test = split_data(load_features(a.data, a.major_faculty))

    table = plot_compare(models, test)
    plot_roc(models, test)
    if a.sweep:
        plot_sweep()
    # Model chính thức chỉ chọn trong các bản KHÔNG dùng xuất thân, giới tính; bản có dùng chỉ để so sánh.
    official = [m for m in models if m["meta"].get("drop_sensitive", True)] or models
    best = (next(m for m in official if m["meta"]["model_name"] == a.best) if a.best
            else max(official, key=lambda m: m["meta"]["metrics"]["cv_auc"]))
    report = evaluate_best(best, test, dev)

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
