#!/usr/bin/env python3
"""
dim_store の全店舗を places_provider_map に INSERT する SQL を生成する。
store_code = store_id（文字列）, provider = 'google', provider_place_id = ''（後で GBP location を設定可）,
display_name = store_name, is_active = true.
"""

import sys
from pathlib import Path

# dim_store の store_id, store_name（bq 取得結果をそのまま利用）
STORES = [
    (3547880, "川越"),
    (3547881, "平塚"),
    (3547882, "越谷"),
    (3547883, "江戸川"),
    (3547884, "松戸"),
    (3547885, "幕張"),
    (3547886, "東村山"),
    (3547887, "川崎丸子橋"),
    (3547888, "町田"),
    (3547889, "習志野"),
    (3547890, "八王子"),
    (3547891, "見沼"),
    (3547892, "新座"),
    (3547893, "前橋"),
    (3547894, "摂津"),
    (3547895, "箕面"),
    (3547896, "藤沢"),
    (3547897, "青梅"),
    (3547898, "高倉（使用禁止）"),
    (3547899, "相模原"),
    (3547900, "志免"),
    (3547901, "栃木工場"),
    (3547902, "瑞穂町"),
    (3547903, "その他本社"),
    (3547904, "浜松"),
    (3547905, "インサイド・セールス（立川CC）"),
    (3547906, "マーケティング"),
    (3547907, "組織開発"),
    (3547908, "【使用しない】経営管理"),
    (3547909, "事業部"),
    (3547910, "本社"),
    (3564156, "羽村"),
    (3568911, "江戸川松江"),
    (3568912, "長岡京"),
    (3568919, "高槻"),
    (3568922, "茨木"),
    (3600761, "垂水"),
    (3609787, "岡山"),
    (3609812, "泉南"),
    (3628425, "札幌西野"),
    (3641634, "法人営業部"),
    (3642024, "札幌清田"),
    (3669685, "姫路"),
    (3675668, "データ分析"),
    (3677756, "八王子高倉"),
    (3708278, "高崎"),
    (3718953, "本庄"),
    (3719415, "宝塚"),
    (3722076, "ベトナム研修所"),
    (3723588, "名古屋北"),
    (3729747, "藤岡"),
    (3734409, "相模原・町田店"),
    (3734410, "第一営業部"),
    (3734419, "第二営業部"),
    (3734421, "第三営業部"),
    (3734426, "西日本事業部"),
    (3734430, "前橋・高崎・藤岡店"),
    (3734434, "東村山・新座店"),
    (3734437, "藤沢・平塚店"),
    (3734439, "越谷・見沼店"),
    (3734440, "札幌西野・清田店"),
    (3734442, "松戸・幕張・習志野店"),
    (3734444, "八王子・高倉・羽村・青梅店"),
    (3734445, "摂津・箕面・高槻店"),
    (3745137, "天理"),
    (3754805, "大垣"),
    (3760077, "札幌西区"),
    (3779233, "盛岡"),
    (3797407, "事業部共通"),
    (3797418, "法人営業部"),
    (3797421, "今後予定店舗"),
    (3797427, "技術部共通"),
    (3797429, "本社共通"),
    (3800875, "四日市"),
    (3802118, "立川CC"),
    (3802119, "栃木"),
    (3802120, "マーケティング本部"),
    (3813625, "東日本事業部"),
    (3825904, "入間"),
]


def esc(s: str) -> str:
    return s.replace("'", "''")


def main() -> int:
    project = "ikeuchi-ga4"
    dataset = "mart_gbp"
    table = f"`{project}.{dataset}.places_provider_map`"
    values = []
    for store_id, store_name in STORES:
        display_esc = esc(store_name)
        values.append(
            f"  ('{store_id}', 'google', '', NULL, '{display_esc}', TRUE, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())"
        )
    sql = f"""-- places_provider_map: dim_store の全店舗を登録（provider_place_id は空。後で GBP location を UPDATE 可）
INSERT INTO {table} (store_code, provider, provider_place_id, provider_account_id, display_name, is_active, created_at, updated_at)
VALUES
""" + ",\n".join(values)
    out = Path(__file__).resolve().parents[1] / "sql" / "040_insert_places_provider_map.sql"
    out.write_text(sql, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
