import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // LLM 予測だけはバックエンドを経由する。API キーをフロントのバンドルへ
    // 埋め込めず、各社 API にはブラウザからの直接呼び出しに CORS 制限が
    // あるため。server が起動していなければ予測枠が縮退するだけで、
    // 早押しと手入力回答は従来どおり動く。
    //
    // 中継するのは /api/llm だけとする。問題データ（/quiz_data）と
    // ジングル（/sound）は PoC 自身が public から配信しており、
    // バックエンドには依存しない。
    proxy: {
      '/api/llm': {
        target: 'http://localhost:8000',
        // server が起動していないのは異常ではなく、想定した縮退状態。
        // 既定では ECONNREFUSED が 500（サーバ内部エラー）として返るが、
        // 実際には上流が応答しないだけなので 502 を返す。
        // ブラウザのコンソールへの出力自体は抑制できないが、
        // ステータスを見たときに原因を取り違えずに済む。
        configure: (proxy) => {
          proxy.on('error', (_error, _request, response) => {
            if ('writeHead' in response && !response.headersSent) {
              response.writeHead(502, { 'Content-Type': 'application/json' });
              response.end('{"error":"server not running"}');
            }
          });
        },
      },
    },
  },
});
