/**
 * public/quiz_data を走査して問題一覧 manifest.json を生成する。
 *
 * PoC はバックエンドを持たないため、ブラウザからディレクトリ一覧を取得できない。
 * 代わりにビルド前へこのスクリプトを挟み、wav/txt/lab が揃った問題だけを列挙する。
 */
import { readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = fileURLToPath(new URL('..', import.meta.url));
const quizDataDir = join(projectRoot, 'public', 'quiz_data');
const manifestPath = join(quizDataDir, 'manifest.json');

/** 3 点セットのうち欠けている拡張子があれば、その問題は出題対象から外す */
const REQUIRED_EXTENSIONS = ['.wav', '.txt', '.lab'] as const;

type Entry = {
  /** 拡張子を除いたファイル名。そのままクイズの正解となる */
  id: string;
  wav: string;
  txt: string;
  lab: string;
};

function splitExtension(fileName: string): { stem: string; ext: string } {
  const dotIndex = fileName.lastIndexOf('.');
  if (dotIndex <= 0) return { stem: fileName, ext: '' };
  return {
    stem: fileName.slice(0, dotIndex),
    ext: fileName.slice(dotIndex).toLowerCase(),
  };
}

function buildManifest(): Entry[] {
  let fileNames: string[];
  try {
    fileNames = readdirSync(quizDataDir);
  } catch {
    console.error(
      `[manifest] ${quizDataDir} を読み取れませんでした。` +
        'VOICEPEAK で出力した wav/txt/lab の 3 点セットを配置してください。',
    );
    return [];
  }

  // stem ごとに、見つかった拡張子と実ファイル名を集める
  const found = new Map<string, Map<string, string>>();
  for (const fileName of fileNames) {
    const { stem, ext } = splitExtension(fileName);
    if (!REQUIRED_EXTENSIONS.includes(ext as (typeof REQUIRED_EXTENSIONS)[number])) continue;
    const byExt = found.get(stem) ?? new Map<string, string>();
    byExt.set(ext, fileName);
    found.set(stem, byExt);
  }

  const entries: Entry[] = [];
  for (const [stem, byExt] of [...found].sort(([a], [b]) => a.localeCompare(b, 'ja'))) {
    const missing = REQUIRED_EXTENSIONS.filter((ext) => !byExt.has(ext));
    if (missing.length > 0) {
      console.warn(`[manifest] ${stem}: ${missing.join(', ')} が無いためスキップします`);
      continue;
    }
    entries.push({
      id: stem,
      wav: byExt.get('.wav')!,
      txt: byExt.get('.txt')!,
      lab: byExt.get('.lab')!,
    });
  }
  return entries;
}

const entries = buildManifest();
writeFileSync(manifestPath, `${JSON.stringify(entries, null, 2)}\n`, 'utf8');
console.log(`[manifest] ${entries.length} 問を ${manifestPath} に書き出しました`);
for (const entry of entries) console.log(`  - ${entry.id}`);
