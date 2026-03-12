# GBP reviews API 実装メモ（調査結果・評価）

## 1. API の選択（v4 のままである理由）

- **reviews.list** は **My Business API v4**（`mybusiness.googleapis.com/v4/.../reviews`）で提供されている。
- **Business Information API v1**（`mybusinessbusinessinformation.googleapis.com`）には **reviews の代替エンドポイントはない**。
- 公式の [Deprecation schedule](https://developers.google.com/my-business/content/sunset-dates) にも **accounts.locations.reviews** の廃止は記載されていない。
- そのため、**reviews 取得は v4 を利用する実装で問題ない**。

参照:
- [accounts.locations.reviews.list (v4)](https://developers.google.com/my-business/reference/rest/v4/accounts.locations.reviews/list)
- [Business Profile APIs is missing endpoints for Listing Reviews (Issue #2456)](https://github.com/googleapis/google-api-go-client/issues/2456) … v1 に reviews がない旨の言及あり

---

## 2. リクエストが返らず「fetch で止まる」原因

### 2.1 requests の timeout が DNS に効かない

- **`requests.get(..., timeout=(3, 5))` の timeout は「接続」と「読み取り」にのみ適用される。**
- **DNS 名前解決は OS 側で行われるため、requests の timeout の対象外**であり、DNS が遅い・ブロックされると **そこでハング** する。
- 参考: [timeout does not apply to name resolution (psf/requests#4531)](https://github.com/psf/requests/issues/4531)

### 2.2 実装での対策（本リポジトリ）

1. **DNS の事前解決に短いタイムアウトを付与**
   - `socket.getaddrinfo(host, 443)` を **別スレッド** で実行し、`join(timeout=3)` で最大 3 秒待つ。
   - この時間内に解決しなければ `TimeoutError` を上げ、その店舗はエラーとしてスキップする。

2. **HTTP GET 全体をスレッドで実行し、最大待ち時間で打ち切り**
   - `requests.get(...)` を別スレッドで実行し、メインスレッドでは `join(timeout=11)` のみ待つ。
   - 11 秒以内にスレッドが終わらなければ「応答が返らなかった」として `TimeoutError` を上げる。
   - これにより、1 店舗あたり最大約 3（DNS）+ 11（GET）= 14 秒で打ち切る。31 店舗で最大約 7 分かかるため、`curl --max-time 420` などで余裕を持って呼ぶとよい。

上記により「fetch で永久に止まる」事態は避ける設計にしている。

---

## 3. 403 Forbidden になる主な要因

- **My Business API**（`mybusiness.googleapis.com`）がプロジェクトで **有効になっていない**、または **Basic API Access 未申請・未承認** でクォータが 0 のまま。
- **OAuth スコープ** に `https://www.googleapis.com/auth/business.manage`（または `plus.business.manage`）が含まれていない。
- 有効化・申請直後は **反映に数分かかることがある**。

対処:
- GCP コンソールで「Google My Business API」を有効化する。
- クォータ 0 の場合は [Basic API Access の申請](https://support.google.com/business/contact/api_default) を行う。
- 詳細は [GBPの店舗コード取得方法.md](GBPの店舗コード取得方法.md) を参照。

---

## 4. 実装の評価まとめ

| 項目 | 評価 | 備考 |
|------|------|------|
| エンドポイント (v4 reviews) | ✅ 問題なし | reviews は v4 のみ。v1 に代替なし。 |
| URL 形式 | ✅ 問題なし | `accounts/{accountId}/locations/{locationId}/reviews` で正しい。 |
| OAuth スコープ | ✅ 問題なし | `business.manage` を使用。 |
| タイムアウト | ✅ 対策済み | DNS 事前解決＋スレッドで GET 全体に最大待ち時間を設定。 |
| 403 時の挙動 | ✅ 問題なし | 店舗単位でエラーにし、他店舗は継続。 |
| ハング防止 | ✅ 対策済み | スレッド＋join(timeout) で長時間ブロックを防止。 |

---

## 5. 環境依存で起きうること

- **社内ネットワーク・ファイアウォール** で `mybusiness.googleapis.com` への接続がブロック／遅延している場合、DNS や TCP 接続で止まることがある。
- その場合は **別ネットワーク（例: 自宅・モバイル）** で試すと、すぐ 403 や 200 が返るかどうか切り分けしやすい。
- **IPv6** で名前解決や接続が遅い環境では、IPv4 に寄せる設定をすると改善する場合がある。
