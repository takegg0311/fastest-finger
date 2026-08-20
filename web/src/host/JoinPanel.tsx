/**
 * 参加用 URL と QR コード。
 *
 * これが無いと当日「192.168.x.x を口頭で伝える」ことになり、
 * 会場で最初に詰まる。
 */
import { useEffect, useState } from 'react';
import QRCode from 'qrcode';

type RoomInfo = {
  join_url: string;
};

export function JoinPanel() {
  const [joinUrl, setJoinUrl] = useState<string | null>(null);
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const response = await fetch('/api/room');
        if (!response.ok) throw new Error('参加用 URL を取得できませんでした');

        const info = (await response.json()) as RoomInfo;
        if (cancelled) return;

        setJoinUrl(info.join_url);
        setQrDataUrl(
          await QRCode.toDataURL(info.join_url, {
            width: 320,
            margin: 1,
            color: { dark: '#0d1117', light: '#ffffff' },
          }),
        );
      } catch (reason: unknown) {
        console.warn('[host] 参加用 URL を取得できませんでした', reason);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  if (joinUrl === null) return null;

  return (
    <section className="join-panel">
      <p className="join-panel-label">スマホで読み取って参加</p>
      {qrDataUrl !== null && <img className="join-panel-qr" src={qrDataUrl} alt="参加用 QR コード" />}
      <p className="join-panel-url">{joinUrl}</p>
    </section>
  );
}
