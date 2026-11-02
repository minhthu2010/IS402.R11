# Kết quả so sánh model

| model | cv_auc | cv_recall | cv_precision | cv_f1 | cv_accuracy | cv_auc_std | test_auc | train_seconds |
|---|---|---|---|---|---|---|---|---|
| LightGBM (100 cây, 4 lá) | 0.7195 | 0.5138 | 0.4521 | 0.481 | 0.764 | 0.0341 | 0.753 | 0.0724 |
| LightGBM (300 cây, 15 lá) | 0.7076 | 0.5089 | 0.4335 | 0.4682 | 0.754 | 0.0199 | 0.7892 | 0.2578 |
| Random Forest | 0.707 | 0.5041 | 0.4235 | 0.4603 | 0.7484 | 0.0342 | 0.77 | 0.8406 |
| Logistic Regression | 0.706 | 0.5122 | 0.4245 | 0.4643 | 0.7484 | 0.019 | 0.776 | 0.042 |
| MLP | 0.676 | 0.5024 | 0.3701 | 0.4262 | 0.7121 | 0.0374 | 0.7594 | 0.283 |
| Đoán tất cả ở lại | 0.5 | 0.0 | 0.0 | 0.0 | 0.7882 | nan | nan | nan |

Model chọn: **LightGBM** (run `purple_pin_hhkg5dhtnb`), ngưỡng 0.23

```
              precision    recall  f1-score   support

       Ở lại      0.895     0.826     0.859       402
      Bỏ học      0.496     0.639     0.559       108

    accuracy                          0.786       510
   macro avg      0.696     0.732     0.709       510
weighted avg      0.810     0.786     0.795       510

```