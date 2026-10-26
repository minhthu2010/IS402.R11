/* =====================================================================
   00_create_database.sql – chạy MỘT LẦN (TV1 – T1.6)
   Synapse Studio → Develop → + SQL script → dán file này
   Thanh trên cùng: Connect to = Built-in, Use database = master → Run.

   Trước khi chạy, cấp quyền "Storage Blob Data Contributor" trên storage account
   (Portal → storage account → Access control (IAM) → Add role assignment) cho:
     - chính bạn (để truy vấn và ghi CETAS khi chạy tay trong Synapse Studio)
     - managed identity của Synapse workspace và của Data Factory
   ===================================================================== */

-- Collation UTF8 giúp đọc chuỗi trong Parquet đúng và nhanh hơn
CREATE DATABASE dropout_lake COLLATE Latin1_General_100_BIN2_UTF8;
GO

/* Sau khi chạy xong: đổi "Use database" sang dropout_lake, xóa phần trên,
   dán đoạn dưới (bỏ dấu comment) và thay <storage> bằng tên storage account, rồi Run.

CREATE EXTERNAL DATA SOURCE lake_raw       WITH (LOCATION = 'https://<storage>.dfs.core.windows.net/raw');
CREATE EXTERNAL DATA SOURCE lake_processed WITH (LOCATION = 'https://<storage>.dfs.core.windows.net/processed');
CREATE EXTERNAL DATA SOURCE lake_curated   WITH (LOCATION = 'https://<storage>.dfs.core.windows.net/curated');
CREATE EXTERNAL FILE FORMAT pq WITH (FORMAT_TYPE = PARQUET, DATA_COMPRESSION = 'org.apache.hadoop.io.compress.SnappyCodec');

-- Cho phép Data Factory chạy các script này (thay adf-dropout bằng tên Data Factory của nhóm)
CREATE USER [adf-dropout] FROM EXTERNAL PROVIDER;
ALTER ROLE db_owner ADD MEMBER [adf-dropout];
*/
