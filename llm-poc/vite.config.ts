import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // この PoC は LLM 予測が主目的であり、server が起動していなければ
    // 何もできない。既存 PoC の「サーバーが無ければ縮退」とは前提が異なる。
    // /api/llm には予測（predict）と記録（log）の両方が含まれる。
    proxy: {
      '/api/llm': {
        target: 'http://localhost:8000',
        // server 未起動を 500（サーバ内部エラー）ではなく 502 で返す。
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
