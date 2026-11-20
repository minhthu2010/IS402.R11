"""Logic dùng chung cho web (FastAPI) và Azure Function của TV3.
File này PHẢI giống hệt nhau ở web/ và function/ (sửa một nơi thì chép sang nơi kia).

Kiểm tra nhanh trên máy (không cần deploy):
    python dropout_common.py check ../tests/valid_3.csv            # kiểm tra file CSV theo data contract
    python dropout_common.py check ../tests/valid_3.csv --score    # kiểm tra + gọi endpoint thật (cần SCORING_URI/KEY trong .env)
    python dropout_common.py sqlcheck                              # thử kết nối Azure SQL (cần SQL_* trong .env)
"""
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

try:                                    # đọc file .env khi chạy trên máy; trên Azure dùng App Settings
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

HERE = Path(__file__).resolve().parent
MAJORS = pd.read_csv(HERE / "major_faculty.csv")
MAJOR_ID = dict(zip(MAJORS["major_name"], MAJORS["major_id"]))

# Cột gốc mà features.py của TV2 truy cập trực tiếp (thiếu cột -> KeyError). Mọi request gửi lên endpoint
# PHẢI có đủ các cột này (giá trị trống = null), nên ở đây ta tự thêm cột thiếu.
BASE_COLUMNS = [
    "STUDENT_IDENTIFIER", "STDNT_AGE", "STDNT_GENDER", "STDNT_BACKGROUND", "IN_STATE_FLAG",
    "INTERNATIONAL_STS", "STDNT_MAJOR", "STDNT_MINOR", "HIGH_SCHL_GPA", "STDNT_TEST_ENTRANCE_COMB",
    "FATHER_HI_EDU_CD", "MOTHER_HI_EDU_CD", "HOUSING_STS", "DISTANCE_FROM_HOME",
    "FIRST_TERM", "FIRST_TERM_ATTEMPT_HRS", "FIRST_TERM_EARNED_HRS",
    "SECOND_TERM", "SECOND_TERM_ATTEMPT_HRS", "SECOND_TERM_EARNED_HRS",
    "GROSS_FIN_NEED", "COST_OF_ATTEND", "EST_FAM_CONTRIBUTION", "UNMET_NEED",
]
GRADE_COLUMNS = [f"CORE_COURSE_GRADE_{i}_{t}" for t in "FS" for i in range(1, 7)]
RAW_COLUMNS = BASE_COLUMNS + GRADE_COLUMNS
REQUIRED = ["STUDENT_IDENTIFIER", "STDNT_MAJOR", "FIRST_TERM"]

NUMERIC = {  # cột: (nhỏ nhất, lớn nhất)
    "STUDENT_IDENTIFIER": (1, 2_147_483_647), "STDNT_AGE": (10, 80), "HIGH_SCHL_GPA": (0, 4),
    "STDNT_TEST_ENTRANCE_COMB": (0, 1600), "FATHER_HI_EDU_CD": (0, 20), "MOTHER_HI_EDU_CD": (0, 20),
    "DISTANCE_FROM_HOME": (0, 20000), "FIRST_TERM": (200001, 203012), "SECOND_TERM": (200001, 203012),
    "FIRST_TERM_ATTEMPT_HRS": (0, 40), "FIRST_TERM_EARNED_HRS": (0, 40),
    "SECOND_TERM_ATTEMPT_HRS": (0, 40), "SECOND_TERM_EARNED_HRS": (0, 40),
    "GROSS_FIN_NEED": (-1e7, 1e7), "COST_OF_ATTEND": (0, 1e7),
    "EST_FAM_CONTRIBUTION": (-1e7, 1e7), "UNMET_NEED": (-1e7, 1e7),
}
INTEGER_COLS = ["STUDENT_IDENTIFIER", "FIRST_TERM", "SECOND_TERM"]
CHOICES = {"STDNT_GENDER": {"F", "M"}, "IN_STATE_FLAG": {"Y", "N"}, "INTERNATIONAL_STS": {"Y", "N"},
           "HOUSING_STS": {"On Campus", "Off Campus"}}
VALID_GRADES = {"A", "B", "C", "D", "F", "NOT REP", "INCOMPL", "Unknown"}

MAX_ROWS = int(os.getenv("MAX_ROWS", "5000"))
BATCH = int(os.getenv("SCORE_BATCH", "100"))
MOCK = os.getenv("MOCK_API", "false").lower() == "true"


# ----------------------------------------------------------------------------- kiểm tra dữ liệu
def _rows(mask, limit=5):
    idx = [int(i) + 2 for i in mask[mask].index]          # +2: dòng tiêu đề, và đánh số từ 1
    s = ", ".join(map(str, idx[:limit]))
    return s + (f" … (+{len(idx) - limit} dòng nữa)" if len(idx) > limit else "")


def validate(df):
    """Trả về (df_sạch, []) nếu hợp lệ, hoặc (None, [danh sách lỗi]). Cả file bị từ chối nếu có 1 lỗi."""
    df = df.copy().reset_index(drop=True)
    df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
    if len(df) == 0:
        return None, ["File không có dòng dữ liệu nào"]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return None, [f"Thiếu cột bắt buộc: {', '.join(missing)}"]
    if len(df) > MAX_ROWS:
        return None, [f"File có {len(df)} dòng, vượt giới hạn {MAX_ROWS} dòng"]
    for c in RAW_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[RAW_COLUMNS].copy()

    errors = []
    for c in RAW_COLUMNS:
        if c in NUMERIC:
            num = pd.to_numeric(df[c], errors="coerce")
            bad = df[c].notna() & num.isna()
            if bad.any():
                errors.append(f"Cột {c}: giá trị không phải số (dòng {_rows(bad)})")
            lo, hi = NUMERIC[c]
            out = num.notna() & ((num < lo) | (num > hi))
            if out.any():
                errors.append(f"Cột {c}: giá trị ngoài khoảng {lo}–{hi} (dòng {_rows(out)})")
            if c in INTEGER_COLS:
                frac = num.notna() & (num % 1 != 0)
                if frac.any():
                    errors.append(f"Cột {c}: phải là số nguyên (dòng {_rows(frac)})")
            df[c] = num
        else:
            s = df[c].astype(object)
            s = s.where(s.notna(), None)
            df[c] = s.map(lambda v: (str(v).strip() or None) if v is not None else None)

    for c in REQUIRED:
        empty = df[c].isna()
        if empty.any():
            errors.append(f"Cột {c}: không được để trống (dòng {_rows(empty)})")
    dup = df["STUDENT_IDENTIFIER"].notna() & df["STUDENT_IDENTIFIER"].duplicated(keep=False)
    if dup.any():
        errors.append(f"STUDENT_IDENTIFIER bị trùng (dòng {_rows(dup)})")
    badmajor = df["STDNT_MAJOR"].notna() & ~df["STDNT_MAJOR"].isin(MAJOR_ID)
    if badmajor.any():
        errors.append(f"STDNT_MAJOR không thuộc 54 ngành của data contract (dòng {_rows(badmajor)})")
    for c, allowed in CHOICES.items():
        bad = df[c].notna() & ~df[c].isin(allowed)
        if bad.any():
            errors.append(f"Cột {c}: chỉ nhận {sorted(allowed)} (dòng {_rows(bad)})")
    for c in GRADE_COLUMNS:
        bad = df[c].notna() & ~df[c].isin(VALID_GRADES)
        if bad.any():
            errors.append(f"Cột {c}: điểm phải là A–F, NOT REP, INCOMPL hoặc Unknown (dòng {_rows(bad)})")
    if errors:
        return None, errors
    for c in INTEGER_COLS[:2]:
        df[c] = df[c].astype("int64")
    return df, []


def to_records(df):
    """DataFrame -> list dict gửi cho endpoint (NaN đổi thành None vì JSON không có NaN)."""
    sub = df[RAW_COLUMNS]
    recs = sub.astype(object).where(sub.notna(), None).to_dict("records")
    for r in recs:
        for k, v in r.items():
            if hasattr(v, "item"):
                r[k] = v.item()
    return recs


def class_code(major_name, first_term):
    """Lớp = ngành × khóa, ví dụ M14-2009 (đúng quy tắc data_contract.md mục 3)."""
    return f"M{int(MAJOR_ID[major_name]):02d}-{int(first_term) // 100}"


# ----------------------------------------------------------------------------- gọi endpoint
class ScoringError(Exception):
    pass


def _mock(records):
    out = []
    for r in records:
        gpa = r.get("HIGH_SCHL_GPA") or 3.0
        p = 0.75 - 0.18 * gpa + (0.25 if not r.get("SECOND_TERM_ATTEMPT_HRS") else 0)
        p = round(min(max(p, 0.02), 0.98), 4)
        out.append({"student_id": r["STUDENT_IDENTIFIER"], "probability": p,
                    "risk_level": "Cao" if p >= 0.23 else "Trung bình" if p >= 0.115 else "Thấp",
                    "top_factors": ["GPA THPT", "Có học HK2", "Số môn D/F HK1"], "model_version": "mock"})
    return out


def score(records, uri=None, key=None, mock=None):
    if MOCK if mock is None else mock:
        return _mock(records)
    uri, key = uri or os.environ["SCORING_URI"], key or os.environ["SCORING_KEY"]
    results = []
    for i in range(0, len(records), BATCH):
        chunk, last = records[i:i + BATCH], None
        for attempt in range(3):
            try:
                r = requests.post(uri, json={"data": chunk}, headers={"Authorization": f"Bearer {key}"}, timeout=120)
            except requests.RequestException as e:
                last = f"Không gọi được endpoint: {e}"
            else:
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"Endpoint trả HTTP {r.status_code}: {r.text[:200]}"
                elif r.status_code >= 400:
                    raise ScoringError(f"Endpoint trả HTTP {r.status_code}: {r.text[:300]} "
                                       "(404 = đã xóa deployment, 401/403 = sai key)")
                else:
                    body = r.json()
                    if isinstance(body, str):
                        body = json.loads(body)
                    if isinstance(body, dict) and "error" in body:
                        raise ScoringError(f"Model báo lỗi: {body['error']}")
                    results.extend(body)
                    break
            time.sleep(2 * (attempt + 1))
        else:
            raise ScoringError(last)
    if len(results) != len(records):
        raise ScoringError(f"Endpoint trả {len(results)} kết quả cho {len(records)} dòng")
    return results


# ----------------------------------------------------------------------------- Azure SQL
def sql_conn():
    import pymssql
    return pymssql.connect(server=os.environ["SQL_SERVER"], user=os.environ["SQL_USER"],
                           password=os.environ["SQL_PASSWORD"], database=os.getenv("SQL_DB", "dropoutdb"),
                           login_timeout=30, timeout=60)


def store_predictions(df, results, source):
    """Ghi kết quả vào bảng predictions (cột theo etl/sql/ddl.sql của TV1)."""
    rows = []
    for (_, r), res in zip(df.iterrows(), results):
        rows.append((int(r["STUDENT_IDENTIFIER"]), class_code(r["STDNT_MAJOR"], r["FIRST_TERM"]),
                     float(res["probability"]), res["risk_level"],
                     "; ".join(res.get("top_factors") or [])[:400], str(res.get("model_version", ""))[:50], source))
    conn = sql_conn()
    try:
        cur = conn.cursor()
        for i in range(0, len(rows), 200):
            part = rows[i:i + 200]
            sql = ("INSERT INTO predictions (student_id, class_code, probability, risk_level, top_factors, "
                   "model_version, source) VALUES " + ",".join(["(%s,%s,%s,%s,%s,%s,%s)"] * len(part)))
            cur.execute(sql, tuple(v for row in part for v in row))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return len(rows)


def score_and_store(df, source):
    results = score(to_records(df))
    n = store_predictions(df, results, source)
    return {"rows": n, "high": sum(1 for x in results if x["risk_level"] == "Cao"), "results": results}


# ----------------------------------------------------------------------------- dòng lệnh để thử
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("path"); c.add_argument("--score", action="store_true")
    sub.add_parser("sqlcheck")
    a = ap.parse_args()
    if a.cmd == "check":
        d, errs = validate(pd.read_csv(a.path, encoding="utf-8-sig"))
        if errs:
            print("TỪ CHỐI:"); [print(" -", e) for e in errs]
        else:
            print(f"HỢP LỆ: {len(d)} dòng")
            if a.score:
                for x in score(to_records(d.head(5))):
                    print(json.dumps(x, ensure_ascii=False))
    else:
        conn = sql_conn(); cur = conn.cursor(); cur.execute("SELECT COUNT(*) FROM predictions")
        print("Kết nối SQL OK, bảng predictions có", cur.fetchone()[0], "dòng"); conn.close()
