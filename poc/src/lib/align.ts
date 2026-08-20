/**
 * 音声の再生位置から「問題文を何文字目まで表示すべきか」を求める。
 *
 * 音素列（.lab）と日本語表記（.txt）は文字数が対応しない（例: 「日本」= n i cl p o N）。
 * ブラウザ内で形態素解析なしに厳密なアライメントは解けないため、次の方式を採る:
 *
 *   1. .lab の無音（pau）で音声を発話チャンクに分割する
 *   2. .txt を読点・句点で同数のチャンクに分割し、順に対応付ける
 *   3. チャンク内部は、そのチャンクの時間幅に対する経過時間の比例配分で文字を送る
 *
 * pau は問題文の読点位置とよく一致するため、チャンク境界では表示が実際の読みに追従する。
 *
 * ただし pau は読点位置だけでなく文中の息継ぎにも現れるため、1. と 2. の個数は
 * しばしば一致しない。そのまま先頭から対応付けると読点でない pau が境界として
 * 採用され、表示が音声から大きくずれる。そこで数が合わない場合は、多い側を
 * 少ない側の個数へ統合してから対応付ける（mergeSegments / mergeTextChunks を参照）。
 *
 * より高精度な方式（読み仮名を付与して音素列とアライメント）へ差し替えられるよう、
 * 同期ロジックはこのモジュールに閉じ込めてある。外部へ公開するのは buildAlignment と
 * visibleLength のみで、この 2 つの契約さえ保てば内部方式は入れ替えられる。
 */
import type { LabFile, SpeechSegment } from './lab';

/** チャンク境界とみなす文字。VOICEPEAK の読み上げはこれらの位置で pau が入りやすい */
const CHUNK_DELIMITERS = /[、。，．？！?!]/;

/** 対応付けられた 1 チャンク分の情報 */
type AlignedChunk = {
  /** このチャンクが始まる時刻（秒） */
  start: number;
  /** このチャンクが終わる時刻（秒） */
  end: number;
  /** 問題文全体における、このチャンク開始時点の表示済み文字数 */
  charStart: number;
  /** 問題文全体における、このチャンク終了時点の表示済み文字数 */
  charEnd: number;
};

export type Alignment = {
  /** 問題文全文 */
  text: string;
  chunks: AlignedChunk[];
};

/**
 * 問題文を区切り文字で分割する。区切り文字は直前のチャンクへ含める
 * （「〜ですが、」までで 1 チャンクとしたいため）。
 */
function splitTextIntoChunks(text: string): string[] {
  const chunks: string[] = [];
  let current = '';

  for (const char of text) {
    current += char;
    if (CHUNK_DELIMITERS.test(char)) {
      chunks.push(current);
      current = '';
    }
  }
  if (current !== '') chunks.push(current);

  return chunks.filter((chunk) => chunk.trim() !== '');
}

/**
 * 統合しても残したい境界を、区間の隙間（pau）が長い順に count 個選ぶ。
 *
 * 返すのは「その要素の直前で区切る」インデックスの集合。読点相当の pau は
 * 文中の息継ぎより有意に長い、という性質を利用している。長さが同じ隙間が
 * 並んだ場合は前方を優先し、結果が入力順で安定するようにしている。
 */
function pickBoundaries(segments: SpeechSegment[], count: number): Set<number> {
  const gaps = segments.slice(1).map((segment, index) => ({
    // segments[index + 1] の直前で区切る
    index: index + 1,
    length: segment.start - segments[index]!.end,
  }));

  gaps.sort((a, b) => b.length - a.length || a.index - b.index);

  return new Set(gaps.slice(0, count).map((gap) => gap.index));
}

/**
 * 発話区間を targetCount 個へ統合する。
 *
 * 文中の息継ぎで生じた短い pau を境界から外し、読点相当の長い pau だけを
 * 残すことで、文字側のチャンクと 1 対 1 に対応させる。
 */
function mergeSegments(segments: SpeechSegment[], targetCount: number): SpeechSegment[] {
  if (segments.length <= targetCount) return segments;

  const boundaries = pickBoundaries(segments, targetCount - 1);
  const merged: SpeechSegment[] = [];
  let current: SpeechSegment = { ...segments[0]! };

  for (let i = 1; i < segments.length; i += 1) {
    const segment = segments[i]!;
    if (boundaries.has(i)) {
      merged.push(current);
      current = { ...segment };
    } else {
      // 境界にしない pau は読み飛ばし、直前の区間へ吸収させる
      current.end = segment.end;
    }
  }
  merged.push(current);

  return merged;
}

/**
 * 文字チャンクを targetCount 個へ統合する。
 *
 * 音声側の区間のほうが少ない場合に使う。どの読点が pau になっていないかは
 * 文字列からは判断できないため、文字数の均等さを手掛かりに、結合しても
 * 最も偏りが小さくなる位置から順に隣接チャンクをまとめる。
 */
function mergeTextChunks(textChunks: string[], targetCount: number): string[] {
  if (textChunks.length <= targetCount) return textChunks;

  const merged = [...textChunks];
  while (merged.length > targetCount) {
    let bestIndex = 0;
    let bestLength = Infinity;

    // 結合後がいちばん短くなる隣接ペアを選ぶ
    for (let i = 0; i + 1 < merged.length; i += 1) {
      const length = [...merged[i]!].length + [...merged[i + 1]!].length;
      if (length < bestLength) {
        bestLength = length;
        bestIndex = i;
      }
    }

    merged.splice(bestIndex, 2, merged[bestIndex]! + merged[bestIndex + 1]!);
  }

  return merged;
}

/**
 * 音声側の発話区間と文字側のチャンクを対応付ける。
 *
 * 個数が食い違う場合は、多い側を少ない側の個数へ統合してから 1 対 1 に対応付ける。
 * 先頭から順に対応付けて余りを最終チャンクへ吸収する方式では、読点でない pau が
 * 境界として採用され、表示が音声から大きくずれるため。
 */
export function buildAlignment(text: string, lab: LabFile): Alignment {
  const normalizedText = text.trim();
  const textChunks = splitTextIntoChunks(normalizedText);
  const segments = lab.segments;

  // どちらかが空なら、全体を 1 チャンクとして時間比例で送る
  if (textChunks.length === 0 || segments.length === 0) {
    return {
      text: normalizedText,
      chunks: [
        {
          start: 0,
          end: lab.duration > 0 ? lab.duration : 1,
          charStart: 0,
          charEnd: [...normalizedText].length,
        },
      ],
    };
  }

  const pairCount = Math.min(textChunks.length, segments.length);
  const pairedSegments = mergeSegments(segments, pairCount);
  const pairedTextChunks = mergeTextChunks(textChunks, pairCount);

  const chunks: AlignedChunk[] = [];
  let charCursor = 0;

  for (let i = 0; i < pairCount; i += 1) {
    const segment = pairedSegments[i]!;
    const charEnd = charCursor + [...pairedTextChunks[i]!].length;

    chunks.push({
      start: segment.start,
      end: segment.end,
      charStart: charCursor,
      charEnd,
    });
    charCursor = charEnd;
  }

  return { text: normalizedText, chunks };
}

/**
 * 再生位置 currentTime（秒）において表示すべき文字数を返す。
 *
 * チャンクとチャンクの間（無音区間）にいる場合は、直前のチャンクを読み終えた
 * 状態を保つ。文字だけが先に進んで見えるのを防ぐため。
 */
export function visibleLength(alignment: Alignment, currentTime: number): number {
  const { chunks } = alignment;
  if (chunks.length === 0) return 0;

  const first = chunks[0]!;
  if (currentTime <= first.start) return 0;

  const last = chunks.at(-1)!;
  if (currentTime >= last.end) return last.charEnd;

  for (const chunk of chunks) {
    if (currentTime >= chunk.end) continue;

    // 無音区間にいる: 直前のチャンクまで表示した状態で待つ
    if (currentTime < chunk.start) return chunk.charStart;

    const span = chunk.end - chunk.start;
    if (span <= 0) return chunk.charEnd;

    const progress = (currentTime - chunk.start) / span;
    const charCount = chunk.charEnd - chunk.charStart;
    return chunk.charStart + Math.floor(progress * charCount);
  }

  return last.charEnd;
}

/** 表示すべき文字数ぶんだけ切り出す。サロゲートペアを壊さないよう配列経由で扱う */
export function visibleText(alignment: Alignment, currentTime: number): string {
  const length = visibleLength(alignment, currentTime);
  return [...alignment.text].slice(0, length).join('');
}
