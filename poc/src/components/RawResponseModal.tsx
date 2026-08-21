import { useEffect, useRef } from 'react';

type Props = {
  title: string;
  raw: string;
  onClose: () => void;
};

/**
 * 生の応答を確認するモーダル。
 *
 * 応答フォーマット違反のとき、画面には違反した旨だけを出す。
 * なぜ違反になったかは生の応答を見ないと分からないため、ここで見せる。
 */
export function RawResponseModal({ title, raw, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        // 背景クリックで閉じる際に、中身のクリックまで拾わないようにする
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="modal-title">{title}</h2>
        <pre className="modal-raw">{raw === '' ? '(応答が空でした)' : raw}</pre>
        <button ref={closeRef} type="button" className="modal-close" onClick={onClose}>
          閉じる
        </button>
      </div>
    </div>
  );
}
