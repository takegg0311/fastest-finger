import { useState } from 'react';
import type { ProviderInfo } from '../lib/llm';
import type { SlotPrediction } from '../lib/useLlmPrediction';
import type { SlotSelection } from '../lib/llmSlots';
import { isCorrect } from '../lib/answer';
import { RawResponseModal } from './RawResponseModal';

type Props = {
  index: number;
  selection: SlotSelection;
  prediction: SlotPrediction;
  providers: ProviderInfo[];
  /** 正解と別解。判定に使う */
  answers: string[];
  /**
   * 正誤を出してよいか。人間が回答するまでは伏せる。
   * 先に ○/× が出ると、それを見て答えられてしまうため。
   */
  revealJudgement: boolean;
  disabled: boolean;
  onSelect: (index: number, selection: SlotSelection) => void;
};

export function LlmSlot({
  index,
  selection,
  prediction,
  providers,
  answers,
  revealJudgement,
  disabled,
  onSelect,
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
    <div className="llm-slot">
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

      <div className="llm-slot-body">
        {renderBody()}
      </div>

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

    // 正誤は人間が回答するまで出さない
    const correct = isCorrect(result.answer, answers);

    return (
      <>
        <p className="llm-slot-answer">
          {revealJudgement && (
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
          <button type="button" className="llm-detail-button" onClick={() => setModalOpen(true)}>
            詳細
          </button>
        </div>
      </>
    );
  }
}

function formatElapsed(elapsedMs: number): string {
  return `${(elapsedMs / 1000).toFixed(1)} 秒`;
}
