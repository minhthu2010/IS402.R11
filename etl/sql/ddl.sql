/* =====================================================================
   ddl.sql – Star schema trên Azure SQL Database (TV1 – T1.4)
   Dữ liệu: Kaggle "Students' Early Attrition Analysis" (UnivData1.xlsx)
   Cách chạy: Portal → SQL database → Query editor → dán toàn bộ file → Run.
   Chạy lại được: mỗi bảng bị xóa trước khi tạo lại (MẤT DỮ LIỆU CŨ).

   - Tên cột trùng đúng với bảng Parquet do Synapse tạo ở curated/ (02_cetas_curated.sql)
     để ADF Copy tự ánh xạ theo tên.
   - Không đặt FOREIGN KEY để ADF nạp song song không lỗi thứ tự; quan hệ khai báo trong Power BI.
   - SQL chỉ nhận dữ liệu thật (block 0) + 1 block mô phỏng (block 1) để vừa gói free 32GB.
     Toàn bộ >4GB nằm trên Data Lake, Synapse xử lý; bảng agg_cohort_major tổng hợp trên toàn bộ.
   ===================================================================== */

DROP TABLE IF EXISTS fact_course_grade, fact_enrollment, student_features, agg_cohort_major,
                     predictions, model_metrics, rls_user_scope, etl_log,
                     dim_student, dim_class, dim_term, dim_major, dim_faculty;

/* ---------- Dimension ---------- */
CREATE TABLE dim_faculty (
    faculty_id   INT           NOT NULL PRIMARY KEY,
    faculty_name NVARCHAR(100) NOT NULL
);

CREATE TABLE dim_major (                        -- 54 ngành, ánh xạ sang 8 khoa (major_faculty.csv)
    major_id   INT           NOT NULL PRIMARY KEY,
    major_name NVARCHAR(100) NOT NULL,
    faculty_id INT           NOT NULL
);

CREATE TABLE dim_term (                         -- 200908 = Fall 2009, 201002 = Spring 2010
    term_code     INT        NOT NULL PRIMARY KEY,
    [year]        INT        NOT NULL,
    season        VARCHAR(6) NOT NULL,          -- Fall / Spring
    academic_year VARCHAR(9) NOT NULL           -- vd 2009-2010
);

CREATE TABLE dim_class (                        -- lớp = ngành × khóa, dùng cho RLS vai trò Cố vấn
    class_code  VARCHAR(12) NOT NULL PRIMARY KEY, -- vd M01-2009
    major_id    INT         NOT NULL,
    cohort_year INT         NOT NULL,
    faculty_id  INT         NOT NULL
);

CREATE TABLE dim_student (
    student_id         INT          NOT NULL PRIMARY KEY,
    age                INT          NULL,
    gender             CHAR(1)      NULL,
    background         VARCHAR(10)  NULL,
    in_state           CHAR(1)      NULL,
    international      CHAR(1)      NULL,
    housing            VARCHAR(12)  NULL,
    distance_from_home FLOAT        NULL,
    high_school        VARCHAR(20)  NULL,
    high_school_gpa    FLOAT        NULL,
    father_edu         NVARCHAR(40) NULL,
    mother_edu         NVARCHAR(40) NULL,
    is_synthetic       BIT          NOT NULL,
    block              INT          NOT NULL
);

/* ---------- Fact ---------- */
CREATE TABLE fact_enrollment (                  -- 1 dòng = 1 sinh viên năm nhất; chứa nhãn bỏ học
    student_id              INT          NOT NULL PRIMARY KEY,
    major_id                INT          NOT NULL,
    faculty_id              INT          NOT NULL,
    class_code              VARCHAR(12)  NOT NULL,
    cohort_year             INT          NOT NULL,
    first_term              INT          NOT NULL,
    second_term             INT          NULL,
    minor                   NVARCHAR(60) NULL,  -- NULL = không có ngành phụ
    degree_group            VARCHAR(30)  NULL,
    entrance1               FLOAT        NULL,
    entrance2               FLOAT        NULL,
    entrance_comb           FLOAT        NULL,
    first_term_attempt_hrs  INT          NULL,
    first_term_earned_hrs   INT          NULL,
    second_term_attempt_hrs INT          NULL,
    second_term_earned_hrs  INT          NULL,
    gross_fin_need          FLOAT        NULL,
    cost_of_attend          FLOAT        NULL,
    est_fam_contribution    FLOAT        NULL,
    unmet_need              FLOAT        NULL,
    returned_2nd_yr         BIT          NOT NULL,
    dropout                 BIT          NOT NULL, -- 1 = không quay lại năm 2
    is_synthetic            BIT          NOT NULL,
    block                   INT          NOT NULL
);

CREATE TABLE fact_course_grade (                -- 12 cột môn/điểm của mỗi sinh viên được xoay thành dòng
    student_id   INT         NOT NULL,
    term_code    INT         NULL,
    term_seq     INT         NOT NULL,          -- 1 = học kỳ đầu, 2 = học kỳ hai
    slot         INT         NOT NULL,          -- môn thứ 1..6 trong học kỳ
    course_code  VARCHAR(12) NOT NULL,          -- vd MATH 1111
    dept         VARCHAR(6)  NOT NULL,          -- vd MATH
    grade        VARCHAR(8)  NULL,              -- A–F, NOT REP, INCOMPL, Unknown
    grade_points FLOAT       NULL,              -- A=4 … F=0; NULL nếu không phải điểm chữ
    is_pass      BIT         NULL,              -- 1 nếu A–C
    is_synthetic BIT         NOT NULL,
    block        INT         NOT NULL
);
-- Để dạng heap (không index) lúc đầu, để T1.7 đo rowstore vs columnstore.

CREATE TABLE agg_cohort_major (                 -- tổng hợp trên TOÀN BỘ >4GB (Synapse tính)
    cohort_year       INT    NOT NULL,
    major_id          INT    NOT NULL,
    faculty_id        INT    NOT NULL,
    is_synthetic      BIT    NOT NULL,
    n_students        BIGINT NOT NULL,
    n_dropout         BIGINT NOT NULL,
    dropout_rate      FLOAT  NOT NULL,
    avg_high_school_gpa FLOAT NULL,
    avg_gpa_term1     FLOAT  NULL
);

/* ---------- Bảng feature cho ML (TV2) – mốc dự đoán: cuối năm nhất ---------- */
CREATE TABLE student_features (
    student_id              INT        NOT NULL PRIMARY KEY,
    age                     INT        NULL,
    is_female               BIT        NULL,
    background              VARCHAR(10) NULL,
    in_state                BIT        NULL,
    international           BIT        NULL,
    on_campus               BIT        NULL,
    distance_from_home      FLOAT      NULL,
    high_school_gpa         FLOAT      NULL,
    entrance_comb           FLOAT      NULL,
    entrance_missing        BIT        NULL,       -- 1 khi entrance_comb NULL
    father_edu_cd           INT        NULL,
    mother_edu_cd           INT        NULL,
    faculty_id              INT        NOT NULL,
    major_id                INT        NOT NULL,
    is_undeclared           BIT        NOT NULL,
    has_minor               BIT        NOT NULL,
    first_term_attempt_hrs  INT        NULL,
    first_term_earned_hrs   INT        NULL,
    earned_ratio_t1         FLOAT      NULL,
    gpa_t1                  FLOAT      NULL,
    n_courses_t1            INT        NOT NULL,   -- số môn có điểm A–F học kỳ 1
    n_df_t1                 INT        NOT NULL,   -- số môn điểm D/F học kỳ 1
    has_second_term         BIT        NOT NULL,
    second_term_attempt_hrs INT        NULL,
    second_term_earned_hrs  INT        NULL,
    earned_ratio_t2         FLOAT      NULL,
    gpa_t2                  FLOAT      NULL,
    n_df_t2                 INT        NOT NULL,
    gpa_change              FLOAT      NULL,       -- gpa_t2 − gpa_t1
    fin_data_missing        BIT        NULL,       -- 1 khi COST_OF_ATTEND = 0/NULL (không có hồ sơ tài chính)
    gross_fin_need          FLOAT      NULL,       -- NULL khi fin_data_missing = 1
    unmet_need              FLOAT      NULL,       -- NULL khi fin_data_missing = 1
    fam_contribution_ratio  FLOAT      NULL,       -- est_fam_contribution / cost_of_attend
    dropout                 BIT        NOT NULL,
    is_synthetic            BIT        NOT NULL,
    block                   INT        NOT NULL
);

/* ---------- Bảng ứng dụng ---------- */
CREATE TABLE predictions (                      -- Function/Web (TV3) ghi vào, Power BI (TV4) đọc
    id            BIGINT IDENTITY PRIMARY KEY,
    student_id    INT           NOT NULL,
    class_code    VARCHAR(12)   NULL,
    probability   FLOAT         NOT NULL,
    risk_level    NVARCHAR(12)  NOT NULL,       -- Thấp / Trung bình / Cao
    top_factors   NVARCHAR(400) NULL,
    model_version VARCHAR(50)   NULL,
    source        VARCHAR(20)   NULL,           -- web / upload
    created_at    DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

CREATE TABLE model_metrics (                    -- TV2 ghi kết quả so sánh model
    run_id     VARCHAR(64)   NOT NULL,
    model_name VARCHAR(50)   NOT NULL,
    params     NVARCHAR(400) NULL,
    metric     VARCHAR(30)   NOT NULL,          -- f1 / recall / roc_auc / train_seconds ...
    value      FLOAT         NOT NULL,
    logged_at  DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

CREATE TABLE rls_user_scope (                   -- phân quyền RLS cho Power BI (TV4)
    user_email NVARCHAR(200) NOT NULL,
    role       NVARCHAR(20)  NOT NULL,          -- Admin / TruongKhoa / CoVan
    faculty_id INT           NULL,              -- dùng cho TruongKhoa
    class_code VARCHAR(12)   NULL               -- dùng cho CoVan
);

CREATE TABLE etl_log (                          -- ADF ghi mỗi lần chạy pipeline
    id            BIGINT IDENTITY PRIMARY KEY,
    pipeline_name NVARCHAR(100) NOT NULL,
    run_id        NVARCHAR(100) NOT NULL,
    activity      NVARCHAR(100) NULL,
    rows_copied   BIGINT        NULL,
    duration_sec  INT           NULL,
    status        NVARCHAR(20)  NOT NULL,
    logged_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

/* ---------- Ví dụ phân quyền: TV4 thay email bằng tài khoản thật của nhóm ---------- */
INSERT INTO rls_user_scope VALUES
    (N'admin@truong.edu.vn',      N'Admin',      NULL, NULL),
    (N'truongkhoa@truong.edu.vn', N'TruongKhoa', 3,    NULL),          -- Khoa học Sức khỏe
    (N'covan@truong.edu.vn',      N'CoVan',      NULL, 'M14-2009');    -- Nursing khóa 2009

/* ---------- Dùng ở T1.7 / T1.8 (chạy riêng khi cần, KHÔNG chạy cùng phần trên) ----------
-- Rowstore: tạo index thường rồi đo truy vấn
CREATE CLUSTERED INDEX cix_grade ON fact_course_grade (term_code, dept, student_id);
-- Columnstore: xóa index trên rồi tạo columnstore, đo lại cùng truy vấn
DROP INDEX cix_grade ON fact_course_grade;
CREATE CLUSTERED COLUMNSTORE INDEX ccix_grade ON fact_course_grade;
-- Truy vấn mẫu để đo (bật SET STATISTICS TIME ON trong Azure Data Studio / SSMS)
SELECT term_code, dept, COUNT(*) AS n, AVG(grade_points) AS avg_gp,
       AVG(CAST(is_pass AS FLOAT)) AS pass_rate
FROM fact_course_grade GROUP BY term_code, dept;
-- Index cho cột Power BI hay lọc
CREATE INDEX ix_enr_class   ON fact_enrollment (class_code)  INCLUDE (dropout, is_synthetic);
CREATE INDEX ix_enr_faculty ON fact_enrollment (faculty_id)  INCLUDE (dropout, is_synthetic);
CREATE INDEX ix_pred_time   ON predictions (created_at DESC);
------------------------------------------------------------------------------------------- */
