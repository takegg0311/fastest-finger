/**
 * LLM 予測 API の呼び出し。
 *
 * API キーはブラウザに置けず、各社 API にはブラウザからの直接呼び出しに
 * CORS 制限があるため、server/ が中継する。開発時は vite.config.ts の
 * proxy が /api/llm を localhost:8000 へ送る。
 *
 * server が無くても PoC は従来どおり動く必要がある。疎通しない場合は
 * checkHealth が null を返し、呼び出し側が予測枠を縮退させる。
 */

const BASE = '/api/llm';

/** health の疎通確認が待つ時間。起動時に走るので短く切る */
const HEALTH_TIMEOUT_MS = 3000;

/**
 * 予測 1 件の上限。server 側も 60 秒で切るが、そちらが無反応な場合に
 * 備えてフロントでも同じだけ待って諦める。
 */
const PREDICT_TIMEOUT_MS = 60000;

export type ProviderInfo = {
  vendor: string;
  /** 画面に出す表示名 */
  label: string;
  available: boolean;
  models: string[];
  /** 使えない理由。キー未設定か未実装か */
  reason?: string;
};

/** 予測が成功した場合の結果 */
export type PredictSuccess = {
  status: 'ok';
  /** 補完後の問題文全文。読み切り時は返らないことがある */
  continuation: string | null;
  answer: string;
  elapsedMs: number;
  raw: string;
};

/**
 * 応答フォーマット違反。処理は成功しているが、モデルが指示に従わなかった。
 * エラーとは区別して扱う。
 */
export type PredictViolation = {
  status: 'violation';
  violation: string;
  elapsedMs: number;
  raw: string;
};

/** API エラーやネットワーク断 */
export type PredictError = {
  status: 'error';
  message: string;
  elapsedMs: number;
};

export type PredictResult = PredictSuccess | PredictViolation | PredictError;

/**
 * 利用可能なプロバイダを問い合わせる。
 * server が起動していない場合は null を返す（エラーにしない）。
 */
export async function checkHealth(): Promise<ProviderInfo[] | null> {
  try {
    const response = await fetch(`${BASE}/health`, {
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
    if (!response.ok) return null;

    const body: unknown = await response.json();
    if (typeof body !== 'object' || body === null) return null;

    const providers = (body as { providers?: unknown }).providers;
    if (!Array.isArray(providers)) return null;

    return providers as ProviderInfo[];
  } catch {
    // server 未起動・プロキシ無し・タイムアウトはすべて「疎通しない」で扱う
    return null;
  }
}

/**
 * 問題文から答えを予測させる。
 *
 * 渡すのは早押し時点で表示されていた文字列だけ。問題文の全文と正解は
 * PoC が保持したままにし、サーバへは送らない（complete が true の場合の
 * partialText は結果的に全文になるが、正解は依然として送らない）。
 */
export async function predict(
  vendor: string,
  model: string,
  partialText: string,
  complete: boolean,
): Promise<PredictResult> {
  const startedAt = performance.now();

  try {
    const response = await fetch(`${BASE}/predict`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        vendor,
        model,
        partial_text: partialText,
        complete,
      }),
      signal: AbortSignal.timeout(PREDICT_TIMEOUT_MS),
    });

    if (!response.ok) {
      return {
        status: 'error',
        message: `サーバがエラーを返しました（HTTP ${response.status}）`,
        elapsedMs: Math.round(performance.now() - startedAt),
      };
    }

    return toResult(await response.json(), startedAt);
  } catch (reason: unknown) {
    const elapsedMs = Math.round(performance.now() - startedAt);
    if (reason instanceof DOMException && reason.name === 'TimeoutError') {
      return {
        status: 'error',
        message: `応答がありませんでした（${PREDICT_TIMEOUT_MS / 1000} 秒）`,
        elapsedMs,
      };
    }
    return {
      status: 'error',
      message: reason instanceof Error ? reason.message : String(reason),
      elapsedMs,
    };
  }
}

/**
 * サーバの応答を画面用の形へ写す。
 *
 * サーバは違反もエラーも HTTP 200 で返す（枠ごとの失敗は画面に出す情報で
 * あってリクエスト自体の失敗ではないため）。ここで 3 通りへ振り分ける。
 */
function toResult(body: unknown, startedAt: number): PredictResult {
  const fallbackElapsed = Math.round(performance.now() - startedAt);

  if (typeof body !== 'object' || body === null) {
    return { status: 'error', message: '応答を解釈できませんでした', elapsedMs: fallbackElapsed };
  }

  const data = body as Record<string, unknown>;
  // 応答時間はサーバ側の実測（API 呼び出しのみ）を使う。
  // ネットワーク往復を含むフロント側の計測より、モデルの比較に適するため。
  const elapsedMs = typeof data.elapsed_ms === 'number' ? data.elapsed_ms : fallbackElapsed;
  const raw = typeof data.raw === 'string' ? data.raw : '';

  if (data.ok === true) {
    return {
      status: 'ok',
      continuation: typeof data.continuation === 'string' ? data.continuation : null,
      answer: typeof data.answer === 'string' ? data.answer : '',
      elapsedMs,
      raw,
    };
  }

  if (typeof data.violation === 'string') {
    return { status: 'violation', violation: data.violation, elapsedMs, raw };
  }

  return {
    status: 'error',
    message: typeof data.error === 'string' ? data.error : '予測に失敗しました',
    elapsedMs,
  };
}
