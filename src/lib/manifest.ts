/**
 * 問題一覧の読み込みと抽選。
 *
 * manifest.json はビルド前に scripts/build-manifest.ts が生成する。
 * バックエンドが無くブラウザからディレクトリ一覧を取得できないため。
 */
import { parseLab, type LabFile } from './lab';
import { buildAlignment, type Alignment } from './align';

const QUIZ_DATA_DIR = '/quiz_data';

export type ManifestEntry = {
  /** 拡張子を除いたファイル名。そのままクイズの正解となる */
  id: string;
  wav: string;
  txt: string;
  lab: string;
};

export type Question = {
  id: string;
  /** 音声ファイルの URL */
  audioUrl: string;
  text: string;
  lab: LabFile;
  alignment: Alignment;
};

function encodePath(fileName: string): string {
  return `${QUIZ_DATA_DIR}/${encodeURIComponent(fileName)}`;
}

export async function loadManifest(): Promise<ManifestEntry[]> {
  const response = await fetch(`${QUIZ_DATA_DIR}/manifest.json`);
  if (!response.ok) {
    throw new Error(
      'manifest.json を読み込めませんでした。`npm run manifest` を実行してください。',
    );
  }
  const entries: unknown = await response.json();
  if (!Array.isArray(entries)) {
    throw new Error('manifest.json の形式が不正です。');
  }
  return entries as ManifestEntry[];
}

export async function loadQuestion(entry: ManifestEntry): Promise<Question> {
  const [text, labText] = await Promise.all([
    fetch(encodePath(entry.txt)).then((r) => {
      if (!r.ok) throw new Error(`${entry.txt} を読み込めませんでした。`);
      return r.text();
    }),
    fetch(encodePath(entry.lab)).then((r) => {
      if (!r.ok) throw new Error(`${entry.lab} を読み込めませんでした。`);
      return r.text();
    }),
  ]);

  const lab = parseLab(labText);
  const trimmedText = text.trim();

  return {
    id: entry.id,
    audioUrl: encodePath(entry.wav),
    text: trimmedText,
    lab,
    alignment: buildAlignment(trimmedText, lab),
  };
}

/**
 * 次の問題を 1 問選ぶ。
 * 直前と同じ問題が続くのを避けるため、候補が 2 問以上あるときは exclude を除外する。
 */
export function pickRandom(
  entries: ManifestEntry[],
  exclude?: string,
): ManifestEntry | undefined {
  if (entries.length === 0) return undefined;

  const candidates =
    entries.length > 1 && exclude !== undefined
      ? entries.filter((entry) => entry.id !== exclude)
      : entries;
  const pool = candidates.length > 0 ? candidates : entries;

  return pool[Math.floor(Math.random() * pool.length)];
}
