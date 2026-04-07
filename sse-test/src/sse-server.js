const http = require('http');

const server = http.createServer((req, res) => {
  if (req.url === '/events') {
    // 1. 告诉客户端：这是 SSE
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    });

    let count = 0;

    const timer = setInterval(() => {
      count++;

      // 2. 发送一条 SSE 事件
      res.write(`data: 第 ${count} 条消息\n\n`);

      // 3. 发 5 条后结束
      if (count >= 5) {
        clearInterval(timer);
        res.write(`data: [DONE]\n\n`);
        res.end();
      }
    }, 1000);

    // 4. 客户端断开时清理
    req.on('close', () => {
      clearInterval(timer);
    });

    return;
  }

  // 普通页面
  res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('SSE server is running. Visit /events');
});

server.listen(3000, () => {
  console.log('SSE server running at http://localhost:3000');
});