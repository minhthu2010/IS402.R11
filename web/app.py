"""Web dự đoán sinh viên bỏ học (TV3): 4 trang Trang chủ / Dự đoán 1 SV / Upload CSV / Lịch sử."""
import datetime as dt
import json
import os
import re
from pathlib import Path

import pandas as pd
import requests
from fastapi import BackgroundTasks, FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import dropout_common as dc

HERE = Path(__file__).resolve().parent
app = FastAPI(title="Dự đoán sinh viên bỏ học")
templates = Jinja2Templates(directory=str(HERE / "templates"))
SAMPLES = json.loads((HERE / "samples.json").read_text(encoding="utf-8"))
LAKE_CONTAINER = "raw"
MAX_UPLOAD = 5 * 1024 * 1024


# ---------------------------------------------------------------- cấu hình form
def F(name, label, kind="number", options=None, step="any", hint=""):
    return {"name": name, "label": label, "kind": kind, "options": options or [], "step": step, "hint": hint}


YN, GR = ["Y", "N"], ["A", "B", "C", "D", "F", "NOT REP", "INCOMPL", "Unknown"]
SECTIONS = [
    ("Thông tin cá nhân", [
        F("STUDENT_IDENTIFIER", "Mã sinh viên *", step="1"), F("STDNT_AGE", "Tuổi", step="1"),
        F("STDNT_GENDER", "Giới tính", "select", ["F", "M"]),
        F("STDNT_BACKGROUND", "Nhóm xuất thân", "select", [f"BGD {i}" for i in range(1, 9)]),
        F("IN_STATE_FLAG", "Trong bang", "select", YN), F("INTERNATIONAL_STS", "Sinh viên quốc tế", "select", YN),
        F("HOUSING_STS", "Nơi ở", "select", ["On Campus", "Off Campus"]),
        F("DISTANCE_FROM_HOME", "Khoảng cách tới nhà")]),
    ("Đầu vào & gia đình", [
        F("HIGH_SCHL_GPA", "GPA THPT (0–4)", step="0.01"), F("STDNT_TEST_ENTRANCE_COMB", "Điểm thi đầu vào (kết hợp)"),
        F("FATHER_HI_EDU_CD", "Học vấn bố (mã)", step="1"), F("MOTHER_HI_EDU_CD", "Học vấn mẹ (mã)", step="1")]),
    ("Chương trình học", [
        F("STDNT_MAJOR", "Ngành *", "select", sorted(dc.MAJOR_ID)), F("STDNT_MINOR", "Ngành phụ (N = không có)", "text")]),
    ("Học kỳ 1", [
        F("FIRST_TERM", "Học kỳ nhập học *", "select", ["200508", "200608", "200708", "200808", "200908", "201008"]),
        F("FIRST_TERM_ATTEMPT_HRS", "Tín chỉ đăng ký", step="1"), F("FIRST_TERM_EARNED_HRS", "Tín chỉ đạt", step="1")]
        + [F(f"CORE_COURSE_GRADE_{i}_F", f"Điểm môn {i}", "select", GR) for i in range(1, 7)]),
    ("Học kỳ 2 (để trống nếu không học)", [
        F("SECOND_TERM", "Học kỳ 2", "select", ["200602", "200702", "200802", "200902", "201002", "201102"]),
        F("SECOND_TERM_ATTEMPT_HRS", "Tín chỉ đăng ký", step="1"), F("SECOND_TERM_EARNED_HRS", "Tín chỉ đạt", step="1")]
        + [F(f"CORE_COURSE_GRADE_{i}_S", f"Điểm môn {i}", "select", GR) for i in range(1, 7)]),
    ("Tài chính", [
        F("GROSS_FIN_NEED", "Nhu cầu tài chính"), F("COST_OF_ATTEND", "Chi phí học tập"),
        F("EST_FAM_CONTRIBUTION", "Gia đình đóng góp"), F("UNMET_NEED", "Phần thiếu hụt")]),
]


def query(sql):
    conn = dc.sql_conn()
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(sql)
        return cur.fetchall()
    finally:
        conn.close()


def vn_time(t):
    return (t + dt.timedelta(hours=7)).strftime("%d/%m/%Y %H:%M:%S") if t else ""


def render(request, name, **ctx):
    return templates.TemplateResponse(request, name, {"mock": dc.MOCK, **ctx})


# ---------------------------------------------------------------- các trang
@app.get("/healthz")
def healthz():
    return {"status": "ok", "mock": dc.MOCK}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    stats, note = {}, []
    try:
        r = query("SELECT COUNT(*) AS total, SUM(CASE WHEN risk_level='Cao' THEN 1 ELSE 0 END) AS high, "
                  "MAX(created_at) AS last FROM predictions")[0]
        stats.update(total=r["total"], high=r["high"] or 0, last=vn_time(r["last"]))
    except Exception as e:
        note.append(f"Chưa đọc được bảng predictions: {type(e).__name__}")
    try:
        r = query("SELECT COUNT(*) AS n, AVG(CAST(dropout AS FLOAT)) AS rate FROM fact_enrollment")[0]
        stats.update(students=r["n"], rate=round((r["rate"] or 0) * 100, 1))
    except Exception as e:
        note.append(f"Chưa đọc được fact_enrollment: {type(e).__name__}")
    return render(request, "home.html", stats=stats, note=note)


@app.get("/predict", response_class=HTMLResponse)
def predict_form(request: Request):
    return render(request, "predict.html", sections=SECTIONS, values={}, samples=SAMPLES)


@app.post("/predict", response_class=HTMLResponse)
async def predict_submit(request: Request):
    form = await request.form()
    rec = {c: ((form.get(c) or "").strip() or None) for c in dc.RAW_COLUMNS}
    ctx = dict(sections=SECTIONS, values=rec, samples=SAMPLES)
    df, errors = dc.validate(pd.DataFrame([rec]))
    if errors:
        return render(request, "predict.html", errors=errors, **ctx)
    try:
        results = dc.score(dc.to_records(df))
    except dc.ScoringError as e:
        return render(request, "predict.html", errors=[str(e)], **ctx)
    ctx.update(result=results[0], major=rec["STDNT_MAJOR"])
    try:
        dc.store_predictions(df, results, "web")
        ctx["saved"] = True
    except Exception as e:
        ctx["warning"] = f"Đã dự đoán nhưng chưa lưu được vào SQL ({type(e).__name__}: {e})"
    return render(request, "predict.html", **ctx)


def _lake():
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(os.environ["LAKE_CONN"]).get_container_client(LAKE_CONTAINER)


def _call_function(url, name):
    try:
        requests.post(url, params={"name": name}, timeout=200)
    except Exception:
        pass                                    # Event Grid vẫn là đường chính; đây chỉ để demo chắc chắn


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):
    return render(request, "upload.html")


@app.post("/upload", response_class=HTMLResponse)
async def upload_submit(request: Request, background: BackgroundTasks, file: UploadFile = File(...)):
    data, error = await file.read(), None
    if not (file.filename or "").lower().endswith(".csv"):
        error = "Chỉ nhận file .csv"
    elif not data:
        error = "File rỗng"
    elif len(data) > MAX_UPLOAD:
        error = f"File lớn hơn {MAX_UPLOAD // 2**20}MB"
    if error:
        return render(request, "upload.html", error=error)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename)
    base = f"{dt.datetime.utcnow():%Y%m%d-%H%M%S}_{safe}"
    try:
        _lake().upload_blob(f"uploads/{base}", data, overwrite=True)
    except Exception as e:
        return render(request, "upload.html", error=f"Không upload được lên Data Lake: {type(e).__name__}: {e}")
    if os.getenv("AUTO_TRIGGER_URL"):
        background.add_task(_call_function, os.environ["AUTO_TRIGGER_URL"], f"uploads/{base}")
    return render(request, "upload.html", uploaded=base)


@app.get("/upload/status")
def upload_status(name: str):
    c = _lake()
    for state, folder in (("done", "processed_uploads"), ("rejected", "rejected"), ("pending", "uploads")):
        if c.get_blob_client(f"{folder}/{name}").exists():
            reason = ""
            if state == "rejected" and c.get_blob_client(f"rejected/{name}.reason.txt").exists():
                reason = c.get_blob_client(f"rejected/{name}.reason.txt").download_blob().readall().decode("utf-8")
            return JSONResponse({"state": state, "reason": reason})
    return JSONResponse({"state": "unknown", "reason": ""})


@app.get("/history", response_class=HTMLResponse)
def history(request: Request):
    rows, error = [], None
    try:
        rows = query("SELECT TOP 200 id, student_id, class_code, probability, risk_level, top_factors, "
                     "model_version, source, created_at FROM predictions ORDER BY created_at DESC")
        for r in rows:
            r["created_at"] = vn_time(r["created_at"])
    except Exception as e:
        error = f"Không đọc được lịch sử: {type(e).__name__}: {e}"
    return render(request, "history.html", rows=rows, error=error)
