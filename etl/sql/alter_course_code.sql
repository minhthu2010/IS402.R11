/* =====================================================================
   alter_course_code.sql – mở rộng course_code trên database đã tạo bằng ddl.sql bản cũ.
   Dữ liệu có 2 dòng ghi tên môn đầy đủ (dài tới 24 ký tự) thay vì mã môn.
   Chạy MỘT LẦN (Query editor → New query → Run). ddl.sql bản hiện tại đã có sẵn thay đổi này.
   ===================================================================== */
ALTER TABLE dbo.fact_course_grade ALTER COLUMN course_code VARCHAR(30) NOT NULL;