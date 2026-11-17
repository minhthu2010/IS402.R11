# T4.7 – Kết quả đo latency và kết luận chọn region

Số liệu đầy đủ: [`results/summary.md`](results/summary.md). Mọi phép đo đều 30/30 lần thành công.

## 1. Độ trễ thuần (`head`, blob 1 KB) – p50 / p95 (ms)

| Đo từ | East Asia | Indonesia Central | Japan East |
|---|---|---|---|
| HCMC | **53 / 58** | 54 / 60 | 98 / 103 |
| VM East Asia | **7 / 10** | 50 / 53 | 50 / 51 |

## 2. Tốc độ truyền file 50 MB (MB/s theo p50)

| Đo từ | Thao tác | East Asia | Indonesia Central | Japan East |
|---|---|---|---|---|
| HCMC | download | 14,4 | **16,0** | 8,3 |
| HCMC | upload | 5,4 (*) | **24,1** | 2,1 |
| VM East Asia | download | **70,9** | 32,0 | 23,4 |
| VM East Asia | upload | **42,5** | 28,5 | 16,0 |

(*) Upload 50 MB từ HCMC tới East Asia dao động lớn (p95 = 18,9 s, gấp đôi p50) và thấp hơn hẳn upload 10 MB tới cùng storage (17,7 MB/s); lần đo 50 MB chạy riêng ở thời điểm khác, nhiều khả năng do mạng gia đình lúc đó.

## 3. Gọi endpoint (1 bản ghi) – p50 / p95 (ms)

| Đo từ | East Asia | Japan East | Chênh lệch p50 |
|---|---|---|---|
| HCMC | **217 / 237** | 246 / 258 | +29 ms |
| VM East Asia | **169 / 185** | 198 / 202 | +29 ms |

Khi gọi từ cùng region (độ trễ mạng ~7–10 ms) một lần gọi vẫn mất ~169 ms, nên phần lớn thời gian (ước tính ~160 ms) là xử lý trong `score.py` (dựng feature, dự đoán, tính `top_factors`).

## 4. Kết luận

Nhóm chọn **East Asia** làm region chính cho toàn bộ hệ thống (Data Lake, SQL, Azure ML endpoint, Function, Web):

1. **Đặt các thành phần cùng region quan trọng nhất.** Trong cùng East Asia, độ trễ storage ~7 ms và tốc độ đọc ~70 MB/s; sang region khác độ trễ ~50 ms và tốc độ giảm 2–3 lần. Function/Web gọi storage và endpoint nhiều lần nên tách region sẽ cộng dồn độ trễ.
2. **Với người dùng ở TP.HCM, East Asia có độ trễ tương đương phương án tốt nhất** (~53 ms so với ~54 ms của Indonesia Central), tốt hơn nhiều Japan East (~98 ms).
3. **Indonesia Central truyền file lớn từ TP.HCM tốt nhất nhưng không có quota Azure ML** trên subscription Azure for Students, nên không đặt được endpoint và không phù hợp làm region chính.

**Japan East** có quota Azure ML (6 vCPU DSv2, 20 vCPU tổng) nên phù hợp làm region dự phòng cho endpoint, đổi lại mỗi lần gọi chậm hơn ~29 ms (p50). Vì thời gian xử lý của model chiếm phần lớn, muốn giảm thời gian phản hồi API thì tối ưu `score.py` hiệu quả hơn đổi region.

## 5. Hạn chế

- Chỉ đo từ 1 đường mạng gia đình tại TP.HCM và 1 VM (B2ats_v2), trong một khung giờ (17/11/2026).
- Upload 50 MB HCMC → East Asia dao động lớn (xem ghi chú mục 2).
- Từ VM, upload 1 MB sang Indonesia/Japan (~300 ms) chậm bất thường so với 10 MB; mới là quan sát, chưa xác định nguyên nhân.
