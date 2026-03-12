# GBP の店舗コード（location リソース名）を取得する方法

`places_provider_map.provider_place_id` に設定する値は **GBP location リソース名**（`accounts/{accountId}/locations/{locationId}`）です。これを取得する手順です。

---

## ビジネスプロフィールマネージャの画面から利用する（スクリーンショット／UI）

**Google ビジネス プロフィール マネージャー**の「お店やサービス」一覧は、そのまま **provider_place_id** の材料になります。

1. **URL のグループ ID**  
   一覧の URL が `business.google.com/groups/114988638871901002510/locations` のとき、**114988638871901002510** が **accountId**（アカウント識別子）に対応する場合があります。  
   ※ API の `accounts.list` で取得する `accounts/{accountId}` の accountId と一致するかは、API で確認すると確実です。

2. **表の「店舗コード」列**  
   各店舗の長い数値（例: `13819288594183642477`, `11363935490739764488`）が、API の **locationId** に対応します。

3. **provider_place_id の組み立て**  
   - **accountId** = URL のグループ ID（または API で確認した accountId）  
   - **locationId** = 表の店舗コード  
   - **provider_place_id** = `accounts/{accountId}/locations/{locationId}`  
   例: `accounts/114988638871901002510/locations/13819288594183642477`

4. **places_provider_map との対応**  
   「ビジネス」列の店舗名（例: 池内自動車 習志野店 → **習志野**）と、dim_store の **store_name** または運用上の店舗コードを突き合わせ、**store_code** を決めてから UPDATE する。

**UPDATE 例（1 店舗）**

```sql
-- 例: 習志野店の店舗コードが 13819288594183642477、accountId が 114988638871901002510 の場合
-- dim_store の store_name='習志野' → store_code='3547889'
UPDATE `ikeuchi-ga4.mart_gbp.places_provider_map`
SET provider_place_id = 'accounts/114988638871901002510/locations/13819288594183642477',
    updated_at = CURRENT_TIMESTAMP()
WHERE store_code = '3547889' AND provider = 'google';
```

一覧を Excel や CSV にし、店舗名↔store_code の対応表を作ったうえで、上記のように UPDATE を並べても利用できます。**API（curl）で取得する方法**は以下で、一括・自動化向けです。

### 店舗コードが未入力・非表示の店舗がある場合

マネージャ画面で「店舗コード」列が空になっている店舗があります。その場合の対処は次のどちらかです。

**方法 1: API で一覧を取得する（推奨）**

API の **accounts.locations.list** では、**すべての location** に対して必ず **name**（= `accounts/{accountId}/locations/{locationId}`）が返ります。UI に店舗コードが出ていなくても、API には locationId が含まれています。

- 下記「curl で実行する」の 1) 2) を実行し、**locations 一覧**を取得する。
- 各 location の **name** がそのまま **provider_place_id**。
- **locationName**（店舗名）で dim_store の store_name と突き合わせ、store_code を決めて UPDATE すればよい。

これで「店舗コード未入力」の店舗も漏れなく provider_place_id を設定できます。

**方法 2: マネージャで店舗コードを入力する（任意）**

GBP マネージャの各店舗の編集画面で、「店舗コード」（外部用の識別子）を入力できる場合があります。これは **API の Location.storeCode** に相当し、**provider_place_id の locationId とは別**です。  
locationId は Google が付与するため、UI に数値が表示されない店舗は **API で name を取得する（方法 1）** のが確実です。

**方法 3: スクリプトで一括取得・UPDATE（推奨）**

リポジトリの **scripts/fetch_gbp_locations.py** が、API で locations を取得し、locationName と dim_store を突き合わせて **places_provider_map の provider_place_id を一括 UPDATE** します。

### スクリプト一覧

| スクリプト | 役割 |
|------------|------|
| **scripts/gbp_oauth_cli.py** | 認証〜locations 取得を CLI で実行。`get-refresh-token` / `get-access-token` / `fetch-locations` のサブコマンド。 |
| **scripts/fetch_gbp_locations.py** | GBP API で accounts → locations を取得し、`LOCATION_NAME_TO_STORE_CODE` で store_code を突き合わせて SQL 生成（および任意で BQ 更新）。429 時は 65 秒待って最大 3 回リトライ。 |
| **scripts/oauth_capture_code.py** | localhost:8080 で認証コードを受け取り、refresh_token を取得する単体ヘルパー（gbp_oauth_cli.py の get-refresh-token と同等）。 |
| **scripts/gbp_request_quota_access.py** | クォータが 0 のときに Basic API Access 申請フォームを開き、プロジェクト番号などを表示する。申請はフォームで手動送信。 |

**実行例（推奨）※ 機密を含むため共有リポジトリにコミットする前に削除すること**
```bash
cd /Users/masaaki/Documents/GitHub/review_observation
export CLIENT_ID="<YOUR_OAUTH_CLIENT_ID>"
export CLIENT_SECRET="<YOUR_OAUTH_CLIENT_SECRET>"
export REFRESH_TOKEN="<YOUR_REFRESH_TOKEN>"
python3 scripts/gbp_oauth_cli.py fetch-locations --dry-run
```

- **Python 3.10 以上を推奨**。Python 3.9 では `importlib.metadata` のエラー（`packages_distributions` がない）が出て失敗することがあります。`python3.10` や `python3.11` が入っていればそれを使う。
- トークンが取れない（401）場合: 下記「curl 0) 方法 A」で access_token を取得し、`--access-token=$ACCESS_TOKEN` を付けて実行する。

**CLI で一括操作（推奨）**

**scripts/gbp_oauth_cli.py** を使うと、認証〜locations 取得を CLI だけで実行できます。

```bash
cd /Users/masaaki/Documents/GitHub/review_observation
export CLIENT_ID="<YOUR_OAUTH_CLIENT_ID>"
export CLIENT_SECRET="<YOUR_OAUTH_CLIENT_SECRET>"
export REFRESH_TOKEN="<YOUR_REFRESH_TOKEN>"
python3 scripts/gbp_oauth_cli.py fetch-locations --dry-run
# 本実行時は --dry-run を外す: python3 scripts/gbp_oauth_cli.py fetch-locations
```
初回のみ refresh_token が必要な場合は `python3 scripts/gbp_oauth_cli.py get-refresh-token` を実行し、表示された REFRESH_TOKEN で上記を置き換える。

**従来どおり fetch_gbp_locations.py を直接実行する場合**

```bash
cd /path/to/review_observation

# 1) まず dry-run（UPDATE せず SQL のみ生成）
PYTHONPATH=. python3 scripts/fetch_gbp_locations.py --dry-run

# 401 のときは方法 A で ACCESS_TOKEN を取得してから:
# PYTHONPATH=. python3 scripts/fetch_gbp_locations.py --dry-run --access-token="$ACCESS_TOKEN"

# 2) 生成された sql/050_update_provider_place_id_from_gbp.sql を確認後、実行
# 手動で BQ に流すか、--dry-run を外してスクリプトで実行
PYTHONPATH=. python3 scripts/fetch_gbp_locations.py
```

- 突き合わせに使う店舗名はスクリプト内の `LOCATION_NAME_TO_STORE_CODE` で拡張できる。未一致の location は標準エラー出力に出す。

---

## 概要（API で取得する場合）

1. **Account Management API** でアカウント一覧を取得 → `accountId` を得る  
2. **My Business API (v4)** でそのアカウント配下の **locations** 一覧を取得 → 各 location の **name** が `accounts/{accountId}/locations/{locationId}`  
3. その **name** を `places_provider_map.provider_place_id` に UPDATE（store_code と対応付ける）

---

## 前提

- 同じ OAuth 2.0 認証（refresh_token）を使用。スコープに **`https://www.googleapis.com/auth/business.manage`** が必要。
- 取得用の **access_token** は、本リポジトリの `gbp_oauth.get_gbp_access_token()` や、Secret Manager の OAuth JSON から取得した refresh_token で取得したトークンを使う。
- **API の有効化**: OAuth クライアントを作成した **同じ GCP プロジェクト**で、次の API を有効にすること。
  - **My Business Account Management API**（`mybusinessaccountmanagement.googleapis.com`）… アカウント一覧用
  - **店舗（locations）一覧用**は次のいずれか。**My Business API v4**（`mybusiness.googleapis.com`）が 404 になる場合は **My Business Business Information API**（`mybusinessbusinessinformation.googleapis.com`）を有効にすること。スクリプトは v4 を試し、404 のとき自動で v1 にフォールバックする。
    - My Business API（`mybusiness.googleapis.com`）… v4
    - My Business Business Information API（`mybusinessbusinessinformation.googleapis.com`）… v1（v4 が 404 のとき使用）
  - v1 を有効にする: [コンソール](https://console.developers.google.com/apis/api/mybusinessbusinessinformation.googleapis.com/overview) で「有効にする」をクリック、または `gcloud services enable mybusinessbusinessinformation.googleapis.com --project=PROJECT_ID`
  - **レビュー（reviews）取得用**: アプリの `POST /`（定点観測）で `reviews.list` を呼ぶ場合は **My Business API**（`mybusiness.googleapis.com`）が有効である必要がある。無効だと 403 Forbidden。有効化: [コンソール](https://console.developers.google.com/apis/api/mybusiness.googleapis.com/overview?project=ikeuchi-data-sync) で「有効にする」、または `gcloud services enable mybusiness.googleapis.com --project=PROJECT_ID`（権限がない場合はコンソールから有効化）。
- **429 (レート制限) / クォータ 0**: 「Requests per minute」が 0 の場合はリクエストが受け付けられず 429 になる。スクリプトは 429 時に約 65 秒待って最大 3 回までリトライするが、**クォータ 0 のままでは必ず失敗する**。**クォータを上げるには**次のスクリプトで申請フォームを開き、手動で申請する: `python3 scripts/gbp_oauth_cli.py request-quota-access`（または `python3 scripts/gbp_request_quota_access.py`）。フォームで **「Application for Basic API Access」** を選択し、表示されるプロジェクト番号などを記入して送信する。承認されるとクォータ（例: 300 QPM）が付与される。既にクォータがある場合の増加は同フォームの **「Quota Increase Request」** を選択する。
- **承認後のクォータ**: Basic API Access 承認後、多くの場合 **300 リクエスト/分**（QPM）が付与される。本スクリプトは 1 回の実行で accounts.list が 1 回＋各アカウントの locations.list が数回（ページネーション分）程度のため、通常は 300/分を超えず、追加のスロットリングは不要。連続で何度も実行する場合のみ、1 分あたりの実行回数に注意する。

### GUI でクォータを申請する方法（URL）

クォータ申請は **API では行えません**。Google のウェブフォーム（GUI）で申請する。

**申請フォーム URL**

- **https://support.google.com/business/contact/api_default**

**手順**

1. 上記 URL をブラウザで開く。
2. ページ内のドロップダウンで次を選択する。
   - **クォータが 0 のとき（初回）**: **「Application for Basic API Access」**
   - **すでにクォータがあり増やしたいとき**: **「Quota Increase Request」**
3. フォームの項目に従って記入する（プロジェクト番号: `957418534824` など）。
4. 送信後、審査結果はメール等で通知される。承認されると GCP の「割り当て」でクォータが付与される。

フォームを開くだけなら `python3 scripts/gbp_oauth_cli.py request-quota-access` を実行してもよい。

**サポートケースに回答がない場合の対処**

「5 営業日以内にメールでお知らせ」とあっても、返信が遅い・届かない事例が報告されている。次のいずれかを試す。

1. **同じフォームで再送・フォローアップ**
   - [https://support.google.com/business/contact/api_default](https://support.google.com/business/contact/api_default) を再度開く。
   - 「Application for Basic API Access」を選択し、**既存のケース ID（例: 4-9801000040318）を本文に明記**して「前回申請から○日経過し回答がないため、フォローアップです」と送信する。

2. **Business Profile コミュニティで質問**
   - [Business Profile コミュニティ](https://support.google.com/business/community) で投稿する。タイトル先頭に **`[API]`** を付けると対応されやすい。
   - 例: 「[API] Application for Basic API Access の申請後、ケース ID 4-9801000040318 で 5 営業日過ぎても返信がない」

3. **開発者向けサポート案内**
   - [Business Profile APIs - Support](https://developers.google.com/my-business/content/support) に連絡方法の一覧がある。API 関連は同ページの「Contact support」から同じフォームへ誘導される。

4. **届いたメールに返信**
   - ケース登録時のメールに返信できる場合は、そのスレッドに「ご確認ください」と返信するとケースが再オープンされることがある。

**プロジェクト番号の確認方法**

- **GCP コンソール**: [Google Cloud Console](https://console.cloud.google.com/) を開く → 画面上部のプロジェクト名の横の **プロジェクトを選択**（またはホーム）→ 一覧の **「ID」** 列がプロジェクト ID。「番号」または「プロジェクト番号」の列があればそれがプロジェクト番号。ない場合は、対象プロジェクトを選択した状態で **☰ → ホーム** または **☰ → IAM と管理 → 設定** で「プロジェクト番号」を確認できる。
- **gcloud**: `gcloud projects describe ikeuchi-data-sync --format="value(projectNumber)"` でプロジェクト ID からプロジェクト番号を取得できる（プロジェクト ID は `ikeuchi-data-sync` など）。

### API が「読み込めませんでした」となる場合

ブラウザで `mybusiness.googleapis.com` のページが開けないときは、次のいずれかを試す。

1. **ライブラリから検索して有効化**
   - GCP コンソール → **API とサービス** → **ライブラリ**
   - 検索ボックスで **「My Business」** または **「Business Profile」** を検索
   - **「My Business API」** または **「Google My Business API」** を開き、**有効にする** をクリック

2. **gcloud で有効化**（プロジェクト ID は `ikeuchi-data-sync` など実際の値に置き換える）
   ```bash
   gcloud services enable mybusinessaccountmanagement.googleapis.com --project=PROJECT_ID
   gcloud services enable mybusiness.googleapis.com --project=PROJECT_ID
   # v4 が 404 のときは Business Information API も有効にする
   gcloud services enable mybusinessbusinessinformation.googleapis.com --project=PROJECT_ID
   ```

3. しばらく時間をおいてから再度ブラウザで開く（コンソールの一時的な不調のことがある）。

---

## Step 1: アカウント一覧の取得

**エンドポイント**

```http
GET https://mybusinessaccountmanagement.googleapis.com/v1/accounts
Authorization: Bearer <access_token>
```

**レスポンス例**

```json
{
  "accounts": [
    {
      "name": "accounts/12345678901234567890",
      "accountName": "マイビジネスアカウント",
      "type": "PERSONAL",
      "role": "OWNER",
      ...
    }
  ],
  "nextPageToken": "..."
}
```

- **name** が `accounts/{accountId}` の形式。この **accountId**（例: `12345678901234567890`）を Step 2 で使う。  
- 複数アカウントがある場合は `nextPageToken` で次ページを取得。

---

## Step 2: 店舗（locations）一覧の取得

**エンドポイント**

```http
GET https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations?pageSize=100
Authorization: Bearer <access_token>
```

Step 1 で得た **accountId** をそのまま URL に埋める。

**レスポンス例**

```json
{
  "locations": [
    {
      "name": "accounts/12345678901234567890/locations/98765432109876543210",
      "storeCode": "KAWAGOE",
      "locationName": "川越店",
      "languageCode": "ja",
      "primaryPhone": "...",
      "address": { ... },
      ...
    }
  ],
  "nextPageToken": "...",
  "totalSize": 30
}
```

- **name**: これが **provider_place_id** に格納する値（`accounts/{accountId}/locations/{locationId}`）。  
- **storeCode**: GBP 側で設定した外部用店舗コード（任意・アカウント内で一意）。dim_store の store_code と一致させている場合はこれで突き合わせ可能。  
- **locationName**: 店舗の表示名。dim_store の store_name と突き合わせて store_code を決めてもよい。

100 件超の場合は `nextPageToken` で `pageToken=...` を付けて続きを取得。

---

## Step 3: places_provider_map の UPDATE

取得した各 location の **name** を、対応する **store_code** の行の **provider_place_id** に設定する。

**例（1 店舗）**

```sql
UPDATE `ikeuchi-ga4.mart_gbp.places_provider_map`
SET provider_place_id = 'accounts/12345678901234567890/locations/98765432109876543210',
    updated_at = CURRENT_TIMESTAMP()
WHERE store_code = '3547880' AND provider = 'google';
```

- **store_code** と GBP の対応は、**locationName** や **storeCode** と dim_store の store_name / 運用上のコードを突き合わせて決める。  
- 一括で対応表（CSV や JSON）を作り、複数行を UPDATE するスクリプトを書いてもよい。

---

## refresh_token を初めて取得する（OAuth 同意画面）

**「アクセスをブロック: リクエストは無効です」が出る場合**  
Google は `urn:ietf:wg:oauth:2.0:oob`（OOB）を廃止しているため、**OAuth 2.0 Playground** または **localhost リダイレクト**を使います。

---

### 方法: OAuth 2.0 Playground（ブラウザのみで取得）

コンソール（ブラウザ）上だけで refresh_token を取得できます。

1. **OAuth クライアントを「ウェブアプリケーション」にする**
   - GCP コンソール → **API とサービス** → **認証情報** → 使用する OAuth クライアントを開く
   - 種類が「デスクトップアプリ」の場合は、**「ウェブアプリケーション」** のクライアントを新規作成するか、既存のウェブ用クライアントを使う
   - **承認済みのリダイレクト URI** に **`https://developers.google.com/oauthplayground`** を追加 → **保存**

2. **OAuth 2.0 Playground を開く**
   - [https://developers.google.com/oauthplayground](https://developers.google.com/oauthplayground) を開く

3. **独自の認証情報を使う**
   - 右上の **歯車アイコン** をクリック
   - **「Use your own OAuth credentials」** にチェック
   - **OAuth Client ID** と **OAuth Client secret** に、手順 1 のクライアントの値を入力

4. **スコープを指定して認証**
   - 左側の「Step 1」で **「Input your own scopes」** に  
     `https://www.googleapis.com/auth/business.manage` を入力（既存のスコープは削除してこの 1 つだけでも可）
   - **「Authorize APIs」** をクリック → Google でログインし、「アクセスを許可」

5. **トークンを取得**
   - 「Step 2」で **「Exchange authorization code for tokens」** をクリック
   - レスポンスに **refresh_token** が表示される。これをコピーして保存し、環境変数で使う:
     ```bash
     export REFRESH_TOKEN="1//0g..."
     ```

※ Playground が使えるのは **ウェブアプリケーション** タイプの OAuth クライアントのみです。既存クライアントが「デスクトップ」の場合は、下記 localhost 方式か、新規で「ウェブアプリケーション」クライアントを作成してください。

---

### 方法: localhost で取得（oauth_capture_code.py）

1. **GCP コンソールでリダイレクト URI を追加**
   - [Google Cloud Console](https://console.cloud.google.com/) → 対象プロジェクト → **API とサービス** → **認証情報**
   - OAuth 2.0 クライアント（例: review_observation_gbp）を開く
   - **承認済みのリダイレクト URI** に **`http://localhost:8080`** を追加 → **保存**
   - 反映に数分かかることがあります

2. **環境変数を設定**
   ```bash
   export CLIENT_ID="あなたのクライアントID.apps.googleusercontent.com"
   export CLIENT_SECRET="GOCSPX-xxx"
   ```

3. **ローカルサーバーを起動して認証**
   ```bash
   cd /path/to/review_observation
   python3 scripts/oauth_capture_code.py
   ```
   - 表示された URL をブラウザで開く
   - Google でログインし、「アクセスを許可」をクリック
   - ブラウザが localhost:8080 にリダイレクトされたら、タブを閉じてターミナルに戻る
   - ターミナルに **refresh_token** が表示される。表示された `export REFRESH_TOKEN="..."` をコピーして実行する

4. その後、下記「方法 A」で access_token を取得し、スクリプトや curl で API を呼び出す。

---

## リクエスト方法一覧

### 推奨: CLI で一括実行

```bash
cd /Users/masaaki/Documents/GitHub/review_observation
export CLIENT_ID="<YOUR_OAUTH_CLIENT_ID>"
export CLIENT_SECRET="<YOUR_OAUTH_CLIENT_SECRET>"
export REFRESH_TOKEN="<YOUR_REFRESH_TOKEN>"
python3 scripts/gbp_oauth_cli.py fetch-locations --dry-run
```

上記で内部的に「0) access_token 取得 → 1) accounts → 2) locations」の順で API を呼ぶ。

---

### API を直接呼ぶ場合（curl）

| 段階 | メソッド | エンドポイント |
|------|----------|----------------|
| access_token 取得 | POST | `https://oauth2.googleapis.com/token`（body: client_id, client_secret, refresh_token, grant_type=refresh_token） |
| 1) アカウント一覧 | GET | `https://mybusinessaccountmanagement.googleapis.com/v1/accounts` |
| 2) 店舗一覧 | GET | `https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations?pageSize=100` |
| 2 の次ページ | GET | 上記に `&pageToken={nextPageToken}` を付与 |

すべて **Authorization: Bearer {access_token}** ヘッダーが必要（access_token 取得を除く）。

---

## curl で実行する

### 0) 変数を設定してから実行する

次の変数を設定しておく。**機密を含むため共有リポジトリにコミットする前に削除すること。** 1) 実行後に `ACCOUNT_ID` を設定し、2) で `nextPageToken` が出たら `PAGE_TOKEN` も設定する。

```bash
# 認証用（方法 A の curl でそのまま使う。Secret Manager や OAuth クライアントの値に置換）
export CLIENT_ID="<YOUR_OAUTH_CLIENT_ID>"
export CLIENT_SECRET="<YOUR_OAUTH_CLIENT_SECRET>"
export REFRESH_TOKEN="<YOUR_REFRESH_TOKEN>"

# 0) のあと、方法 A で ACCESS_TOKEN が入る。1) のレスポンスから ACCOUNT_ID を設定する。
# export ACCOUNT_ID="12345678901234567890"
# 2) で nextPageToken が出た場合のみ
# export PAGE_TOKEN="CjQK..."
```

### 0) access_token を用意する（必須）

**401 UNAUTHENTICATED が出る場合は、`ACCESS_TOKEN` が未設定または期限切れです。** 必ず 0) を実行してから 1) 以降の curl を実行する。

**access_token は取得できたが、accounts や locations の API 呼び出しで 401 になる場合**

- **スコープ**: refresh_token 取得時の OAuth 同意で **`https://www.googleapis.com/auth/business.manage`** が含まれている必要があります。別スコープ（例: cloud-platform のみ）で取ったトークンでは My Business API は使えません。
- **API 有効化**: Google Cloud コンソールで対象プロジェクトに **Business Profile API**（および Account Management API）が有効になっているか確認してください。
- **トークン期限**: access_token の有効期限は約 1 時間です。長時間経過した場合は方法 A で再取得してください。
- スクリプトは 401 時に API のエラー本文を標準エラーに出力するので、メッセージで原因を確認できます。

**方法 A: refresh_token から取得（上記で export した変数をそのまま使う）**

```bash
RESP=$(curl -s -X POST "https://oauth2.googleapis.com/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "refresh_token=${REFRESH_TOKEN}" \
  -d "grant_type=refresh_token")
export ACCESS_TOKEN=$(echo "$RESP" | jq -r '.access_token')
echo "ACCESS_TOKEN length: ${#ACCESS_TOKEN}"
```

**方法 B: 既に取得済みのトークンを export する**

```bash
export ACCESS_TOKEN="ya29.xxxx..."
```

**方法 C: 本リポジトリの Python で取得し、その場で export（Secret Manager に gbp-oauth-json が登録済みの場合）**

```bash
cd /path/to/review_observation
export ACCESS_TOKEN=$(python3 -c "
from src.config import GBP_OAUTH_SECRET_NAME, GCP_PROJECT
from src import gbp_oauth
print(gbp_oauth.get_gbp_access_token(GBP_OAUTH_SECRET_NAME, GCP_PROJECT))
")
echo "Token length: ${#ACCESS_TOKEN}"
```

その後、同じシェルで 1) 2) の curl を実行する。

---

### 1) アカウント一覧を取得

```bash
curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://mybusinessaccountmanagement.googleapis.com/v1/accounts" | jq .
```

レスポンスの `accounts[].name` が `accounts/1234567890` の形式。`/` の後ろが **accountId**。次で使うため変数にしておく:

```bash
export ACCOUNT_ID="12345678901234567890"   # 上記レスポンスの name から取得
```

---

### 2) 店舗（locations）一覧を取得

```bash
curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://mybusiness.googleapis.com/v4/accounts/${ACCOUNT_ID}/locations?pageSize=100" | jq .
```

各 `locations[].name` が **provider_place_id** に設定する値（`accounts/{accountId}/locations/{locationId}`）。  
`storeCode` / `locationName` で dim_store と突き合わせる。

---

### 3) 2) で nextPageToken が返った場合（2 ページ目以降）

```bash
export PAGE_TOKEN="CjQK..."   # 2) のレスポンスの nextPageToken の値

curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://mybusiness.googleapis.com/v4/accounts/${ACCOUNT_ID}/locations?pageSize=100&pageToken=${PAGE_TOKEN}" | jq .
```

---

### 4) 一括で name だけ取り出す例

```bash
curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://mybusiness.googleapis.com/v4/accounts/${ACCOUNT_ID}/locations?pageSize=100" \
  | jq -r '.locations[]? | "\(.name)\t\(.storeCode // "")\t\(.locationName // "")"'
```

出力はタブ区切り: `provider_place_id` / `storeCode` / `locationName`。  
複数ページ時は `PAGE_TOKEN` を設定して 3) の curl を繰り返し、同様に jq で取り出す。

---

## Python での取得例（本リポジトリの認証を利用）

```python
import os
import requests
from src.config import GBP_OAUTH_SECRET_NAME, GCP_PROJECT
from src import gbp_oauth

token = gbp_oauth.get_gbp_access_token(GBP_OAUTH_SECRET_NAME, GCP_PROJECT)

# アカウント一覧
r = requests.get(
    "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
    headers={"Authorization": f"Bearer {token}"},
    timeout=30,
)
r.raise_for_status()
accounts = r.json().get("accounts", [])
for acc in accounts:
    name = acc.get("name", "")  # accounts/123...
    if not name.startswith("accounts/"):
        continue
    account_id = name.replace("accounts/", "").split("/")[0]
    # 店舗一覧
    r2 = requests.get(
        f"https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations",
        params={"pageSize": 100},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r2.raise_for_status()
    data = r2.json()
    for loc in data.get("locations", []):
        print(loc.get("name"), loc.get("storeCode"), loc.get("locationName"))
```

---

## 参照

- [Account Management API: accounts.list](https://developers.google.com/my-business/reference/accountmanagement/rest/v1/accounts/list)
- [My Business API v4: accounts.locations.list](https://developers.google.com/my-business/reference/rest/v4/accounts.locations/list)
- [Location リソース](https://developers.google.com/my-business/reference/rest/v4/accounts.locations#Location)（name / storeCode / locationName）
- 本リポジトリ: [docs/店舗マスタ参照.md](店舗マスタ参照.md)（provider_place_id の論理名と UPDATE の位置づけ）
