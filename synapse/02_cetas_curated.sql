/* =====================================================================
   02_cetas_curated.sql – tiền xử lý & tổng hợp bằng CETAS (TV1 – T1.6)
   Use database = dropout_lake → Run (chạy sau 01_views.sql).

   Mỗi khối ghi một thư mục Parquet trong container curated/; ADF Copy các thư mục này vào
   bảng cùng tên trên Azure SQL (ddl.sql).

   PHẠM VI NẠP VÀO SQL: các bảng chi tiết chỉ lấy block <= 1 (dữ liệu thật + 1 block mô phỏng,
   khoảng 220 nghìn sinh viên) để vừa gói Azure SQL free. Bảng agg_cohort_major tổng hợp trên
   TOÀN BỘ dữ liệu >4GB, cho thấy Synapse xử lý được quy mô lớn.

   CHẠY LẠI: DROP EXTERNAL TABLE không xóa file. Trước khi chạy lại, xóa các thư mục trong
   curated/ (Storage Explorer, hoặc activity "Delete" trong pipeline ADF).

   Mốc dự đoán: cuối năm nhất (sau học kỳ 2). Nhãn RETURNED_2ND_YR là việc quay lại học kỳ đầu
   năm hai, nên mọi thông tin của học kỳ 1 và 2 đều có trước nhãn, không bị rò rỉ.
   ===================================================================== */

/* ---------- dim_faculty, dim_major ---------- */
IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'dim_faculty') DROP EXTERNAL TABLE dbo.dim_faculty;
GO
CREATE EXTERNAL TABLE dbo.dim_faculty
WITH (LOCATION = 'dim_faculty/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT DISTINCT faculty_id, faculty_name FROM dbo.v_major_faculty;
GO

IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'dim_major') DROP EXTERNAL TABLE dbo.dim_major;
GO
CREATE EXTERNAL TABLE dbo.dim_major
WITH (LOCATION = 'dim_major/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT major_id, major_name, faculty_id FROM dbo.v_major_faculty;
GO

/* ---------- dim_term ---------- */
IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'dim_term') DROP EXTERNAL TABLE dbo.dim_term;
GO
CREATE EXTERNAL TABLE dbo.dim_term
WITH (LOCATION = 'dim_term/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT t.term_code,
       t.term_code / 100 AS [year],
       CASE WHEN t.term_code % 100 = 8 THEN 'Fall' ELSE 'Spring' END AS season,
       CASE WHEN t.term_code % 100 = 8
            THEN CONCAT(t.term_code / 100, '-', t.term_code / 100 + 1)
            ELSE CONCAT(t.term_code / 100 - 1, '-', t.term_code / 100) END AS academic_year
FROM (SELECT first_term AS term_code FROM dbo.v_students WHERE block <= 1
      UNION SELECT second_term FROM dbo.v_students WHERE block <= 1 AND second_term IS NOT NULL) t;
GO

/* ---------- dim_class (lớp = ngành × khóa) ---------- */
IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'dim_class') DROP EXTERNAL TABLE dbo.dim_class;
GO
CREATE EXTERNAL TABLE dbo.dim_class
WITH (LOCATION = 'dim_class/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT DISTINCT CONCAT('M', RIGHT(CONCAT('0', m.major_id), 2), '-', s.first_term / 100) AS class_code,
       m.major_id, s.first_term / 100 AS cohort_year, m.faculty_id
FROM dbo.v_students s JOIN dbo.v_major_faculty m ON m.major_name = s.major_name
WHERE s.block <= 1;
GO

/* ---------- dim_student ---------- */
IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'dim_student') DROP EXTERNAL TABLE dbo.dim_student;
GO
CREATE EXTERNAL TABLE dbo.dim_student
WITH (LOCATION = 'dim_student/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT student_id, age, gender, background, in_state, international, housing, distance_from_home,
       high_school, high_school_gpa, father_edu, mother_edu, is_synthetic, block
FROM dbo.v_students
WHERE block <= 1;
GO

/* ---------- fact_enrollment (có nhãn dropout) ---------- */
IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'fact_enrollment') DROP EXTERNAL TABLE dbo.fact_enrollment;
GO
CREATE EXTERNAL TABLE dbo.fact_enrollment
WITH (LOCATION = 'fact_enrollment/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT s.student_id, m.major_id, m.faculty_id,
       CONCAT('M', RIGHT(CONCAT('0', m.major_id), 2), '-', s.first_term / 100) AS class_code,
       s.first_term / 100 AS cohort_year, s.first_term, s.second_term,
       s.minor, s.degree_group, s.entrance1, s.entrance2, s.entrance_comb,
       CAST(s.first_term_attempt_hrs AS INT)  AS first_term_attempt_hrs,
       CAST(s.first_term_earned_hrs AS INT)   AS first_term_earned_hrs,
       CAST(s.second_term_attempt_hrs AS INT) AS second_term_attempt_hrs,
       CAST(s.second_term_earned_hrs AS INT)  AS second_term_earned_hrs,
       s.gross_fin_need, s.cost_of_attend, s.est_fam_contribution, s.unmet_need,
       CAST(s.returned_2nd_yr AS BIT)     AS returned_2nd_yr,
       CAST(1 - s.returned_2nd_yr AS BIT) AS dropout,
       s.is_synthetic, s.block
FROM dbo.v_students s JOIN dbo.v_major_faculty m ON m.major_name = s.major_name
WHERE s.block <= 1;
GO

/* ---------- fact_course_grade ---------- */
IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'fact_course_grade') DROP EXTERNAL TABLE dbo.fact_course_grade;
GO
CREATE EXTERNAL TABLE dbo.fact_course_grade
WITH (LOCATION = 'fact_course_grade/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT student_id, term_code, term_seq, slot, course_code, dept, grade, grade_points, is_pass, is_synthetic, block
FROM dbo.v_course_grades
WHERE block <= 1;
GO

/* ---------- student_features (bảng feature cho TV2) ---------- */
IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'student_features') DROP EXTERNAL TABLE dbo.student_features;
GO
CREATE EXTERNAL TABLE dbo.student_features
WITH (LOCATION = 'student_features/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT s.student_id, s.age,
       CAST(CASE s.gender WHEN 'F' THEN 1 WHEN 'M' THEN 0 END AS BIT)        AS is_female,
       s.background,
       CAST(CASE s.in_state WHEN 'Y' THEN 1 WHEN 'N' THEN 0 END AS BIT)      AS in_state,
       CAST(CASE s.international WHEN 'Y' THEN 1 WHEN 'N' THEN 0 END AS BIT) AS international,
       CAST(CASE s.housing WHEN 'On Campus' THEN 1 WHEN 'Off Campus' THEN 0 END AS BIT) AS on_campus,
       s.distance_from_home, s.high_school_gpa, s.entrance_comb,
       CAST(CASE WHEN s.entrance_comb IS NULL THEN 1 ELSE 0 END AS BIT) AS entrance_missing,
       CAST(s.father_edu_cd AS INT) AS father_edu_cd, CAST(s.mother_edu_cd AS INT) AS mother_edu_cd,
       m.faculty_id, m.major_id,
       CAST(CASE WHEN m.faculty_id = 8 THEN 1 ELSE 0 END AS BIT)      AS is_undeclared,
       CAST(CASE WHEN s.minor IS NULL THEN 0 ELSE 1 END AS BIT)       AS has_minor,
       CAST(s.first_term_attempt_hrs AS INT)                          AS first_term_attempt_hrs,
       CAST(s.first_term_earned_hrs AS INT)                           AS first_term_earned_hrs,
       s.first_term_earned_hrs / NULLIF(s.first_term_attempt_hrs, 0)  AS earned_ratio_t1,
       g.gpa_t1,
       COALESCE(g.n_courses_t1, 0)                                    AS n_courses_t1,
       COALESCE(g.n_df_t1, 0)                                         AS n_df_t1,
       CAST(CASE WHEN s.second_term_attempt_hrs > 0 THEN 1 ELSE 0 END AS BIT) AS has_second_term,
       CAST(s.second_term_attempt_hrs AS INT)                         AS second_term_attempt_hrs,
       CAST(s.second_term_earned_hrs AS INT)                          AS second_term_earned_hrs,
       s.second_term_earned_hrs / NULLIF(s.second_term_attempt_hrs, 0) AS earned_ratio_t2,
       g.gpa_t2,
       COALESCE(g.n_df_t2, 0)                                         AS n_df_t2,
       g.gpa_t2 - g.gpa_t1                                            AS gpa_change,
       -- COST_OF_ATTEND = 0 nghĩa là không có hồ sơ tài chính (feature_spec.md), không phải học phí 0 đồng
       CAST(CASE WHEN ISNULL(s.cost_of_attend, 0) = 0 THEN 1 ELSE 0 END AS BIT) AS fin_data_missing,
       CASE WHEN ISNULL(s.cost_of_attend, 0) = 0 THEN NULL ELSE s.gross_fin_need END AS gross_fin_need,
       CASE WHEN ISNULL(s.cost_of_attend, 0) = 0 THEN NULL ELSE s.unmet_need END     AS unmet_need,
       s.est_fam_contribution / NULLIF(s.cost_of_attend, 0)           AS fam_contribution_ratio,
       CAST(1 - s.returned_2nd_yr AS BIT)                             AS dropout,
       s.is_synthetic, s.block
FROM dbo.v_students s
JOIN dbo.v_major_faculty m ON m.major_name = s.major_name
LEFT JOIN (SELECT student_id,
                  AVG(CASE WHEN term_seq = 1 THEN grade_points END)                 AS gpa_t1,
                  SUM(CASE WHEN term_seq = 1 AND grade_points IS NOT NULL THEN 1 ELSE 0 END) AS n_courses_t1,  -- chỉ môn có điểm A–F
                  SUM(CASE WHEN term_seq = 1 AND grade IN ('D', 'F') THEN 1 ELSE 0 END) AS n_df_t1,
                  AVG(CASE WHEN term_seq = 2 THEN grade_points END)                 AS gpa_t2,
                  SUM(CASE WHEN term_seq = 2 AND grade IN ('D', 'F') THEN 1 ELSE 0 END) AS n_df_t2
           FROM dbo.v_course_grades
           WHERE block <= 1
           GROUP BY student_id) g ON g.student_id = s.student_id
WHERE s.block <= 1;
GO

/* ---------- agg_cohort_major: tổng hợp trên TOÀN BỘ >4GB ---------- */
IF EXISTS (SELECT 1 FROM sys.external_tables WHERE name = 'agg_cohort_major') DROP EXTERNAL TABLE dbo.agg_cohort_major;
GO
CREATE EXTERNAL TABLE dbo.agg_cohort_major
WITH (LOCATION = 'agg_cohort_major/', DATA_SOURCE = lake_curated, FILE_FORMAT = pq) AS
SELECT s.first_term / 100 AS cohort_year, m.major_id, m.faculty_id, s.is_synthetic,
       COUNT_BIG(*)                                     AS n_students,
       SUM(CAST(1 - s.returned_2nd_yr AS BIGINT))       AS n_dropout,
       AVG(CAST(1 - s.returned_2nd_yr AS FLOAT))        AS dropout_rate,
       AVG(s.high_school_gpa)                           AS avg_high_school_gpa,
       AVG(g.gpa_t1)                                    AS avg_gpa_term1
FROM dbo.v_students s
JOIN dbo.v_major_faculty m ON m.major_name = s.major_name
LEFT JOIN (SELECT student_id, AVG(grade_points) AS gpa_t1
           FROM dbo.v_course_grades WHERE term_seq = 1 GROUP BY student_id) g ON g.student_id = s.student_id
GROUP BY s.first_term / 100, m.major_id, m.faculty_id, s.is_synthetic;
GO

-- Kiểm tra: tỉ lệ bỏ học theo khoa trên dữ liệu thật
SELECT f.faculty_name, COUNT(*) AS so_sv, AVG(CAST(e.dropout AS FLOAT)) AS ti_le_bo_hoc
FROM dbo.fact_enrollment e JOIN dbo.dim_faculty f ON f.faculty_id = e.faculty_id
WHERE e.is_synthetic = 0
GROUP BY f.faculty_name ORDER BY ti_le_bo_hoc DESC;
