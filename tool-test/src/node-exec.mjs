import { spawn } from'node:child_process';

//linux命令
//const command = 'ls -la';
//const command = 'echo -e "n\nn" | pnpm create vite react-todo-app --template react-ts';

//Windows命令
//const command = 'dir /a';
const command = 'echo n,n | pnpm create vite react-todo-app --template react-ts';
const cwd = process.cwd();

// 解析命令和参数
const [cmd, ...args] = command.split(' ');

const child = spawn(cmd, args, {
  cwd,
stdio: 'inherit', // 实时输出到控制台
shell: true,
});

let errorMsg = '';

child.on('error', (error) => {
  errorMsg = error.message;
});

child.on('close', (code) => {
if (code === 0) {
    process.exit(0);
  } else {
    if (errorMsg) {
      console.error(`错误: ${errorMsg}`);
    }
    process.exit(code || 1);
  }
});