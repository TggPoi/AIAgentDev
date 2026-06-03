import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { AgentRun } from './entities/agent-run.entity';
import { AgentTask } from './entities/agent-task.entity';
import { LearningController } from './learning.controller';
import { LearningService } from './learning.service';

@Module({
  imports: [TypeOrmModule.forFeature([AgentTask, AgentRun])],
  controllers: [LearningController],
  providers: [LearningService],
})
export class LearningModule {}
