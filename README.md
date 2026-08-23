# AI横断クイズ (trans-ai-quiz)

早押しクイズの問題文を各社 LLM へ送り、続きの補完と答えを比較する。
現在の実験の主対象は [`llm-poc`](docs/llm.md#llm-poc) である。

同一ネットワーク内で開催するオンライン早押し（投影 + スマホ）も持つ。
元になった 1 台完結の PoC（[`poc/`](docs/poc.md)）は凍結している。

## 構成

フロントは 3 つ（`llm-poc/`・オンライン版・凍結 `poc/`）。
`server/` は LLM 中継とオンライン版の早押し判定を担う共通バックエンドである。

出題データとジングル SE はリポジトリルートに置き、オンライン版と凍結 `poc/` で共有している。
`llm-poc` は問題データを使わない。

| ディレクトリ | 内容 |
| --- | --- |
| `llm-poc/` | LLM 予測比較の PoC。[詳細](docs/llm.md) |
| `web/` | オンライン版のフロントエンド。出題者用（投影）と回答者用（スマホ）。[詳細](docs/online.md) |
| `poc/` | **凍結**。音声読み上げによる早押しの PoC。[詳細](docs/poc.md) |
| `server/` | バックエンド（Python / FastAPI）。[LLM 中継](docs/llm.md) と [オンライン版の判定](docs/online.md) |
| `docs/` | 詳細ドキュメント |

```
trans-ai-quiz/
├── docs/          詳細ドキュメント
├── quiz_data/     問題データ（CSV と VOICEPEAK の出力）
├── sound/         ジングル SE
├── server/        バックエンド（オンライン版の判定・LLM 中継）
├── web/           オンライン版フロントエンド
├── llm-poc/       LLM 予測比較 PoC
└── poc/           音声早押し PoC（凍結）
```

## 必要なもの

- Node.js 20 以上
- オンライン版と `llm-poc` を動かす場合は、追加で Python 3.12 以上と [uv](https://docs.astral.sh/uv/)
- LLM 予測を使う場合は、各社の API キー

## セットアップ

```bash
npm install
```

npm workspaces 構成のため、リポジトリルートで実行する。

## llm-poc

`server` が起動している必要がある。

```bash
cp server/.env.example server/.env
cd server && uv run uvicorn app.main:app --port 8000
```

`server/.env` に使うプロバイダのキーを設定する。

| 環境変数 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Claude |
| `GEMINI_API_KEY` | Google Gemini |
| `XAI_API_KEY` | xAI Grok |

別のターミナルで:

```bash
npm run dev -w llm-poc
```

操作・記録・プロンプトは [docs/llm.md](docs/llm.md)。

## オンライン版

```bash
cp quiz_data/questions_example.csv quiz_data/questions.csv
npm run build -w web
cd server && uv sync && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

起動すると、出題者用 URL（トークン付き）と参加者用 URL が表示される。
`questions.csv` の検証に失敗した場合、サーバは起動するが `/host` `/player` `/ws` は 503 になる。

`--workers` は増やさないこと。ルームの状態はプロセス内のメモリに持つ。

問題は VOICEPEAK の音声（`.wav` / `.txt` / `.lab`）が無くても、`questions.csv` に
行を足すだけで出題できる（読み上げなし・1 文字ずつ等速の文字送りになる）。

問題データの形式は [docs/quiz-data.md](docs/quiz-data.md)。
開催手順・開発時の起動は [docs/online.md](docs/online.md)。
