"""Train 1 model dự đoán bỏ học, log kết quả bằng MLflow. Chạy được trên laptop lẫn Azure ML.

Ví dụ trên laptop:
    python ml/src/train.py --data ml/data/students.csv --major-faculty ml/data/major_faculty.csv --model logreg
Trên Azure ML: xem ml/run_jobs.py (cùng file này, chỉ khác chỗ chạy).

--data nhận 1 trong 2 dạng:
  * students.csv gốc (có cột STUDENT_IDENTIFIER) -> tự tính feature bằng features.py (tuần 1–2)
  * bảng curated/student_features của TV1 (file .parquet / .csv hoặc thư mục Parquet) (từ tuần 3)
Dù dạng nào, CHỈ dùng dòng is_synthetic = 0 (3.400 sinh viên thật).

Kết quả:
  * metric MLflow: val_auc, val_f1, val_recall, val_precision, cv_auc_mean, test_*, train_seconds, threshold
  * thư mục outputs/model/: model.pkl (pipeline sklearn đầy đủ) + meta.json (ngưỡng, danh sách feature)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (f1_score, fbeta_score, precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import CAT_FEATURES, FEATURES, TERM2_FEATURES, add_missing_tv2_columns, build_features  # noqa: E402

try:
    import mlflow
except ImportError:          # cho phép chạy thử khi chưa cài mlflow
    mlflow = None

SEED = 42


# ---------------------------------------------------------------- dữ liệu
def load_features(data, major_faculty=None, include_synthetic=False):
    p = Path(data)
    if p.is_dir():
        df = pd.read_parquet(p)
    elif p.suffix == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)
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
    """70% train / 15% validation / 15% test, giữ tỉ lệ bỏ học (stratify). Cùng seed = cùng cách chia."""
    dev, test = train_test_split(df, test_size=0.15, stratify=df["dropout"], random_state=seed)
    train, val = train_test_split(dev, test_size=0.15 / 0.85, stratify=dev["dropout"], random_state=seed)
    return train, val, test


def feature_list(drop_term2=False):
    return [f for f in FEATURES if not (drop_term2 and f in TERM2_FEATURES)]


# ---------------------------------------------------------------- model
def make_model(a):
    if a.model == "logreg":
        return LogisticRegression(C=a.C, class_weight="balanced", max_iter=2000)
    if a.model == "rf":
        return RandomForestClassifier(n_estimators=a.n_estimators, max_depth=a.max_depth or None,
                                      min_samples_leaf=a.min_samples_leaf, class_weight="balanced",
                                      n_jobs=-1, random_state=SEED)
    if a.model == "lgbm":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(n_estimators=a.n_estimators, learning_rate=a.learning_rate, num_leaves=a.num_leaves,
                              min_child_samples=a.min_samples_leaf, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.8, class_weight="balanced", random_state=SEED, verbose=-1)
    if a.model == "xgb":
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=a.n_estimators, learning_rate=a.learning_rate,
                             max_depth=a.max_depth or 4, subsample=0.8, colsample_bytree=0.8,
                             scale_pos_weight=a.pos_weight, eval_metric="auc", random_state=SEED)
    if a.model == "mlp":
        return MLPClassifier(hidden_layer_sizes=tuple(int(x) for x in a.hidden.split(",")), alpha=a.alpha,
                             max_iter=500, early_stopping=True, random_state=SEED)
    raise SystemExit(f"Model không hỗ trợ: {a.model}")


def make_pipeline(model, features):
    num = [f for f in features if f not in CAT_FEATURES]
    cat = [f for f in features if f in CAT_FEATURES]
    prep = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), num),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                          ("oh", OneHotEncoder(handle_unknown="ignore"))]), cat),
    ])
    return Pipeline([("prep", prep), ("clf", model)])


def oversample(X, y, seed=SEED):
    """MLP không có class_weight -> nhân bản ngẫu nhiên lớp bỏ học trong tập train cho cân bằng."""
    rng = np.random.default_rng(seed)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    extra = rng.choice(pos, len(neg) - len(pos), replace=True)
    idx = np.concatenate([neg, pos, extra])
    return X.iloc[idx], y.iloc[idx]


def pick_threshold(y, p):
    """Ngưỡng có F2 cao nhất trên validation: F2 coi recall nặng gấp đôi precision
    (bỏ sót sinh viên sắp bỏ học tốn kém hơn báo nhầm)."""
    grid = np.arange(0.10, 0.91, 0.01)
    scores = [fbeta_score(y, p >= t, beta=2, zero_division=0) for t in grid]
    return float(grid[int(np.argmax(scores))])


def scores(prefix, y, p, t):
    pred = (p >= t).astype(int)
    return {f"{prefix}_auc": roc_auc_score(y, p),
            f"{prefix}_f1": f1_score(y, pred, zero_division=0),
            f"{prefix}_recall": recall_score(y, pred, zero_division=0),
            f"{prefix}_precision": precision_score(y, pred, zero_division=0)}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--major-faculty", default=None)
    ap.add_argument("--model", default="logreg", choices=["logreg", "rf", "lgbm", "xgb", "mlp"])
    ap.add_argument("--drop-term2", type=int, default=0, help="1 = dự đoán ở cuối học kỳ 1 (bỏ cột học kỳ 2)")
    # tham số (mỗi model chỉ dùng phần của mình; sweep job đổi các giá trị này)
    ap.add_argument("--C", type=float, default=1.0)
    ap.add_argument("--n-estimators", type=int, default=300)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--num-leaves", type=int, default=31)
    ap.add_argument("--max-depth", type=int, default=0)
    ap.add_argument("--min-samples-leaf", type=int, default=20)
    ap.add_argument("--pos-weight", type=float, default=3.7)   # ≈ số SV ở lại / số SV bỏ học
    ap.add_argument("--hidden", default="64,32")
    ap.add_argument("--alpha", type=float, default=1e-3)
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--benchmark-synthetic", type=int, default=0,
                    help="1 = giữ dữ liệu mô phỏng, CHỈ để đo thời gian train (T2.7)")
    a = ap.parse_args()

    df = load_features(a.data, a.major_faculty, include_synthetic=bool(a.benchmark_synthetic))
    feats = feature_list(a.drop_term2)
    train, val, test = split_data(df)
    Xtr, ytr = train[feats], train["dropout"].astype(int)
    print(f"Sinh viên thật: {len(df)} | train {len(train)} / val {len(val)} / test {len(test)} "
          f"| tỉ lệ bỏ học {df['dropout'].mean():.1%} | {len(feats)} feature")

    if mlflow:
        mlflow.start_run()
        params = {k: v for k, v in vars(a).items() if k not in ("data", "major_faculty", "out")}
        mlflow.log_params(params)
        mlflow.set_tag("model_name", "benchmark" if a.benchmark_synthetic else a.model)

    pipe = make_pipeline(make_model(a), feats)
    if a.model == "mlp":
        Xtr, ytr = oversample(Xtr, ytr)
    t0 = time.perf_counter()
    pipe.fit(Xtr, ytr)
    train_seconds = time.perf_counter() - t0

    p_val = pipe.predict_proba(val[feats])[:, 1]
    p_test = pipe.predict_proba(test[feats])[:, 1]
    t = pick_threshold(val["dropout"], p_val)

    # độ ổn định: AUC 5-fold trên phần train + val (dữ liệu nhỏ nên 1 lần chia dễ "may/rủi")
    dev = pd.concat([train, val])
    cv = np.array([np.nan]) if a.benchmark_synthetic else cross_val_score(
        make_pipeline(make_model(a), feats), dev[feats], dev["dropout"].astype(int),
        cv=StratifiedKFold(5, shuffle=True, random_state=SEED), scoring="roc_auc")

    m = {**scores("val", val["dropout"], p_val, t), **scores("test", test["dropout"], p_test, t),
         "cv_auc_mean": float(cv.mean()), "cv_auc_std": float(cv.std()),
         "threshold": t, "train_seconds": train_seconds}
    for k, v in m.items():
        print(f"  {k:16s} {v:.4f}")

    out = Path(a.out) / "model"
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, out / "model.pkl")
    train[feats].sample(min(200, len(train)), random_state=SEED).to_csv(out / "background.csv", index=False)
    meta = {"model_name": a.model, "threshold": t, "features": feats, "drop_term2": bool(a.drop_term2),
            "metrics": m, "params": {k: v for k, v in vars(a).items() if k not in ("data", "major_faculty", "out")}}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if mlflow:
        mlflow.log_metrics({k: v for k, v in m.items() if not np.isnan(v)})
        mlflow.log_artifacts(str(out), artifact_path="model")
        mlflow.end_run()


if __name__ == "__main__":
    main()
