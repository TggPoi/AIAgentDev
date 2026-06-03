import { IsNotEmpty, IsString, MaxLength } from 'class-validator';

export class ClaimAgentTaskDto {
  @IsString()
  @IsNotEmpty()
  @MaxLength(200)
  workerId: string;
}
