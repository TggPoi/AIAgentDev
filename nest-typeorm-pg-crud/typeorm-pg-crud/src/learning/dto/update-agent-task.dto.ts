import { Type } from 'class-transformer';
import {
  IsEnum,
  IsISO8601,
  IsInt,
  IsObject,
  IsOptional,
  IsString,
  MaxLength,
  Min,
} from 'class-validator';
import { AgentTaskStatus } from '../entities/agent-task.entity';

// 更新任务时的请求体。
// 这个 DTO 同时承担“字段校验”和“乐观锁版本号校验”的职责。
export class UpdateAgentTaskDto {
  // expectedVersion 是客户端读取数据时看到的版本号。
  // 更新时要求数据库当前 version 仍然等于它，否则说明数据已经被别人改过。
  @Type(() => Number)
  @IsInt()
  @Min(1)
  expectedVersion: number;

  // 以下字段都是可选字段，表示 PATCH 语义：只更新请求中出现的字段。
  @IsOptional()
  @IsString()
  @MaxLength(500)
  title?: string;

  @IsOptional()
  @IsString()
  @MaxLength(4000)
  description?: string;

  @IsOptional()
  @IsObject()
  metadata?: Record<string, unknown>;

  // status 必须是 AgentTaskStatus 枚举中的值。
  // 这样可以避免写入随意字符串，例如 "doing"、"done"。
  @IsOptional()
  @IsEnum(AgentTaskStatus)
  status?: AgentTaskStatus;

  // 允许重新设置任务可领取时间。
  @IsOptional()
  @IsISO8601()
  availableAt?: string;
}
