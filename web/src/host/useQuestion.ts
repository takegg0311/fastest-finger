/**
 * 出題内容から、文字送りに必要なアライメントを組み立てる。
 *
 * .lab の解析と対応付けは出題者フロントで行い、サーバへは持たせない。
 * 文字送りは「ローカルの audio.currentTime に対する純粋な関数」であり、
 * 音声を鳴らしているのはこの画面自身なので、間にネットワークを挟めば
 * 精度が落ちるだけで得るものが無い。
 */
import { useEffect, useState } from 'react';
import { buildAlignment, type Alignment } from '../lib/align';
import { parseLab } from '../lib/lab';
import type { QuestionView } from '../protocol';

export type LoadedQuestion = {
  id: string;
  text: string;
  audioUrl: string;
  answers: string[];
  alignment: Alignment;
};

export function useQuestion(question: QuestionView | null): LoadedQuestion | null {
  const [loaded, setLoaded] = useState<LoadedQuestion | null>(null);

  const questionId = question?.id ?? null;
  const labUrl = question?.lab_url ?? null;

  useEffect(() => {
    if (question === null || labUrl === null) {
      setLoaded(null);
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
          answers: question.answers,
          alignment: buildAlignment(text, lab),
        });
      } catch (reason: unknown) {
        if (cancelled) return;
        console.warn('[host] 音素ラベルを読み込めませんでした', reason);
        // ラベルが無くても出題は止めない。chunks が空だと visibleLength は
        // 常に 0 を返すので、呼び出し側で全文表示に切り替える（hasAlignment）
        const text = question.text.trim();
        setLoaded({
          id: question.id,
          text,
          audioUrl: question.audio_url,
          answers: question.answers,
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
