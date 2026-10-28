"""Script chấm điểm cho Azure ML managed online endpoint (TV3 deploy, TV2 viết).

Đầu vào (POST JSON):
    {"data": [ {cột gốc như students.csv: STUDENT_IDENTIFIER, STDNT_AGE, HIGH_SCHL_GPA, CORE_COURSE_GRADE_1_F, ...}, ... ]}
  hoặc các dòng đã là feature (cột như bảng student_features) — script tự nhận ra.
Đầu ra:
    [ {"student_id": 7123456, "probability": 0.81, "risk_level": "Cao",
       "top_factors": ["Có học HK2", "GPA HK1", "Số môn D/F HK1"], "model_version": "lgbm"}, ... ]
risk_level: Cao khi xác suất ≥ ngưỡng của model; Trung bình khi ≥ nửa ngưỡng; còn lại Thấp.

Thư mục code khi deploy = ml/src (chứa score.py, features.py, explain.py, major_faculty.csv).
Model đăng ký = thư mục chứa model.pkl, meta.json, background.csv (outputs/model của job train).
Chạy thử trên laptop:  python ml/src/score.py --model-dir outputs/model --request ml/deploy/sample_requests.json
"""
import json
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from explain import contributions, top_factors          # noqa: E402
from features import add_missing_tv2_columns, build_features  # noqa: E402

pipe = meta = background = major_faculty = None


def init(model_dir=None):
    global pipe, meta, background, major_faculty
    root = Path(model_dir or os.getenv("AZUREML_MODEL_DIR", "."))
    folder = next(root.rglob("model.pkl")).parent          # vị trí thư mục model khác nhau tùy cách đăng ký
    pipe = joblib.load(folder / "model.pkl")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    bg = folder / "background.csv"
    background = add_missing_tv2_columns(pd.read_csv(bg)) if bg.exists() else None
    major_faculty = pd.read_csv(HERE / "major_faculty.csv")


def _to_features(rows: pd.DataFrame) -> pd.DataFrame:
    cols = [c.strip().replace(" ", "_") for c in rows.columns]
    rows = rows.set_axis(cols, axis=1)
    if "STUDENT_IDENTIFIER" in cols or "STDNT_MAJOR" in cols:
        if "STUDENT_IDENTIFIER" not in cols:
            rows["STUDENT_IDENTIFIER"] = range(len(rows))
        return build_features(rows, major_faculty)
    rows = rows.copy()
    if "student_id" not in rows:
        rows["student_id"] = range(len(rows))
    for f in meta["features"]:
        if f not in rows:
            rows[f] = np.nan                                  # thiếu cột -> model tự điền trung vị
    return add_missing_tv2_columns(rows)


def risk_level(p, t):
    return "Cao" if p >= t else "Trung bình" if p >= t / 2 else "Thấp"


def run(raw_data):
    try:
        body = json.loads(raw_data) if isinstance(raw_data, (str, bytes)) else raw_data
        rows = pd.DataFrame(body["data"])
        if rows.empty:
            return {"error": "Không có dòng dữ liệu nào trong 'data'"}
        feat = _to_features(rows)
        feats, t = meta["features"], meta["threshold"]
        prob = pipe.predict_proba(feat[feats])[:, 1]
        contrib = contributions(pipe, feat, feats, background)
        out = []
        for i, p in enumerate(prob):
            sid = feat["student_id"].iloc[i]
            out.append({
                "student_id": int(sid) if pd.notna(sid) else None,
                "probability": round(float(p), 4),
                "risk_level": risk_level(p, t),
                "top_factors": top_factors(contrib.iloc[i]) if contrib is not None else [],
                "model_version": meta["model_name"],
            })
        return out
    except Exception as e:                                    # trả lỗi rõ ràng cho web/Function thay vì 500 trống
        return {"error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default="outputs/model")
    ap.add_argument("--request", required=True)
    a = ap.parse_args()
    init(a.model_dir)
    reqs = json.loads(Path(a.request).read_text(encoding="utf-8"))
    for name, req in reqs.items():
        print(name, json.dumps(run(json.dumps(req)), ensure_ascii=False, indent=1))
