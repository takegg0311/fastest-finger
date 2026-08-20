# fastest-finger

VOICEPEAK で作成した音声を用いた早押しクイズ WEB アプリ（PoC）。

音声の再生に合わせて問題文が少しずつ表示され、早押しで停止・回答できる。
バックエンドを持たないフロントエンド単体構成。

## 必要なもの

- Node.js 20 以上

## セットアップ

```bash
npm install
```

### 出題データの配置

**出題データとジングル SE はリポジトリに含まれていない**（`.gitignore` で除外）。
各自でローカルに配置する。

ただしデータ形式のサンプルとして、`questions_example.csv` と
対応する 1 問分の音声（`20260820/0.wav` / `.txt` / `.lab`）のみ追跡している。
`questions_example.csv` を `questions.csv` にコピーすれば、この 1 問で動作する。

```bash
cp public/quiz_data/questions_example.csv public/quiz_data/questions.csv
```

#### 1. 問題データ — `public/quiz_data/`

問題文と正解は `questions.csv` で管理し、VOICEPEAK の出力ファイルは
**リネームせず**バッチ（日付）フォルダにそのまま置く。

```
public/quiz_data/
├── questions_example.csv   ← サンプル（追跡対象）
├── questions.csv           ← 実データ（各自で用意）
└── 20260820/          ← バッチ = VOICEPEAK プロジェクト 1 つ
    ├── 0.wav / 0.txt / 0.lab
    └── 1.wav / 1.txt / 1.lab
```

`questions.csv` は 5 列。

```csv
batch,seq,text,answer,alt_answers
20260820,0,日本で一番高い山は富士山ですが、世界で一番高い山はどこ？,エベレスト,
20260820,1,大蛇を意味する名を持つプログラミング言語は何でしょう？,Python,パイソン|ニシキヘビ
```

| 列 | 内容 |
| --- | --- |
| `batch` | バッチ名（`YYYYMMDD`）。`public/quiz_data/{batch}/` に対応 |
| `seq` | VOICEPEAK が出力した連番（0 起点）。`{seq}.wav` などに対応 |
| `text` | 問題文。**改行を含めない**（1 問 1 ブロック） |
| `answer` | 正解 |
| `alt_answers` | 別解。`\|` 区切りで複数指定可。無ければ空 |

VOICEPEAK は連番を 0 起点でしか振れず接頭語も付けられないため、
バッチフォルダと連番の組で一意性を与えている。

##### 問題を追加する手順

1. `questions.csv` の `text` 列を表計算ソフトでまとめて選択し、VOICEPEAK に貼り付ける
   （改行がそのままブロック分割になる）
2. `public/quiz_data/{バッチ名}/` へ連番出力する（接尾語なし）
3. `npm run manifest` を実行する

CSV の `text` と出力された `.txt` の中身が一致しない場合、
どの行がズレているかを報告してビルドが止まる。
同日に作り直す場合は、同じフォルダへ先頭から再出力する。

#### 2. ジングル SE — `public/sound/`

| ファイル名 | 再生タイミング |
| --- | --- |
| `set.WAV` | 出題時（この再生完了後に問題音声が始まる） |
| `buzz.WAV` | 早押し時 |
| `correct.WAV` | 正解時 |
| `wrong.WAV` | 不正解時 |

## 起動

```bash
npm run dev
```

`npm run dev` / `npm run build` は、実行前に `questions.csv` を読んで
問題一覧 `manifest.json` を自動生成する。データを追加・削除した際は再実行する。

manifest だけを作り直したい場合:

```bash
npm run manifest
```

## 操作

1. 「開始」を押すとジングルが鳴り、続いて問題音声が再生される
2. 再生に合わせて問題文が表示されていく
3. **スペースキー** または画面中央のボタンで早押し（音声と表示が止まる）
4. 答えを入力して「回答」を押すと正誤判定
5. 「次へ」で次の問題へ

早押しせずに最後まで再生された場合も、そのまま回答できる。

## 仕組み

### 音声と問題文の同期

音素ラベル（`.lab`）と日本語表記（`.txt`）は文字数が対応しないため
（例: 「日本」= `n i cl p o N`）、以下の方式で対応付けている。

1. `.lab` の無音区間（`pau`）で音声を発話チャンクに分割する
2. `.txt` を読点・句点で同数のチャンクに分割し、順に対応付ける
3. チャンク内部は、時間の経過割合に応じて文字を送る

VOICEPEAK の読み上げでは `pau` が読点の位置とよく一致するため、
チャンクの境目で表示が実際の読み位置に追従する。

同期ロジックは [`src/lib/align.ts`](src/lib/align.ts) に閉じ込めてあり、
より高精度な方式（読み仮名を付与して音素列とアライメント）へ差し替えられる。

## 構成

```
scripts/build-manifest.ts   questions.csv の検証と manifest.json の生成
src/
├── App.tsx                 画面全体と音声再生の制御
├── state/quizMachine.ts    出題サイクルの状態遷移
├── lib/
│   ├── lab.ts              .lab パーサ（HTK 形式 → 秒、pau 区間の抽出）
│   ├── align.ts            音声と問題文の対応付け
│   ├── answer.ts           正誤判定（正解・別解との照合）
│   ├── manifest.ts         問題の読み込みと抽選
│   └── sound.ts            ジングル SE の再生
└── components/             画面パーツ
```

## スコープ外

Python バックエンド化と、出題者用/回答者用を分けたオンライン早押し
（同一ネットワーク内での最速判定）は本 PoC には含まない。
