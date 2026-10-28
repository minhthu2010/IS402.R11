"""Train 1 model dự đoán bỏ học, log kết quả bằng MLflow. Chạy được trên laptop lẫn Azure ML.

Ví dụ trên laptop:
    python ml/src/train.py --data ml/data/students.csv --major-faculty ml/data/major_faculty.csv --model logreg
Trên Azure ML: xem ml/run_jobs.py (cùng file này, chỉ khác chỗ chạy).

--data nhận 1 trong 2 dạng:
  * students.csv gốc (có cột STUDENT_IDENTIFIER) -> tự tính feature bằng features.py (tuần 1–2)
  * bảng curated/student_features của TV1 (file .parquet / .csv hoặc thư mục Parquet) (từ tuần 3)
Dù dạng nào, CHỈ dùng dòng is_synthetic = 0 (3.400 sinh viên thật).

Quy trình (chống rò rỉ, tận dụng hết dữ liệu nhỏ):
  1. Tách 15% làm tập TEST, khóa lại, chỉ chấm đúng 1 lần ở cuối. 85% còn lại = tập DEV.
  2. Cross-validation 5 fold trên DEV -> xác suất "out-of-fold" cho mọi sinh viên DEV
     (mỗi sinh viên được chấm bởi model KHÔNG nhìn thấy nó). Từ đó tính cv_auc và chọn NGƯỠNG.
  3. Train lại model trên toàn bộ DEV, chấm TEST bằng ngưỡng ở bước 2.
  Mọi bước điền thiếu, log, chuẩn hóa, one-hot nằm trong Pipeline nên chỉ học từ phần dữ liệu train của mỗi fold.

Kết quả:
  * metric MLflow: cv_auc, cv_auc_std, cv_recall, cv_precision, cv_f1, cv_accuracy, threshold,
    test_auc, test_recall, test_precision, test_f1, test_accuracy, test_baseline_accuracy, train_seconds
  * thư mục outputs/model/: model.pkl (pipeline sklearn đầy đủ), meta.json (ngưỡng, feature, metric), background.csv
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
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import (CAT_FEATURES, FEATURES, LOG_FEATURES, SENSITIVE_FEATURES, TERM2_FEATURES,  # noqa: E402
                      add_missing_tv2_columns, build_features, log1p_nonneg)

try:
    import mlflow
except ImportError:          # cho phép chạy thử khi chưa cài mlflow
    mlflow = None

SEED = 42
N_FOLDS = 5


# ---------------------------------------------------------------- dữ liệu
def load_features(data, major_faculty=None, include_synthetic=False):
    p = Path(data)
    df = pd.read_parquet(p) if (p.is_dir() or p.suffix == ".parquet") else pd.read_csv(p)
    if "STUDENT_IDENTIFIER" in df.columns or "STUDENT IDENTIFIER" in df.columns:
        if major_faculty is None:
            raise SystemExit("Dữ liệu gốc students.csv cần thêm --major-faculty")
        df = build_features(df, pd.read_csv(major_faculty))
    else:
        df = add_missing_tv2_columns(df)
    if include_synthetic:      # CHỈ để đo thời gian (T2.7), không dùng model/metric của lần chạy này
        print("CẢNH BÁO: đang train cả dữ liệu mô phỏng – chỉ dùng để benchmark thời gian")
        return df.reset_index(drop=True)
    return df[df["is_synthetic"].astype(int) == 0].reset_index(drop=True)


def split_data(df, seed=SEED):
    """85% DEV (cross-validation, chọn ngưỡng, train) / 15% TEST (chấm 1 lần). Cùng seed = cùng cách chia."""
    dev, test = train_test_split(df, test_size=0.15, stratify=df["dropout"], random_state=seed)
    return dev.reset_index(drop=True), test.reset_index(drop=True)


def feature_list(drop_term2=False, drop_sensitive=True):
    return [f for f in FEATURES
            if not (drop_term2 and f in TERM2_FEATURES) and not (drop_sensitive and f in SENSITIVE_FEATURES)]


# ---------------------------------------------------------------- model
def make_model(a):
    # Mặc định KHÔNG đánh trọng số lớp: mất cân bằng đã được xử lý ở bước chọn ngưỡng, nên xác suất
    # model trả ra giữ đúng ý nghĩa (0,3 ≈ 30% khả năng bỏ học) để hiển thị trên web và Power BI.
    cw = "balanced" if a.balanced else None
    if a.model == "logreg":
        return LogisticRegression(C=a.C, class_weight=cw, max_iter=5000)
    if a.model == "rf":
        return RandomForestClassifier(n_estimators=a.n_estimators, max_depth=a.max_depth or None,
                                      min_samples_leaf=a.min_samples_leaf, class_weight=cw,
                                      n_jobs=-1, random_state=SEED)
    if a.model == "lgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=a.n_estimators, learning_rate=a.learning_rate, num_leaves=a.num_leaves,
                              min_child_samples=a.min_samples_leaf, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, reg_lambda=1.0, class_weight=cw,
                              random_state=SEED, verbose=-1)
    if a.model == "xgb":
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=a.n_estimators, learning_rate=a.learning_rate,
                             max_depth=a.max_depth or 4, subsample=0.8, colsample_bytree=0.8,
                             scale_pos_weight=a.pos_weight if a.balanced else 1.0,
                             eval_metric="logloss", random_state=SEED)
    if a.model == "mlp":
        return MLPClassifier(hidden_layer_sizes=tuple(int(x) for x in a.hidden.split(",")), alpha=a.alpha,
                             max_iter=1000, early_stopping=True, random_state=SEED)
    raise SystemExit(f"Model không hỗ trợ: {a.model}")


def make_pipeline(model, features):
    log = [f for f in features if f in LOG_FEATURES]
    num = [f for f in features if f not in CAT_FEATURES and f not in LOG_FEATURES]
    cat = [f for f in features if f in CAT_FEATURES]
    # Không thêm cột "missing indicator" tự động: chỗ thiếu quan trọng đã có cờ riêng
    # (has_second_term, entrance_missing, fin_data_missing); thêm nữa sẽ tạo nhiều cột trùng nhau
    # (mọi cột học kỳ 2 cùng thiếu một lúc) làm hệ số LogReg và phần giải thích bị nhiễu.
    num_steps = [("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]
    prep = ColumnTransformer([
        ("log", Pipeline([("imp", SimpleImputer(strategy="median")),
                          ("log", FunctionTransformer(log1p_nonneg, feature_names_out="one-to-one")),
                          ("sc", StandardScaler())]), log),
        ("num", Pipeline(num_steps), num),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                          ("oh", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), cat),
    ])
    # Truyền DataFrame có tên cột qua mọi bước, để LightGBM/XGBoost nhận cùng tên cột lúc train và lúc dự đoán.
    prep.set_output(transform="pandas")
    return Pipeline([("prep", prep), ("clf", model)])


def out_of_fold(pipe, X, y, seed=SEED):
    """Xác suất bỏ học cho mọi dòng, mỗi dòng được chấm bởi model train trên 4 fold còn lại."""
    oof = np.zeros(len(y))
    fold_auc = []
    for tr, te in StratifiedKFold(N_FOLDS, shuffle=True, random_state=seed).split(X, y):
        m = clone(pipe).fit(X.iloc[tr], y.iloc[tr])
        oof[te] = m.predict_proba(X.iloc[te])[:, 1]
        fold_auc.append(roc_auc_score(y.iloc[te], oof[te]))
    return oof, np.array(fold_auc)


def pick_threshold(y, p, rule="recall", min_recall=0.50):
    """Chọn ngưỡng xác suất từ dự đoán out-of-fold.
    rule="recall" (mặc định): ngưỡng CAO NHẤT mà vẫn phát hiện được >= min_recall số SV bỏ học
        -> ưu tiên không bỏ sót, nhưng gắn cờ ít người nhất có thể (precision cao nhất).
    rule="f1": ngưỡng có F1 cao nhất (cân bằng recall và precision).
    """
    y = np.asarray(y).astype(int)
    grid = np.round(np.arange(0.02, 0.96, 0.01), 2)
    if rule == "recall":
        ok = [t for t in grid if recall_score(y, p >= t, zero_division=0) >= min_recall]
        if ok:
            return float(max(ok))
    f1s = [f1_score(y, p >= t, zero_division=0) for t in grid]
    return float(grid[int(np.argmax(f1s))])


def scores(prefix, y, p, t):
    pred = (p >= t).astype(int)
    return {f"{prefix}_auc": roc_auc_score(y, p),
            f"{prefix}_recall": recall_score(y, pred, zero_division=0),
            f"{prefix}_precision": precision_score(y, pred, zero_division=0),
            f"{prefix}_f1": f1_score(y, pred, zero_division=0),
            f"{prefix}_accuracy": accuracy_score(y, pred)}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--major-faculty", default=None)
    ap.add_argument("--model", default="logreg", choices=["logreg", "rf", "lgbm", "xgb", "mlp"])
    ap.add_argument("--drop-term2", type=int, default=0, help="1 = dự đoán ở cuối học kỳ 1 (bỏ cột học kỳ 2)")
    ap.add_argument("--drop-sensitive", type=int, default=1,
                    help="1 (mặc định) = không dùng nhóm xuất thân và giới tính; 0 = dùng (để so sánh)")
    ap.add_argument("--balanced", type=int, default=0, help="1 = đánh trọng số lớp (xác suất sẽ bị thổi phồng)")
    # tham số (mỗi model chỉ dùng phần của mình; sweep job đổi các giá trị này)
    ap.add_argument("--C", type=float, default=1.0)
    ap.add_argument("--n-estimators", type=int, default=300)
    ap.add_argument("--learning-rate", type=float, default=0.03)
    ap.add_argument("--num-leaves", type=int, default=15)
    ap.add_argument("--max-depth", type=int, default=0)
    ap.add_argument("--min-samples-leaf", type=int, default=20)
    ap.add_argument("--pos-weight", type=float, default=3.7)   # ≈ số SV ở lại / số SV bỏ học
    ap.add_argument("--hidden", default="32")
    ap.add_argument("--alpha", type=float, default=1e-2)
    ap.add_argument("--threshold-rule", default="recall", choices=["recall", "f1"])
    ap.add_argument("--min-recall", type=float, default=0.50,
                    help="dùng với --threshold-rule recall. 0,5 trên dữ liệu thật: gắn cờ ~1/4 SV, precision ~46%%")
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--benchmark-synthetic", type=int, default=0,
                    help="1 = giữ dữ liệu mô phỏng, CHỈ để đo thời gian train (T2.7)")
    a = ap.parse_args()

    df = load_features(a.data, a.major_faculty, include_synthetic=bool(a.benchmark_synthetic))
    feats = feature_list(a.drop_term2, a.drop_sensitive)
    dev, test = split_data(df)
    Xd, yd = dev[feats], dev["dropout"].astype(int)
    Xt, yt = test[feats], test["dropout"].astype(int)
    print(f"Sinh viên: {len(df)} | dev {len(dev)} (CV {N_FOLDS} fold) / test {len(test)} "
          f"| tỉ lệ bỏ học {df['dropout'].mean():.1%} | {len(feats)} feature")

    params = {k: v for k, v in vars(a).items() if k not in ("data", "major_faculty", "out")}
    if mlflow:
        mlflow.start_run()
        mlflow.log_params(params)
        mlflow.set_tag("model_name", "benchmark" if a.benchmark_synthetic else a.model)

    pipe = make_pipeline(make_model(a), feats)
    m = {}
    if not a.benchmark_synthetic:
        oof, fold_auc = out_of_fold(pipe, Xd, yd)
        t = pick_threshold(yd, oof, a.threshold_rule, a.min_recall)
        m.update(scores("cv", yd, oof, t))
        m["cv_auc_std"] = float(fold_auc.std())
    else:
        t = 0.5

    t0 = time.perf_counter()
    pipe.fit(Xd, yd)                                     # model cuối: train trên toàn bộ DEV
    train_seconds = time.perf_counter() - t0
    p_test = pipe.predict_proba(Xt)[:, 1]
    m.update(scores("test", yt, p_test, t))
    m["test_baseline_accuracy"] = float(max(yt.mean(), 1 - yt.mean()))   # đoán "tất cả ở lại"
    m["threshold"] = t
    m["train_seconds"] = train_seconds
    for k, v in m.items():
        print(f"  {k:24s} {v:.4f}")

    out = Path(a.out) / "model"
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, out / "model.pkl")
    Xd.sample(min(200, len(Xd)), random_state=SEED).to_csv(out / "background.csv", index=False)
    meta = {"model_name": a.model, "threshold": t, "features": feats, "drop_term2": bool(a.drop_term2),
            "drop_sensitive": bool(a.drop_sensitive),
            "metrics": m, "params": params}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if mlflow:
        mlflow.log_metrics({k: v for k, v in m.items() if not np.isnan(v)})
        mlflow.log_artifacts(str(out), artifact_path="model")
        mlflow.end_run()


if __name__ == "__main__":
    main()
