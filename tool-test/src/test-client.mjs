import { spawn } from 'node:child_process';

const child = spawn('node', ['\src\\test-server.mjs'], {
  stdio: ['pipe', 'pipe', 'inherit'],
});

child.stdout.setEncoding('utf8');

child.stdout.on('data', (chunk) => {
  console.log('Client 收到 Server 响应:', chunk.toString());
});

child.stdin.write('你好，Server\n');

setTimeout(() => {
  child.stdin.write('请再回复一次\n');
}, 500);

setTimeout(() => {
  child.kill();
}, 1500);