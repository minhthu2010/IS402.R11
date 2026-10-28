"""Gửi job train lên Azure ML compute cluster (SDK v2: azure-ai-ml).

Chuẩn bị: tải config.json của workspace (Azure ML Studio → tên workspace góc trên phải →
"Download config file") đặt vào thư mục ml/. Đăng nhập: `az login` (laptop) — trên compute instance không cần.

Ví dụ (chạy từ thư mục gốc repo):
    python ml/run_jobs.py env                                   # tạo môi trường dropout-env (1 lần)
    python ml/run_jobs.py train --models logreg                 # baseline
    python ml/run_jobs.py train --models logreg rf lgbm mlp     # 4 model
    python ml/run_jobs.py sweep --model lgbm --trials 20        # tuning model tốt nhất
    python ml/run_jobs.py register --job <tên job> --desc "baseline"   # đăng ký model để TV3 deploy
    python ml/run_jobs.py train --models lgbm --drop-term2 1    # bản dự đoán cuối học kỳ 1 (so sánh)
    python ml/run_jobs.py train --models lgbm --extra="--n-estimators 400 --num-leaves 15"   # tham số tốt nhất của sweep
Dùng bảng curated của TV1 (từ tuần 3) thay cho students.csv:
    python ml/run_jobs.py train --models logreg rf lgbm mlp --curated azureml://datastores/<datastore>/paths/curated/student_features/
"""
import argparse
from pathlib import Path

from azure.ai.ml import Input, MLClient, command
from azure.ai.ml.entities import Environment, Model
from azure.ai.ml.sweep import Choice, Uniform
from azure.identity import DefaultAzureCredential

HERE = Path(__file__).resolve().parent
ENV_NAME = "dropout-env"
COMPUTE = "cpu-cluster"


def client():
    return MLClient.from_config(DefaultAzureCredential(), path=str(HERE / "config.json"))


def create_env(ml):
    env = Environment(name=ENV_NAME, description="Môi trường train + chấm điểm model bỏ học",
                      image="mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest",
                      conda_file=str(HERE / "deploy" / "conda.yml"))
    env = ml.environments.create_or_update(env)
    print(f"Môi trường {env.name}:{env.version} đang được build (xem tab Environments, ~10 phút lần đầu)")


def bench(ml, a):
    """T2.7: cùng 1 lệnh train chạy trên cluster, dữ liệu = 1 block mô phỏng (đã đăng ký data asset)."""
    job = command(
        code=str(HERE / "src"),
        command=("python train.py --data ${{inputs.data}} --major-faculty ${{inputs.mf}} "
                 f"--model {a.model} --benchmark-synthetic 1"),
        inputs={"data": Input(type="uri_file", path=a.data),
                "mf": Input(type="uri_file", path="azureml:major-faculty:1")},
        environment=f"{ENV_NAME}@latest", compute=COMPUTE,
        experiment_name="dropout-benchmark", display_name=f"bench-{a.model}")
    job = ml.jobs.create_or_update(job)
    print(f"benchmark → {job.studio_url}")


def data_inputs(a):
    """Trả về (inputs, phần lệnh) cho dữ liệu: students.csv thật hoặc bảng curated của TV1."""
    if a.curated:
        return {"data": Input(type="uri_folder", path=a.curated)}, "--data ${{inputs.data}}"
    return ({"data": Input(type="uri_file", path=f"azureml:students-real:{a.data_version}"),
             "mf": Input(type="uri_file", path=f"azureml:major-faculty:{a.data_version}")},
            "--data ${{inputs.data}} --major-faculty ${{inputs.mf}}")


def train(ml, a):
    inputs, data_cmd = data_inputs(a)
    for m in a.models:
        job = command(
            code=str(HERE / "src"),
            command=f"python train.py {data_cmd} --model {m} --drop-term2 {a.drop_term2} {a.extra}",
            inputs=inputs, environment=f"{ENV_NAME}@latest", compute=COMPUTE,
            experiment_name="dropout-models",
            display_name=f"{m}{'-t1only' if a.drop_term2 else ''}",
            tags={"owner": "TV2", "model": m},
        )
        job = ml.jobs.create_or_update(job)
        print(f"{m:7s} → {job.studio_url}")


SPACES = {   # vùng tìm tham số cho sweep
    "lgbm": ("--n-estimators ${{inputs.n_estimators}} --learning-rate ${{inputs.learning_rate}} "
             "--num-leaves ${{inputs.num_leaves}} --min-samples-leaf ${{inputs.min_samples_leaf}}",
             {"n_estimators": 300, "learning_rate": 0.05, "num_leaves": 31, "min_samples_leaf": 20},
             dict(n_estimators=Choice([100, 200, 400, 600]), learning_rate=Uniform(min_value=0.01, max_value=0.2),
                  num_leaves=Choice([7, 15, 31, 63]), min_samples_leaf=Choice([10, 20, 40, 80]))),
    "rf": ("--n-estimators ${{inputs.n_estimators}} --max-depth ${{inputs.max_depth}} "
           "--min-samples-leaf ${{inputs.min_samples_leaf}}",
           {"n_estimators": 300, "max_depth": 0, "min_samples_leaf": 20},
           dict(n_estimators=Choice([200, 400, 800]), max_depth=Choice([0, 6, 10, 16]),
                min_samples_leaf=Choice([1, 5, 10, 20, 40]))),
}


def sweep(ml, a):
    inputs, data_cmd = data_inputs(a)
    param_cmd, defaults, space = SPACES[a.model]
    base = command(
        code=str(HERE / "src"),
        command=f"python train.py {data_cmd} --model {a.model} {param_cmd}",
        inputs={**inputs, **defaults}, environment=f"{ENV_NAME}@latest", compute=COMPUTE,
    )
    job = base(**space).sweep(compute=COMPUTE, sampling_algorithm="random",
                              primary_metric="val_auc", goal="Maximize")
    job.set_limits(max_total_trials=a.trials, max_concurrent_trials=1, timeout=7200)
    job.experiment_name = "dropout-sweep"
    job.display_name = f"sweep-{a.model}"
    job = ml.jobs.create_or_update(job)
    print(f"sweep {a.model} → {job.studio_url}")


def register(ml, a):
    """Đăng ký thư mục outputs/model của 1 job train thành model dropout-model."""
    model = Model(name="dropout-model", type="custom_model", description=a.desc,
                  path=f"azureml://jobs/{a.job}/outputs/artifacts/paths/outputs/model/",
                  tags={"owner": "TV2", "job": a.job})
    model = ml.models.create_or_update(model)
    print(f"Đã đăng ký {model.name}:{model.version} từ job {a.job}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("env")
    for name in ("train", "sweep"):
        p = sub.add_parser(name)
        p.add_argument("--curated", default=None, help="đường dẫn azureml:// tới thư mục curated/student_features")
        p.add_argument("--data-version", default="1")
    t = sub.choices["train"]
    t.add_argument("--models", nargs="+", default=["logreg"])
    t.add_argument("--drop-term2", type=int, default=0)
    t.add_argument("--extra", default="", help='tham số thêm cho train.py, viết có dấu =, vd --extra="--num-leaves 15"')
    s = sub.choices["sweep"]
    s.add_argument("--model", default="lgbm", choices=list(SPACES))
    s.add_argument("--trials", type=int, default=20)
    b = sub.add_parser("bench")
    b.add_argument("--data", default="azureml:students-block1:1", help="data asset 1 block mô phỏng")
    b.add_argument("--model", default="lgbm")
    r = sub.add_parser("register")
    r.add_argument("--job", required=True, help="Name của job train (trang job → Overview → Name)")
    r.add_argument("--desc", default="")
    a = ap.parse_args()

    ml = client()
    {"env": lambda: create_env(ml), "train": lambda: train(ml, a), "sweep": lambda: sweep(ml, a),
     "register": lambda: register(ml, a), "bench": lambda: bench(ml, a)}[a.cmd]()


if __name__ == "__main__":
    main()
