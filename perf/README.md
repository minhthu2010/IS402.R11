# perf/ – T4.7 Đo latency giữa các region (TV4)

Đo độ trễ đọc/ghi Blob Storage ở 3 region và thời gian gọi Azure ML online endpoint ở 2 region,
từ 2 nơi: máy cá nhân tại TP.HCM và 1 VM trên Azure. Kết quả và kết luận chọn region: [`ket_luan.md`](ket_luan.md).

## Thiết lập đo

| Thành phần | Cấu hình |
|---|---|
| Storage (container `latency-test`) | East Asia (storage của TV1), Japan East (`tv4latencysa02`), Indonesia Central (`tv4latencysa03`) |
| Endpoint | East Asia: `dropout-ep-pa` (TV3). Japan East: bản sao `dropout-ep-tv4-r2` (đã xóa sau khi đo). Cùng `dropout-model:2`, `dropout-env:1`, `Standard_DS2_v2` × 1 |
| Nơi đo | `hcmc`: laptop Windows, mạng gia đình TP.HCM. `vm-eastasia`: VM Ubuntu B2ats_v2 ở East Asia (cùng region với workspace AML và data lake) |
| Phép đo storage | upload / download file ngẫu nhiên 1 KB, 1 MB, 10 MB, 50 MB; `head` = đọc metadata blob 1 KB (gần với RTT mạng) |
| Phép đo endpoint | POST 1 bản ghi (`sample_request.json`, dạng feature, không có mã sinh viên) |
| Lặp | 30 lần mỗi phép, bỏ 2–3 lần warm-up, đảo thứ tự region mỗi vòng, giữ kết nối (keep-alive) |
| Thống kê | p50, p95 (ms); tốc độ MB/s = kích thước / p50 |

Region được phép dùng bị giới hạn bởi policy của Azure for Students. Indonesia Central không có quota Azure ML nên không dựng được endpoint ở đó; endpoint thứ 2 đặt ở Japan East.

## Cấu trúc

```
perf/
├── blob_latency.py          # đo storage
├── endpoint_latency.py      # đo endpoint
├── summarize.py             # gộp results/*_raw_*.csv -> summary.csv, summary.md, chart_*.png
├── requirements.txt
├── targets.example.json     # danh sách storage (không chứa key)
├── endpoints.example.json   # danh sách endpoint (không chứa key)
├── sample_request.json
├── endpoint_region2/        # endpoint.yml + deployment.yml để dựng lại endpoint ở region 2
├── results/                 # dữ liệu đo thô, bảng tổng hợp, biểu đồ, ảnh quota
└── ket_luan.md
```

## Chạy lại

```bash
pip install -r requirements.txt
cp targets.example.json targets.json         # sửa tên storage
export CONN_EASTASIA='...' CONN_JAPANEAST='...' CONN_INDONESIA='...'   # PowerShell: $env:CONN_EASTASIA='...'
python blob_latency.py --client hcmc --reps 30

cp endpoints.example.json endpoints.json     # điền URL scoring
export KEY_EP1='...' KEY_EP2='...'
python endpoint_latency.py --client hcmc --reps 30

python summarize.py --in results
```

Dựng endpoint region 2 (Azure CLI + extension `ml`), xem chú thích trong `endpoint_region2/deployment.yml`:

```bash
az group create -n rg-latency-r2 -l japaneast --tags module=latency
az ml workspace create -n aml-latency-r2 -g rg-latency-r2 -l japaneast
az ml online-endpoint create -f endpoint.yml -g rg-latency-r2 -w aml-latency-r2
az ml online-deployment create -f deployment.yml -g rg-latency-r2 -w aml-latency-r2 --all-traffic
# đo xong:
az group delete -n rg-latency-r2 --yes
```

**Không commit** connection string, key, `targets.json`/`endpoints.json` đã điền, thư mục `testfiles/`.
