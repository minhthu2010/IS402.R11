/* =====================================================================
   03_benchmark.sql – đo CSV vs Parquet bằng Synapse serverless (TV1 – T1.7)
   Use database = dropout_lake. Chạy từng truy vấn riêng (bôi đen → Run), mỗi truy vấn 3 lần.
   Ghi lại: thời gian chạy và "Total data processed" ở tab Messages.
   ===================================================================== */

-- (1) Đọc CSV mô phỏng ở raw/ (phải quét toàn bộ file, mọi cột)
SELECT r.FIRST_TERM AS first_term, COUNT_BIG(*) AS so_sv, AVG(CAST(r.RETURNED_2ND_YR AS FLOAT)) AS ti_le_quay_lai
FROM OPENROWSET(BULK 'synthetic/students/*.csv', DATA_SOURCE = 'lake_raw',
                FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE)
     WITH (FIRST_TERM INT 12, RETURNED_2ND_YR INT 39) AS r   -- số 12, 39 là thứ tự cột trong file CSV
GROUP BY r.FIRST_TERM;

-- (2) Cùng truy vấn trên Parquet ở processed/ (Parquet chỉ đọc 2 cột cần dùng nên quét ít hơn nhiều)
SELECT first_term, COUNT_BIG(*) AS so_sv, AVG(CAST(returned_2nd_yr AS FLOAT)) AS ti_le_quay_lai
FROM dbo.v_students WHERE is_synthetic = 1
GROUP BY first_term;

-- (3) Truy vấn nặng: xoay bảng điểm và tính GPA theo khoa trên toàn bộ dữ liệu
SELECT m.faculty_name, g.term_seq, COUNT_BIG(*) AS so_mon, AVG(g.grade_points) AS gpa_tb
FROM dbo.v_course_grades g
JOIN dbo.v_students s ON s.student_id = g.student_id
JOIN dbo.v_major_faculty m ON m.major_name = s.major_name
GROUP BY m.faculty_name, g.term_seq;

-- (4) Đọc một block: so trước/sau khi chia thư mục theo khóa (T1.8)
SELECT major_name, COUNT_BIG(*) AS so_sv
FROM dbo.v_students WHERE first_term = 200908
GROUP BY major_name;
