# Data contract – Dự đoán sinh viên bỏ học

| | |
|---|---|
| Người phụ trách | TV1 – Data Platform |
| Phiên bản | 1.1 (28/10) – cập nhật mục 8 theo feature_spec.md v1.0 của TV2 |
| Nguồn | Kaggle "Students' Early Attrition Analysis" (vijaysimhan/student-admissions-data-for-a-university), file `UnivData1.xlsx`, giấy phép CDLA-Sharing 1.0 |

Mọi thay đổi tên cột, kiểu dữ liệu hay quy tắc trong file này phải báo cả nhóm và tăng số phiên bản.

## 1. Tổng quan dữ liệu thật (đo bằng profiling)

| Chỉ số | Giá trị |
|---|---|
| Số sinh viên | 3.400 (mỗi dòng 1 sinh viên năm nhất, mã không trùng) |
| Số cột | 56 (sheet "University information"); sheet "Variable Dictionary" mô tả từng cột |
| Khóa nhập học | 6 khóa: Fall 2005 → Fall 2010 (`FIRST_TERM` = 200508 … 201008) |
| Ngành | 54 ngành (`STDNT_MAJOR`), 84 môn cốt lõi thuộc 31 bộ môn |
| Tỉ lệ bỏ học | **21,3%** (723 / 3.400) |
| Dung lượng | 857 KB (xlsx), 0,86 MB khi xuất CSV |

Cột thiếu nhiều: `STDNT_TEST_ENTRANCE1` 67,5%, `STDNT_TEST_ENTRANCE2` 26,7%, `STDNT_TEST_ENTRANCE_COMB` 15,2%, `FATHER/MOTHER_HI_EDU_CD` 13–14%, `SECOND_TERM_*_HRS` 6,1%. Các cột môn thứ 4–6 trống khi sinh viên học ít môn (bình thường, không phải lỗi).

## 2. Nhãn bỏ học

| Cột | Định nghĩa |
|---|---|
| `RETURNED_2ND_YR` | 1 = quay lại học kỳ đầu năm hai; 0 = không quay lại |
| `dropout` | `1 − RETURNED_2ND_YR` |

**Mốc dự đoán:** cuối năm nhất (sau học kỳ 2). Mọi cột của học kỳ 1 và 2 đều có trước nhãn nên được dùng làm feature.
Lưu ý cho TV2: 206 sinh viên không có số tín chỉ học kỳ 2 và 86,9% trong số đó bỏ học. Feature `has_second_term` rất mạnh nhưng hợp lệ ở mốc cuối năm nhất. Nếu muốn dự đoán sớm hơn (cuối học kỳ 1) thì phải bỏ toàn bộ cột học kỳ 2.

## 3. Ánh xạ khoa / khóa / lớp

| Khái niệm | Lấy từ | Quy tắc |
|---|---|---|
| Khoa (`faculty_id`) | `STDNT_MAJOR` | 54 ngành gom vào 8 khoa theo file `data/reference/major_faculty.csv` |
| Khóa (`cohort_year`) | `FIRST_TERM` | `FIRST_TERM / 100`, vd 200908 → 2009 |
| Lớp (`class_code`) | ngành + khóa | `M` + `major_id` 2 chữ số + `-` + khóa, vd `M14-2009` (Nursing khóa 2009); 258 lớp trong dữ liệu thật |
| Học kỳ (`term_code`) | `FIRST_TERM`, `SECOND_TERM` | đuôi `08` = Fall, `02` = Spring |

| faculty_id | Khoa | Số SV thật | Tỉ lệ bỏ học |
|---|---|---:|---:|
| 1 | Khoa học Tự nhiên & Kỹ thuật | 545 | 22,2% |
| 2 | Công nghệ Thông tin | 161 | 23,6% |
| 3 | Khoa học Sức khỏe | 490 | 23,3% |
| 4 | Kinh doanh | 427 | 22,0% |
| 5 | Sư phạm | 435 | 16,8% |
| 6 | Nghệ thuật | 322 | 14,9% |
| 7 | Khoa học Xã hội & Nhân văn | 510 | 23,9% |
| 8 | Chương trình chung (chưa chọn ngành) | 510 | 22,2% |

Dùng cho: `dim_faculty`, `dim_major`, `dim_class`, Filter 1 trên Power BI, RLS (Trưởng khoa lọc theo `faculty_id`, Cố vấn lọc theo `class_code`).

## 4. Cột nguồn (sau khi đổi `STUDENT IDENTIFIER` → `STUDENT_IDENTIFIER`)

| Nhóm | Cột | Kiểu | Ghi chú |
|---|---|---|---|
| Định danh | STUDENT_IDENTIFIER | INT | Khóa chính |
| Nhân khẩu | STDNT_AGE | INT | 16–26, phần lớn 18 |
| | STDNT_GENDER | CHAR(1) | F / M |
| | STDNT_BACKGROUND | VARCHAR | BGD 1 … BGD 8 (mã hóa, không rõ nghĩa) |
| | IN_STATE_FLAG, INTERNATIONAL_STS | CHAR(1) | Y / N |
| | HOUSING_STS | VARCHAR | On Campus / Off Campus |
| | DISTANCE_FROM_HOME | FLOAT | Khoảng cách từ nhà tới trường |
| Học vấn đầu vào | HIGH_SCHL_GPA | FLOAT | 0–4 |
| | HIGH_SCHL_NAME | VARCHAR | 439 trường (mã hóa) |
| | STDNT_TEST_ENTRANCE1 / 2 / _COMB | FLOAT | Điểm thi đầu vào (thang ~ACT / ~SAT / kết hợp) |
| Gia đình | FATHER_HI_EDU_CD / _DESC, MOTHER_HI_EDU_CD / _DESC | FLOAT / VARCHAR | Trình độ học vấn bố / mẹ |
| Chương trình | STDNT_MAJOR, STDNT_MINOR | VARCHAR | MINOR = `N` nghĩa là không có ngành phụ |
| | DEGREE_GROUP_CD / _DESC | VARCHAR | Bachelors / Associate / Career Associate |
| Học kỳ 1 | FIRST_TERM | INT | vd 200908 |
| | CORE_COURSE_NAME_1_F … _6_F, CORE_COURSE_GRADE_1_F … _6_F | VARCHAR | Mã môn (vd `MATH 1111`) và điểm chữ |
| | FIRST_TERM_ATTEMPT_HRS / _EARNED_HRS | INT | Tín chỉ đăng ký / đạt |
| Học kỳ 2 | SECOND_TERM, CORE_COURSE_*_S, SECOND_TERM_ATTEMPT_HRS / _EARNED_HRS | | Như học kỳ 1 |
| Tài chính | GROSS_FIN_NEED, COST_OF_ATTEND, EST_FAM_CONTRIBUTION, UNMET_NEED | FLOAT | UNMET_NEED có thể âm |
| Nhãn | RETURNED_2ND_YR | INT | Xem mục 2 |
| Thêm bởi TV1 | is_synthetic | INT | 0 = thật, 1 = mô phỏng |
| | block | INT | 0 = thật, 1…N = số block mô phỏng |

Điểm chữ: `A, B, C, D, F` (quy đổi A=4, B=3, C=2, D=1, F=0; đạt = A–C). `NOT REP`, `INCOMPL`, `Unknown` không tính vào GPA.

## 5. Dữ liệu mô phỏng (>4GB)

Sinh bằng `data/generate_data.py` (seed 42, mặc định 80 block × 220.000 dòng ≈ 17,6 triệu sinh viên, ≈ 4,3GB CSV).

| Thuộc tính | Quy tắc |
|---|---|
| Cách sinh | Mỗi dòng lấy ngẫu nhiên có hoàn lại một sinh viên thật |
| Mã sinh viên | Từ 100.000.000 trở đi (dữ liệu thật nằm trong khoảng 7–8 triệu) |
| Nhiễu | GPA THPT + N(0; 0,1); điểm đầu vào ±30 (thang SAT) / ±1 (thang ACT); khoảng cách × lognormal(0; 0,2); 4 cột tài chính × cùng hệ số lognormal(0; 0,1); tín chỉ ±1 (đạt ≤ đăng ký); 10% điểm môn đổi lên/xuống 1 bậc |
| Giữ nguyên | Ngành, khóa, môn học, nhãn |
| Đánh dấu | `is_synthetic = 1`, `block = k` |

Đã kiểm tra trên 2 block: tỉ lệ bỏ học mô phỏng 21,5% (thật 21,3%), phân phối điểm môn lệch dưới 1 điểm phần trăm so với dữ liệu thật.

**Quy tắc bắt buộc:** dữ liệu mô phỏng chỉ dùng cho lưu trữ, ETL, benchmark và minh họa quy mô. **Model chỉ được train và đánh giá trên dữ liệu thật (`is_synthetic = 0`).**

## 6. Bố cục Data Lake

```
raw/
  original/UnivData1.xlsx                    ← file gốc tải từ Kaggle
  real/students/students.csv                 ← dữ liệu thật (CSV)
  real/dictionary/variable_dictionary.csv
  synthetic/students/students_bNNN.csv       ← dữ liệu mô phỏng
  reference/major_faculty/major_faculty.csv  ← ánh xạ ngành → khoa
  uploads/                                   ← file CSV người dùng upload từ web (TV3)
  rejected/                                  ← file upload sai định dạng (Function chuyển vào)
processed/                                   ← ADF Copy CSV → Parquet, giữ nguyên cấu trúc thư mục
  real/students/  synthetic/students/  reference/major_faculty/
curated/                                     ← Synapse CETAS, ADF nạp sang Azure SQL
  dim_faculty/ dim_major/ dim_term/ dim_class/ dim_student/
  fact_enrollment/ fact_course_grade/ student_features/ agg_cohort_major/
```

## 7. Bảng đích trên Azure SQL

Xem `etl/sql/ddl.sql`. Các bảng chi tiết chỉ chứa dữ liệu thật + block 1 (khoảng 223 nghìn sinh viên) để vừa gói Azure SQL free. Bảng `agg_cohort_major` tổng hợp trên toàn bộ dữ liệu.

| Bảng | Hạt (1 dòng =) | Ai dùng |
|---|---|---|
| dim_faculty, dim_major, dim_term, dim_class, dim_student | 1 khoa / ngành / học kỳ / lớp / sinh viên | Power BI |
| fact_enrollment | 1 sinh viên năm nhất, có `dropout` | Power BI, TV2 |
| fact_course_grade | 1 môn của 1 sinh viên trong 1 học kỳ (22.564 dòng với dữ liệu thật) | Power BI (Filter 2) |
| student_features | 1 sinh viên, các feature tại mốc cuối năm nhất | TV2 train model |
| agg_cohort_major | 1 khóa × 1 ngành × thật/mô phỏng | Power BI (trang Tổng quan) |
| predictions | 1 lần dự đoán | Function/Web ghi (TV3), Power BI đọc |
| model_metrics | 1 metric của 1 run | TV2 ghi, Power BI đọc |
| rls_user_scope | 1 người dùng × 1 phạm vi | Power BI RLS (TV4) |
| etl_log | 1 lần chạy pipeline | TV1 theo dõi |

## 8. Feature (đã chốt theo feature_spec.md v1.0 của TV2)

Định nghĩa chi tiết và các quyết định (feature nào model không dùng, cách xử lý giá trị thiếu) nằm trong `feature_spec.md`. Bảng `student_features` trên lake và SQL chứa đủ các cột dưới đây; giá trị thiếu để NULL, không điền ở ETL.

| Feature | Công thức |
|---|---|
| age, is_female, background, in_state, international, on_campus, distance_from_home | Từ cột nhân khẩu (`is_female`, `background` giữ cho Power BI, model chính thức không dùng) |
| high_school_gpa, entrance_comb, entrance_missing, father_edu_cd, mother_edu_cd | Học vấn đầu vào, gia đình; `entrance_missing` = 1 khi `entrance_comb` NULL |
| faculty_id, major_id, is_undeclared, has_minor | Chương trình học (model dùng `faculty_id`, không dùng `major_id`) |
| first_term_attempt_hrs, first_term_earned_hrs, earned_ratio_t1 | Tín chỉ học kỳ 1, tỉ lệ đạt (số thực, NULL khi đăng ký 0 tín chỉ) |
| gpa_t1, n_courses_t1, n_df_t1 | GPA và số môn **có điểm A–F** học kỳ 1, số môn D/F (`NOT REP`, `INCOMPL`, `Unknown` không tính) |
| has_second_term, second_term_*_hrs, earned_ratio_t2, gpa_t2, n_df_t2, gpa_change | Tương tự cho học kỳ 2; `gpa_change` = `gpa_t2 − gpa_t1` |
| fin_data_missing, gross_fin_need, unmet_need, fam_contribution_ratio | `fin_data_missing` = 1 khi `COST_OF_ATTEND` = 0 hoặc NULL (không có hồ sơ tài chính); khi đó `gross_fin_need`, `unmet_need` để NULL |

## 9. Xác nhận

| Thành viên | Đồng ý | Ngày | Ghi chú |
|---|---|---|---|
| TV2 – Analytics & Model | ☐ | | |
| TV3 – Serving & App | ☐ | | |
| TV4 – Insight & Quản trị | ☐ | | |
