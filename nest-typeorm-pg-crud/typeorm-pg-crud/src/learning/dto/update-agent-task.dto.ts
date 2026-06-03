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

export class UpdateAgentTaskDto {
  @Type(() => Number)
  @IsInt()
  @Min(1)
  expectedVersion: number;

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

  @IsOptional()
  @IsEnum(AgentTaskStatus)
  status?: AgentTaskStatus;

  @IsOptional()
  @IsISO8601()
  availableAt?: string;
}
