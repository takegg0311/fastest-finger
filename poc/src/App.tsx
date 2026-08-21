import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { visibleLength } from './lib/align';
import { formatAnswer, isCorrect } from './lib/answer';
import {
  loadManifest,
  loadQuestion,
  pickRandom,
  type ManifestEntry,
} from './lib/manifest';
import { playJingle } from './lib/sound';
import { useLlmPrediction } from './lib/useLlmPrediction';
import {
  canAnswer,
  canBuzz,
  initialState,
  quizReducer,
} from './state/quizMachine';
import { AnswerInput } from './components/AnswerInput';
import { BuzzButton } from './components/BuzzButton';
import { LlmPanel } from './components/LlmPanel';
import { QuestionView } from './components/QuestionView';
import { ResultView } from './components/ResultView';
import { StartScreen } from './components/StartScreen';

export function App() {
  const [state, dispatch] = useReducer(quizReducer, initialState);
  const [entries, setEntries] = useState<ManifestEntry[]>([]);
  /** 音声の再生位置。requestAnimationFrame で更新し、文字送りを駆動する */
  const [currentTime, setCurrentTime] = useState(0);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const frameRef = useRef<number | null>(null);
  /** 直前に出題した問題。同じ問題が連続しないようにするため */
  const lastIdRef = useRef<string | undefined>(undefined);

  const { phase, question, frozenLength, judgement, error } = state;

  const llm = useLlmPrediction();

  // 起動時に問題一覧を読み込む
  useEffect(() => {
    let cancelled = false;
    loadManifest()
      .then((loaded) => {
        if (cancelled) return;
        if (loaded.length === 0) {
          dispatch({
            type: 'loadFailed',
            message:
              '問題が 1 問もありません。public/quiz_data に wav / txt / lab の 3 点セットを配置してください。',
          });
          return;
        }
        setEntries(loaded);
        dispatch({ type: 'ready' });
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        dispatch({
          type: 'loadFailed',
          message: reason instanceof Error ? reason.message : String(reason),
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 表示中の文字数。早押し後は frozenLength で固定する
  const shownLength =
    question === null
      ? 0
      : (frozenLength ?? visibleLength(question.alignment, currentTime));
  const shownText =
    question === null ? '' : [...question.text].slice(0, shownLength).join('');

  /** 再生位置の監視を止める */
  const stopTracking = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
  }, []);

  // reading の間だけ再生位置を追い続ける
  useEffect(() => {
    if (phase !== 'reading') return;

    const audio = audioRef.current;
    if (audio === null) return;

    audio.currentTime = 0;
    setCurrentTime(0);
    void audio.play().catch((reason: unknown) => {
      console.warn('[audio] 問題音声を再生できませんでした', reason);
    });

    const tick = () => {
      const current = audioRef.current;
      if (current !== null) setCurrentTime(current.currentTime);
      frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);

    return stopTracking;
  }, [phase, stopTracking]);

  /** 出題を始める。ジングルを鳴らし切ってから問題音声へ入る */
  const startQuestion = useCallback(async () => {
    const entry = pickRandom(entries, lastIdRef.current);
    if (entry === undefined) return;

    // データ読み込みを待つ間、前問の結果を残したままにしない
    dispatch({ type: 'next' });
    llm.reset();

    try {
      const loaded = await loadQuestion(entry);
      lastIdRef.current = loaded.id;
      setCurrentTime(0);
      dispatch({ type: 'questionLoaded', question: loaded });
      await playJingle('set');
      dispatch({ type: 'jingleEnded' });
    } catch (reason: unknown) {
      dispatch({
        type: 'loadFailed',
        message: reason instanceof Error ? reason.message : String(reason),
      });
    }
  }, [entries, llm]);

  /** 早押し。音声と文字送りの双方をその場で止める */
  const handleBuzz = useCallback(() => {
    if (!canBuzz(phase) || question === null) return;

    const audio = audioRef.current;
    const at = audio?.currentTime ?? currentTime;
    audio?.pause();
    stopTracking();

    // 押したことのフィードバックなので、鳴り終わりを待たずに回答へ進ませる
    void playJingle('buzz');

    const shown = visibleLength(question.alignment, at);
    dispatch({ type: 'buzz', visibleLength: shown });

    // 早押しした時点で見えていた文字列だけを送る。丸めずに生のまま渡すのは、
    // 早押しの実態に忠実であることを優先するため。問題文の全文と正解は送らない。
    llm.run([...question.text].slice(0, shown).join(''), false);
  }, [phase, question, currentTime, stopTracking, llm]);

  /** 早押しされないまま音声が終わった場合 */
  const handleAudioEnded = useCallback(() => {
    if (question === null) return;
    stopTracking();
    dispatch({
      type: 'audioEnded',
      visibleLength: [...question.text].length,
    });

    // 読み切られた場合は続きの予測が要らないため、全文を complete で送る。
    // 全文を渡すことになるが、正解は依然として送らない。
    llm.run(question.text, true);
  }, [question, stopTracking, llm]);

  const handleSubmitAnswer = useCallback(
    (input: string) => {
      if (question === null) return;
      const correct = isCorrect(input, question.answers);
      dispatch({ type: 'judged', judgement: { input, correct } });
      void playJingle(correct ? 'correct' : 'wrong');
    },
    [question],
  );

  // スペースキーでも早押しできるようにする
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.code !== 'Space' && event.key !== ' ') return;
      if (!canBuzz(phase)) return;

      // 入力欄にフォーカスがある場合は通常のスペース入力として扱う
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
        return;
      }

      event.preventDefault();
      handleBuzz();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [phase, handleBuzz]);

  const isPlaying = phase === 'jingle' || phase === 'reading';

  return (
    <main className="app">
      <h1 className="app-title">早押しクイズ</h1>

      {(phase === 'loading' || phase === 'idle') && (
        <StartScreen
          label={phase === 'loading' ? '読み込み中…' : '開始'}
          disabled={phase === 'loading' || entries.length === 0}
          error={error}
          onStart={() => void startQuestion()}
        />
      )}

      {question !== null && phase !== 'idle' && phase !== 'loading' && (
        <>
          <audio
            ref={audioRef}
            src={question.audioUrl}
            onEnded={handleAudioEnded}
            preload="auto"
          />

          <QuestionView text={phase === 'jingle' ? '' : shownText} />

          {isPlaying && (
            <BuzzButton disabled={!canBuzz(phase)} onBuzz={handleBuzz} />
          )}

          {canAnswer(phase) && (
            <>
              {phase === 'timeUp' && (
                <p className="notice">問題文を最後まで読み切りました</p>
              )}
              <AnswerInput onSubmit={handleSubmitAnswer} />
            </>
          )}

          {phase === 'result' && judgement !== null && (
            <ResultView
              correct={judgement.correct}
              input={judgement.input}
              answer={formatAnswer(question.answers)}
              fullText={question.text}
              onNext={() => void startQuestion()}
            />
          )}

          <LlmPanel
            health={llm.health}
            providers={llm.providers}
            slots={llm.slots}
            predictions={llm.predictions}
            answers={question.answers}
            // 人間が回答するまで正誤は伏せる。先に ○/× が出ると、
            // それを見て答えられてしまう。
            revealJudgement={phase === 'result'}
            // 出題中に選択を変えると、送信済みの枠と表示がずれる
            disabled={phase === 'jingle' || phase === 'reading'}
            onRefresh={() => void llm.refresh()}
            onSelect={llm.selectSlot}
          />
        </>
      )}

      {(phase === 'loading' || phase === 'idle') && (
        <LlmPanel
          health={llm.health}
          providers={llm.providers}
          slots={llm.slots}
          predictions={llm.predictions}
          answers={[]}
          revealJudgement={false}
          disabled={false}
          onRefresh={() => void llm.refresh()}
          onSelect={llm.selectSlot}
        />
      )}
    </main>
  );
}
