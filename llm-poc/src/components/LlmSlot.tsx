import { useState } from 'react';
import type { ProviderInfo } from '../lib/llm';
import type { SlotPrediction } from '../lib/useLlmPrediction';
import type { SlotSelection } from '../lib/llmSlots';
import { matchesAnswer } from '../lib/answer';
import { RawResponseModal } from './RawResponseModal';

type Props = {
  index: number;
  selection: SlotSelection;
  prediction: SlotPrediction;
  providers: ProviderInfo[];
  /** 入力された正解。空なら判定しない */
  expectedAnswer: string;
  /** 手動正解にされているか */
  manual: boolean;
  /** 枠の選択を変えられないか（送信中・記録済み） */
  disabled: boolean;
  /** 記録済み。手動正解の変更を止める */
  locked: boolean;
  onSelect: (index: number, selection: SlotSelection) => void;
  onToggleManual: (index: number) => void;
};

export function LlmSlot({
  index,
  selection,
  prediction,
  providers,
  expectedAnswer,
  manual,
  disabled,
  locked,
  onSelect,
  onToggleManual,
}: Props) {
  const [modalOpen, setModalOpen] = useState(false);

  const usable = providers.filter((provider) => provider.available);
  const current = usable.find((provider) => provider.vendor === selection.vendor);

  const handleVendorChange = (vendor: string) => {
    if (vendor === '') {
      onSelect(index, { vendor: null, model: null });
      return;
    }
    const provider = usable.find((item) => item.vendor === vendor);
    onSelect(index, { vendor, model: provider?.models[0] ?? null });
  };

  return (
    <div className={`llm-slot ${manual ? 'is-manual' : ''}`}>
      <div className="llm-slot-selectors">
        <select
          className="llm-select"
          value={selection.vendor ?? ''}
          disabled={disabled}
          aria-label={`枠 ${index + 1} のプロバイダ`}
          onChange={(event) => handleVendorChange(event.target.value)}
        >
          <option value="">（使わない）</option>
          {usable.map((provider) => (
            <option key={provider.vendor} value={provider.vendor}>
              {provider.label}
            </option>
          ))}
        </select>

        <select
          className="llm-select"
          value={selection.model ?? ''}
          disabled={disabled || current === undefined}
          aria-label={`枠 ${index + 1} のモデル`}
          onChange={(event) =>
            onSelect(index, { vendor: selection.vendor, model: event.target.value })
          }
        >
          {current === undefined ? (
            <option value="">—</option>
          ) : (
            current.models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))
          )}
        </select>
      </div>

      <div className="llm-slot-body">{renderBody()}</div>

      {modalOpen && (
        <RawResponseModal
          title={`${current?.label ?? ''} ${selection.model ?? ''} の応答`}
          raw={prediction.state === 'done' && 'raw' in prediction.result ? prediction.result.raw : ''}
          onClose={() => setModalOpen(false)}
        />
      )}
    </div>
  );

  function renderBody() {
    if (selection.vendor === null) {
      return <p className="llm-slot-idle">未選択</p>;
    }

    if (prediction.state === 'idle') {
      return <p className="llm-slot-idle">待機中</p>;
    }

    if (prediction.state === 'pending') {
      return (
        <p className="llm-slot-pending">
          <span className="spinner" aria-hidden="true" />
          予測中…
        </p>
      );
    }

    const { result } = prediction;

    if (result.status === 'error') {
      return (
        <>
          <p className="llm-slot-error">{result.message}</p>
          <p className="llm-slot-elapsed">{formatElapsed(result.elapsedMs)}</p>
        </>
      );
    }

    if (result.status === 'violation') {
      return (
        <>
          <p className="llm-slot-violation">応答ルール違反</p>
          <p className="llm-slot-violation-reason">{result.violation}</p>
          <div className="llm-slot-footer">
            <span className="llm-slot-elapsed">{formatElapsed(result.elapsedMs)}</span>
            <button type="button" className="llm-detail-button" onClick={() => setModalOpen(true)}>
              詳細
            </button>
          </div>
        </>
      );
    }

    // 正解が未入力のうちは判定しない。空欄に対して × が並ぶのを避ける
    const hasExpected = expectedAnswer.trim() !== '';
    const auto = hasExpected && matchesAnswer(result.answer, expectedAnswer);
    const correct = auto || manual;

    return (
      <>
        <p className="llm-slot-answer">
          {hasExpected && (
            <span
              className={`llm-slot-mark ${correct ? 'is-correct' : 'is-wrong'}`}
              aria-label={correct ? '正解' : '不正解'}
            >
              {correct ? '○' : '×'}
            </span>
          )}
          {result.answer}
        </p>

        {result.continuation !== null && (
          <p className="llm-slot-continuation">{result.continuation}</p>
        )}

        <div className="llm-slot-footer">
          <span className="llm-slot-elapsed">{formatElapsed(result.elapsedMs)}</span>
          <div className="llm-slot-actions">
            {/* 自動判定で既に正解なら手動は要らない。表記揺れ・別解のときだけ出す */}
            {hasExpected && !auto && (
              <button
                type="button"
                className={`llm-manual-button ${manual ? 'is-active' : ''}`}
                disabled={locked}
                aria-pressed={manual}
                onClick={() => onToggleManual(index)}
              >
                {manual ? '手動正解を取消' : '正解にする'}
              </button>
            )}
            <button type="button" className="llm-detail-button" onClick={() => setModalOpen(true)}>
              詳細
            </button>
          </div>
        </div>
      </>
    );
  }
}

function formatElapsed(elapsedMs: number): string {
  return `${(elapsedMs / 1000).toFixed(1)} 秒`;
}
