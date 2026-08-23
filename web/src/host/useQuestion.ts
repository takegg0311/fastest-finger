/**
 * 出題内容から、文字送りに必要なアライメントを組み立てる。
 *
 * .lab の解析と対応付けは出題者フロントで行い、サーバへは持たせない。
 * 文字送りは「ローカルの audio.currentTime に対する純粋な関数」であり、
 * 音声を鳴らしているのはこの画面自身なので、間にネットワークを挟めば
 * 精度が落ちるだけで得るものが無い。
 */
import { useEffect, useState } from 'react';
import { buildAlignment, buildUniformAlignment, type Alignment } from '../lib/align';
import { parseLab } from '../lib/lab';
import type { QuestionView } from '../protocol';

/**
 * .lab を解析して組み立てた、文字送りに必要な一式。
 *
 * answers は含めない。正解は phase によって送られたり送られなかったりし、
 * .lab の再取得とは無関係に変わるため、room_state から直接読む。
 */
export type LoadedQuestion = {
  id: string;
  text: string;
  /** 音声なし問題では null。呼び出し側は <audio> を使わず時計で送る */
  audioUrl: string | null;
  alignment: Alignment;
};

export function useQuestion(question: QuestionView | null): LoadedQuestion | null {
  const [loaded, setLoaded] = useState<LoadedQuestion | null>(null);

  const questionId = question?.id ?? null;
  const labUrl = question?.lab_url ?? null;

  useEffect(() => {
    if (question === null) {
      setLoaded(null);
      return;
    }

    // 音声なし問題。.lab の取得を挟まず、等速のアライメントを合成する
    if (labUrl === null || question.audio_url === null) {
      const text = question.text.trim();
      setLoaded({
        id: question.id,
        text,
        audioUrl: null,
        alignment: buildUniformAlignment(text, question.char_interval_ms),
      });
      return;
    }

    let cancelled = false;

    void (async () => {
      try {
        const response = await fetch(labUrl);
        if (!response.ok) throw new Error(`${labUrl} を読み込めませんでした`);

        const lab = parseLab(await response.text());
        if (cancelled) return;

        const text = question.text.trim();
        setLoaded({
          id: question.id,
          text,
          audioUrl: question.audio_url,
          alignment: buildAlignment(text, lab),
        });
      } catch (reason: unknown) {
        if (cancelled) return;
        console.warn('[host] 音素ラベルを読み込めませんでした', reason);
        // ラベルが無くても出題は止めない。chunks が空だと visibleLength は
        // 常に 0 を返すので、呼び出し側で全文表示に切り替える（hasAlignment）。
        // 音声そのものは鳴らせるので audioUrl は保つ。
        const text = question.text.trim();
        setLoaded({
          id: question.id,
          text,
          audioUrl: question.audio_url,
          alignment: { text, chunks: [] },
        });
      }
    })();

    return () => {
      cancelled = true;
    };
    // question の中身は id が変われば入れ替わる
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionId, labUrl]);

  return loaded;
}
