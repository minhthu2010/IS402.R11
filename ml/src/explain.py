"""Giải thích dự đoán: mức đóng góp của từng feature vào rủi ro bỏ học (SHAP).

Dùng chung cho evaluate.py (biểu đồ SHAP) và score.py (top_factors trả về cho web).
  * Model cây (rf, lgbm, xgb): shap.TreeExplainer
  * Logistic Regression: hệ số × (giá trị − trung bình) — đúng bằng SHAP của model tuyến tính
  * MLP: không hỗ trợ (KernelExplainer quá chậm cho endpoint) -> trả về rỗng
"""
import numpy as np
import pandas as pd

LABELS_VI = {   # tên dễ đọc hiển thị trên web / Power BI
    "age": "Tuổi", "is_female": "Giới tính nữ", "background": "Nhóm xuất thân", "in_state": "Trong bang",
    "international": "SV quốc tế", "on_campus": "Ở ký túc xá", "distance_from_home": "Khoảng cách tới trường",
    "high_school_gpa": "GPA THPT", "entrance_comb": "Điểm đầu vào", "entrance_missing": "Thiếu điểm đầu vào",
    "father_edu_cd": "Học vấn bố", "mother_edu_cd": "Học vấn mẹ", "faculty_id": "Khoa",
    "is_undeclared": "Chưa chọn ngành", "has_minor": "Có ngành phụ",
    "first_term_attempt_hrs": "Tín chỉ đăng ký HK1", "first_term_earned_hrs": "Tín chỉ đạt HK1",
    "earned_ratio_t1": "Tỉ lệ tín chỉ đạt HK1", "gpa_t1": "GPA HK1", "n_courses_t1": "Số môn HK1",
    "n_df_t1": "Số môn D/F HK1", "has_second_term": "Đăng ký học HK2 (có/không)",
    "second_term_attempt_hrs": "Tín chỉ đăng ký HK2", "second_term_earned_hrs": "Tín chỉ đạt HK2",
    "earned_ratio_t2": "Tỉ lệ tín chỉ đạt HK2", "gpa_t2": "GPA HK2", "n_df_t2": "Số môn D/F HK2",
    "gpa_change": "Thay đổi GPA HK2 so với HK1", "gross_fin_need": "Nhu cầu tài chính",
    "unmet_need": "Phần tài chính thiếu hụt", "fin_data_missing": "Không có hồ sơ tài chính", "fam_contribution_ratio": "Tỉ lệ gia đình đóng góp",
}


def _original_name(transformed, features):
    """'num__gpa_t1' -> 'gpa_t1'; 'cat__faculty_id_3.0' -> 'faculty_id'."""
    name = transformed.split("__", 1)[-1].replace("missingindicator_", "")
    for f in sorted(features, key=len, reverse=True):
        if name == f or name.startswith(f + "_"):
            return f
    return name


def contributions(pipe, X, features, background=None):
    """DataFrame (số sinh viên × feature gốc): đóng góp vào log-odds bỏ học; dương = đẩy rủi ro lên."""
    prep, clf = pipe[:-1], pipe[-1]
    Xt = prep.transform(X[features])
    names = list(prep.get_feature_names_out())
    Xt = Xt.toarray() if hasattr(Xt, "toarray") else np.asarray(Xt, dtype=float)
    kind = type(clf).__name__

    if kind == "LogisticRegression":
        if background is None:
            mean = np.zeros(Xt.shape[1])
        else:
            b = prep.transform(background[features])
            mean = np.asarray(b.toarray() if hasattr(b, "toarray") else b, dtype=float).mean(axis=0)
        sv = (Xt - mean) * clf.coef_[0]
    elif kind in ("RandomForestClassifier", "LGBMClassifier", "XGBClassifier"):
        try:
            import shap
        except ImportError:                # thiếu shap thì vẫn dự đoán được, chỉ không có top_factors
            return None
        import warnings
        with warnings.catch_warnings():        # shap báo đổi định dạng kết quả LightGBM; đã xử lý ở dưới
            warnings.simplefilter("ignore", UserWarning)
            sv = shap.TreeExplainer(clf).shap_values(Xt)
        if isinstance(sv, list):           # bản shap cũ: [lớp 0, lớp 1]
            sv = sv[1]
        sv = np.asarray(sv)
        if sv.ndim == 3:                   # (n, feature, lớp)
            sv = sv[:, :, 1]
    else:
        return None

    df = pd.DataFrame(sv, columns=[_original_name(n, features) for n in names])
    return df.T.groupby(level=0).sum().T  # gộp các cột one-hot về feature gốc


def top_factors(contrib_row, k=3):
    """3 feature đẩy rủi ro lên nhiều nhất, tên tiếng Việt."""
    pos = contrib_row[contrib_row > 0].sort_values(ascending=False).head(k)
    return [LABELS_VI.get(f, f) for f in pos.index]
