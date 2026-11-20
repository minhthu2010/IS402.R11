"""Azure Function (TV3): phát hiện file CSV mới ở raw/uploads/ -> kiểm tra -> chấm điểm -> ghi SQL.

Hai cách kích hoạt, dùng chung hàm process_blob:
  1) on_upload : blob trigger kiểu Event Grid (đường chính, phản ứng trong vài giây)
  2) process   : HTTP POST /api/process?name=uploads/<file>.csv  (chạy lại thủ công / web gọi ngay sau upload)
Chống xử lý trùng: lấy "lease" trên blob, bên nào đến sau sẽ bỏ qua.
Kết quả: file ok -> raw/processed_uploads/ ; file lỗi -> raw/rejected/ (kèm <tên>.reason.txt) ;
         lỗi hệ thống (endpoint/SQL) -> giữ nguyên ở raw/uploads/ để chạy lại bằng HTTP.
"""
import io
import json
import logging
import os

import azure.functions as func
import pandas as pd
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

import dropout_common as dc

app = func.FunctionApp()
CONTAINER = "raw"


def _container():
    return BlobServiceClient.from_connection_string(os.environ["LAKE_CONN"]).get_container_client(CONTAINER)


def process_blob(blob_name: str) -> dict:
    """blob_name tính từ gốc container raw, ví dụ 'uploads/20261115-101500_sv.csv'."""
    cont = _container()
    src = cont.get_blob_client(blob_name)
    base = blob_name.split("/")[-1]
    try:
        lease = src.acquire_lease(lease_duration=60)
    except ResourceNotFoundError:
        return {"status": "skip", "reason": "blob không còn ở uploads/ (đã xử lý)"}
    except HttpResponseError:
        return {"status": "skip", "reason": "blob đang được xử lý bởi lượt khác"}

    def reject(reasons):
        text = "\n".join(reasons)
        cont.upload_blob(f"rejected/{base}", data, overwrite=True)
        cont.upload_blob(f"rejected/{base}.reason.txt", text.encode("utf-8"), overwrite=True)
        src.delete_blob(lease=lease)
        logging.warning("TỪ CHỐI %s: %s", base, text)
        return {"status": "rejected", "reasons": reasons}

    try:
        data = src.download_blob(lease=lease).readall()
        try:
            df = pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")
        except Exception as e:                                   # file rỗng, không phải CSV...
            return reject([f"Không đọc được file CSV: {type(e).__name__}: {e}"])
        clean, errors = dc.validate(df)
        if errors:
            return reject(errors)
        summary = dc.score_and_store(clean, source="upload")     # gọi endpoint + INSERT predictions
        cont.upload_blob(f"processed_uploads/{base}", data, overwrite=True)
        src.delete_blob(lease=lease)
        logging.info("ĐÃ XỬ LÝ %s: %s dòng, %s rủi ro Cao", base, summary["rows"], summary["high"])
        return {"status": "done", "rows": summary["rows"], "high": summary["high"]}
    except Exception as e:
        try:
            lease.release()                                       # giữ file để chạy lại
        except Exception:
            pass
        logging.exception("LỖI HỆ THỐNG khi xử lý %s", base)
        return {"status": "error", "reason": f"{type(e).__name__}: {e}"}


@app.blob_trigger(arg_name="myblob", path="raw/uploads/{name}", connection="LAKE_CONN", source="EventGrid")
def on_upload(myblob: func.InputStream):
    name = myblob.name.split("/", 1)[1]                          # 'raw/uploads/x.csv' -> 'uploads/x.csv'
    logging.info("Phát hiện file mới: %s (%s byte)", name, myblob.length)
    logging.info("Kết quả: %s", process_blob(name))


@app.route(route="process", auth_level=func.AuthLevel.FUNCTION, methods=["GET", "POST"])
def process(req: func.HttpRequest) -> func.HttpResponse:
    name = req.params.get("name", "")
    if not name.startswith("uploads/") or ".." in name:
        return func.HttpResponse(json.dumps({"error": "name phải dạng uploads/<tên file>.csv"}), status_code=400,
                                 mimetype="application/json")
    return func.HttpResponse(json.dumps(process_blob(name), ensure_ascii=False), mimetype="application/json")
