/**
 * LLM の回答と正解の照合。
 *
 * 既存 PoC（poc/src/lib/answer.ts）は正規化した上での「部分一致」で
 * 判定しているが、この PoC では採らない。部分一致を許すと、正解語を
 * 含むだけの長い誤答（正解「富士山」に対する「富士山ではありません」など）が
 * 自動的に正解と判定され、手動正解ボタンの意味が薄れるため。
 *
 * 一方で全角半角や記号の揺れまで不一致にすると（`Ｐｙｔｈｏｎ` と `Python`）、
 * 比較の邪魔になるだけで観測したい差にはならない。
 *
 * そこで正規化は流用しつつ、比較は完全一致とする。
 * 表記揺れや別解は、枠ごとの手動正解ボタンで人が拾う。
 */

/** 全角英数字を半角へ寄せる */
function toHalfWidth(value: string): string {
  return value.replace(/[Ａ-Ｚａ-ｚ０-９]/g, (char) =>
    String.fromCharCode(char.charCodeAt(0) - 0xfee0),
  );
}

/**
 * 比較用の正規化。
 * 全角/半角・大文字小文字・空白・記号の揺れを吸収する。
 */
export function normalize(value: string): string {
  return toHalfWidth(value.normalize('NFKC'))
    .toLowerCase()
    .replace(/[\s・･\-ー―‐]/g, '');
}

/**
 * LLM の回答が正解と一致するか。
 *
 * 正規化した上での完全一致。どちらかが空なら不一致とする
 * （正解未入力の状態で ○ が出ないようにするため）。
 */
export function matchesAnswer(answer: string, expected: string): boolean {
  const normalizedAnswer = normalize(answer);
  const normalizedExpected = normalize(expected);
  if (normalizedAnswer === '' || normalizedExpected === '') return false;

  return normalizedAnswer === normalizedExpected;
}
