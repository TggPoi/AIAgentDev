import { IsObject, IsOptional } from 'class-validator';

// 创建一次任务运行记录时的请求体。
export class CreateAgentRunDto {
  // input 用 jsonb 保存本次运行的输入。
  // 结构可能因不同 Agent 或工具而变化，所以使用 Record<string, unknown>。
  @IsOptional()
  @IsObject()
  input?: Record<string, unknown>;
}
