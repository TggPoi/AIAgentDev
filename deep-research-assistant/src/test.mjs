import path from "node:path";
import { fileURLToPath } from "node:url";

const projectDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);

//项目根目录: D:\AI_Agent_Project\deep-research-assistant
console.log("项目根目录:", projectDir);