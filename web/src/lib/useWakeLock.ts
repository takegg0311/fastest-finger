/**
 * 画面をスリープさせない。
 *
 * スマホが画面ロックすると WebSocket が切れ、出題中に押せなくなる。
 * 再接続はするが、ロックの解除に手間取れば早押しに間に合わない。
 *
 * 対応していないブラウザでは黙って何もしない（出題を止めない）。
 */
import { useEffect } from 'react';

export function useWakeLock(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    if (!('wakeLock' in navigator)) return;

    let sentinel: WakeLockSentinel | null = null;
    let released = false;

    const acquire = async () => {
      try {
        sentinel = await navigator.wakeLock.request('screen');
      } catch (reason: unknown) {
        // 電池が少ないと拒否されることがある。出題は続けられるので警告に留める
        console.warn('[wakeLock] 取得できませんでした', reason);
      }
    };

    // タブを離れると自動で解除されるので、戻ってきたら取り直す
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && !released) void acquire();
    };

    void acquire();
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      released = true;
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      void sentinel?.release().catch(() => undefined);
    };
  }, [enabled]);
}
