/**
 * 出題者の操作。正誤判定は出題者が口頭回答を聞いて押す。
 * 文字入力による判定は行わない。
 */
import type { Phase } from '../protocol';

type Props = {
  phase: Phase;
  connected: boolean;
  onStart: () => void;
  onJudge: (correct: boolean) => void;
  onRelease: () => void;
  onNext: () => void;
};

export function Controls({ phase, connected, onStart, onJudge, onRelease, onNext }: Props) {
  if (!connected) {
    return <p className="host-error">サーバに接続しています…</p>;
  }

  switch (phase) {
    case 'idle':
      return (
        <button type="button" className="control primary" onClick={onStart}>
          出題する
        </button>
      );

    case 'reading':
      return <p className="control-hint">読み上げ中…（早押しを待っています）</p>;

    case 'buzzed':
    case 'timeUp':
      return (
        <div className="control-row">
          <button type="button" className="control correct" onClick={() => onJudge(true)}>
            正解
          </button>
          <button type="button" className="control wrong" onClick={() => onJudge(false)}>
            不正解
          </button>
          {phase === 'buzzed' && (
            <button type="button" className="control" onClick={onRelease}>
              解除して続ける
            </button>
          )}
        </div>
      );

    case 'result':
      return (
        <div className="control-row">
          <button type="button" className="control primary" onClick={onNext}>
            次の問題へ
          </button>
          <button type="button" className="control" onClick={onRelease}>
            解除して続ける
          </button>
        </div>
      );
  }
}
