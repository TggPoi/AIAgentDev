import { forwardRef, Module } from '@nestjs/common';
import { JobService } from './job.service';
import { JobAgentService } from '../ai/job-agent.service';
import { ToolModule } from '../tool/tool.module';

@Module({
  imports: [forwardRef(() => ToolModule)],
  providers: [JobService, JobAgentService],
  exports: [JobService],
})
export class JobModule {}