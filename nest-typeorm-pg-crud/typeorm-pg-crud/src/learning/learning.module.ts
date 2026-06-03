import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { AgentRun } from './entities/agent-run.entity';
import { AgentTask } from './entities/agent-task.entity';
import { LearningController } from './learning.controller';
import { LearningService } from './learning.service';

@Module({
  // forFeature 会把 AgentTask、AgentRun 对应的 Repository 注册到当前模块。
  // 注册后，Service 才能使用 @InjectRepository(AgentTask) 注入 Repository。
  imports: [TypeOrmModule.forFeature([AgentTask, AgentRun])],
  // Controller 负责暴露 HTTP 接口。
  controllers: [LearningController],
  // Provider 负责承载业务逻辑，并由 Nest 依赖注入系统管理生命周期。
  providers: [LearningService],
})
export class LearningModule {}
