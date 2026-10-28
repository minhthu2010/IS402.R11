"""Tính feature tại mốc cuối năm nhất từ students.csv (cột gốc theo data_contract.md của TV1).

Kết quả có đúng tên cột như bảng curated/student_features mà TV1 tính bằng Synapse
(synapse/02_cetas_curated.sql), cộng thêm vài feature TV2 đề xuất (đánh dấu "TV2").
Nhờ vậy cùng một code train chạy được trên students.csv (tuần 1–2) lẫn bảng curated (từ tuần 3).

Dùng:
    from features import build_features, FEATURES, CAT_FEATURES
    feat = build_features(pd.read_csv("students.csv"), pd.read_csv("major_faculty.csv"))
"""
import numpy as np
import pandas as pd

GRADE_POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}   # NOT REP / INCOMPL / Unknown -> không tính

NUM_FEATURES = [
    "age", "is_female", "in_state", "international", "on_campus", "distance_from_home",
    "high_school_gpa", "entrance_comb", "entrance_missing", "father_edu_cd", "mother_edu_cd",
    "is_undeclared", "has_minor",
    "first_term_attempt_hrs", "first_term_earned_hrs", "earned_ratio_t1", "gpa_t1", "n_courses_t1", "n_df_t1",
    "has_second_term", "second_term_attempt_hrs", "second_term_earned_hrs", "earned_ratio_t2", "gpa_t2", "n_df_t2",
    "gpa_change",
    "gross_fin_need", "unmet_need", "fam_contribution_ratio",
]
CAT_FEATURES = ["background", "faculty_id"]
FEATURES = NUM_FEATURES + CAT_FEATURES
# Các cột học kỳ 2: bỏ đi nếu muốn dự đoán sớm hơn (cuối học kỳ 1)
TERM2_FEATURES = ["has_second_term", "second_term_attempt_hrs", "second_term_earned_hrs",
                  "earned_ratio_t2", "gpa_t2", "n_df_t2", "gpa_change"]


def _obj(s):
    """Cột chữ dạng object, ô trống = np.nan (SimpleImputer không xử lý được pd.NA)."""
    s = s.astype(object)
    return s.where(s.notna(), np.nan)


def _yn(s):
    return s.map({"Y": 1, "N": 0})


def _term_grades(df, term):
    """GPA, số môn có điểm, số môn D/F của 1 học kỳ (term = 'F' học kỳ 1, 'S' học kỳ 2)."""
    cols = [f"CORE_COURSE_GRADE_{i}_{term}" for i in range(1, 7) if f"CORE_COURSE_GRADE_{i}_{term}" in df]
    g = df[cols].apply(lambda c: c.astype("string").str.strip())
    pts = g.apply(lambda c: c.map(GRADE_POINTS)).astype(float)
    n = pts.notna().sum(axis=1)
    return pts.mean(axis=1), n, g.isin(["D", "F"]).sum(axis=1)


def build_features(raw: pd.DataFrame, major_faculty: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [c.strip().replace(" ", "_") for c in df.columns]
    mf = major_faculty[["major_name", "major_id", "faculty_id"]]
    df = df.merge(mf, how="left", left_on="STDNT_MAJOR", right_on="major_name")

    out = pd.DataFrame({"student_id": df["STUDENT_IDENTIFIER"]})
    out["age"] = df["STDNT_AGE"]
    out["is_female"] = df["STDNT_GENDER"].map({"F": 1, "M": 0})
    out["background"] = _obj(df["STDNT_BACKGROUND"])
    out["in_state"] = _yn(df["IN_STATE_FLAG"])
    out["international"] = _yn(df["INTERNATIONAL_STS"])
    out["on_campus"] = df["HOUSING_STS"].map({"On Campus": 1, "Off Campus": 0})
    out["distance_from_home"] = df["DISTANCE_FROM_HOME"]
    out["high_school_gpa"] = df["HIGH_SCHL_GPA"]
    out["entrance_comb"] = df["STDNT_TEST_ENTRANCE_COMB"]
    out["entrance_missing"] = df["STDNT_TEST_ENTRANCE_COMB"].isna().astype(int)          # TV2
    out["father_edu_cd"] = df["FATHER_HI_EDU_CD"]
    out["mother_edu_cd"] = df["MOTHER_HI_EDU_CD"]
    out["faculty_id"] = df["faculty_id"]
    out["major_id"] = df["major_id"]
    out["is_undeclared"] = (df["faculty_id"] == 8).astype(int)
    minor = df["STDNT_MINOR"].astype("string").str.strip()
    out["has_minor"] = (minor.notna() & (minor != "N")).astype(int)

    a1, e1 = df["FIRST_TERM_ATTEMPT_HRS"], df["FIRST_TERM_EARNED_HRS"]
    out["first_term_attempt_hrs"], out["first_term_earned_hrs"] = a1, e1
    out["earned_ratio_t1"] = e1 / a1.replace(0, np.nan)
    out["gpa_t1"], out["n_courses_t1"], out["n_df_t1"] = _term_grades(df, "F")

    a2, e2 = df["SECOND_TERM_ATTEMPT_HRS"], df["SECOND_TERM_EARNED_HRS"]
    out["has_second_term"] = (a2.fillna(0) > 0).astype(int)
    out["second_term_attempt_hrs"], out["second_term_earned_hrs"] = a2, e2
    out["earned_ratio_t2"] = e2 / a2.replace(0, np.nan)
    out["gpa_t2"], _, out["n_df_t2"] = _term_grades(df, "S")
    out["gpa_change"] = out["gpa_t2"] - out["gpa_t1"]                                   # TV2

    out["gross_fin_need"] = df["GROSS_FIN_NEED"]
    out["unmet_need"] = df["UNMET_NEED"]
    out["fam_contribution_ratio"] = df["EST_FAM_CONTRIBUTION"] / df["COST_OF_ATTEND"].replace(0, np.nan)

    if "RETURNED_2ND_YR" in df:
        out["dropout"] = 1 - df["RETURNED_2ND_YR"]
    out["is_synthetic"] = df["is_synthetic"] if "is_synthetic" in df else 0
    return out


def add_missing_tv2_columns(feat: pd.DataFrame) -> pd.DataFrame:
    """Bảng curated của TV1 có thể chưa có các cột TV2 đề xuất -> tự bổ sung."""
    feat = feat.copy()
    if "entrance_missing" not in feat:
        feat["entrance_missing"] = feat["entrance_comb"].isna().astype(int)
    if "gpa_change" not in feat:
        feat["gpa_change"] = feat["gpa_t2"] - feat["gpa_t1"]
    for c in ["is_female", "in_state", "international", "on_campus", "is_undeclared", "has_minor",
              "has_second_term", "dropout"]:
        if c in feat:
            feat[c] = feat[c].astype(float)
    feat["background"] = _obj(feat["background"])
    return feat
