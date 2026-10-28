/* =====================================================================
   alter_2026-10-28_feature_spec.sql – cập nhật bảng student_features theo feature_spec.md v1.0
   Chạy MỘT LẦN trên database đã tạo bằng ddl.sql bản cũ (Query editor → New query → Run).
   Database tạo mới từ ddl.sql bản hiện tại đã có sẵn 3 cột này, không cần chạy file này.
   ===================================================================== */

IF COL_LENGTH('dbo.student_features', 'entrance_missing') IS NULL
    ALTER TABLE dbo.student_features ADD entrance_missing BIT NULL;
IF COL_LENGTH('dbo.student_features', 'gpa_change') IS NULL
    ALTER TABLE dbo.student_features ADD gpa_change FLOAT NULL;
IF COL_LENGTH('dbo.student_features', 'fin_data_missing') IS NULL
    ALTER TABLE dbo.student_features ADD fin_data_missing BIT NULL;

-- Kiểm tra: phải ra 37 cột
SELECT COUNT(*) AS so_cot FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'student_features';
