/** 参加時の名前入力。出題者用画面へ表示するために使う */
import { useState } from 'react';

type Props = {
  defaultValue: string;
  disabled: boolean;
  onSubmit: (name: string) => void;
};

export function NameForm({ defaultValue, disabled, onSubmit }: Props) {
  const [value, setValue] = useState(defaultValue);
  const trimmed = value.trim();

  return (
    <form
      className="name-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (trimmed !== '') onSubmit(trimmed);
      }}
    >
      <label className="name-form-label" htmlFor="player-name">
        名前を入力してください
      </label>
      <input
        id="player-name"
        className="name-form-input"
        value={value}
        maxLength={12}
        autoComplete="off"
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit" className="name-form-submit" disabled={disabled || trimmed === ''}>
        参加する
      </button>
    </form>
  );
}
