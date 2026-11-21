"""Dựng / test / xóa online endpoint chấm điểm bỏ học (TV3).

Chuẩn bị: có ml/config.json (tải từ Azure ML Studio) và đã `az login`.
Chạy từ thư mục gốc repo:
    python ml/deploy/deploy_endpoint.py deploy --model-version 2 --endpoint dropout-ep-<hậu tố>
    python ml/deploy/deploy_endpoint.py test   --endpoint dropout-ep-<hậu tố>
    python ml/deploy/deploy_endpoint.py info   --endpoint dropout-ep-<hậu tố>   # URL + key
    python ml/deploy/deploy_endpoint.py logs   --endpoint dropout-ep-<hậu tố>
    python ml/deploy/deploy_endpoint.py stop   --endpoint dropout-ep-<hậu tố>   # xóa deployment, ngừng tính tiền
    python ml/deploy/deploy_endpoint.py delete --endpoint dropout-ep-<hậu tố>   # xóa luôn endpoint
"""
import argparse
import json
import tempfile
from pathlib import Path

from azure.ai.ml import MLClient
from azure.ai.ml.entities import CodeConfiguration, ManagedOnlineDeployment, ManagedOnlineEndpoint, OnlineRequestSettings
from azure.identity import DefaultAzureCredential

HERE = Path(__file__).resolve().parent          # ml/deploy
ML_DIR = HERE.parent                            # ml
DEPLOYMENT = "main"


def client():
    return MLClient.from_config(DefaultAzureCredential(), path=str(ML_DIR / "config.json"))


def deploy(ml, a):
    print(f"[1/3] Tạo endpoint {a.endpoint} ...")
    ep = ml.online_endpoints.begin_create_or_update(
        ManagedOnlineEndpoint(name=a.endpoint, auth_mode="key", description="Dự đoán sinh viên bỏ học")
    ).result()
    print(f"[2/3] Tạo deployment (mất 10–15 phút, đừng tắt cửa sổ) ...")
    dep = ManagedOnlineDeployment(
        name=DEPLOYMENT, endpoint_name=a.endpoint,
        model=f"azureml:dropout-model:{a.model_version}",
        environment=f"azureml:dropout-env:{a.env_version}",
        code_configuration=CodeConfiguration(code=str(ML_DIR / "src"), scoring_script="score.py"),
        instance_type=a.instance, instance_count=1,
        request_settings=OnlineRequestSettings(request_timeout_ms=90000))
    ml.online_deployments.begin_create_or_update(dep).result()
    print("[3/3] Chuyển 100% traffic vào deployment ...")
    ep = ml.online_endpoints.get(a.endpoint)
    ep.traffic = {DEPLOYMENT: 100}
    ml.online_endpoints.begin_create_or_update(ep).result()
    info(ml, a)


def info(ml, a):
    ep = ml.online_endpoints.get(a.endpoint)
    key = ml.online_endpoints.get_keys(a.endpoint).primary_key
    print("Scoring URI :", ep.scoring_uri)
    print("Key (BÍ MẬT, không commit lên GitHub):", key)


def test(ml, a):
    reqs = json.loads((HERE / "sample_requests.json").read_text(encoding="utf-8"))
    for name, body in reqs.items():
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        out = ml.online_endpoints.invoke(endpoint_name=a.endpoint, deployment_name=DEPLOYMENT,
                                         request_file=f.name)
        print(f"--- {name} ---")
        try:
            print(json.dumps(json.loads(out), ensure_ascii=False, indent=2))
        except Exception:
            print(out)


def logs(ml, a):
    print(ml.online_deployments.get_logs(name=DEPLOYMENT, endpoint_name=a.endpoint, lines=300))


def stop(ml, a):
    ml.online_deployments.begin_delete(name=DEPLOYMENT, endpoint_name=a.endpoint).result()
    print("Đã xóa deployment (endpoint rỗng không tốn tiền). Dựng lại bằng lệnh deploy.")


def delete(ml, a):
    ml.online_endpoints.begin_delete(name=a.endpoint).result()
    print("Đã xóa endpoint.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["deploy", "test", "info", "logs", "stop", "delete"])
    ap.add_argument("--endpoint", required=True, help="3–32 ký tự, chữ thường/số/dấu gạch ngang, duy nhất trong region")
    ap.add_argument("--model-version", default="2", help="Số version của dropout-model (xem tab Models)")
    ap.add_argument("--env-version", default="1", help="Version của dropout-env")
    ap.add_argument("--instance", default="Standard_DS2_v2")
    a = ap.parse_args()
    {"deploy": deploy, "test": test, "info": info, "logs": logs, "stop": stop, "delete": delete}[a.action](client(), a)


if __name__ == "__main__":
    main()
