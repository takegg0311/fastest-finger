/** 投影用の問題文表示。読み上げに追従して文字が増えていく */
import type { JudgementView } from '../protocol';

type Props = {
  /** 現在表示すべきところまで切り出した問題文 */
  text: string;
  /** 停止後に全文を見せる場合の全文。表示しないときは null */
  fullText: string | null;
  /** 正解。まだ出してよい phase でないときは null */
  answers: string[] | null;
  judgement: JudgementView | null;
};

export function QuestionView({ text, fullText, answers, judgement }: Props) {
  return (
    <div className="question">
      <p className="question-text">
        {text}
        <span className="question-caret" />
      </p>

      {fullText !== null && fullText !== text && (
        <p className="question-full">{fullText}</p>
      )}

      {answers !== null && answers.length > 0 && (
        <p className="question-answer">
          <span className="question-answer-label">正解</span>
          {answers.join(' / ')}
        </p>
      )}

      {judgement !== null && (
        <p className={judgement.correct ? 'judgement correct' : 'judgement wrong'}>
          {judgement.name} さん {judgement.correct ? '正解' : '不正解'}
        </p>
      )}
    </div>
  );
}
