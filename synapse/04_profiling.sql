/* =====================================================================
   04_profiling.sql – profiling dữ liệu thật trên Data Lake (TV1 – T1.1, bước B7)
   Use database = dropout_lake. Bôi đen từng truy vấn → Run, chụp kết quả cho báo cáo mục 1.2–1.3.
   Kết quả đối chiếu với data/data_contract.md (mục 1 và 3).
   ===================================================================== */

-- (1) Số sinh viên và tỉ lệ bỏ học (kỳ vọng: 3.400 SV, 21,3%)
SELECT COUNT(*) AS so_sv, AVG(1.0 - RETURNED_2ND_YR) AS ti_le_bo_hoc
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw',
                FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS r;

-- (2) Tỉ lệ bỏ học theo khóa
SELECT FIRST_TERM, COUNT(*) AS so_sv, AVG(1.0 - RETURNED_2ND_YR) AS ti_le_bo_hoc
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw',
                FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS r
GROUP BY FIRST_TERM ORDER BY FIRST_TERM;

-- (3) Tỉ lệ bỏ học theo nơi ở và trong/ngoài bang
SELECT HOUSING_STS, IN_STATE_FLAG, COUNT(*) AS so_sv, AVG(1.0 - RETURNED_2ND_YR) AS ti_le_bo_hoc
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw',
                FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS r
GROUP BY HOUSING_STS, IN_STATE_FLAG;

-- (4) Mức thiếu của các cột điểm đầu vào (kỳ vọng: 67,5% / 26,7% / 15,2%)
SELECT SUM(CASE WHEN STDNT_TEST_ENTRANCE1 IS NULL THEN 1 ELSE 0 END) AS thieu_ent1,
       SUM(CASE WHEN STDNT_TEST_ENTRANCE2 IS NULL THEN 1 ELSE 0 END) AS thieu_ent2,
       SUM(CASE WHEN STDNT_TEST_ENTRANCE_COMB IS NULL THEN 1 ELSE 0 END) AS thieu_comb,
       COUNT(*) AS tong
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw',
                FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS r;

-- (5) Tỉ lệ bỏ học theo khoa (ghép bảng ánh xạ ngành → khoa)
SELECT m.faculty_name, COUNT(*) AS so_sv, AVG(1.0 - s.RETURNED_2ND_YR) AS ti_le_bo_hoc
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw',
                FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS s
JOIN OPENROWSET(BULK 'reference/major_faculty/major_faculty.csv', DATA_SOURCE = 'lake_raw',
                FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS m
  ON m.major_name = s.STDNT_MAJOR
GROUP BY m.faculty_name ORDER BY ti_le_bo_hoc DESC;
