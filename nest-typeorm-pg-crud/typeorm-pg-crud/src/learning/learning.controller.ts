import {
  Body,
  Controller,
  Delete,
  Get,
  Param,
  ParseUUIDPipe,
  Patch,
  Post,
  Query,
} from '@nestjs/common';
import { ClaimAgentTaskDto } from './dto/claim-agent-task.dto';
import { CreateAgentRunDto } from './dto/create-agent-run.dto';
import { CreateAgentTaskDto } from './dto/create-agent-task.dto';
import { ListAgentTasksDto } from './dto/list-agent-tasks.dto';
import { UpdateAgentTaskDto } from './dto/update-agent-task.dto';
import { LearningService } from './learning.service';

// Controller 负责把 HTTP 请求映射到 Service 方法。
// 这里的所有接口都会带上统一前缀：/learning/tasks。
@Controller('learning/tasks')
export class LearningController {
  // Nest 会通过依赖注入创建 LearningService 实例。
  // Controller 不直接操作数据库，只负责接收参数并调用业务逻辑。
  constructor(private readonly learningService: LearningService) {}

  // POST /learning/tasks
  // 普通创建：每次请求都会尝试创建一条新任务。
  @Post()
  create(@Body() dto: CreateAgentTaskDto) {
    return this.learningService.create(dto);
  }

  // POST /learning/tasks/upsert
  // 幂等创建或更新：externalKey 相同则复用同一条业务任务。
  @Post('upsert')
  upsert(@Body() dto: CreateAgentTaskDto) {
    return this.learningService.upsert(dto);
  }

  // POST /learning/tasks/claim
  // worker 领取一条可执行任务，用于学习并发领取和行锁。
  @Post('claim')
  claim(@Body() dto: ClaimAgentTaskDto) {
    return this.learningService.claimNextQueuedTask(dto.workerId);
  }

  // GET /learning/tasks/stats
  // 统计每种任务状态下有多少条任务。
  @Get('stats')
  stats() {
    return this.learningService.getStatusCounts();
  }

  // GET /learning/tasks?limit=20&beforeCreatedAt=...&beforeId=...
  // 使用游标分页读取任务列表。
  @Get()
  findAll(@Query() dto: ListAgentTasksDto) {
    return this.learningService.findAll(dto);
  }

  // GET /learning/tasks/:id
  // ParseUUIDPipe 会先校验 id 是否是合法 UUID，不合法会直接返回 400。
  @Get(':id')
  findOne(@Param('id', ParseUUIDPipe) id: string) {
    return this.learningService.findOne(id);
  }

  // PATCH /learning/tasks/:id
  // 使用 expectedVersion 做乐观锁更新，避免覆盖别人刚刚提交的修改。
  @Patch(':id')
  update(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateAgentTaskDto,
  ) {
    return this.learningService.update(id, dto);
  }

  // DELETE /learning/tasks/:id
  // 删除一条任务；如果任务不存在，Service 会抛出 404。
  @Delete(':id')
  remove(@Param('id', ParseUUIDPipe) id: string) {
    return this.learningService.remove(id);
  }

  // POST /learning/tasks/:id/runs
  // 为某个任务创建一次运行记录，并把任务状态改为 running。
  @Post(':id/runs')
  createRun(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: CreateAgentRunDto,
  ) {
    return this.learningService.createRun(id, dto);
  }
}
