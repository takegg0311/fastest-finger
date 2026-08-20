/**
 * 早押しボタン。
 *
 * onClick ではなく onPointerDown で発火させる。click は指を離すまで
 * 発火せず、その分だけ不利になるため。
 */
type Props = {
  disabled: boolean;
  onBuzz: () => void;
};

export function BuzzButton({ disabled, onBuzz }: Props) {
  return (
    <button
      type="button"
      className="buzz-button"
      disabled={disabled}
      onPointerDown={(event) => {
        // 押した指でスクロールや長押しメニューが出ないようにする
        event.preventDefault();
        if (!disabled) onBuzz();
      }}
    >
      <span className="buzz-button-label">PUSH</span>
    </button>
  );
}
