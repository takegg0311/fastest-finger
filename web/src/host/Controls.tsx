/**
 * 出題者の操作。正誤判定は出題者が口頭回答を聞いて押す。
 * 文字入力による判定は行わない。
 *
 * 正解を出すのは check / timeUp に入ってから。投影は参加者も見るので、
 * 回答権を得た時点で正解が見えていると、それを読んで答えられてしまう。
 */
import type { Phase } from '../protocol';

type Props = {
  phase: Phase;
  connected: boolean;
  onStart: () => void;
  onTimeUp: () => void;
  onCheck: () => void;
  onJudge: (correct: boolean) => void;
  onRelease: () => void;
  onNext: () => void;
};

export function Controls({
  phase,
  connected,
  onStart,
  onTimeUp,
  onCheck,
  onJudge,
  onRelease,
  onNext,
}: Props) {
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

    case 'readingEnded':
      // 読み切っても締め切らない。考えてから押す間を残す
      return (
        <div className="control-row">
          <p className="control-hint">読み切りました（まだ押せます）</p>
          <button type="button" className="control primary" onClick={onTimeUp}>
            タイムアップ
          </button>
        </div>
      );

    case 'buzzed':
      return (
        <div className="control-row">
          <button type="button" className="control primary" onClick={onCheck}>
            チェック
          </button>
          <button type="button" className="control" onClick={onRelease}>
            解除して続ける
          </button>
        </div>
      );

    case 'check':
      return (
        <div className="control-row">
          <button type="button" className="control correct" onClick={() => onJudge(true)}>
            正解
          </button>
          <button type="button" className="control wrong" onClick={() => onJudge(false)}>
            不正解
          </button>
        </div>
      );

    case 'timeUp':
      // 誰も押さなかったのでスルー。判定する相手が居ない
      return (
        <div className="control-row">
          <p className="control-hint">正解者なし</p>
          <button type="button" className="control primary" onClick={onNext}>
            次の問題へ
          </button>
        </div>
      );

    case 'result':
      return (
        <button type="button" className="control primary" onClick={onNext}>
          次の問題へ
        </button>
      );
  }
}
