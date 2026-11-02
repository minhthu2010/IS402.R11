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


def aml_clients():
    import mlflow
    from azure.ai.ml import MLClient
    from azure.identity import DefaultAzureCredential
    ml = MLClient.from_config(DefaultAzureCredential(exclude_interactive_browser_credential=False), path=str(HERE / "config.json"))
    mlflow.set_tracking_uri(ml.workspaces.get(ml.workspace_name).mlflow_tracking_uri)
    return ml, mlflow


def mlflow_client():
    return aml_clients()[1]


def finished_runs(mlflow, experiment):
    """Các run đã chạy xong của 1 experiment. Azure ML đặt tên trạng thái khác MLflow gốc
    (Completed thay vì FINISHED), nên lọc bằng pandas thay vì filter_string của MLflow."""
    runs = mlflow.search_runs(experiment_names=[experiment])
    if runs.empty:
        raise SystemExit(f"Không tìm thấy run nào trong experiment '{experiment}'. "
                         "Kiểm tra config.json trỏ đúng workspace và job đã chạy xong.")
    runs = runs[runs["status"].astype(str).str.upper().isin(["FINISHED", "COMPLETED"])]
    if runs.empty:
        raise SystemExit(f"Experiment '{experiment}' chưa có run nào chạy xong.")
    return runs


def param(runs, name, default):
    """Cột tham số của run; run cũ chưa log tham số đó thì coi như giá trị mặc định."""
    col = f"params.{name}"
    return runs[col].fillna(default).astype(str) if col in runs else pd.Series(default, index=runs.index)


def load_aml(dst, run_ids=None):
    ml, mlflow = aml_clients()
    runs = finished_runs(mlflow, "dropout-models")
    if run_ids:                                  # chọn đích danh các job (Name trong tab Overview)
        runs = runs[runs["run_id"].isin(run_ids)]
        missing = set(run_ids) - set(runs["run_id"])
        if missing:
            raise SystemExit(f"Không tìm thấy job đã chạy xong: {', '.join(sorted(missing))}")
    else:                                        # mặc định: job mới nhất của mỗi loại model, bản chính thức
        keep = (param(runs, "drop_term2", "0") == "0") & (param(runs, "drop_sensitive", "1") == "1")
        keep &= runs["tags.model_name"].notna() & (runs["tags.model_name"] != "benchmark")
        runs = runs[keep]
    runs = runs.sort_values("start_time", ascending=False)
    out = []
    groups = runs.groupby("run_id", sort=False) if run_ids else runs.groupby("tags.model_name", sort=False)
    for name, r in groups:
        rid = r.iloc[0]["run_id"]                       # run mới nhất của loại model này (hoặc job được chỉ định)
        # Tải thư mục outputs/model của job (Azure ML tự lưu ./outputs) bằng SDK, không qua mlflow
        target = dst / rid
        if not any(target.rglob("model.pkl")):
            ml.jobs.download(name=rid, download_path=str(target))
        m = load_dir(next(target.rglob("model.pkl")).parent)
        m["run_id"] = rid
        out.append(m)
        print(f"{name:7s} run {rid}")
    return out


# ---------------------------------------------------------------- biểu đồ
def model_label(m, models):
    """Tên hiển thị của 1 model; thêm chú thích trong ngoặc khi cần phân biệt các bản cùng loại."""
    meta, p = m["meta"], m["meta"].get("params", {})
    name = NAMES.get(meta["model_name"], meta["model_name"])
    if not meta.get("drop_sensitive", False):
        name += " (+xuất thân, giới tính)"
    if meta.get("drop_term2", False):
        name += " (cuối HK1)"
    if str(p.get("data_source", "")) == "curated":
        name += " (curated)"
    same = [x for x in models if x["meta"]["model_name"] == meta["model_name"]
            and x["meta"].get("drop_term2") == meta.get("drop_term2")
            and str(x["meta"].get("params", {}).get("data_source", "")) == str(p.get("data_source", ""))]
    if meta["model_name"] == "lgbm" and len(same) > 1:
        name += f" ({p.get('n_estimators')} cây, {p.get('num_leaves')} lá)"   # phân biệt bản mặc định / sau sweep
    return name


def wrap(label):
    """Mỗi phần trong ngoặc xuống 1 dòng riêng để nhãn trục không đè lên nhau."""
    return label.replace(" (", "\n(")


def plot_compare(models, test):
    """Cột trái: metric cross-validation (5 fold trên tập dev) của từng model + mốc "đoán tất cả ở lại"."""
    rows = [{"model": model_label(m, models),
             **{k: m["meta"]["metrics"][k] for k in SHOW + ["cv_auc_std", "test_auc", "train_seconds"]}}
            for m in models]
    df = pd.DataFrame(rows).sort_values("cv_auc", ascending=False)
    base_acc = max(test["dropout"].mean(), 1 - test["dropout"].mean())
    base = pd.DataFrame([{"model": "Đoán tất cả ở lại", "cv_auc": 0.5, "cv_recall": 0.0, "cv_precision": 0.0,
                          "cv_f1": 0.0, "cv_accuracy": base_acc}])
    plot = pd.concat([df, base], ignore_index=True).set_index("model")[SHOW]
    plot.index = [wrap(i) for i in plot.index]
    n = len(plot)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(max(14, 2.3 * n + 4), 5.6),
                                 gridspec_kw={"width_ratios": [3.2, 1.1]})
    plot.rename(columns=lambda c: c.replace("cv_", "").upper()).plot.bar(ax=a1, rot=0, width=0.85)
    a1.set(ylim=(0, 1.05), ylabel="Cross-validation 5 fold (tập dev)", xlabel="",
           title="So sánh model: ROC-AUC, recall, precision, F1, accuracy (lớp dương = bỏ học)")
    a1.tick_params(axis="x", labelsize=9)
    a1.legend(ncols=5, loc="upper center", bbox_to_anchor=(0.5, -0.17), frameon=False)
    for c in a1.containers:
        a1.bar_label(c, fmt="%.2f", fontsize=7)
    a2.barh([wrap(x) for x in df["model"]], df["train_seconds"], color="grey")
    a2.set(xlabel="Giây", title="Thời gian train (toàn bộ dev)")
    a2.tick_params(axis="y", labelsize=9)
    a2.invert_yaxis()
    fig.tight_layout()
    save(fig, "10_so_sanh_model.png")
    return pd.concat([df, base], ignore_index=True)


def plot_roc(models, test):
    fig, ax = plt.subplots(figsize=(6, 6))
    for m in models:
        p = m["pipe"].predict_proba(test[m["meta"]["features"]])[:, 1]
        fpr, tpr, _ = roc_curve(test["dropout"], p)
        ax.plot(fpr, tpr, label=f"{model_label(m, models)}: AUC {roc_auc_score(test['dropout'], p):.3f}")
    ax.plot([0, 1], [0, 1], "--", c="grey", lw=1)
    ax.set(xlabel="Tỉ lệ báo nhầm (FPR)", ylabel="Tỉ lệ phát hiện đúng (recall / TPR)", title="Đường ROC trên tập test")
    ax.legend(loc="lower right")
    save(fig, "11_roc.png")


def plot_sweep():
    mlflow = mlflow_client()
    runs = finished_runs(mlflow, "dropout-sweep")      # gồm cả job cha (không có metric) -> bị loại ở dòng dưới
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
    ap.add_argument("--runs", nargs="*", default=None,
                    help="dùng với --aml: Name các job muốn so sánh (mặc định: job mới nhất của mỗi model)")
    ap.add_argument("--local", nargs="*", default=[])
    ap.add_argument("--data", required=True)
    ap.add_argument("--major-faculty", default=None)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--best", default=None, help="model cuối: Name của job (vd purple_pin_...) hoặc loại model (lgbm); mặc định: cv_auc cao nhất")
    ap.add_argument("--sql", action="store_true")
    a = ap.parse_args()
    FIG.mkdir(exist_ok=True)

    models = load_aml(HERE / "downloads", a.runs) if a.aml else [load_dir(d) for d in a.local]
    if not models:
        raise SystemExit("Không có model nào: dùng --aml hoặc --local <thư mục>")
    dev, test = split_data(load_features(a.data, a.major_faculty))

    table = plot_compare(models, test)
    plot_roc(models, test)
    if a.sweep:
        plot_sweep()
    # Model chính thức chỉ chọn trong các bản KHÔNG dùng xuất thân, giới tính; bản có dùng chỉ để so sánh.
    official = [m for m in models if m["meta"].get("drop_sensitive", True)] or models
    if a.best:                                   # Name của job (ưu tiên) hoặc tên loại model
        match = [m for m in models if m["run_id"] == a.best] or [m for m in official if m["meta"]["model_name"] == a.best]
        if not match:
            raise SystemExit(f"--best {a.best}: không khớp job hay loại model nào trong danh sách")
        best = match[0]
    else:
        best = max(official, key=lambda m: m["meta"]["metrics"]["cv_auc"])
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
