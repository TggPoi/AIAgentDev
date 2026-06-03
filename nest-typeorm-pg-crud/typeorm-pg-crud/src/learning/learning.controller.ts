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

@Controller('learning/tasks')
export class LearningController {
  constructor(private readonly learningService: LearningService) {}

  @Post()
  create(@Body() dto: CreateAgentTaskDto) {
    return this.learningService.create(dto);
  }

  @Post('upsert')
  upsert(@Body() dto: CreateAgentTaskDto) {
    return this.learningService.upsert(dto);
  }

  @Post('claim')
  claim(@Body() dto: ClaimAgentTaskDto) {
    return this.learningService.claimNextQueuedTask(dto.workerId);
  }

  @Get('stats')
  stats() {
    return this.learningService.getStatusCounts();
  }

  @Get()
  findAll(@Query() dto: ListAgentTasksDto) {
    return this.learningService.findAll(dto);
  }

  @Get(':id')
  findOne(@Param('id', ParseUUIDPipe) id: string) {
    return this.learningService.findOne(id);
  }

  @Patch(':id')
  update(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: UpdateAgentTaskDto,
  ) {
    return this.learningService.update(id, dto);
  }

  @Delete(':id')
  remove(@Param('id', ParseUUIDPipe) id: string) {
    return this.learningService.remove(id);
  }

  @Post(':id/runs')
  createRun(
    @Param('id', ParseUUIDPipe) id: string,
    @Body() dto: CreateAgentRunDto,
  ) {
    return this.learningService.createRun(id, dto);
  }
}
