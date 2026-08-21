/**
 * LLM 予測の状態管理。
 *
 * 出題サイクル（quizMachine）とは分けている。予測は早押し後に非同期で
 * 進み、人間の回答とは独立に到着するため、同じ状態機械に混ぜると
 * 出題の遷移が読めなくなる。
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

/** 枠 1 つぶんの予測状態 */
export type SlotPrediction =
  | { state: 'idle' }
  | { state: 'pending' }
  | { state: 'done'; result: PredictResult };

export function useLlmPrediction() {
  const [health, setHealth] = useState<HealthStatus>('checking');
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [slots, setSlots] = useState<SlotSelection[]>(loadSlots);
  const [predictions, setPredictions] = useState<SlotPrediction[]>(() =>
    slots.map(() => ({ state: 'idle' })),
  );

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

  /** 予測結果を捨てる。次の問題へ進むときに呼ぶ */
  const reset = useCallback(() => {
    generationRef.current += 1;
    setPredictions((current) => current.map(() => ({ state: 'idle' })));
  }, []);

  /**
   * 全枠へ並列に送信する。応答は届いた順にその枠だけを更新する。
   *
   * partialText は早押し時点で表示されていた文字列。complete が true なら
   * 読み切られており、続きの予測は要らない。
   */
  const run = useCallback(
    (partialText: string, complete: boolean) => {
      if (health !== 'online') return;

      const targets = activeSlots(slots);
      if (targets.length === 0) return;

      generationRef.current += 1;
      const generation = generationRef.current;

      // 送信対象の枠だけを待機中にする
      setPredictions(
        slots.map((slot) =>
          slot.vendor !== null && slot.model !== null
            ? { state: 'pending' as const }
            : { state: 'idle' as const },
        ),
      );

      slots.forEach((slot, index) => {
        if (slot.vendor === null || slot.model === null) return;

        void predict(slot.vendor, slot.model, partialText, complete).then((result) => {
          // 次の問題へ進んだ後に届いた応答は捨てる
          if (generationRef.current !== generation) return;

          setPredictions((current) =>
            current.map((prediction, i) =>
              i === index ? { state: 'done', result } : prediction,
            ),
          );
        });
      });
    },
    [health, slots],
  );

  return { health, providers, slots, predictions, refresh, selectSlot, run, reset };
}
