const http = require('http');

const server = http.createServer((req, res) => {
  if (req.url === '/events') {
    // 1. 告诉客户端：这是 SSE 响应
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    });

    let count = 0;

    const timer = setInterval(() => {
      count++;

      const payload = {
        index: count,
        message: `这是第 ${count} 条 SSE 消息`,
        time: new Date().toISOString(),
      };

      // 2. 按 SSE 格式发送一条事件
      // 每条消息以空行结束
      res.write(`data: ${JSON.stringify(payload)}\n\n`);

      if (count >= 5) {
        clearInterval(timer);

        // 3. 发送一个结束标记
        res.write(`data: [DONE]\n\n`);
        res.end();
      }
    }, 1000);

    // 4. 客户端断开时清理定时器
    req.on('close', () => {
      clearInterval(timer);
    });

    return;
  }

  res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('SSE server running. Visit /events');
});

server.listen(3000, () => {
  console.log('SSE server running at http://localhost:3000');
});