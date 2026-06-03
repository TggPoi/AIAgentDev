import { IsNotEmpty, IsString, MaxLength } from 'class-validator';

// DTO 描述接口请求体的结构。
// ClaimAgentTaskDto 用在 POST /learning/tasks/claim。
export class ClaimAgentTaskDto {
  // workerId 表示是哪一个 worker 在领取任务。
  // 实际项目中可以放机器名、进程 ID、容器 ID 或业务 worker 名称。
  @IsString()
  @IsNotEmpty()
  @MaxLength(200)
  workerId: string;
}
