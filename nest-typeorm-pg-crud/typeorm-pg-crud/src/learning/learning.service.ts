import {
  BadRequestException,
  ConflictException,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { DataSource, QueryDeepPartialEntity, Repository } from 'typeorm';
import { CreateAgentRunDto } from './dto/create-agent-run.dto';
import { CreateAgentTaskDto } from './dto/create-agent-task.dto';
import { ListAgentTasksDto } from './dto/list-agent-tasks.dto';
import { UpdateAgentTaskDto } from './dto/update-agent-task.dto';
import { AgentRun, AgentRunStatus } from './entities/agent-run.entity';
import { AgentTask, AgentTaskStatus } from './entities/agent-task.entity';

@Injectable()
export class LearningService {
  constructor(
    @InjectRepository(AgentTask)
    private readonly tasks: Repository<AgentTask>,
    @InjectRepository(AgentRun)
    private readonly runs: Repository<AgentRun>,
    private readonly dataSource: DataSource,
  ) {}

  async create(dto: CreateAgentTaskDto) {
    const task = this.tasks.create({
      ...dto,
      metadata: dto.metadata ?? {},
      availableAt: dto.availableAt ? new Date(dto.availableAt) : undefined,
    });

    return this.tasks.save(task);//上面只是创建Entity实例，还没有写入数据库，执行Save时才能写入数据库
  }

  async upsert(dto: CreateAgentTaskDto) {
    await this.tasks.upsert(
      {
        ...dto,
        metadata: (dto.metadata ?? {}) as QueryDeepPartialEntity<
          Record<string, unknown>
        >,
        availableAt: dto.availableAt ? new Date(dto.availableAt) : new Date(),
      },
      {
        conflictPaths: ['externalKey'],
        skipUpdateIfNoValuesChanged: true,
      },
    );

    return this.tasks.findOneByOrFail({ externalKey: dto.externalKey });
  }

  async findAll(dto: ListAgentTasksDto) {
    const limit = dto.limit ?? 20;
    const hasCreatedAt = dto.beforeCreatedAt !== undefined;
    const hasId = dto.beforeId !== undefined;

    if (hasCreatedAt !== hasId) {
      throw new BadRequestException('beforeCreatedAt 和 beforeId 必须同时提供');
    }

    const query = this.tasks
      .createQueryBuilder('task')
      .orderBy('task.createdAt', 'DESC')
      .addOrderBy('task.id', 'DESC')
      .take(limit);

    if (dto.beforeCreatedAt && dto.beforeId) {
      query.andWhere(
        '(task.createdAt < :beforeCreatedAt OR (task.createdAt = :beforeCreatedAt AND task.id < :beforeId))',
        {
          beforeCreatedAt: dto.beforeCreatedAt,
          beforeId: dto.beforeId,
        },
      );
    }

    const items = await query.getMany();
    const last = items.at(-1);

    return {
      items,
      nextCursor:
        items.length === limit && last
          ? {
              beforeCreatedAt: last.createdAt,
              beforeId: last.id,
            }
          : null,
    };
  }

  async findOne(id: string) {
    const task = await this.tasks.findOne({
      where: { id },
      relations: { runs: true },
      order: { runs: { createdAt: 'DESC' } },
    });

    if (!task) {
      throw new NotFoundException(`Learning task ${id} not found`);
    }

    return task;
  }

  async update(id: string, dto: UpdateAgentTaskDto) {
    const patch: QueryDeepPartialEntity<AgentTask> = {
      version: () => '"version" + 1',
    };

    if (dto.title !== undefined) patch.title = dto.title;
    if (dto.description !== undefined) patch.description = dto.description;
    if (dto.metadata !== undefined) {
      patch.metadata = dto.metadata as QueryDeepPartialEntity<
        Record<string, unknown>
      >;
    }
    if (dto.status !== undefined) patch.status = dto.status;
    if (dto.availableAt !== undefined) {
      patch.availableAt = new Date(dto.availableAt);
    }

    if (Object.keys(patch).length === 1) {
      throw new BadRequestException('至少提供一个需要修改的字段');
    }

    const result = await this.tasks.update(
      { id, version: dto.expectedVersion },
      patch,
    );

    if (result.affected !== 1) {
      throw new ConflictException(
        '任务不存在或版本已经变化，请重新读取后再更新',
      );
    }

    return this.findOne(id);
  }

  async remove(id: string) {
    const result = await this.tasks.delete(id);

    if (result.affected !== 1) {
      throw new NotFoundException(`Learning task ${id} not found`);
    }

    return { deleted: true };
  }

  async createRun(taskId: string, dto: CreateAgentRunDto) {
    return this.dataSource.transaction(async (manager) => {
      const task = await manager.findOneBy(AgentTask, { id: taskId });

      if (!task) {
        throw new NotFoundException(`Learning task ${taskId} not found`);
      }

      const run = manager.create(AgentRun, {
        taskId,
        status: AgentRunStatus.RUNNING,
        input: dto.input ?? {},
      });

      const savedRun = await manager.save(run);

      await manager.update(AgentTask, taskId, {
        status: AgentTaskStatus.RUNNING,
      });

      return savedRun;
    });
  }

  async claimNextQueuedTask(workerId: string) {
    const queryRunner = this.dataSource.createQueryRunner();

    await queryRunner.connect();
    await queryRunner.startTransaction();

    try {
      const rawRows: unknown = await queryRunner.query(
        `WITH next_task AS (
           SELECT id
           FROM learning_agent_tasks
           WHERE status = $1
             AND available_at <= CURRENT_TIMESTAMP
           ORDER BY available_at ASC, id ASC
           FOR UPDATE SKIP LOCKED
           LIMIT 1
         )
         UPDATE learning_agent_tasks AS task
         SET status = $2,
             locked_at = CURRENT_TIMESTAMP,
             locked_by = $3,
             attempt_count = task.attempt_count + 1,
             version = task.version + 1,
             updated_at = CURRENT_TIMESTAMP
         FROM next_task
         WHERE task.id = next_task.id
         RETURNING task.*`,
        [AgentTaskStatus.QUEUED, AgentTaskStatus.RUNNING, workerId],
      );

      const rows = rawRows as AgentTask[];

      await queryRunner.commitTransaction();
      return rows[0] ?? null;
    } catch (error) {
      await queryRunner.rollbackTransaction();
      throw error;
    } finally {
      await queryRunner.release();
    }
  }

  async getStatusCounts() {
    return this.tasks
      .createQueryBuilder('task')
      .select('task.status', 'status')
      .addSelect('COUNT(*)::int', 'count')
      .groupBy('task.status')
      .orderBy('task.status', 'ASC')
      .getRawMany<{ status: AgentTaskStatus; count: number }>();
  }
}
