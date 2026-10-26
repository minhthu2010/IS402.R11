# Hướng dẫn từng bước – Thành viên 1 (Data Platform)

Dữ liệu: Kaggle **"Students' Early Attrition Analysis"** do giảng viên cung cấp (file `UnivData1.xlsx`:
3.400 sinh viên năm nhất, 56 cột, nhãn `RETURNED_2ND_YR`).

Làm lần lượt từ trên xuống, mỗi bước có ô ☐ để tích khi xong. Azure làm bằng giao diện; git và
Azure CLI chạy bằng lệnh trong terminal của VS Code (PowerShell); SQL thì dán vào ô soạn thảo rồi Run.

**Quy ước tên** – thay `<ten>` bằng tên viết tắt không dấu của bạn (vd `minh`), vì tên storage,
SQL server, Data Factory, Synapse phải là duy nhất trên toàn Azure:

| Tài nguyên | Tên |
|---|---|
| Resource Group | `rg-dropout-data` |
| Storage account (Data Lake) | `stdropout<ten>` (chỉ chữ thường và số, 3–24 ký tự) |
| SQL server / database | `sql-dropout-<ten>` / `dropoutdb` |
| Data Factory | `adf-dropout-<ten>` |
| Synapse workspace | `syn-dropout-<ten>` |
| Region | `Southeast Asia` (nếu bị policy chặn, chọn region được phép gần nhất) |

**Các file đi kèm** (thư mục `tv1/`, chép vào repo ở bước A3):

| File | Dùng ở |
|---|---|
| `data/generate_data.py` | B4, C1 – chuyển xlsx sang CSV và sinh dữ liệu >4GB |
| `data/reference/major_faculty.csv` | Ánh xạ 54 ngành → 8 khoa |
| `data/data_contract.md` | B8 |
| `etl/sql/ddl.sql` | B11 |
| `synapse/00_create_database.sql`, `01_views.sql`, `02_cetas_curated.sql`, `03_benchmark.sql` | B6, D7, E1 |

---

## 0. Bức tranh tổng thể

```
 Máy bạn                         Data Lake (stdropout<ten>)                          Azure SQL (dropoutdb)
 ─────────                       ─────────────────────────                          ─────────────────────
 UnivData1.xlsx                  raw/original/   (file gốc)
   └ generate_data.py ──upload─▶ raw/real/       (3.400 SV, CSV)                     dim_*, fact_*,
                       ──upload─▶ raw/synthetic/  (~17,6 triệu SV, >4GB CSV)         student_features,
                       ──upload─▶ raw/reference/  (ngành → khoa)                     agg_cohort_major
                                       │  ADF Copy                                         ▲
                                       ▼                                                   │ ADF Copy
                                  processed/ (Parquet) ── Synapse serverless ──▶ curated/ ─┘
                                                          (view + CETAS: xoay bảng điểm,
                                                           tính GPA, feature, tổng hợp)
                                  raw/uploads/ ← web của TV3
 Toàn bộ chuỗi ADF Copy → Synapse → ADF Copy nằm trong 1 pipeline "pl_dropout_etl", chạy bằng trigger.
```

Azure SQL chỉ nhận dữ liệu thật + 1 block mô phỏng (~223 nghìn SV) để vừa gói miễn phí 32GB.
Phần >4GB nằm trên lake và được Synapse xử lý; kết quả tổng hợp toàn bộ ở bảng `agg_cohort_major`.

**Chi phí phần của bạn:** storage vài cent/tháng; Azure SQL gói free 0 đồng; ADF chỉ tính khi pipeline
chạy; Synapse serverless ~5 USD cho mỗi TB quét (vài GB ≈ vài cent). Không có gì chạy 24/7, nên
**không cần xóa tài nguyên sau mỗi buổi**. Nếu dùng Data Flow thì tắt "Data flow debug" ngay sau khi dùng.

---

## PHẦN A – Chuẩn bị (ngày 1)

### A1. Cài phần mềm
☐ **VS Code** + extension **Python** (của Microsoft)
☐ **Python 3.11 trở lên** (lúc cài tích "Add python.exe to PATH")
☐ **Git** và **Azure CLI**
☐ **Azure Storage Explorer** (upload/xem file trên lake)
☐ **Azure Data Studio** (đo thời gian truy vấn SQL ở phần benchmark)
☐ Mở VS Code → **Terminal → New Terminal**, cài thư viện Python:
```bash
pip install pandas numpy openpyxl
```
☐ Đăng nhập Azure CLI bằng tài khoản trường:
```bash
az login
```

### A2. Chuẩn bị dữ liệu
☐ Tạo thư mục làm việc, ví dụ `D:\dropout\`, chép `UnivData1.xlsx` vào đó.
☐ Ổ đĩa còn trống **ít nhất 6GB** (cho dữ liệu mô phỏng).

### A3. Lấy repo của nhóm và chép file
☐ Clone repo (TV3 tạo) vào `D:\dropout\repo`:
```bash
git clone <url-repo-cua-nhom> D:\dropout\repo
```
☐ Chép các thư mục `data/`, `etl/`, `synapse/` và file hướng dẫn này từ `tv1/` vào `D:\dropout\repo\`.
☐ Thêm vào file `.gitignore` của repo (chưa có thì tạo) để **không đưa dữ liệu lớn lên git**:
```
out/
*.xlsx
```
☐ Tạo branch, commit, đẩy lên (chạy trong `D:\dropout\repo`):
```bash
cd D:\dropout\repo
```
```bash
git checkout -b tv1/setup
```
```bash
git add .gitignore data etl synapse HUONG_DAN_TV1.md
```
```bash
git commit -m "TV1: script, ddl, synapse va data contract"
```
```bash
git push -u origin tv1/setup
```
☐ Mở link git in ra để tạo **Pull Request** cho thành viên khác review.

> Mỗi task sau làm tương tự: `git checkout main` → `git pull` → `git checkout -b tv1/<ten-task>` → làm → `git add` → `git commit` → `git push -u origin tv1/<ten-task>` → Pull Request.
> Commit và PR của bạn là bằng chứng cộng tác cho rubric 5.4.

### A4. Tạo Resource Group riêng cho phần dữ liệu
Vì sao tạo trong subscription của bạn: Synapse khi tạo cần quyền ở cấp subscription (nó tự tạo thêm một
resource group quản lý). Nếu chỉ được cấp quyền trong Resource Group của TV4 thì bước tạo Synapse sẽ lỗi.
Phần của bạn rất rẻ nên đặt ở subscription của bạn là hợp lý. Báo TV4 để ghi vào báo cáo.

☐ Portal (portal.azure.com) → tìm **Resource groups** → **+ Create** → Subscription của bạn · tên `rg-dropout-data` · Region Southeast Asia → **Review + create → Create**.
☐ Mở `rg-dropout-data` → **Access control (IAM) → + Add → Add role assignment** → Role **Contributor** → Members: email trường của TV2, TV3, TV4 → **Review + assign**.
☐ **Tags** → thêm `owner = TV1`, `module = data` → Apply.

---

## PHẦN B – Tuần 1: Data Lake, profiling, data contract, Azure SQL

### B1. Tạo Data Lake (storage account)
☐ Portal → **Storage accounts → + Create**
   - **Basics**: Resource group `rg-dropout-data` · Name `stdropout<ten>` · Region Southeast Asia · Performance **Standard** · Redundancy **LRS**
   - **Advanced**: tích **Enable hierarchical namespace** ← BẮT BUỘC, đây là thứ biến storage thành Data Lake Gen2
   - **Review + create → Create** → **Go to resource**

### B2. Tạo container và thư mục
☐ Storage account → **Data storage → Containers → + Container**: tạo `raw`, `processed`, `curated`.
☐ Mở `raw` → **+ Add Directory**: tạo `original`, `uploads`, `rejected`. (Các thư mục `real`, `synthetic`, `reference` sẽ tự có khi upload ở B4, C2.)

### B3. Cấp quyền đọc/ghi dữ liệu
Quyền Owner/Contributor chỉ cho quản lý tài nguyên, **chưa cho đọc/ghi file**:
☐ Storage account → **Access control (IAM) → + Add role assignment** → Role **Storage Blob Data Contributor** → Members: **chính bạn**, **TV3** (ghi `raw/uploads/`), **TV2** (đọc curated) → Review + assign.
☐ Chờ 5–10 phút cho quyền có hiệu lực.

### B4. Chuyển xlsx sang CSV và upload dữ liệu thật
☐ Trong terminal VS Code, chạy script với `--blocks 0` (chỉ xuất dữ liệu thật, vài giây):
```bash
cd D:\dropout
```
```bash
python repo\data\generate_data.py --xlsx UnivData1.xlsx --out out --blocks 0
```
   Kết quả: `out\real\students\students.csv`, `out\real\dictionary\variable_dictionary.csv`, `out\reference\major_faculty\major_faculty.csv`. Script báo lỗi nếu có ngành chưa ánh xạ khoa.
☐ Mở **Azure Storage Explorer** → Sign in with Azure → `stdropout<ten>` → Blob Containers → `raw`:
   - Vào `original` → **Upload → Upload Files** → chọn `UnivData1.xlsx`.
   - Quay về gốc `raw` → **Upload → Upload Folder** → chọn `D:\dropout\out\real` → Upload. Lặp lại với `D:\dropout\out\reference`.
   - Kết quả phải có `raw/real/students/students.csv` và `raw/reference/major_faculty/major_faculty.csv`.

### B5. Tạo Synapse workspace
☐ Portal → **Azure Synapse Analytics → + Create**
   - **Basics**: Resource group `rg-dropout-data` · Workspace name `syn-dropout-<ten>` · Region Southeast Asia · Data Lake Storage Gen2: **From subscription** → Account `stdropout<ten>` → File system **Create new** `synapse` · tích **Assign myself the Storage Blob Data Contributor role…**
   - **Security**: *Use both local and Microsoft Entra ID authentication*, đặt SQL admin password (ghi lại)
   - **Networking**: tích **Allow connections from all IP addresses**
   - **Review + create → Create** (3–5 phút)
☐ Cấp quyền cho Synapse đọc/ghi lake: storage account → IAM → Add role assignment → **Storage Blob Data Contributor** → **Managed identity** → loại *Synapse workspace* → `syn-dropout-<ten>`.
☐ Mở workspace → **Open Synapse Studio** → **Manage → Git configuration → Configure** → GitHub → repo nhóm · Collaboration branch `main` · Root folder `/synapse-studio` → Apply. (Thư mục khác `/synapse` để không đè file SQL bạn tự quản lý.)

### B6. Tạo database Synapse
☐ Synapse Studio → **Develop → + → SQL script** → dán `synapse/00_create_database.sql` → **Connect to: Built-in · Use database: master** → **Run**.
☐ Làm mới ô "Use database" → chọn **dropout_lake**. Xóa nội dung cũ, dán đoạn trong khối `/* ... */` ở cuối file (bỏ `/*` và `*/`), thay `<storage>` bằng `stdropout<ten>`.
   **Tạm bỏ 2 dòng `CREATE USER` và `ALTER ROLE`** (Data Factory chưa có; làm ở D3) → **Run**.

### B7. Profiling dữ liệu thật
☐ Synapse Studio → **Data → Linked** → `stdropout<ten>` → `raw` → `real/students` → chuột phải `students.csv` → **New SQL script → Select TOP 100 rows** → Run.
☐ SQL script mới (Use database = dropout_lake), chạy lần lượt và chụp kết quả cho báo cáo mục 1.2–1.3:
```sql
-- Số dòng, tỉ lệ bỏ học
SELECT COUNT(*) AS so_sv, AVG(1.0 - RETURNED_2ND_YR) AS ti_le_bo_hoc
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw', FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS r;

-- Tỉ lệ bỏ học theo khóa
SELECT FIRST_TERM, COUNT(*) AS so_sv, AVG(1.0 - RETURNED_2ND_YR) AS ti_le_bo_hoc
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw', FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS r
GROUP BY FIRST_TERM ORDER BY FIRST_TERM;

-- Tỉ lệ bỏ học theo nơi ở và theo bang
SELECT HOUSING_STS, IN_STATE_FLAG, COUNT(*) AS so_sv, AVG(1.0 - RETURNED_2ND_YR) AS ti_le_bo_hoc
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw', FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS r
GROUP BY HOUSING_STS, IN_STATE_FLAG;

-- Mức thiếu của các cột điểm đầu vào
SELECT SUM(CASE WHEN STDNT_TEST_ENTRANCE1 IS NULL THEN 1 ELSE 0 END) AS thieu_ent1,
       SUM(CASE WHEN STDNT_TEST_ENTRANCE2 IS NULL THEN 1 ELSE 0 END) AS thieu_ent2,
       SUM(CASE WHEN STDNT_TEST_ENTRANCE_COMB IS NULL THEN 1 ELSE 0 END) AS thieu_comb, COUNT(*) AS tong
FROM OPENROWSET(BULK 'real/students/students.csv', DATA_SOURCE = 'lake_raw', FORMAT = 'CSV', PARSER_VERSION = '2.0', HEADER_ROW = TRUE) AS r;
```
☐ Đối chiếu với số liệu đã ghi sẵn ở mục 1 và 3 của `data_contract.md` (21,3% bỏ học, 3.400 SV…). Mở thêm `UnivData1.xlsx` bằng Excel để xem sheet "Variable Dictionary".

### B8. Data contract và chia sẻ dữ liệu cho nhóm
☐ Đọc lại `data/data_contract.md`, sửa nếu số liệu ở B7 khác. Commit lên branch `tv1/data-contract` → Pull Request → nhờ TV2, TV3, TV4 tích xác nhận ở mục 9.
☐ Dữ liệu thật rất nhỏ (0,86MB) nên **không cần file mẫu**: gửi `out\real\students\students.csv` và `major_faculty.csv` cho TV2, TV4 qua Drive/Teams để họ làm EDA và Power BI ngay.
☐ **Hạn: giữa tuần 1.**

### B9. Tạo Azure SQL Database
☐ Portal → **Azure SQL → + Create → SQL databases: Single database**. Nếu có banner **"Want to try Azure SQL Database for free?"** → **Apply offer**.
   - Resource group `rg-dropout-data` · Database `dropoutdb` · Server **Create new** `sql-dropout-<ten>` (Southeast Asia) · Authentication **Use both SQL and Microsoft Entra** · admin Entra = bạn · SQL admin `sqladmin` + mật khẩu
   - Free offer: "Behavior when free limit reached" → **Auto-pause the database until next month**
   - **Networking**: Public endpoint · **Allow Azure services…: Yes** · **Add current client IP: Yes**
   - **Review + create → Create**

### B10. Tạo bảng
☐ Database `dropoutdb` → **Query editor (preview)** → đăng nhập → dán toàn bộ `etl/sql/ddl.sql` → **Run** → mục Tables có 13 bảng.
☐ Tạo tài khoản cho thành viên khác (thay mật khẩu; **không** đưa mật khẩu admin cho ai):
```sql
CREATE USER app_writer WITH PASSWORD = 'DoiMatKhau#1';   -- TV2 ghi model_metrics, TV3 ghi predictions
ALTER ROLE db_datareader ADD MEMBER app_writer;
ALTER ROLE db_datawriter ADD MEMBER app_writer;
CREATE USER bi_reader WITH PASSWORD = 'DoiMatKhau#2';    -- TV4 dùng cho Power BI
ALTER ROLE db_datareader ADD MEMBER bi_reader;
```
☐ Gửi riêng qua chat nhóm (không đưa lên git) cho TV3, TV4: server `sql-dropout-<ten>.database.windows.net`, database `dropoutdb`, user/mật khẩu tương ứng.

### B11. Vẽ ERD
☐ **dbdiagram.io → Import → From SQL Server** → dán `ddl.sql` → nối quan hệ: `fact_enrollment.student_id → dim_student`, `major_id → dim_major`, `class_code → dim_class`, `first_term → dim_term`, `fact_course_grade.student_id → dim_student`, `dim_major.faculty_id → dim_faculty` → **Export PNG**.
☐ Lưu `docs/erd.png` trong repo, gửi TV3, TV4. **Hạn: cuối tuần 1.**

---

## PHẦN C – Tuần 1 đến giữa tuần 2: sinh dữ liệu >4GB

### C1. Sinh dữ liệu mô phỏng
☐ Terminal VS Code:
```bash
cd D:\dropout
```
```bash
python repo\data\generate_data.py --xlsx UnivData1.xlsx --out out
```
   Mặc định 80 block × 220.000 sinh viên. Mỗi block khoảng 5 giây và 56MB, tổng khoảng 7 phút.
☐ Mở `out\size_report.md`: dòng cuối phải là **"Kết luận: ĐẠT mức >4GB"**. Nếu chưa đạt, chạy lại với `--blocks 90`.
☐ Chép `size_report.md` vào `repo\data\` rồi commit. Đây là bảng dung lượng cho báo cáo mục 1.3.

### C2. Upload dữ liệu mô phỏng
☐ Storage Explorer → `raw` → **Upload → Upload Folder** → chọn `D:\dropout\out\synthetic` → Upload. Kết quả: `raw/synthetic/students/students_b001.csv` … `students_b080.csv`.
☐ Ghi lại thời gian, tốc độ ở khung **Activities** → chụp màn hình (số liệu "upload bằng Storage Explorer/AzCopy" cho benchmark).
☐ Báo TV3: `raw/uploads/` đã sẵn sàng và TV3 có quyền ghi. **Hạn: tuần 2.**

---

## PHẦN D – Giữa tuần 2 đến giữa tuần 3: pipeline ETL tự động

### D1. Tạo Data Factory
☐ Portal → **Data factories → + Create** → `rg-dropout-data` · `adf-dropout-<ten>` · Southeast Asia · tab Git configuration: **Configure Git later** → Create.
☐ Storage account → IAM → **Storage Blob Data Contributor** → Managed identity → loại *Data factory (V2)* → `adf-dropout-<ten>`.

### D2. Kết nối Git cho ADF
☐ Data Factory → **Launch studio** → **Manage → Git configuration → Configure** → GitHub → repo nhóm · Collaboration branch `main` · Publish branch `adf_publish` · Root folder `/adf` → Apply.
☐ Từ giờ: **Save all** = JSON lên git; **Publish** = trigger chạy thật.

### D3. Cho ADF quyền chạy script trên Synapse
☐ Synapse Studio → SQL script mới · Use database **dropout_lake**:
```sql
CREATE USER [adf-dropout-<ten>] FROM EXTERNAL PROVIDER;
ALTER ROLE db_owner ADD MEMBER [adf-dropout-<ten>];
```

### D4. Linked service
ADF Studio → **Manage → Linked services → + New**:
☐ **ls_lake**: *Azure Data Lake Storage Gen2* · **System Assigned Managed Identity** · From Azure subscription → `stdropout<ten>` → Test connection → Create.
☐ **ls_sql**: *Azure SQL Database* · server `sql-dropout-<ten>` · database `dropoutdb` · **SQL authentication** `sqladmin` → Test connection → Create.
☐ **ls_synapse**: *Azure Synapse Analytics* · **Enter manually** · FQDN `syn-dropout-<ten>-ondemand.sql.azuresynapse.net` · Database `dropout_lake` · **System Assigned Managed Identity** → Test connection → Create.

### D5. Dataset có tham số
ADF Studio → **Author → + → Dataset**:
☐ **ds_raw_csv**: *ADLS Gen2 → DelimitedText* · `ls_lake` · container `raw`, thư mục và file để trống · tích **First row as header** · Import schema **None**.
   Parameters: `folder`, `file` (String). Connection: Directory `@dataset().folder`, File name `@dataset().file`.
☐ **ds_parquet**: *ADLS Gen2 → Parquet* · `ls_lake` · Import schema None.
   Parameters: `container`, `folder`. Connection: File system `@dataset().container`, Directory `@dataset().folder`, File name trống, Compression **snappy**.
☐ **ds_sql_table**: *Azure SQL Database* · `ls_sql` · không chọn bảng.
   Parameters: `table`. Connection → Table → **Edit**: schema `dbo`, table `@dataset().table`.
☐ **Save all**.

### D6. Pipeline 1 – CSV sang Parquet (`pl_raw_to_processed`)
☐ Author → **+ → Pipeline** → `pl_raw_to_processed` → tab **Parameters** → `folders` (Array), Default value:
```
["real/students","synthetic/students","reference/major_faculty"]
```
☐ Kéo **ForEach** vào → Settings: Items `@pipeline().parameters.folders`, Batch count `3`.
☐ Bên trong ForEach: 1 activity **Copy data** `copy_to_parquet`:
   - Source: `ds_raw_csv` (folder, file trống) · File path type **Wildcard file path** · Wildcard folder path `@{item()}` · Wildcard file name `*.csv`
   - Sink: `ds_parquet` · container `processed` · folder `@{item()}`
☐ **Debug** → 3 lần copy xanh → kiểm tra `processed/real/students/`, `processed/synthetic/students/`, `processed/reference/major_faculty/` có file → **Save all**.

### D7. Chạy thử Synapse bằng tay
☐ Synapse Studio → SQL script (dropout_lake) → dán `synapse/01_views.sql` → Run → bảng cuối: 3.400 SV thật (~21% bỏ học) và ~17,6 triệu SV mô phỏng.
☐ SQL script mới → dán `synapse/02_cetas_curated.sql` → Run (vài phút vì khối cuối quét toàn bộ dữ liệu) → container `curated` có 9 thư mục; bảng cuối hiện tỉ lệ bỏ học theo khoa (Nghệ thuật thấp nhất ~15%).
☐ Muốn chạy lại 02: xóa 9 thư mục trong `curated` trước.
☐ Commit lại 3 file SQL nếu có sửa.

### D8. Pipeline 2 – nạp curated vào SQL (`pl_curated_to_sql`)
☐ Pipeline mới `pl_curated_to_sql` → Parameter `tables` (Array), Default:
```
["dim_faculty","dim_major","dim_term","dim_class","dim_student","fact_enrollment","fact_course_grade","student_features","agg_cohort_major"]
```
☐ ForEach (Items `@pipeline().parameters.tables`, Batch count `3`) → bên trong **Copy data** `copy_to_sql`:
   - Source: `ds_parquet` · container `curated` · folder trống · **Wildcard file path** · Wildcard folder path `@{item()}` · Wildcard file name `*`
   - Sink: `ds_sql_table` · table `@{item()}` · **Pre-copy script** `TRUNCATE TABLE dbo.@{item()}` · Write behavior **Insert**
☐ **Debug** → Query editor SQL chạy `SELECT is_synthetic, COUNT(*) FROM fact_enrollment GROUP BY is_synthetic;` → phải ra 3.400 và 220.000.

### D9. Pipeline chính `pl_dropout_etl`
☐ Pipeline mới `pl_dropout_etl`, nối các activity bằng mũi tên xanh (On success):

| # | Activity | Cấu hình |
|---|---|---|
| 1 | **Execute Pipeline** `run_raw_to_processed` | Invoked `pl_raw_to_processed` · tích Wait on completion |
| 2 | **Delete** `clear_curated` | `ds_parquet` · container `curated` · folder trống · **Wildcard file path**, file name `*` · tích **Recursively** · bỏ Enable logging |
| 3 | **Script** `synapse_cetas` | Linked service `ls_synapse` · bấm **+** để thêm **9 ô**, mỗi ô dán **một khối** của `02_cetas_curated.sql` (dòng `IF EXISTS … DROP …` + câu `CREATE EXTERNAL TABLE …`), **bỏ chữ GO** · NonQuery |
| 4 | **Execute Pipeline** `run_curated_to_sql` | Invoked `pl_curated_to_sql` · Wait on completion |
| 5 | **Script** `write_log` | `ls_sql` · NonQuery · nội dung bên dưới |

```
INSERT INTO etl_log (pipeline_name, run_id, activity, status)
VALUES ('@{pipeline().Pipeline}', '@{pipeline().RunId}', 'full_run', 'Succeeded')
```
☐ **Debug** toàn bộ → xanh hết → **Save all** → chạy lại lần 2 để chắc **không cần thao tác tay** (điều kiện "xong" của T1.5).

### D10. Trigger
☐ Đăng ký Event Grid (một lần): Portal → **Subscriptions** → subscription của bạn → **Resource providers** → `Microsoft.EventGrid` → **Register**.
☐ `pl_dropout_etl` → **Add trigger → New/Edit → + New**:
   - `tr_nightly`: **Schedule**, mỗi ngày 23:00 (UTC+7).
   - `tr_new_raw_file`: **Storage events** · `stdropout<ten>` · container `raw` · Blob path begins with `real/` · **Blob created**.
☐ **Publish all** → upload lại `students.csv` vào `raw/real/students/` → **Monitor → Pipeline runs** thấy pipeline tự chạy → chụp màn hình.
☐ Khi không cần chạy hằng đêm: **Manage → Triggers** → Stop `tr_nightly` → Publish (tiết kiệm credit).

### D11. (Thêm, nếu còn thời gian) Data Flow để demo
☐ Author → **+ → Data flow**: Source `ds_raw_csv` (real/students, students.csv) → **Derived column** đổi `STDNT_MINOR = 'N'` thành rỗng → **Filter** bỏ dòng thiếu `STUDENT_IDENTIFIER` → Sink `ds_parquet` (processed, clean/students).
☐ Bật **Data flow debug** chỉ khi thử, **tắt ngay sau khi xong**. Thời gian chạy gửi TV2 cho phần so sánh laptop vs cloud (T2.7).

☐ **Bàn giao giữa tuần 3:** báo TV2 bảng `student_features` đã có trong SQL và `curated/student_features/`.

---

## PHẦN E – Tuần 3: Benchmark đọc/ghi (T1.7)

Ghi số đo vào `benchmark.xlsx` (mỗi phép 3 lần + cột trung bình), vẽ biểu đồ cột trong Excel.

☐ **E1. CSV vs Parquet:** Storage Explorer → chuột phải `raw/synthetic/students` và `processed/synthetic/students` → **Folder Statistics** → ghi dung lượng. Synapse → dán `03_benchmark.sql` → bôi đen truy vấn (1) Run, rồi (2); tab **Messages** ghi thời gian và "Total data processed".
☐ **E2. Upload Portal vs Storage Explorer:** cùng 1 file (vd `out\synthetic\students\students_b001.csv`, ~56MB) upload vào một thư mục thử trong `raw` qua nút **Upload** trên Portal (bấm giờ) và qua Storage Explorer → tính MB/s. Xóa file thử sau khi đo.
☐ **E3. Rowstore vs columnstore:** Azure Data Studio → kết nối `sql-dropout-<ten>.database.windows.net` → `SET STATISTICS TIME ON;` → chạy truy vấn mẫu cuối `ddl.sql` 3 lần → tạo `CLUSTERED INDEX` → đo lại → `DROP INDEX` + `CLUSTERED COLUMNSTORE INDEX` → đo lại. Ghi thêm `EXEC sp_spaceused 'fact_course_grade';` mỗi lần.
☐ **E4. Synapse vs Azure SQL:** truy vấn (3) của `03_benchmark.sql` chạy trên toàn bộ dữ liệu ở Synapse; so với truy vấn tương tự trên `fact_course_grade` của SQL (ít dữ liệu hơn) → ghi nhận xét về quy mô.
☐ Đưa `benchmark.xlsx` vào `repo\etl\results\` → commit.

---

## PHẦN F – Tuần 4: Tối ưu lưu trữ (T1.8)

Mỗi mục: đo **trước** → áp dụng → đo **sau** → ghi bảng trước/sau.

☐ **Nén:** dung lượng CSV (raw) vs Parquet snappy (processed) – lấy từ E1.
☐ **Lifecycle:** storage account → **Data management → Lifecycle management → + Add a rule** → `raw-to-cool` · Limit blobs with filters · Base blobs: Last modified > 30 ngày → **Move to cool storage** · Filter: prefix `raw/synthetic/` → Add. Chụp màn hình, ghi giá Hot vs Cool từ trang Pricing.
☐ **Index cho Power BI:** chạy 3 câu `CREATE INDEX` cuối `ddl.sql` → nhờ TV4 đo thời gian tải trang report trước/sau.
☐ **Columnstore:** giữ `CLUSTERED COLUMNSTORE INDEX` trên `fact_course_grade` (theo kết quả E3).
☐ **Incremental load:** `pl_raw_to_processed` → `copy_to_parquet` → Source → **Filter by last modified** → Start time `@addDays(utcNow(), -1)` → so thời gian với lần nạp toàn bộ.
☐ (Tùy chọn) **Chia thư mục theo khóa (partition):** dùng Data Flow ở D11, Sink → tab Optimize → Partition option **Key** → cột `FIRST_TERM`, rồi so truy vấn (4) trong `03_benchmark.sql` trước/sau.

---

## PHẦN G – Việc làm sau MỖI buổi (5 phút)

☐ Tắt **Data flow debug** nếu đã bật. Phần còn lại để nguyên được.
☐ ADF: **Save all**. Synapse Studio: **Publish all**.
☐ **Export JSON tài nguyên** (yêu cầu của giảng viên), trong `D:\dropout\repo`:
```bash
az group export -n rg-dropout-data | Out-File -Encoding utf8 "infra/tv1/rg_$(Get-Date -Format yyyy-MM-dd).json"
```
   Lần đầu tạo thư mục trước: `mkdir infra\tv1`. Nếu lệnh báo không export được vài loại tài nguyên thì vẫn dùng được file kết quả (ADF và Synapse đã lên git qua Git integration).
☐ **Kiểm tra bí mật** rồi commit:
```bash
git add infra/tv1 data etl synapse
```
```bash
git diff --cached | Select-String -Pattern "password|accountkey|connectionstring|sharedaccesskey"
```
   Lệnh trên **không in gì** là an toàn. Nếu có, mở file thay giá trị bằng `"<secret>"` rồi `git add` lại.
```bash
git commit -m "TV1: <viec da lam> <ngay>"
```
```bash
git push
```
☐ Cập nhật trạng thái task của bạn trong Master Checklist ở buổi họp.

---

## PHẦN H – Bàn giao, báo cáo, demo

| Hạn | Bàn giao | Cho ai | ☐ |
|---|---|---|---|
| Giữa tuần 1 | `data_contract.md` + `students.csv` thật + `major_faculty.csv` | TV2, TV4 | ☐ |
| Cuối tuần 1 | Schema SQL (DDL + ERD) + tài khoản `app_writer`, `bi_reader` | TV3, TV4 | ☐ |
| Tuần 2 | Thư mục `raw/uploads/` + quyền ghi; danh sách cột của file upload = cột của `students.csv` | TV3 | ☐ |
| Giữa tuần 3 | `student_features` trong SQL và lake | TV2 | ☐ |
| Tuần 3 | Tên storage account để đo latency | TV4 | ☐ |
| Tuần 3 | Thời gian chạy pipeline/Data Flow cho so sánh laptop vs cloud | TV2 | ☐ |

**Phần viết trong báo cáo Word:**
☐ 1.1–1.2 Giới thiệu bài toán, nguồn dữ liệu (Kaggle, giấy phép CDLA-Sharing), loại dữ liệu
☐ 1.3 Kích thước dữ liệu: bảng `size_report.md`, ghi rõ 3.400 SV thật và phần mô phỏng, lý do mô phỏng
☐ 2.1 Lý thuyết lưu trữ: Data Lake và các zone, CSV vs Parquet, rowstore vs columnstore, star schema, serverless SQL
☐ 3.1–3.2 Mô hình dữ liệu (ERD), lưu trữ cloud, pipeline ETL (ảnh pipeline + Monitor)
☐ 3.3 Tốc độ đọc/ghi và tối ưu: bảng + biểu đồ benchmark, bảng trước/sau
☐ 5 slide PowerPoint + template PowerPoint chung cho nhóm

**Demo (khoảng 4 phút):**
☐ Storage Explorer: 3 zone, dữ liệu >4GB
☐ Mở một lần chạy `pl_dropout_etl` trong Monitor (hoặc chạy trực tiếp)
☐ Synapse: chạy truy vấn (3) của `03_benchmark.sql`, chỉ "Total data processed"
☐ Query editor: `SELECT TOP 10 * FROM student_features;`
☐ Bảng benchmark

---

## PHẦN I – Lỗi thường gặp

| Lỗi | Nguyên nhân / cách sửa |
|---|---|
| `No module named openpyxl` khi chạy script | `pip install openpyxl` |
| Script báo *Ngành chưa có trong major_faculty.csv* | Thêm dòng cho ngành đó vào `data/reference/major_faculty.csv` |
| `AuthorizationPermissionMismatch` / 403 | Thiếu **Storage Blob Data Contributor** (B3, B5, D1) hoặc mới cấp chưa đủ 10 phút |
| Synapse: *Content of directory … cannot be listed* | Như trên, hoặc sai tên container/đường dẫn |
| Synapse: *External data source 'lake_raw' does not exist* | Chưa chọn Use database = dropout_lake, hoặc chưa chạy phần 2 của B6 |
| CETAS: *directory … is not empty* | Xóa thư mục tương ứng trong `curated/` rồi chạy lại |
| View trả về toàn NULL | Tên cột trong Parquet khác tên trong `01_views.sql` (vd file CSV chưa đổi `STUDENT IDENTIFIER`); dùng CSV do script tạo ra |
| ADF `ls_synapse`: *Login failed* | Chưa chạy D3 |
| Query editor: *Client with IP … not allowed* | Bấm link allowlist trong thông báo, hoặc server → Networking → Add client IP |
| SQL báo database tạm dừng | Hết hạn mức free của tháng; đổi sang *Continue using database for additional charges* hoặc chờ tháng sau |
| Copy sang SQL lỗi *column … does not exist* | Chạy lại `ddl.sql` bản mới nhất; tên cột SQL phải trùng tên cột Parquet ở curated |
| Trigger không chạy | Chưa **Publish all**; trigger storage event cần `Microsoft.EventGrid` (D10) |
| `git push` bị từ chối | Chạy `git pull` trước, sửa xung đột nếu có, rồi push lại |
| Tạo Synapse báo lỗi quyền | Phải tạo trong subscription của bạn (A4) |
