import {
  IsISO8601,
  IsNotEmpty,
  IsObject,
  IsOptional,
  IsString,
  MaxLength,
} from 'class-validator';

// 创建 AgentTask 的请求体。
// class-validator 装饰器会配合全局 ValidationPipe 自动校验请求参数。
export class CreateAgentTaskDto {
  // externalKey 是业务幂等键。
  // upsert 时会根据这个字段判断“同一个外部任务”是否已经存在。
  @IsString()
  @IsNotEmpty()
  @MaxLength(200)
  externalKey: string;

  // title 是任务标题，适合展示在任务列表中。
  @IsString()
  @IsNotEmpty()
  @MaxLength(500)
  title: string;

  // description 是可选长文本，数据库中允许为 null。
  @IsOptional()
  @IsString()
  @MaxLength(4000)
  description?: string;

  // metadata 对应数据库 jsonb 字段，保存结构不固定的补充信息。
  @IsOptional()
  @IsObject()
  metadata?: Record<string, unknown>;

  // availableAt 控制任务最早什么时候可以被 worker 领取。
  // 使用 ISO8601 字符串，例如 2026-06-03T10:00:00.000Z。
  @IsOptional()
  @IsISO8601()
  availableAt?: string;
}
