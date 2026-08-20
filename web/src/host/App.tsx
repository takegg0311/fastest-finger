/**
 * 出題者用の画面。スクリーン投影を想定している。
 *
 * この画面だけが音声を鳴らす。回答者の端末は無音。
 * 出題者の操作が起点になるので、ブラウザの自動再生ポリシーにも掛からない。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { visibleLength } from '../lib/align';
import { playJingle } from '../lib/sound';
import { useConnection } from '../lib/useConnection';
import type { ClientMessage, RoomStateMessage, ServerMessage } from '../protocol';
import { Controls } from './Controls';
import { JoinPanel } from './JoinPanel';
import { PlayerList } from './PlayerList';
import { QuestionView } from './QuestionView';
import { useQuestion } from './useQuestion';

/** URL の ?token= から出題者用トークンを取る */
function hostTokenFromUrl(): string {
  return new URLSearchParams(window.location.search).get('token') ?? '';
}

export function App() {
  const [state, setState] = useState<RoomStateMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** 音声の再生位置。requestAnimationFrame で更新し、文字送りを駆動する */
  const [currentTime, setCurrentTime] = useState(0);
  /** 早押し・読み切りで確定した表示文字数。null なら再生位置に追従する */
  const [frozenLength, setFrozenLength] = useState<number | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const hostToken = useRef(hostTokenFromUrl());

  const question = useQuestion(state?.question ?? null);

  // 停止処理から参照するため、最新値を ref に持つ
  const questionRef = useRef(question);
  questionRef.current = question;
  /** ジングル中に押されたかどうか。await を跨いで再生を止めるために使う */
  const frozenRef = useRef(false);

  const stopTracking = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
  }, []);

  /** 音声と文字送りをその場で止める */
  const freeze = useCallback(() => {
    const audio = audioRef.current;
    const loaded = questionRef.current;
    frozenRef.current = true;
    audio?.pause();
    stopTracking();

    if (loaded === null) return;
    const at = audio?.currentTime ?? 0;
    setFrozenLength(visibleLength(loaded.alignment, at));
  }, [stopTracking]);

  const handleOpen = useCallback((send: (message: ClientMessage) => void) => {
    send({ type: 'host_hello', host_token: hostToken.current });
  }, []);

  const handleMessage = useCallback(
    (message: ServerMessage) => {
      switch (message.type) {
        case 'room_state':
          setState(message);
          break;

        case 'buzz_accepted':
          // 誰かが押した。問題文と音声をその場で止める。
          // 押したフィードバックなので、鳴り終わりは待たない
          freeze();
          void playJingle('buzz');
          break;

        case 'error':
          setError(message.message);
          break;
      }
    },
    [freeze],
  );

  const { status, send } = useConnection({ onOpen: handleOpen, onMessage: handleMessage });

  const phase = state?.phase ?? 'idle';
  const roundId = state?.round_id ?? 0;

  // 新しい問題が読み込まれたら、ジングルを鳴らしてから音声を再生する
  const questionId = question?.id ?? null;
  useEffect(() => {
    if (question === null || phase !== 'reading') return;
    // 解除で戻ってきた場合は続きから鳴らすため、先頭に戻すのは新しい問題のときだけ
    const audio = audioRef.current;
    if (audio === null) return;

    let cancelled = false;

    // 前問で確定した表示文字数はここで捨てる。ジングルの再生完了を待ってから
    // 捨てると、その間ずっと前問の文字数で固定されたままになり、
    // 問題音声が始まっても文字送りが動かない。
    audio.currentTime = 0;
    setCurrentTime(0);
    setFrozenLength(null);
    frozenRef.current = false;

    void (async () => {
      await playJingle('set');
      // ジングルの間に押されていたら鳴らし始めない。
      // サーバは start_question の時点で早押しを受け付けている
      if (cancelled || frozenRef.current) return;

      audio.currentTime = 0;
      await audio.play().catch((reason: unknown) => {
        console.warn('[host] 問題音声を再生できませんでした', reason);
      });
    })();

    return () => {
      cancelled = true;
    };
    // ラウンドが変われば鳴らし直す。phase の往復（お手つき解除）では鳴らさない。
    // questionId だけを見ていると、同じ問題を続けて出したときに再生位置が
    // 前回の終端のままになり、即座に読み切り扱いになる。
    // questionId も依存に残すのは、出題直後はまだ .lab の取得中で
    // question が null のことがあり、その回の effect は何もせず抜けるため。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roundId, questionId]);

  // reading の間だけ再生位置を追い続ける
  useEffect(() => {
    if (phase !== 'reading' || question === null) return;

    const audio = audioRef.current;

    const tick = () => {
      const current = audioRef.current;
      if (current !== null) setCurrentTime(current.currentTime);
      frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);

    // 投影用のタブが背面に回るとブラウザが rAF を止め、文字送りだけが
    // 凍りつく（音声は鳴り続ける）。timeupdate は止まらないので保険に使う。
    // 精度は rAF に劣るが、表示が置き去りになるよりはよい。
    const handleTimeUpdate = () => {
      if (document.visibilityState === 'visible') return;
      const current = audioRef.current;
      if (current !== null) setCurrentTime(current.currentTime);
    };
    audio?.addEventListener('timeupdate', handleTimeUpdate);

    return () => {
      stopTracking();
      audio?.removeEventListener('timeupdate', handleTimeUpdate);
    };
  }, [phase, question, stopTracking]);

  /** お手つき解除で reading へ戻ったら、続きから再生する */
  useEffect(() => {
    if (phase !== 'reading') return;
    const audio = audioRef.current;
    if (audio === null || audio.paused === false) return;
    if (frozenLength === null) return;

    setFrozenLength(null);
    void audio.play().catch(() => undefined);
    // 解除のときだけ動かしたいので frozenLength は依存に含めない
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, roundId]);

  /** 押されないまま読み切った */
  const handleAudioEnded = useCallback(() => {
    if (question === null) return;
    stopTracking();
    setFrozenLength([...question.text].length);
    send({ type: 'reading_ended', round_id: roundId });
  }, [question, roundId, send, stopTracking]);

  const handleStart = useCallback(() => {
    setError(null);
    send({ type: 'start_question' });
  }, [send]);

  const handleJudge = useCallback(
    (correct: boolean) => {
      send({ type: 'judge', round_id: roundId, correct });
      void playJingle(correct ? 'correct' : 'wrong');
    },
    [roundId, send],
  );

  const handleRelease = useCallback(() => {
    send({ type: 'release', round_id: roundId });
  }, [roundId, send]);

  const handleNext = useCallback(() => {
    send({ type: 'next' });
  }, [send]);

  // 表示中の文字数。停止後は frozenLength で固定する
  const hasAlignment = question !== null && question.alignment.chunks.length > 0;
  const shownLength =
    question === null
      ? 0
      : (frozenLength ??
        (hasAlignment ? visibleLength(question.alignment, currentTime) : [...question.text].length));

  if (hostToken.current === '') {
    return (
      <main className="host">
        <p className="host-error">
          出題者用トークンがありません。サーバ起動時に表示された URL を開いてください。
        </p>
      </main>
    );
  }

  return (
    <main className="host">
      {question !== null && (
        <audio
          ref={audioRef}
          src={question.audioUrl}
          onEnded={handleAudioEnded}
          preload="auto"
        />
      )}

      <section className="host-stage">
        {state?.buzzed != null ? (
          <div className="buzzed-banner" aria-live="assertive">
            <span className="buzzed-name">{state.buzzed.name}</span>
          </div>
        ) : null}

        <QuestionView
          text={question === null ? '' : [...question.text].slice(0, shownLength).join('')}
          fullText={phase === 'result' || phase === 'timeUp' ? (question?.text ?? '') : null}
          answers={
            phase === 'buzzed' || phase === 'timeUp' || phase === 'result'
              ? (question?.answers ?? [])
              : []
          }
          judgement={state?.judgement ?? null}
        />
      </section>

      <aside className="host-side">
        <JoinPanel />
        <PlayerList players={state?.players ?? []} buzzedId={state?.buzzed?.player_id ?? null} />
      </aside>

      <footer className="host-controls">
        <Controls
          phase={phase}
          connected={status === 'open'}
          onStart={handleStart}
          onJudge={handleJudge}
          onRelease={handleRelease}
          onNext={handleNext}
        />
        {error !== null && <p className="host-error">{error}</p>}
      </footer>
    </main>
  );
}
