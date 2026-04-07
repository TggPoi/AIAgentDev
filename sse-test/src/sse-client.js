const http = require('http');

http.get('http://localhost:3000/events', (res) => {
  console.log('status:', res.statusCode);
  console.log('headers:', res.headers);
  console.log('--- 开始接收原始流 ---');

  res.on('data', (chunk) => {
    console.log('收到 chunk:');
    console.log(chunk.toString());
  });

  res.on('end', () => {
    console.log('--- 流结束 ---');
  });
});