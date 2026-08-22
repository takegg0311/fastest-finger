/**
 * LLM 予測の状態管理。
 *
 * 既存 PoC（poc/src/lib/useLlmPrediction.ts）から移植したが、
 * 手動正解の状態をここで持つ点が異なる。手動正解は枠ごとに独立して
 * 切り替わり、確定時の記録にも要るため、予測結果と同じ寿命で管理する。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { checkHealth, predict, type PredictResult, type ProviderInfo } from './llm';
import {
  activeSlots,
  defaultSlots,
  loadSlots,
  reconcile,
  saveSlots,
  type SlotSelection,
} from './llmSlots';

/** server との疎通状態 */
export type HealthStatus = 'checking' | 'online' | 'offline';

/**
 * 枠 1 つぶんの予測状態。
 *
 * pending / done は送信時の vendor / model を持つ。記録する vendor / model を
 * 「現在の枠選択」から読むと、応答が届いた後に枠を変えられた場合に、
 * 古い予測と新しい選択を組み合わせた行が CSV に残る。
 * 実験ログとして誤りなので、送信した時点の組をここへ固定する。
 */
export type SlotPrediction =
  | { state: 'idle' }
  | { state: 'pending'; vendor: string; model: string }
  | { state: 'done'; vendor: string; model: string; result: PredictResult };

export function useLlmPrediction() {
  const [health, setHealth] = useState<HealthStatus>('checking');
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [slots, setSlots] = useState<SlotSelection[]>(loadSlots);
  const [predictions, setPredictions] = useState<SlotPrediction[]>(() =>
    slots.map(() => ({ state: 'idle' })),
  );
  /** 枠ごとの手動正解。表記揺れ・別解を人が拾うために使う */
  const [manualCorrect, setManualCorrect] = useState<boolean[]>(() => slots.map(() => false));

  /**
   * 予測の世代。次の問題へ進んだ後に前問の応答が届いても捨てるため。
   * 応答は最大 60 秒かかるので、遅れて到着しうる。
   */
  const generationRef = useRef(0);

  /** 疎通を確認し、使えるプロバイダに合わせて枠を整える */
  const refresh = useCallback(async () => {
    setHealth('checking');
    const found = await checkHealth();

    if (found === null) {
      setHealth('offline');
      setProviders([]);
      return;
    }

    setHealth('online');
    setProviders(found);
    setSlots((current) => {
      // 保存が空（初回）なら使えるプロバイダを並べ、そうでなければ
      // 保存済みの選択を実際に使える組み合わせへ突き合わせる
      const hasSelection = current.some((slot) => slot.vendor !== null);
      const next = hasSelection ? reconcile(current, found) : defaultSlots(found);
      saveSlots(next);
      return next;
    });
  }, []);

  // 起動時に 1 回だけ確認する。以降は再チェックボタンから呼ぶ
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectSlot = useCallback((index: number, selection: SlotSelection) => {
    setSlots((current) => {
      const next = current.map((slot, i) => (i === index ? selection : slot));
      saveSlots(next);
      return next;
    });
  }, []);

  /** 手動正解を切り替える。押し間違いを戻せるようトグルにする */
  const toggleManual = useCallback((index: number) => {
    setManualCorrect((current) => current.map((value, i) => (i === index ? !value : value)));
  }, []);

  /** 予測結果を捨てる。次の問題へ進むときに呼ぶ */
  const reset = useCallback(() => {
    generationRef.current += 1;
    setPredictions((current) => current.map(() => ({ state: 'idle' })));
    setManualCorrect((current) => current.map(() => false));
  }, []);

  /**
   * 全枠へ並列に送信する。応答は届いた順にその枠だけを更新する。
   *
   * questionText は画面で入力された問題文。complete が true なら
   * 読み切りとして扱い、続きの予測は求めない。
   */
  const run = useCallback(
    (questionText: string, complete: boolean) => {
      if (health !== 'online') return;

      const targets = activeSlots(slots);
      if (targets.length === 0) return;

      generationRef.current += 1;
      const generation = generationRef.current;

      // 送信対象の枠だけを待機中にする。この時点の vendor / model を持たせ、
      // 以降の記録はこれを使う（枠を変えられても影響を受けない）
      setPredictions(
        slots.map((slot) =>
          slot.vendor !== null && slot.model !== null
            ? { state: 'pending' as const, vendor: slot.vendor, model: slot.model }
            : { state: 'idle' as const },
        ),
      );
      // 前回の手動正解を引きずらない
      setManualCorrect(slots.map(() => false));

      slots.forEach((slot, index) => {
        const vendor = slot.vendor;
        const model = slot.model;
        if (vendor === null || model === null) return;

        void predict(vendor, model, questionText, complete).then((result) => {
          // 次の問題へ進んだ後に届いた応答は捨てる
          if (generationRef.current !== generation) return;

          setPredictions((current) =>
            current.map((prediction, i) =>
              i === index ? { state: 'done', vendor, model, result } : prediction,
            ),
          );
        });
      });
    },
    [health, slots],
  );

  return {
    health,
    providers,
    slots,
    predictions,
    manualCorrect,
    refresh,
    selectSlot,
    toggleManual,
    run,
    reset,
  };
}
