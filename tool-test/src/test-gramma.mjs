import fs from'node:fs/promises';
import path from'node:path';

let filePath = '/project/docs/report.txt';
const dir = path.dirname(filePath);
console.log(`  [工具调用] execute_command("${dir}")`);