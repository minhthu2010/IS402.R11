"""Chuẩn bị dữ liệu Kaggle "Students' Early Attrition Analysis" và sinh dữ liệu mô phỏng >4GB.

Đầu vào: UnivData1.xlsx (sheet "University information": 3.400 sinh viên × 56 cột,
sheet "Variable Dictionary": mô tả cột).

Đầu ra (cùng bố cục với container raw/ trên Data Lake, upload nguyên thư mục lên là xong):
  out/real/students/students.csv            dữ liệu thật, đổi "STUDENT IDENTIFIER" → STUDENT_IDENTIFIER
  out/real/dictionary/variable_dictionary.csv
  out/synthetic/students/students_b001.csv  ... mỗi block một file
  out/reference/major_faculty/major_faculty.csv   ánh xạ ngành → khoa
  out/size_report.md                        bảng dung lượng đo thực tế (rubric 1.3)

Dữ liệu mô phỏng: mỗi dòng lấy ngẫu nhiên (có hoàn lại) một sinh viên thật, đổi mã sinh viên
và thêm nhiễu nhỏ vào điểm đầu vào, GPA, khoảng cách, tài chính, số tín chỉ, 10% điểm môn học.
Nhãn RETURNED_2ND_YR giữ theo dòng gốc. Cột is_synthetic = 1, block = số thứ tự block.
Dữ liệu mô phỏng CHỈ dùng cho lưu trữ, ETL, benchmark; KHÔNG dùng để train model.

Cách chạy:
    python generate_data.py --xlsx UnivData1.xlsx --out out
  --blocks 80 --rows-per-block 220000 (mặc định) cho khoảng 17,6 triệu dòng ≈ 4,3GB (mỗi block ~56MB, ~5 giây).
Cùng tham số và --seed thì chạy lại ra đúng dữ liệu cũ.
"""
import argparse
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
GRADES = ["A", "B", "C", "D", "F"]
GRADE_COLS = [f"CORE_COURSE_GRADE_{i}_{t}" for t in "FS" for i in range(1, 7)]
SYN_ID_START = 100_000_000          # mã sinh viên thật nằm trong khoảng 7–8 triệu


def load_real(xlsx):
    df = pd.read_excel(xlsx, sheet_name="University information")
    df.columns = [c.strip().replace(" ", "_") for c in df.columns]
    df["is_synthetic"] = 0
    df["block"] = 0
    return df


def check_majors(df, ref):
    missing = sorted(set(df["STDNT_MAJOR"].dropna()) - set(ref["major_name"]))
    if missing:
        raise SystemExit(f"Ngành chưa có trong major_faculty.csv: {missing}")


def shift_grades(col, rng, frac=0.10):
    """Đổi 10% điểm chữ A–F lên hoặc xuống một bậc; giữ nguyên NOT REP / INCOMPL / Unknown / trống."""
    pos = col.map({g: i for i, g in enumerate(GRADES)})
    pick = pos.notna() & (rng.random(len(col)) < frac)
    new = (pos[pick] + rng.choice([-1, 1], pick.sum())).clip(0, 4).astype(int)
    out = col.copy()
    out[pick] = [GRADES[i] for i in new]
    return out


def make_block(real, k, rows, rng):
    df = real.iloc[rng.integers(0, len(real), rows)].reset_index(drop=True)
    n = len(df)
    df["STUDENT_IDENTIFIER"] = SYN_ID_START + (k - 1) * rows + np.arange(n)

    df["HIGH_SCHL_GPA"] = (df["HIGH_SCHL_GPA"] + rng.normal(0, 0.10, n)).clip(0, 4).round(2)
    df["STDNT_TEST_ENTRANCE1"] = (df["STDNT_TEST_ENTRANCE1"] + rng.integers(-1, 2, n)).clip(1, 36)
    delta = (rng.normal(0, 30, n) / 10).round() * 10
    df["STDNT_TEST_ENTRANCE2"] = (df["STDNT_TEST_ENTRANCE2"] + delta).clip(400, 1600)
    df["STDNT_TEST_ENTRANCE_COMB"] = (df["STDNT_TEST_ENTRANCE_COMB"] + delta).clip(400, 1600)
    df["DISTANCE_FROM_HOME"] = (df["DISTANCE_FROM_HOME"] * rng.lognormal(0, 0.2, n)).round()

    f = rng.lognormal(0, 0.10, n)   # cùng một hệ số cho các cột tài chính để giữ quan hệ giữa chúng
    for c in ["GROSS_FIN_NEED", "COST_OF_ATTEND", "EST_FAM_CONTRIBUTION", "UNMET_NEED"]:
        df[c] = (df[c] * f).round()

    for t in ["FIRST", "SECOND"]:
        att, ern = f"{t}_TERM_ATTEMPT_HRS", f"{t}_TERM_EARNED_HRS"
        d = rng.integers(-1, 2, n)
        df[att] = (df[att] + d).clip(lower=0)
        df[ern] = np.minimum(df[ern] + d, df[att]).clip(lower=0)

    for c in GRADE_COLS:
        df[c] = shift_grades(df[c], rng)

    df["is_synthetic"] = 1
    df["block"] = k
    return df


def write_csv(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, float_format="%.10g")


def size_report(out, real_rows, syn_rows, blocks):
    def folder(p):
        return sum(f.stat().st_size for f in p.rglob("*.csv"))
    real_b, syn_b = folder(out / "real"), folder(out / "synthetic")
    total = (real_b + syn_b) / 2**30
    lines = ["# Bảng dung lượng dữ liệu (đo thực tế)", "",
             f"Sinh bằng `generate_data.py`, {blocks} block.", "",
             "| Phần | Số sinh viên | Dung lượng CSV |", "|---|---:|---:|",
             f"| Dữ liệu thật (Kaggle UnivData1) | {real_rows:,} | {real_b / 2**20:,.2f} MB |",
             f"| Dữ liệu mô phỏng | {syn_rows:,} | {syn_b / 2**30:,.2f} GB |",
             f"| **Tổng** | **{real_rows + syn_rows:,}** | **{total:,.2f} GB** |", "",
             f"Kết luận: {'ĐẠT' if total > 4 else 'CHƯA ĐẠT, hãy tăng --blocks'} mức >4GB."]
    (out / "size_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", default="UnivData1.xlsx")
    ap.add_argument("--out", default="out")
    ap.add_argument("--blocks", type=int, default=80)
    ap.add_argument("--rows-per-block", type=int, default=220_000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    out, rng, t0 = Path(a.out), np.random.default_rng(a.seed), time.time()

    real = load_real(a.xlsx)
    ref = pd.read_csv(HERE / "reference" / "major_faculty.csv")
    check_majors(real, ref)
    write_csv(real, out / "real" / "students" / "students.csv")
    d = pd.read_excel(a.xlsx, sheet_name="Variable Dictionary", header=None, names=["column", "description"])
    d["column"] = d["column"].str.strip().str.replace(" ", "_")
    write_csv(d, out / "real" / "dictionary" / "variable_dictionary.csv")
    (out / "reference" / "major_faculty").mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "reference" / "major_faculty.csv", out / "reference" / "major_faculty" / "major_faculty.csv")
    print(f"Dữ liệu thật: {len(real):,} sinh viên, tỉ lệ bỏ học {1 - real['RETURNED_2ND_YR'].mean():.1%}")

    syn_rows = 0
    for k in range(1, a.blocks + 1):
        block = make_block(real, k, a.rows_per_block, rng)
        write_csv(block, out / "synthetic" / "students" / f"students_b{k:03d}.csv")
        syn_rows += len(block)
        print(f"[{time.time() - t0:6.0f}s] block {k}/{a.blocks}")

    size_report(out, len(real), syn_rows, a.blocks)
    print(f"Hoàn tất sau {time.time() - t0:.0f} giây. Kết quả ở: {out.resolve()}")


if __name__ == "__main__":
    main()
