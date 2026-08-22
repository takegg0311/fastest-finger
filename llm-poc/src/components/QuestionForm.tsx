/**
 * 問題文の入力と送信。
 *
 * 「途中まで」は、入力されたテキストがそのまま途中までの内容になる。
 * 全文を入れてスライダーで位置を指定する方式は採らない。早押しで
 * 実際に読まれた分を貼り付ける使い方を想定しており、切れ目を
 * 別途指定させると入力が二度手間になるため。
 */
type Props = {
  questionText: string;
  complete: boolean;
  /** 送信中は入力を止める。応答と表示がずれるため */
  disabled: boolean;
  /** 送信できる状態か（サーバ疎通と枠の選択が揃っているか） */
  canSubmit: boolean;
  onChangeText: (value: string) => void;
  onChangeComplete: (value: boolean) => void;
  onSubmit: () => void;
};

export function QuestionForm({
  questionText,
  complete,
  disabled,
  canSubmit,
  onChangeText,
  onChangeComplete,
  onSubmit,
}: Props) {
  const empty = questionText.trim() === '';

  return (
    <section className="question-form">
      <label className="field">
        <span className="field-label">問題文</span>
        <textarea
          className="question-input"
          value={questionText}
          disabled={disabled}
          rows={4}
          placeholder="早押しクイズの問題文を入力してください。途中で切れていても構いません。"
          onChange={(event) => onChangeText(event.target.value)}
        />
      </label>

      <div className="question-form-controls">
        <div className="toggle-group" role="radiogroup" aria-label="問題文の状態">
          <button
            type="button"
            role="radio"
            aria-checked={!complete}
            className={`toggle ${!complete ? 'is-active' : ''}`}
            disabled={disabled}
            onClick={() => onChangeComplete(false)}
          >
            途中まで
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={complete}
            className={`toggle ${complete ? 'is-active' : ''}`}
            disabled={disabled}
            onClick={() => onChangeComplete(true)}
          >
            読み切り
          </button>
        </div>

        <button
          type="button"
          className="submit-button"
          disabled={disabled || empty || !canSubmit}
          onClick={onSubmit}
        >
          送信
        </button>
      </div>

      <p className="question-form-hint">
        {complete
          ? '読み切り: 答えのみを予測します。'
          : '途中まで: 問題文の続きを補完した上で、答えを予測します。'}
      </p>
    </section>
  );
}
