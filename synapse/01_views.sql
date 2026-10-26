/* =====================================================================
   01_views.sql – view đọc Parquet trên lake (TV1 – T1.6)
   Use database = dropout_lake → Run. Chạy lại bao nhiêu lần cũng được.

   Bố cục thư mục do pipeline ADF tạo ra (tên file do ADF đặt, không cần đuôi .parquet):
     processed/real/students/            ← dữ liệu thật (3.400 dòng)
     processed/synthetic/students/       ← dữ liệu mô phỏng (>4GB khi còn là CSV)
     processed/reference/major_faculty/  ← ánh xạ ngành → khoa
   Dữ liệu thật và mô phỏng cùng cấu trúc cột (có sẵn cột is_synthetic, block).

   ADF Copy CSV → Parquet mặc định ghi mọi cột dạng chuỗi, nên khai báo VARCHAR rồi đổi kiểu
   bằng TRY_CAST. NULLIF(x, '') để ô trống thành NULL (vì TRY_CAST('' AS INT) ra 0).
   ===================================================================== */

CREATE OR ALTER VIEW dbo.v_major_faculty AS
SELECT TRY_CAST(r.major_id AS INT) AS major_id, r.major_name,
       TRY_CAST(r.faculty_id AS INT) AS faculty_id, r.faculty_name
FROM OPENROWSET(BULK 'reference/major_faculty/*', DATA_SOURCE = 'lake_processed', FORMAT = 'PARQUET')
     WITH (major_id VARCHAR(5), major_name VARCHAR(100), faculty_id VARCHAR(5), faculty_name NVARCHAR(100)) AS r;
GO

CREATE OR ALTER VIEW dbo.v_students AS
SELECT TRY_CAST(NULLIF(r.STUDENT_IDENTIFIER, '') AS INT)       AS student_id,
       TRY_CAST(NULLIF(r.STDNT_AGE, '') AS INT)                AS age,
       NULLIF(r.STDNT_GENDER, '')                              AS gender,
       NULLIF(r.STDNT_BACKGROUND, '')                          AS background,
       NULLIF(r.IN_STATE_FLAG, '')                             AS in_state,
       NULLIF(r.INTERNATIONAL_STS, '')                         AS international,
       r.STDNT_MAJOR                                           AS major_name,
       NULLIF(NULLIF(r.STDNT_MINOR, ''), 'N')                  AS minor,
       TRY_CAST(NULLIF(r.STDNT_TEST_ENTRANCE1, '') AS FLOAT)   AS entrance1,
       TRY_CAST(NULLIF(r.STDNT_TEST_ENTRANCE2, '') AS FLOAT)   AS entrance2,
       TRY_CAST(NULLIF(r.STDNT_TEST_ENTRANCE_COMB, '') AS FLOAT) AS entrance_comb,
       TRY_CAST(NULLIF(r.FIRST_TERM, '') AS INT)               AS first_term,
       TRY_CAST(NULLIF(r.SECOND_TERM, '') AS INT)              AS second_term,
       NULLIF(r.CORE_COURSE_NAME_1_F, '') AS c1_f, NULLIF(r.CORE_COURSE_GRADE_1_F, '') AS g1_f,
       NULLIF(r.CORE_COURSE_NAME_2_F, '') AS c2_f, NULLIF(r.CORE_COURSE_GRADE_2_F, '') AS g2_f,
       NULLIF(r.CORE_COURSE_NAME_3_F, '') AS c3_f, NULLIF(r.CORE_COURSE_GRADE_3_F, '') AS g3_f,
       NULLIF(r.CORE_COURSE_NAME_4_F, '') AS c4_f, NULLIF(r.CORE_COURSE_GRADE_4_F, '') AS g4_f,
       NULLIF(r.CORE_COURSE_NAME_5_F, '') AS c5_f, NULLIF(r.CORE_COURSE_GRADE_5_F, '') AS g5_f,
       NULLIF(r.CORE_COURSE_NAME_6_F, '') AS c6_f, NULLIF(r.CORE_COURSE_GRADE_6_F, '') AS g6_f,
       NULLIF(r.CORE_COURSE_NAME_1_S, '') AS c1_s, NULLIF(r.CORE_COURSE_GRADE_1_S, '') AS g1_s,
       NULLIF(r.CORE_COURSE_NAME_2_S, '') AS c2_s, NULLIF(r.CORE_COURSE_GRADE_2_S, '') AS g2_s,
       NULLIF(r.CORE_COURSE_NAME_3_S, '') AS c3_s, NULLIF(r.CORE_COURSE_GRADE_3_S, '') AS g3_s,
       NULLIF(r.CORE_COURSE_NAME_4_S, '') AS c4_s, NULLIF(r.CORE_COURSE_GRADE_4_S, '') AS g4_s,
       NULLIF(r.CORE_COURSE_NAME_5_S, '') AS c5_s, NULLIF(r.CORE_COURSE_GRADE_5_S, '') AS g5_s,
       NULLIF(r.CORE_COURSE_NAME_6_S, '') AS c6_s, NULLIF(r.CORE_COURSE_GRADE_6_S, '') AS g6_s,
       NULLIF(r.HOUSING_STS, '')                               AS housing,
       TRY_CAST(NULLIF(r.RETURNED_2ND_YR, '') AS INT)          AS returned_2nd_yr,
       TRY_CAST(NULLIF(r.DISTANCE_FROM_HOME, '') AS FLOAT)     AS distance_from_home,
       TRY_CAST(NULLIF(r.HIGH_SCHL_GPA, '') AS FLOAT)          AS high_school_gpa,
       NULLIF(r.HIGH_SCHL_NAME, '')                            AS high_school,
       TRY_CAST(NULLIF(r.FATHER_HI_EDU_CD, '') AS FLOAT)       AS father_edu_cd,
       NULLIF(r.FATHER_HI_EDU_DESC, '')                        AS father_edu,
       TRY_CAST(NULLIF(r.MOTHER_HI_EDU_CD, '') AS FLOAT)       AS mother_edu_cd,
       NULLIF(r.MOTHER_HI_EDU_DESC, '')                        AS mother_edu,
       NULLIF(r.DEGREE_GROUP_DESC, '')                         AS degree_group,
       TRY_CAST(NULLIF(r.FIRST_TERM_ATTEMPT_HRS, '') AS FLOAT)  AS first_term_attempt_hrs,
       TRY_CAST(NULLIF(r.FIRST_TERM_EARNED_HRS, '') AS FLOAT)   AS first_term_earned_hrs,
       TRY_CAST(NULLIF(r.SECOND_TERM_ATTEMPT_HRS, '') AS FLOAT) AS second_term_attempt_hrs,
       TRY_CAST(NULLIF(r.SECOND_TERM_EARNED_HRS, '') AS FLOAT)  AS second_term_earned_hrs,
       TRY_CAST(NULLIF(r.GROSS_FIN_NEED, '') AS FLOAT)         AS gross_fin_need,
       TRY_CAST(NULLIF(r.COST_OF_ATTEND, '') AS FLOAT)         AS cost_of_attend,
       TRY_CAST(NULLIF(r.EST_FAM_CONTRIBUTION, '') AS FLOAT)   AS est_fam_contribution,
       TRY_CAST(NULLIF(r.UNMET_NEED, '') AS FLOAT)             AS unmet_need,
       CAST(TRY_CAST(NULLIF(r.is_synthetic, '') AS INT) AS BIT) AS is_synthetic,
       TRY_CAST(NULLIF(r.block, '') AS INT)                    AS block
FROM OPENROWSET(BULK '*/students/*', DATA_SOURCE = 'lake_processed', FORMAT = 'PARQUET')
     WITH (STUDENT_IDENTIFIER VARCHAR(12), STDNT_AGE VARCHAR(5), STDNT_GENDER VARCHAR(1),
           STDNT_BACKGROUND VARCHAR(10), IN_STATE_FLAG VARCHAR(1), INTERNATIONAL_STS VARCHAR(1),
           STDNT_MAJOR VARCHAR(100), STDNT_MINOR VARCHAR(60),
           STDNT_TEST_ENTRANCE1 VARCHAR(10), STDNT_TEST_ENTRANCE2 VARCHAR(10), STDNT_TEST_ENTRANCE_COMB VARCHAR(10),
           FIRST_TERM VARCHAR(6),
           CORE_COURSE_NAME_1_F VARCHAR(12), CORE_COURSE_GRADE_1_F VARCHAR(8),
           CORE_COURSE_NAME_2_F VARCHAR(12), CORE_COURSE_GRADE_2_F VARCHAR(8),
           CORE_COURSE_NAME_3_F VARCHAR(12), CORE_COURSE_GRADE_3_F VARCHAR(8),
           CORE_COURSE_NAME_4_F VARCHAR(12), CORE_COURSE_GRADE_4_F VARCHAR(8),
           CORE_COURSE_NAME_5_F VARCHAR(12), CORE_COURSE_GRADE_5_F VARCHAR(8),
           CORE_COURSE_NAME_6_F VARCHAR(12), CORE_COURSE_GRADE_6_F VARCHAR(8),
           SECOND_TERM VARCHAR(6),
           CORE_COURSE_NAME_1_S VARCHAR(12), CORE_COURSE_GRADE_1_S VARCHAR(8),
           CORE_COURSE_NAME_2_S VARCHAR(12), CORE_COURSE_GRADE_2_S VARCHAR(8),
           CORE_COURSE_NAME_3_S VARCHAR(12), CORE_COURSE_GRADE_3_S VARCHAR(8),
           CORE_COURSE_NAME_4_S VARCHAR(12), CORE_COURSE_GRADE_4_S VARCHAR(8),
           CORE_COURSE_NAME_5_S VARCHAR(12), CORE_COURSE_GRADE_5_S VARCHAR(8),
           CORE_COURSE_NAME_6_S VARCHAR(12), CORE_COURSE_GRADE_6_S VARCHAR(8),
           HOUSING_STS VARCHAR(12), RETURNED_2ND_YR VARCHAR(2), DISTANCE_FROM_HOME VARCHAR(12),
           HIGH_SCHL_GPA VARCHAR(6), HIGH_SCHL_NAME VARCHAR(20),
           FATHER_HI_EDU_CD VARCHAR(4), FATHER_HI_EDU_DESC VARCHAR(40),
           MOTHER_HI_EDU_CD VARCHAR(4), MOTHER_HI_EDU_DESC VARCHAR(40),
           DEGREE_GROUP_DESC VARCHAR(30),
           FIRST_TERM_ATTEMPT_HRS VARCHAR(6), FIRST_TERM_EARNED_HRS VARCHAR(6),
           SECOND_TERM_ATTEMPT_HRS VARCHAR(6), SECOND_TERM_EARNED_HRS VARCHAR(6),
           GROSS_FIN_NEED VARCHAR(15), COST_OF_ATTEND VARCHAR(15),
           EST_FAM_CONTRIBUTION VARCHAR(15), UNMET_NEED VARCHAR(15),
           is_synthetic VARCHAR(2), block VARCHAR(5)) AS r;
GO

/* Xoay 12 cặp cột môn/điểm thành dòng: 1 dòng = 1 môn của 1 sinh viên trong 1 học kỳ */
CREATE OR ALTER VIEW dbo.v_course_grades AS
SELECT s.student_id,
       CASE WHEN v.term_seq = 1 THEN s.first_term ELSE s.second_term END AS term_code,
       v.term_seq, v.slot, v.course_code,
       LEFT(v.course_code, CHARINDEX(' ', v.course_code + ' ') - 1) AS dept,
       v.grade,
       CASE v.grade WHEN 'A' THEN 4.0 WHEN 'B' THEN 3.0 WHEN 'C' THEN 2.0
                    WHEN 'D' THEN 1.0 WHEN 'F' THEN 0.0 END AS grade_points,
       CAST(CASE WHEN v.grade IN ('A', 'B', 'C') THEN 1
                 WHEN v.grade IN ('D', 'F') THEN 0 END AS BIT) AS is_pass,
       s.is_synthetic, s.block
FROM dbo.v_students s
CROSS APPLY (VALUES (1, 1, s.c1_f, s.g1_f), (1, 2, s.c2_f, s.g2_f), (1, 3, s.c3_f, s.g3_f),
                    (1, 4, s.c4_f, s.g4_f), (1, 5, s.c5_f, s.g5_f), (1, 6, s.c6_f, s.g6_f),
                    (2, 1, s.c1_s, s.g1_s), (2, 2, s.c2_s, s.g2_s), (2, 3, s.c3_s, s.g3_s),
                    (2, 4, s.c4_s, s.g4_s), (2, 5, s.c5_s, s.g5_s), (2, 6, s.c6_s, s.g6_s)
            ) AS v(term_seq, slot, course_code, grade)
WHERE v.course_code IS NOT NULL;
GO

-- Kiểm tra nhanh: số sinh viên và tỉ lệ bỏ học, thật vs mô phỏng
SELECT is_synthetic, COUNT_BIG(*) AS so_sv, AVG(1.0 - returned_2nd_yr) AS ti_le_bo_hoc
FROM dbo.v_students GROUP BY is_synthetic;
