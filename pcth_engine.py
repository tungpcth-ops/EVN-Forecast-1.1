import io
import numpy as np
import pandas as pd


def pcth_group_formula(base_kwh, growth_pct=0.0, t_base=None, t_forecast=None,
                       kt_per_c=0.0, calendar_factor=1.0,
                       add_kwh=0.0, subtract_kwh=0.0):
    """Công thức theo bài giảng PCTH:
    Ahat = A0 * (1+g) * Ht * Hl + DeltaA_tang - DeltaA_giam
    Ht = 1 + KT * (T_du_bao - T_nen)
    """
    base = float(base_kwh or 0)
    g = float(growth_pct or 0) / 100.0
    hl = float(calendar_factor or 1.0)
    if t_base is None or t_forecast is None or pd.isna(t_base) or pd.isna(t_forecast):
        ht = 1.0
        delta_t = np.nan
    else:
        delta_t = float(t_forecast) - float(t_base)
        ht = 1.0 + float(kt_per_c or 0.0) * delta_t
    forecast = base * (1.0 + g) * ht * hl + float(add_kwh or 0) - float(subtract_kwh or 0)
    growth_vs_base = (forecast / base - 1.0) * 100.0 if base > 0 else np.nan
    return {
        "base_kwh": base,
        "growth_pct": float(growth_pct or 0),
        "delta_t_c": delta_t,
        "kt_per_c": float(kt_per_c or 0),
        "weather_factor": ht,
        "calendar_factor": hl,
        "add_kwh": float(add_kwh or 0),
        "subtract_kwh": float(subtract_kwh or 0),
        "forecast_kwh": forecast,
        "growth_vs_base_pct": growth_vs_base,
    }


def large_customer_forecast(run_days, run_kwh_per_day, run_growth_pct=0.0,
                            stop_days=0.0, stop_kwh_per_day=0.0):
    run_component = float(run_days or 0) * float(run_kwh_per_day or 0) * (1.0 + float(run_growth_pct or 0)/100.0)
    stop_component = float(stop_days or 0) * float(stop_kwh_per_day or 0)
    return {
        "run_component_kwh": run_component,
        "stop_component_kwh": stop_component,
        "forecast_kwh": run_component + stop_component,
    }


def new_customer_forecast(capacity_kw, hours_per_day, days, load_factor=1.0):
    return float(capacity_kw or 0) * float(hours_per_day or 0) * float(days or 0) * float(load_factor or 0)


def economic_reference(activity_growth_pct, elasticity_kg):
    return float(activity_growth_pct or 0) * float(elasticity_kg or 0)


def _norm_col(name):
    return str(name).strip().lower().replace("đ", "d").replace(" ", "_")


def parse_pcth_workbook(fileobj):
    """Đọc workbook nhập liệu PCTH. Các sheet là tùy chọn."""
    xls = pd.ExcelFile(fileobj)
    out = {}
    for sheet in xls.sheet_names:
        out[sheet] = pd.read_excel(xls, sheet_name=sheet)
    return out


def calculate_pcth_from_tables(tables):
    results = []
    # Nhóm KH còn lại
    gdf = tables.get("Nhom_KH")
    if gdf is not None and not gdf.empty:
        for _, r in gdf.iterrows():
            group = str(r.get("Nhóm khách hàng", r.get("Nhom_KH", "Nhóm KH")))
            calc = pcth_group_formula(
                r.get("Điện nền (kWh)", r.get("Dien_nen_kWh", 0)),
                r.get("Tăng cơ sở g (%)", r.get("g_pct", 0)),
                r.get("T nền (°C)", r.get("T_nen_C", np.nan)),
                r.get("T dự báo (°C)", r.get("T_du_bao_C", np.nan)),
                r.get("KT (1/°C)", r.get("KT_1_per_C", 0)),
                r.get("Hệ số lịch", r.get("He_so_lich", 1)),
                r.get("Tăng thêm (kWh)", r.get("Tang_them_kWh", 0)),
                r.get("Giảm trừ (kWh)", r.get("Giam_tru_kWh", 0)),
            )
            results.append({
                "Dòng dự báo": group,
                "Loại": "Nhóm còn lại",
                "Điện nền (kWh)": calc["base_kwh"],
                "Dự báo (kWh)": calc["forecast_kwh"],
                "Tăng so nền (%)": calc["growth_vs_base_pct"],
                "g (%)": calc["growth_pct"],
                "ΔT (°C)": calc["delta_t_c"],
                "KT (1/°C)": calc["kt_per_c"],
                "Ht": calc["weather_factor"],
                "Hl": calc["calendar_factor"],
                "Tăng thêm (kWh)": calc["add_kwh"],
                "Giảm trừ (kWh)": calc["subtract_kwh"],
                "Người phụ trách": r.get("Người phụ trách", ""),
                "Căn cứ": r.get("Căn cứ", ""),
            })

    # KH lớn
    ldf = tables.get("KH_lon")
    if ldf is not None and not ldf.empty:
        for _, r in ldf.iterrows():
            calc = large_customer_forecast(
                r.get("Số ngày chạy", 0),
                r.get("kWh/ngày chạy", 0),
                r.get("Tăng điện ngày chạy (%)", 0),
                r.get("Số ngày dừng", 0),
                r.get("kWh/ngày dừng", 0),
            )
            results.append({
                "Dòng dự báo": str(r.get("Tên KH", r.get("Mã KH", "KH lớn"))),
                "Loại": "KH lớn - lịch vận hành",
                "Điện nền (kWh)": float(r.get("Điện nền (kWh)", 0) or 0),
                "Dự báo (kWh)": calc["forecast_kwh"],
                "Tăng so nền (%)": ((calc["forecast_kwh"] / float(r.get("Điện nền (kWh)", 0)) - 1)*100
                                      if float(r.get("Điện nền (kWh)", 0) or 0) > 0 else np.nan),
                "g (%)": float(r.get("Tăng điện ngày chạy (%)", 0) or 0),
                "ΔT (°C)": np.nan,
                "KT (1/°C)": np.nan,
                "Ht": np.nan,
                "Hl": np.nan,
                "Tăng thêm (kWh)": calc["run_component_kwh"],
                "Giảm trừ (kWh)": 0.0,
                "Người phụ trách": r.get("Người phụ trách", ""),
                "Căn cứ": r.get("Căn cứ", ""),
            })

    # KH mới
    ndf = tables.get("KH_moi")
    if ndf is not None and not ndf.empty:
        for _, r in ndf.iterrows():
            kwh = new_customer_forecast(
                r.get("Công suất định mức (kW)", 0),
                r.get("Giờ/ngày", 0),
                r.get("Số ngày", 0),
                r.get("Hệ số tải", 1),
            )
            kwh += float(r.get("Điện bổ sung trực tiếp (kWh)", 0) or 0)
            results.append({
                "Dòng dự báo": str(r.get("Tên KH", "KH mới")),
                "Loại": "Khách hàng mới",
                "Điện nền (kWh)": 0.0,
                "Dự báo (kWh)": kwh,
                "Tăng so nền (%)": np.nan,
                "g (%)": np.nan,
                "ΔT (°C)": np.nan,
                "KT (1/°C)": np.nan,
                "Ht": np.nan,
                "Hl": np.nan,
                "Tăng thêm (kWh)": kwh,
                "Giảm trừ (kWh)": 0.0,
                "Người phụ trách": r.get("Người phụ trách", ""),
                "Căn cứ": r.get("Căn cứ", ""),
            })

    # Điện mặt trời - chỉ trừ phần mua lưới giảm thêm
    sdf = tables.get("DMTMN")
    if sdf is not None and not sdf.empty:
        for _, r in sdf.iterrows():
            red = float(r.get("Mua lưới giảm thêm (kWh)", 0) or 0)
            results.append({
                "Dòng dự báo": str(r.get("Tên/Mã KH", "ĐMTMN")),
                "Loại": "Điện mặt trời - giảm mua lưới",
                "Điện nền (kWh)": 0.0,
                "Dự báo (kWh)": -red,
                "Tăng so nền (%)": np.nan,
                "g (%)": np.nan,
                "ΔT (°C)": np.nan,
                "KT (1/°C)": np.nan,
                "Ht": np.nan,
                "Hl": np.nan,
                "Tăng thêm (kWh)": 0.0,
                "Giảm trừ (kWh)": red,
                "Người phụ trách": r.get("Người phụ trách", ""),
                "Căn cứ": r.get("Căn cứ", ""),
            })

    detail = pd.DataFrame(results)
    if detail.empty:
        return detail, pd.DataFrame()
    total_base = detail.loc[detail["Điện nền (kWh)"] > 0, "Điện nền (kWh)"].sum()
    total_fc = detail["Dự báo (kWh)"].sum()
    summary = pd.DataFrame([{
        "Tổng nền (kWh)": total_base,
        "Tổng dự báo PCTH (kWh)": total_fc,
        "Tăng/giảm (kWh)": total_fc-total_base,
        "Tăng/giảm (%)": ((total_fc/total_base)-1)*100 if total_base>0 else np.nan,
    }])
    return detail, summary


def scenario_from_groups(base_groups, low_g_delta=-1.0, high_g_delta=1.0,
                         low_temp_delta=-0.5, high_temp_delta=0.5):
    """Tạo 3 kịch bản Thấp/Cơ sở/Cao từ bảng nhóm. Không phải xác suất/khoảng tin cậy."""
    if base_groups is None or base_groups.empty:
        return pd.DataFrame()
    rows=[]
    for label, dg, dt in [("Thấp", low_g_delta, low_temp_delta), ("Cơ sở",0,0), ("Cao",high_g_delta,high_temp_delta)]:
        total=0.0
        for _,r in base_groups.iterrows():
            calc=pcth_group_formula(
                r.get("Điện nền (kWh)",0),
                float(r.get("Tăng cơ sở g (%)",0) or 0)+dg,
                r.get("T nền (°C)",np.nan),
                (float(r.get("T dự báo (°C)",np.nan))+dt if pd.notna(r.get("T dự báo (°C)",np.nan)) else np.nan),
                r.get("KT (1/°C)",0),
                r.get("Hệ số lịch",1),
                r.get("Tăng thêm (kWh)",0),
                r.get("Giảm trừ (kWh)",0),
            )
            total += calc["forecast_kwh"]
        rows.append({"Kịch bản":label,"Tổng nhóm (kWh)":total,"Điều chỉnh g (điểm %)":dg,"Điều chỉnh nhiệt (°C)":dt})
    return pd.DataFrame(rows)
