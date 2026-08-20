/**
 * WebSocket のメッセージ型。server/app/protocol.py と対になる。
 * 片方を変えたらもう片方も変えること。
 */

export type Phase =
  | 'idle'
  /** 問題音声を再生中。早押しを受け付ける */
  | 'reading'
  /** 読み切ったが、まだ締め切っていない。早押しを受け付ける */
  | 'readingEnded'
  /** 誰かが回答権を得た。正解はまだ出さない */
  | 'buzzed'
  /** 正解を確認して正誤を判定する。ここで正解が投影に出る */
  | 'check'
  /** 誰も押さずに締め切った */
  | 'timeUp'
  | 'result';

export type BuzzRejectReason =
  | 'too_late'
  | 'stale_round'
  | 'locked_out'
  | 'wrong_phase';

export type PlayerView = {
  id: string;
  name: string;
  /** 切断しても一覧からは消さない。投影画面から名前が消えると混乱するため */
  connected: boolean;
  /** お手つきで同一ラウンドの早押しを禁じられている */
  locked_out: boolean;
};

export type BuzzedView = {
  player_id: string;
  name: string;
};

/** 出題内容。回答者へは null で送られる */
export type QuestionView = {
  id: string;
  text: string;
  audio_url: string;
  lab_url: string;
  /**
   * 正解と別解。投影は参加者も見るため、正解を出してよい phase
   * （check / timeUp / result）でのみ値が入る。それ以外は null。
   */
  answers: string[] | null;
};

export type JudgementView = {
  player_id: string;
  name: string;
  correct: boolean;
};

// ---------------------------------------------------- クライアント → サーバ

export type ClientMessage =
  | { type: 'join'; name: string; token?: string | null }
  | { type: 'host_hello'; host_token: string }
  | { type: 'buzz'; round_id: number; client_sent_at?: number }
  | { type: 'start_question'; question_id?: string | null }
  | { type: 'reading_ended'; round_id: number }
  | { type: 'time_up'; round_id: number }
  | { type: 'check'; round_id: number }
  | { type: 'judge'; round_id: number; correct: boolean }
  | { type: 'release'; round_id: number }
  | { type: 'next' };

// ---------------------------------------------------- サーバ → クライアント

export type WelcomeMessage = {
  type: 'welcome';
  player_id: string;
  token: string;
  role: 'player' | 'host';
};

export type RoomStateMessage = {
  type: 'room_state';
  round_id: number;
  phase: Phase;
  players: PlayerView[];
  buzzed: BuzzedView | null;
  question: QuestionView | null;
  judgement: JudgementView | null;
};

export type BuzzAcceptedMessage = {
  type: 'buzz_accepted';
  round_id: number;
  player_id: string;
  name: string;
};

export type BuzzRejectedMessage = {
  type: 'buzz_rejected';
  round_id: number;
  reason: BuzzRejectReason;
};

export type ErrorMessage = {
  type: 'error';
  code: string;
  message: string;
};

export type ServerMessage =
  | WelcomeMessage
  | RoomStateMessage
  | BuzzAcceptedMessage
  | BuzzRejectedMessage
  | ErrorMessage;

/** 押せなかった理由を、回答者に見せる文言にする */
export function describeRejectReason(reason: BuzzRejectReason): string {
  switch (reason) {
    case 'too_late':
      return '他の人が先に押しました';
    case 'locked_out':
      return 'この問題では、もう押せません';
    case 'stale_round':
    case 'wrong_phase':
      return '今は押せません';
  }
}
