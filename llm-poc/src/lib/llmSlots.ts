/**
 * 予測枠の選択状態。vendor / model の組を最大 4 つ持ち、localStorage に残す。
 *
 * 保存するのは選択だけで、予測結果は残さない。予測結果は送信ごとに
 * 作り直し、確定時に CSV へ記録する（記録先はサーバ側）。
 */
import type { ProviderInfo } from './llm';

export const MAX_SLOTS = 4;

// 既存 PoC（poc/）とは別のキーにする。同じホスト（localhost）で動くため、
// 共有すると片方の枠選択がもう片方に引きずられる。
const STORAGE_KEY = 'fastest-finger:llm-poc:slots';

export type SlotSelection = {
  /** 未選択なら null。枠は残したまま使わない状態にできる */
  vendor: string | null;
  model: string | null;
};

export const EMPTY_SLOT: SlotSelection = { vendor: null, model: null };

/** 保存済みの選択を読む。壊れていれば空の 4 枠を返す */
export function loadSlots(): SlotSelection[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === null) return emptySlots();

    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return emptySlots();

    const slots = parsed.slice(0, MAX_SLOTS).map(toSlot);
    while (slots.length < MAX_SLOTS) slots.push({ ...EMPTY_SLOT });
    return slots;
  } catch {
    return emptySlots();
  }
}

export function saveSlots(slots: SlotSelection[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(slots));
  } catch {
    // プライベートブラウジングなどで書けなくても、動作は続けられる
  }
}

function emptySlots(): SlotSelection[] {
  return Array.from({ length: MAX_SLOTS }, () => ({ ...EMPTY_SLOT }));
}

function toSlot(value: unknown): SlotSelection {
  if (typeof value !== 'object' || value === null) return { ...EMPTY_SLOT };
  const record = value as Record<string, unknown>;
  return {
    vendor: typeof record.vendor === 'string' ? record.vendor : null,
    model: typeof record.model === 'string' ? record.model : null,
  };
}

/**
 * 保存されていた選択を、実際に使えるプロバイダへ突き合わせる。
 *
 * キーを外した・モデル一覧が変わった場合に、選べない組み合わせが
 * 残らないようにする。使えなくなった枠は未選択に戻す。
 */
export function reconcile(slots: SlotSelection[], providers: ProviderInfo[]): SlotSelection[] {
  const usable = new Map(
    providers.filter((provider) => provider.available).map((provider) => [provider.vendor, provider]),
  );

  return slots.map((slot) => {
    if (slot.vendor === null) return { ...EMPTY_SLOT };

    const provider = usable.get(slot.vendor);
    if (provider === undefined) return { ...EMPTY_SLOT };

    // vendor は使えるがモデルが消えている場合は、先頭のモデルへ寄せる
    if (slot.model === null || !provider.models.includes(slot.model)) {
      return { vendor: slot.vendor, model: provider.models[0] ?? null };
    }

    return slot;
  });
}

/**
 * 初期選択を決める。保存が無い場合に、使えるプロバイダを先頭から並べる。
 * 同じ vendor の別モデルを並べることもできるが、既定では 1 社 1 枠とする。
 */
export function defaultSlots(providers: ProviderInfo[]): SlotSelection[] {
  const usable = providers.filter((provider) => provider.available);
  const slots = emptySlots();

  usable.slice(0, MAX_SLOTS).forEach((provider, index) => {
    slots[index] = { vendor: provider.vendor, model: provider.models[0] ?? null };
  });

  return slots;
}

/** 実際に送信できる枠だけを取り出す */
export function activeSlots(slots: SlotSelection[]): { vendor: string; model: string }[] {
  return slots.flatMap((slot) =>
    slot.vendor !== null && slot.model !== null
      ? [{ vendor: slot.vendor, model: slot.model }]
      : [],
  );
}
