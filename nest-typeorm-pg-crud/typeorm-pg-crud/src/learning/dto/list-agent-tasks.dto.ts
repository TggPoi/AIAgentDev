import { Type } from 'class-transformer';
import {
  IsISO8601,
  IsInt,
  IsOptional,
  IsUUID,
  Max,
  Min,
} from 'class-validator';

// 查询任务列表的 query string DTO。
// 示例：GET /learning/tasks?limit=20&beforeCreatedAt=...&beforeId=...
export class ListAgentTasksDto {
  // URL query 参数默认是字符串。
  // @Type(() => Number) 会把 "20" 转成数字 20，然后 IsInt 才能正确校验。
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(100)
  limit?: number;

  // 游标分页的时间部分。
  // 它必须和 beforeId 一起出现，避免同一 createdAt 下翻页不稳定。
  @IsOptional()
  @IsISO8601()
  beforeCreatedAt?: string;

  // 游标分页的 id 部分。
  // createdAt + id 组合可以形成稳定排序。
  @IsOptional()
  @IsUUID()
  beforeId?: string;
}
