/**
 * 正解の入力と、記録の確定。
 *
 * 確定を独立した操作にしているのは、手動正解ボタンが正解入力の後から
 * 押せるため。正解を入れた時点で記録すると手動正解を反映できず、
 * 追記型の CSV では後から行を直せない。
 */
type Props = {
  expectedAnswer: string;
  /** 予測が 1 件でも届いているか。届く前に確定させない */
  hasResults: boolean;
  /** 記録の送信中 */
  saving: boolean;
  /** 確定済み。二重記録を防ぐ */
  saved: boolean;
  onChange: (value: string) => void;
  onConfirm: () => void;
  onReset: () => void;
};

export function AnswerForm({
  expectedAnswer,
  hasResults,
  saving,
  saved,
  onChange,
  onConfirm,
  onReset,
}: Props) {
  const empty = expectedAnswer.trim() === '';

  return (
    <section className="answer-form">
      <label className="field">
        <span className="field-label">正解</span>
        <input
          className="answer-input"
          type="text"
          value={expectedAnswer}
          disabled={saved}
          placeholder="正解を入力すると、各枠に ○ / × が出ます"
          onChange={(event) => onChange(event.target.value)}
        />
      </label>

      <div className="answer-form-controls">
        <button
          type="button"
          className="confirm-button"
          disabled={!hasResults || empty || saving || saved}
          onClick={onConfirm}
        >
          {saving ? '記録中…' : saved ? '記録済み' : 'この問題を確定'}
        </button>

        <button type="button" className="reset-button" onClick={onReset}>
          次の問題へ
        </button>
      </div>

      {saved && (
        <p className="answer-form-hint">
          記録しました。「次の問題へ」で入力を空にできます。
        </p>
      )}
    </section>
  );
}
