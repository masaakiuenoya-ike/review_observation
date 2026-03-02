#!/usr/bin/env python3
"""
dim_store の全店舗を対象に performance_monthly_snapshot 用 INSERT を生成する。
川越・平塚・越谷・江戸川は実データ、それ以外は metrics を NULL で 2023-07/08/09 を挿入。
実行: python scripts/gen_020_import_monthly.py
"""

# dim_store の全 store_id（bq query で取得した一覧）
STORE_IDS = [
    3547880,
    3547881,
    3547882,
    3547883,
    3547884,
    3547885,
    3547886,
    3547887,
    3547888,
    3547889,
    3547890,
    3547891,
    3547892,
    3547893,
    3547894,
    3547895,
    3547896,
    3547897,
    3547898,
    3547899,
    3547900,
    3547901,
    3547902,
    3547903,
    3547904,
    3547905,
    3547906,
    3547907,
    3547908,
    3547909,
    3547910,
    3564156,
    3568911,
    3568912,
    3568919,
    3568922,
    3600761,
    3609787,
    3609812,
    3628425,
    3641634,
    3642024,
    3669685,
    3675668,
    3677756,
    3708278,
    3718953,
    3719415,
    3722076,
    3723588,
    3729747,
    3734409,
    3734410,
    3734419,
    3734421,
    3734426,
    3734430,
    3734434,
    3734437,
    3734439,
    3734440,
    3734442,
    3734444,
    3734445,
    3745137,
    3754805,
    3760077,
    3779233,
    3797407,
    3797418,
    3797421,
    3797427,
    3797429,
    3800875,
    3802118,
    3802119,
    3802120,
    3813625,
    3825904,
]
# 川越・平塚・越谷・江戸川の実データ (2023-07, 08, 09): impressions, calls, direction_requests, website_clicks
REAL_DATA = {
    3547880: [(None, 47, 255, 101), (None, 54, 190, 88), (None, 37, 199, 73)],
    3547881: [(None, 65, 278, 91), (None, 70, 231, 133), (None, 145, 222, 104)],
    3547882: [(None, 46, 148, 102), (None, 63, 115, 87), (None, 35, 174, 60)],
    3547883: [(None, 79, 387, 154), (None, 103, 409, 155), (None, 110, 375, 151)],
}
MONTHS = ["2023-07-01", "2023-08-01", "2023-09-01"]


def row(store_id: str, month: str, imp, calls, dr, web) -> str:
    def v(x):
        return "NULL" if x is None else str(x)

    return f"( DATE('{month}'), '{store_id}', 'google', NULL, {v(imp)}, {v(calls)}, {v(dr)}, {v(web)}, CURRENT_TIMESTAMP(), 'import', 'ok' )"


def main():
    lines = []
    for sid in STORE_IDS:
        s = str(sid)
        data = REAL_DATA.get(sid)
        for i, month in enumerate(MONTHS):
            if data:
                imp, calls, dr, web = data[i]
                lines.append(row(s, month, imp, calls, dr, web))
            else:
                lines.append(row(s, month, None, None, None, None))
    print(",\n".join(lines))


if __name__ == "__main__":
    main()
