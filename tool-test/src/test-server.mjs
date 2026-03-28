process.stdin.setEncoding('utf8');

process.stdin.on('data', (chunk) => {
  const input = chunk.toString().trim();

  if (!input) {
    return;
  }

  const response = `服务器收到消息：${input}\n`;

  process.stdout.write(response);
});