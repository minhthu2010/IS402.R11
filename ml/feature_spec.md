
## 1. Quyết định chung

- **Mốc dự đoán: cuối năm nhất** (sau học kỳ 2). Mọi cột học kỳ 1 và 2 đều có trước nhãn nên hợp lệ.
- **Nhãn:** `dropout = 1 − RETURNED_2ND_YR`.
- **Chỉ train và đánh giá trên dữ liệu thật** (`is_synthetic = 0`).
- **Giá trị thiếu để NULL**, không điền ở ETL. Model tự điền (trung vị / giá trị phổ biến nhất) bên trong pipeline, học từ tập train.
- **Điểm chữ:** A=4, B=3, C=2, D=1, F=0. `NOT REP`, `INCOMPL`, `Unknown`, ô trống không tính vào GPA và không tính là môn D/F.
- **Không dùng làm feature:** `STUDENT_IDENTIFIER`, `HIGH_SCHL_NAME` (439 trường, gây nhiễu), `FIRST_TERM` / khóa (model phải dùng được cho khóa sau), `major_id` (đã có `faculty_id`), `STDNT_TEST_ENTRANCE1/2` (thiếu nhiều, đã có bản kết hợp).
- **Đặc điểm nhân khẩu nhạy cảm** `background`, `is_female`: vẫn giữ trong bảng `student_features` (Power BI cần để phân tích), nhưng **model chính thức không dùng**. Đã thử: bỏ 2 cột này AUC chỉ giảm 0,013 (0,720 → 0,708 cross-validation), trên tập test gần như không đổi.

## 2. Danh sách feature

Cột "Có trong bảng TV1": ✅ = đã có trong CETAS hiện tại; ➕ = cần thêm (xem mục 3).

| Feature | Kiểu | Công thức | Cột nguồn | Có trong bảng TV1 |
|---|---|---|---|---|
| `age` | INT | giữ nguyên | `STDNT_AGE` | ✅ |
| `in_state` | BIT | Y→1, N→0 | `IN_STATE_FLAG` | ✅ |
| `international` | BIT | Y→1, N→0 | `INTERNATIONAL_STS` | ✅ |
| `on_campus` | BIT | On Campus→1, Off Campus→0 | `HOUSING_STS` | ✅ |
| `distance_from_home` | FLOAT | giữ nguyên (model lấy log(1+x) bên trong pipeline) | `DISTANCE_FROM_HOME` | ✅ |
| `high_school_gpa` | FLOAT | giữ nguyên | `HIGH_SCHL_GPA` | ✅ |
| `entrance_comb` | FLOAT | giữ nguyên | `STDNT_TEST_ENTRANCE_COMB` | ✅ |
| `entrance_missing` | BIT | 1 khi `entrance_comb` NULL | `STDNT_TEST_ENTRANCE_COMB` | ➕ |
| `father_edu_cd`, `mother_edu_cd` | INT | giữ nguyên | `FATHER_HI_EDU_CD`, `MOTHER_HI_EDU_CD` | ✅ |
| `faculty_id` | INT (phân loại) | ánh xạ `major_faculty.csv` | `STDNT_MAJOR` | ✅ |
| `is_undeclared` | BIT | 1 khi `faculty_id = 8` | `STDNT_MAJOR` | ✅ |
| `has_minor` | BIT | 1 khi `STDNT_MINOR` khác `N` và không trống | `STDNT_MINOR` | ✅ |
| `first_term_attempt_hrs`, `first_term_earned_hrs` | INT | giữ nguyên | `FIRST_TERM_*_HRS` | ✅ |
| `earned_ratio_t1` | FLOAT | earned / attempt; NULL khi attempt = 0 | `FIRST_TERM_*_HRS` | ✅ |
| `gpa_t1` | FLOAT | trung bình điểm số các môn có điểm A–F, học kỳ 1 | `CORE_COURSE_GRADE_1..6_F` | ✅ |
| `n_courses_t1` | INT | số môn có điểm A–F, học kỳ 1 | `CORE_COURSE_GRADE_1..6_F` | ✅ |
| `n_df_t1` | INT | số môn điểm D hoặc F, học kỳ 1 | `CORE_COURSE_GRADE_1..6_F` | ✅ |
| `has_second_term` | BIT | 1 khi `SECOND_TERM_ATTEMPT_HRS > 0` (NULL tính là 0) | `SECOND_TERM_ATTEMPT_HRS` | ✅ |
| `second_term_attempt_hrs`, `second_term_earned_hrs` | INT | giữ nguyên | `SECOND_TERM_*_HRS` | ✅ |
| `earned_ratio_t2` | FLOAT | như học kỳ 1 | `SECOND_TERM_*_HRS` | ✅ |
| `gpa_t2`, `n_df_t2` | FLOAT, INT | như học kỳ 1 | `CORE_COURSE_GRADE_1..6_S` | ✅ |
| `gpa_change` | FLOAT | `gpa_t2 − gpa_t1` | — | ➕ |
| `fin_data_missing` | BIT | 1 khi `COST_OF_ATTEND` = 0 hoặc NULL | `COST_OF_ATTEND` | ➕ |
| `gross_fin_need` | FLOAT | giữ nguyên; **NULL khi `fin_data_missing = 1`** | `GROSS_FIN_NEED` | ✅ (cần sửa) |
| `unmet_need` | FLOAT | giữ nguyên (có thể âm); **NULL khi `fin_data_missing = 1`** | `UNMET_NEED` | ✅ (cần sửa) |
| `fam_contribution_ratio` | FLOAT | `EST_FAM_CONTRIBUTION / COST_OF_ATTEND`; NULL khi cost = 0 | 2 cột tài chính | ✅ |
| `background`, `is_female` | VARCHAR, BIT | giữ nguyên | `STDNT_BACKGROUND`, `STDNT_GENDER` | ✅ (model không dùng) |
| `dropout` | BIT | `1 − RETURNED_2ND_YR` | `RETURNED_2ND_YR` | ✅ (nhãn) |

**Vì sao có `fin_data_missing`:** ít nhất 1/4 sinh viên có `COST_OF_ATTEND = 0`, kèm `GROSS_FIN_NEED`, `EST_FAM_CONTRIBUTION`, `UNMET_NEED` cũng bằng 0. Đó là "không có hồ sơ tài chính", không phải "học phí 0 đồng". Để nguyên số 0, model hiểu sai thành "không cần hỗ trợ tài chính".

## 3. Đề nghị TV1 sửa CETAS `student_features`

Thêm vào danh sách SELECT trong `synapse/02_cetas_curated.sql`:

```sql
CAST(CASE WHEN s.entrance_comb IS NULL THEN 1 ELSE 0 END AS BIT)                    AS entrance_missing,
g.gpa_t2 - g.gpa_t1                                                                 AS gpa_change,
CAST(CASE WHEN ISNULL(s.cost_of_attend, 0) = 0 THEN 1 ELSE 0 END AS BIT)            AS fin_data_missing,
```

và đổi 2 dòng tài chính hiện có thành:

```sql
CASE WHEN ISNULL(s.cost_of_attend, 0) = 0 THEN NULL ELSE s.gross_fin_need END       AS gross_fin_need,
CASE WHEN ISNULL(s.cost_of_attend, 0) = 0 THEN NULL ELSE s.unmet_need END           AS unmet_need,
```

Thêm 3 cột tương ứng vào bảng `student_features` trong `etl/sql/ddl.sql` (`entrance_missing BIT NULL`, `gpa_change FLOAT NULL`, `fin_data_missing BIT NULL`).

Nếu chưa kịp sửa, code train vẫn chạy được: `features.py` tự tính 3 cột này khi bảng curated thiếu. Nhưng nên sửa để Power BI (TV4) và model nhìn cùng một số liệu.

## 4. Kiểm tra sau khi TV1 chạy lại ETL

- [ ] `earned_ratio_t1`, `earned_ratio_t2` phải là số thực (vd 0,78), không được toàn 0 và 1. Nếu Parquet lưu tín chỉ dạng số nguyên, phép chia trong Synapse sẽ bị làm tròn: cần `CAST(... AS FLOAT)` trước khi chia.
- [ ] Số dòng thật = 3.400; tỉ lệ `dropout` = 21,3%; 206 sinh viên `has_second_term = 0`.
- [ ] TV2 train lại trên bảng curated (`run_jobs.py train --curated ...`): `cv_auc` phải xấp xỉ khi train trên `students.csv` (~0,71). Lệch nhiều → so từng cột.
