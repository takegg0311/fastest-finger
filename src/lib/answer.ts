/**
 * 正誤判定。
 *
 * 問題データのファイル名（拡張子を除いたもの）がそのまま正解であり、
 * 括弧内は別表記の正解候補として扱う。
 *   例: `パイソン(Python)` → 候補 ["パイソン", "Python"]
 *
 * 判定は正規化した上での部分一致とする（PoC のため緩めに取る）。
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
function normalize(value: string): string {
  return toHalfWidth(value.normalize('NFKC'))
    .toLowerCase()
    .replace(/[\s・･\-ー―‐]/g, '');
}

/**
 * 問題 ID（ファイル名の拡張子を除いた部分）から正解候補を取り出す。
 * 括弧の外側と内側をそれぞれ候補とする。
 */
export function extractAnswers(id: string): string[] {
  const answers: string[] = [];

  // 全角・半角の丸括弧と角括弧の中身を候補にする
  const bracketPattern = /[(（[［]([^)）\]］]*)[)）\]］]/g;
  for (const match of id.matchAll(bracketPattern)) {
    const inner = match[1]?.trim();
    if (inner) answers.push(inner);
  }

  // 括弧を取り除いた残りも候補にする
  const outer = id.replace(bracketPattern, '').trim();
  if (outer) answers.unshift(outer);

  // 候補が 1 つも取れなければ ID 全体を使う
  if (answers.length === 0) answers.push(id.trim());

  return answers;
}

/** 入力が正解候補のいずれかと部分一致するか */
export function isCorrect(input: string, id: string): boolean {
  const normalizedInput = normalize(input);
  if (normalizedInput === '') return false;

  return extractAnswers(id).some((answer) => {
    const normalizedAnswer = normalize(answer);
    if (normalizedAnswer === '') return false;
    return (
      normalizedInput.includes(normalizedAnswer) ||
      normalizedAnswer.includes(normalizedInput)
    );
  });
}

/** 表示用の正解文字列。候補が複数あれば併記する */
export function formatAnswer(id: string): string {
  return extractAnswers(id).join(' / ');
}
