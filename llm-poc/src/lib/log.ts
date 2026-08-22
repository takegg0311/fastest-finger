/**
 * 予測結果の記録。
 *
 * ブラウザからファイルへ追記できないため、記録はサーバが行う。
 * この PoC は LLM 予測が主目的で server の起動が前提であり、
 * 記録だけをローカル（localStorage）へ退避させる必要はない。
 *
 * 記録するのは「確定」操作の時点。正解の入力と手動正解ボタンの操作が
 * 済んでから 1 送信ぶんをまとめて送る。追記型の CSV は行の更新に
 * 向かないため、送信のたびに書いて後から直す方式は採らない。
 */

const BASE = '/api/llm';

/** 記録 1 件 = 1 送信 × 1 LLM */
export type LogRecord = {
  vendor: string;
  model: string;
  /** LLM が返した答え。失敗時は空 */
  answer: string;
  /** 補完された問題文全文。読み切り時と失敗時は null */
  continuation: string | null;
  elapsedMs: number;
  /** 予測が成功したか。応答ルール違反・エラーは false */
  ok: boolean;
  /** 失敗の種別。成功時は null */
  errorKind: string | null;
  /** 最終的な正誤（手動正解を反映した後） */
  correct: boolean;
  /** 手動正解ボタンで正解にしたか */
  manual: boolean;
};

export type LogPayload = {
  questionText: string;
  /** 読み切りとして送信したか */
  complete: boolean;
  expectedAnswer: string;
  records: LogRecord[];
};

/**
 * 1 送信ぶんの結果を CSV へ追記する。
 *
 * 失敗した場合はメッセージを返す。記録に失敗しても画面の状態は壊さず、
 * 何が起きたかだけを伝える（実験そのものは継続できるため）。
 */
export async function appendLog(payload: LogPayload): Promise<string | null> {
  try {
    const response = await fetch(`${BASE}/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question_text: payload.questionText,
        complete: payload.complete,
        expected_answer: payload.expectedAnswer,
        records: payload.records.map((record) => ({
          vendor: record.vendor,
          model: record.model,
          answer: record.answer,
          continuation: record.continuation,
          elapsed_ms: record.elapsedMs,
          ok: record.ok,
          error_kind: record.errorKind,
          correct: record.correct,
          manual: record.manual,
        })),
      }),
    });

    if (!response.ok) {
      return `記録に失敗しました（HTTP ${response.status}）`;
    }

    // HTTP ステータスだけでは足りない。サーバが 200 のまま ok: false を
    // 返す実装へ戻った場合に、取りこぼしを成功として扱ってしまうため、
    // 本文も確認する。
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null) {
      const data = body as Record<string, unknown>;
      if (data.ok === false) {
        return typeof data.error === 'string' ? data.error : '記録に失敗しました';
      }
    }

    return null;
  } catch (reason: unknown) {
    return reason instanceof Error ? reason.message : String(reason);
  }
}
