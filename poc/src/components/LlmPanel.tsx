import type { ProviderInfo } from '../lib/llm';
import type { SlotSelection } from '../lib/llmSlots';
import type { HealthStatus, SlotPrediction } from '../lib/useLlmPrediction';
import { LlmSlot } from './LlmSlot';

type Props = {
  health: HealthStatus;
  providers: ProviderInfo[];
  slots: SlotSelection[];
  predictions: SlotPrediction[];
  answers: string[];
  revealJudgement: boolean;
  /** 出題中は選択を変えさせない。送信済みの枠と表示がずれるため */
  disabled: boolean;
  onRefresh: () => void;
  onSelect: (index: number, selection: SlotSelection) => void;
};

/**
 * LLM 予測枠。
 *
 * server が起動していなくても PoC は従来どおり動く必要があるため、
 * 疎通しない場合も枠自体は表示し、理由を出す。なぜ予測が出ないのかが
 * 分からないと、設定の誤りなのか未起動なのか判断できない。
 */
export function LlmPanel({
  health,
  providers,
  slots,
  predictions,
  answers,
  revealJudgement,
  disabled,
  onRefresh,
  onSelect,
}: Props) {
  const unusable = providers.filter((provider) => !provider.available);
  const hasUsable = providers.some((provider) => provider.available);

  return (
    <section className="llm-panel">
      <header className="llm-panel-header">
        <h2 className="llm-panel-title">LLM の予測</h2>
        <div className="llm-panel-status">
          <span className={`llm-health is-${health}`}>{healthLabel(health)}</span>
          <button
            type="button"
            className="llm-refresh-button"
            onClick={onRefresh}
            disabled={health === 'checking'}
          >
            再チェック
          </button>
        </div>
      </header>

      {health === 'offline' && (
        <p className="llm-panel-notice">
          サーバー未起動。LLM の予測は使えませんが、早押しと回答は通常どおり行えます。
          <br />
          <code>cd server &amp;&amp; uv run uvicorn app.main:app --port 8000</code>
          {' '}で起動し、再チェックを押してください。
        </p>
      )}

      {health === 'online' && !hasUsable && (
        <p className="llm-panel-notice">
          利用できるプロバイダがありません。<code>server/.env</code> に API キーを設定してください。
        </p>
      )}

      {health === 'online' && hasUsable && (
        <div className="llm-slots">
          {slots.map((slot, index) => (
            <LlmSlot
              key={index}
              index={index}
              selection={slot}
              prediction={predictions[index] ?? { state: 'idle' }}
              providers={providers}
              answers={answers}
              revealJudgement={revealJudgement}
              disabled={disabled}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}

      {health === 'online' && unusable.length > 0 && (
        <p className="llm-panel-unusable">
          利用不可: {unusable.map((provider) => `${provider.label}（${provider.reason ?? '理由不明'}）`).join(' / ')}
        </p>
      )}
    </section>
  );
}

function healthLabel(health: HealthStatus): string {
  if (health === 'checking') return '確認中…';
  return health === 'online' ? 'サーバー接続済み' : 'サーバー未起動';
}
