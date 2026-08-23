/**
 * LLM 予測比較 PoC。
 *
 * 早押しクイズの問題文を各社 LLM へ同じプロンプトで送り、
 * 答え（途中までの場合は問題文の補完も）を並べて比較する。
 *
 * 既存 PoC（poc/）は音声を鳴らして早押しする検証用で、LLM 予測は
 * その付随機能だった。この PoC は比較そのものが目的なので、
 * 出題サイクルを持たず、問題文はテキストで直接入力する。
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { activeSlots } from './lib/llmSlots';
import { appendLog, type LogRecord } from './lib/log';
import { matchesAnswer } from './lib/answer';
import { useLlmPrediction } from './lib/useLlmPrediction';
import { AnswerForm } from './components/AnswerForm';
import { LlmPanel } from './components/LlmPanel';
import { QuestionForm } from './components/QuestionForm';

/**
 * 送信した内容の控え。
 *
 * 記録する問題文と complete は、フォームの現在値ではなくこれを使う。
 * 送信後もフォームは編集できるため、現在値を記録すると
 * 「答えは前の問題文に対するもの、メタデータは編集後」という行が残る。
 */
type Submission = {
  questionText: string;
  complete: boolean;
};

export function App() {
  const [questionText, setQuestionText] = useState('');
  const [complete, setComplete] = useState(false);
  const [expectedAnswer, setExpectedAnswer] = useState('');
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  /**
   * 記録の送信中かどうか。saving（state）は反映が非同期なので、
   * 同一ティック内の二度押しを止められない。
   */
  const savingRef = useRef(false);

  const llm = useLlmPrediction();
  const { health, providers, slots, predictions, manualCorrect } = llm;

  /** 送信中は入力と枠の選択を止める。応答と表示がずれるため */
  const pending = predictions.some((prediction) => prediction.state === 'pending');
  /**
   * 確定してよいか。1 件でも届いていれば足りるとはしない。
   * 応答の速さは枠によって大きく違い（実測で 2 秒台〜15 秒台）、
   * 速い枠だけで確定すると遅い枠が CSV から丸ごと欠ける。
   */
  const canConfirm = !pending && predictions.some((prediction) => prediction.state === 'done');
  const canSubmit = health === 'online' && activeSlots(slots).length > 0;

  const handleSubmit = useCallback(() => {
    const text = questionText.trim();
    if (text === '') return;

    // 送信し直したら、前回の記録状態は引き継がない
    setSaved(false);
    setLogError(null);
    setSubmission({ questionText: text, complete });
    llm.run(text, complete);
  }, [questionText, complete, llm]);

  /** 入力を空にして次の問題へ移る */
  const handleReset = useCallback(() => {
    setQuestionText('');
    setExpectedAnswer('');
    setSubmission(null);
    setSaved(false);
    setLogError(null);
    llm.reset();
  }, [llm]);

  /**
   * 記録するレコードを組み立てる。
   *
   * 正誤は「自動判定 または 手動正解」。手動正解かどうかは manual 列に
   * 残し、後から自動判定だけの集計もできるようにする。
   */
  const records = useMemo<LogRecord[]>(() => {
    const result: LogRecord[] = [];

    // vendor / model は予測結果が持つもの（送信時の控え）を使う。
    // 現在の枠選択（slots）から読むと、応答後に枠を変えられた場合に
    // 古い予測と新しい選択を組み合わせた行が残る。
    predictions.forEach((prediction, index) => {
      if (prediction.state !== 'done') return;

      const manual = manualCorrect[index] ?? false;
      const outcome = prediction.result;

      if (outcome.status === 'ok') {
        result.push({
          vendor: prediction.vendor,
          model: prediction.model,
          answer: outcome.answer,
          continuation: outcome.continuation,
          elapsedMs: outcome.elapsedMs,
          ok: true,
          errorKind: null,
          correct: matchesAnswer(outcome.answer, expectedAnswer) || manual,
          manual,
        });
        return;
      }

      // 違反・エラーは答えを持たない。手動正解の対象にもならないが、
      // 送信した事実は記録する（どのモデルが失敗したかを残すため）。
      // 失敗の種別は潰さずそのまま残す。どのモデルがどう落ちたかは
      // 比較実験の観測対象そのものであるため。
      result.push({
        vendor: prediction.vendor,
        model: prediction.model,
        answer: '',
        continuation: null,
        elapsedMs: outcome.elapsedMs,
        ok: false,
        errorKind: outcome.status === 'violation' ? 'violation' : outcome.kind,
        correct: false,
        manual: false,
      });
    });

    return result;
  }, [predictions, manualCorrect, expectedAnswer]);

  const handleConfirm = useCallback(async () => {
    if (records.length === 0 || submission === null) return;
    // setSaving の反映を待たずに二度目が入りうるので、ref で止める
    if (savingRef.current) return;

    savingRef.current = true;
    setSaving(true);
    setLogError(null);

    const failure = await appendLog({
      questionText: submission.questionText,
      complete: submission.complete,
      expectedAnswer: expectedAnswer.trim(),
      records,
    });

    savingRef.current = false;
    setSaving(false);
    if (failure === null) {
      setSaved(true);
      return;
    }
    setLogError(failure);
  }, [records, submission, expectedAnswer]);

  return (
    <main className="app">
      <header className="app-header">
        <h1 className="app-title">LLM 予測比較</h1>
        <p className="app-description">
          早押しクイズの問題文を各社 LLM へ送り、答えを比較します。
        </p>
      </header>

      <QuestionForm
        questionText={questionText}
        complete={complete}
        disabled={pending}
        canSubmit={canSubmit}
        onChangeText={setQuestionText}
        onChangeComplete={setComplete}
        onSubmit={handleSubmit}
      />

      <LlmPanel
        health={health}
        providers={providers}
        slots={slots}
        predictions={predictions}
        manualCorrect={manualCorrect}
        expectedAnswer={expectedAnswer}
        disabled={pending}
        locked={saved}
        onRefresh={() => void llm.refresh()}
        onSelect={llm.selectSlot}
        onToggleManual={llm.toggleManual}
      />

      <AnswerForm
        expectedAnswer={expectedAnswer}
        canConfirm={canConfirm}
        saving={saving}
        saved={saved}
        onChange={setExpectedAnswer}
        onConfirm={() => void handleConfirm()}
        onReset={handleReset}
      />

      {logError !== null && <p className="app-error">記録に失敗しました: {logError}</p>}
    </main>
  );
}
