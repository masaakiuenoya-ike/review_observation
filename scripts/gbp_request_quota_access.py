#!/usr/bin/env python3
"""
GBP API のクォータが 0 のとき、Basic API Access を申請するためのフォームを開き、
申請に必要な情報（プロジェクト番号など）を表示する。

Google はクォータ申請を API で受け付けておらず、ウェブフォームでの申請が必要。
このスクリプトはフォームを開き、コピペ用の情報を出すだけなので、
申請そのものはユーザーがフォームに記入して送信する。
"""
from __future__ import annotations

import sys
import webbrowser

# ikeuchi-data-sync の OAuth クライアントから得たプロジェクト番号
PROJECT_NUMBER = "957418534824"
FORM_URL = "https://support.google.com/business/contact/api_default"
# 申請種別: フォームのドロップダウンで「Application for Basic API Access」を選択する


def main() -> int:
    print("GBP API のクォータ申請（Basic API Access）")
    print()
    print("次の URL をブラウザで開き、フォームで「Application for Basic API Access」を選択して申請してください。")
    print(FORM_URL)
    print()
    print("--- 申請時に必要な情報（コピペ用）---")
    print(f"プロジェクト番号（Project Number）: {PROJECT_NUMBER}")
    print("  ※ GCP コンソールの「ホーム」または「プロジェクトの設定」で確認可能。")
    print()
    print("前提条件（Google の案内）:")
    print("  - ビジネスを代表するウェブサイトがあること")
    print("  - 確認済みで 60 日以上アクティブな Google ビジネスプロフィールを管理していること")
    print("  - 申請メールアドレスがそのプロフィールのオーナー/マネージャーであること")
    print()
    try:
        webbrowser.open(FORM_URL)
        print("ブラウザでフォームを開きました。")
    except Exception as e:
        print(f"ブラウザを開けませんでした: {e}", file=sys.stderr)
        print("上記 URL を手動で開いてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
