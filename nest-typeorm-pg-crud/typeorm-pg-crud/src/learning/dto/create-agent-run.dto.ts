import { IsObject, IsOptional } from 'class-validator';

export class CreateAgentRunDto {
  @IsOptional()
  @IsObject()
  input?: Record<string, unknown>;
}
