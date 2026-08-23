import type { ProviderInfo } from '../lib/llm';
import type { SlotSelection } from '../lib/llmSlots';
import type { HealthStatus, SlotPrediction } from '../lib/useLlmPrediction';
import { LlmSlot } from './LlmSlot';

type Props = {
  health: HealthStatus;
  providers: ProviderInfo[];
  slots: SlotSelection[];
  predictions: SlotPrediction[];
  manualCorrect: boolean[];
  expectedAnswer: string;
  /** 送信中は選択を変えさせない。送信済みの枠と表示がずれるため */
  disabled: boolean;
  /** 記録済み。手動正解の変更を止める */
  locked: boolean;
  onRefresh: () => void;
  onSelect: (index: number, selection: SlotSelection) => void;
  onToggleManual: (index: number) => void;
};

/**
 * LLM 予測枠。
 *
 * 既存 PoC と違い、この PoC は server が無いと何もできない。
 * そのため疎通しない場合は「縮退して動く」ではなく、起動方法を案内する。
 */
export function LlmPanel({
  health,
  providers,
  slots,
  predictions,
  manualCorrect,
  expectedAnswer,
  disabled,
  locked,
  onRefresh,
  onSelect,
  onToggleManual,
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
          サーバー未起動のため、予測を実行できません。
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
              expectedAnswer={expectedAnswer}
              manual={manualCorrect[index] ?? false}
              disabled={disabled}
              locked={locked}
              onSelect={onSelect}
              onToggleManual={onToggleManual}
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
