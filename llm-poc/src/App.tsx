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
import { useCallback, useMemo, useState } from 'react';
import { activeSlots } from './lib/llmSlots';
import { appendLog, type LogRecord } from './lib/log';
import { matchesAnswer } from './lib/answer';
import { useLlmPrediction } from './lib/useLlmPrediction';
import { AnswerForm } from './components/AnswerForm';
import { LlmPanel } from './components/LlmPanel';
import { QuestionForm } from './components/QuestionForm';

export function App() {
  const [questionText, setQuestionText] = useState('');
  const [complete, setComplete] = useState(false);
  const [expectedAnswer, setExpectedAnswer] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);

  const llm = useLlmPrediction();
  const { health, providers, slots, predictions, manualCorrect } = llm;

  /** 送信中は入力と枠の選択を止める。応答と表示がずれるため */
  const pending = predictions.some((prediction) => prediction.state === 'pending');
  /** 予測が 1 件でも届いているか */
  const hasResults = predictions.some((prediction) => prediction.state === 'done');
  const canSubmit = health === 'online' && activeSlots(slots).length > 0;

  const handleSubmit = useCallback(() => {
    const text = questionText.trim();
    if (text === '') return;

    // 送信し直したら、前回の記録状態は引き継がない
    setSaved(false);
    setLogError(null);
    llm.run(text, complete);
  }, [questionText, complete, llm]);

  /** 入力を空にして次の問題へ移る */
  const handleReset = useCallback(() => {
    setQuestionText('');
    setExpectedAnswer('');
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

    slots.forEach((slot, index) => {
      if (slot.vendor === null || slot.model === null) return;

      const prediction = predictions[index];
      if (prediction === undefined || prediction.state !== 'done') return;

      const manual = manualCorrect[index] ?? false;
      const outcome = prediction.result;

      if (outcome.status === 'ok') {
        result.push({
          vendor: slot.vendor,
          model: slot.model,
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
      // 送信した事実は記録する（どのモデルが失敗したかを残すため）
      result.push({
        vendor: slot.vendor,
        model: slot.model,
        answer: '',
        continuation: null,
        elapsedMs: outcome.elapsedMs,
        ok: false,
        errorKind: outcome.status === 'violation' ? 'violation' : 'error',
        correct: false,
        manual: false,
      });
    });

    return result;
  }, [slots, predictions, manualCorrect, expectedAnswer]);

  const handleConfirm = useCallback(async () => {
    if (records.length === 0) return;

    setSaving(true);
    setLogError(null);

    const failure = await appendLog({
      questionText: questionText.trim(),
      complete,
      expectedAnswer: expectedAnswer.trim(),
      records,
    });

    setSaving(false);
    if (failure === null) {
      setSaved(true);
      return;
    }
    setLogError(failure);
  }, [records, questionText, complete, expectedAnswer]);

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
        hasResults={hasResults}
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
