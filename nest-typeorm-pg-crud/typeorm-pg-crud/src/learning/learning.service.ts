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
    // Repository<AgentTask> 是专门操作 learning_agent_tasks 表的对象。
    // 普通 CRUD 优先使用 Repository，类型更明确。
    @InjectRepository(AgentTask)
    private readonly tasks: Repository<AgentTask>,
    // Repository<AgentRun> 是专门操作 learning_agent_runs 表的对象。
    @InjectRepository(AgentRun)
    private readonly runs: Repository<AgentRun>,
    // DataSource 用于开启事务、创建 QueryRunner，以及执行更底层的数据库操作。
    private readonly dataSource: DataSource,
  ) {}

  // 普通创建任务：create() 只创建 Entity 实例，save() 才真正写入数据库。
  async create(dto: CreateAgentTaskDto) {
    const task = this.tasks.create({
      ...dto,
      // 请求没传 metadata 时，给 jsonb 字段一个空对象。
      metadata: dto.metadata ?? {},
      // DTO 中的 availableAt 是字符串，Entity 中的 availableAt 是 Date。
      availableAt: dto.availableAt ? new Date(dto.availableAt) : undefined,
    });

    return this.tasks.save(task);
  }

  // 幂等写入：externalKey 相同表示同一个外部业务任务。
  // 第一次请求会 INSERT；重复请求触发唯一键冲突时会 UPDATE。
  async upsert(dto: CreateAgentTaskDto) {
    await this.tasks.upsert(
      {
        ...dto,
        // QueryDeepPartialEntity 是 TypeORM update/upsert 使用的“部分字段对象”类型。
        // 这里的类型断言只影响 TypeScript 检查，不改变运行时数据。
        metadata: (dto.metadata ?? {}) as QueryDeepPartialEntity<
          Record<string, unknown>
        >,
        availableAt: dto.availableAt ? new Date(dto.availableAt) : new Date(),
      },
      {
        // 告诉 TypeORM：发生 externalKey 唯一约束冲突时，走 upsert 更新逻辑。
        conflictPaths: ['externalKey'],
        // 新旧值没有变化时尽量跳过 UPDATE，减少无意义写入。
        skipUpdateIfNoValuesChanged: true,
      },
    );

    // upsert 返回的是执行结果，不一定包含完整 Entity。
    // 为了接口返回完整任务，这里再按 externalKey 查询一次。
    return this.tasks.findOneByOrFail({ externalKey: dto.externalKey });
  }

  // 任务列表使用稳定游标分页。
  // 排序字段是 createdAt DESC + id DESC，游标也必须同时包含这两个字段。
  async findAll(dto: ListAgentTasksDto) {
    const limit = dto.limit ?? 20;
    const hasCreatedAt = dto.beforeCreatedAt !== undefined;
    const hasId = dto.beforeId !== undefined;

    // 只传 beforeCreatedAt 或只传 beforeId 都会导致分页条件不完整。
    if (hasCreatedAt !== hasId) {
      throw new BadRequestException('beforeCreatedAt 和 beforeId 必须同时提供');
    }

    // QueryBuilder 适合表达动态 WHERE、ORDER BY、分页等复杂查询。
    const query = this.tasks
      .createQueryBuilder('task') //开始构造 SQL，把下面的步骤组合为一个SQL
      .orderBy('task.createdAt', 'DESC')
      .addOrderBy('task.id', 'DESC')
      .take(limit);

    if (dto.beforeCreatedAt && dto.beforeId) {
      // 游标条件：
      // 1. 先取 createdAt 更早的记录；
      // 2. 如果 createdAt 相同，再取 id 更小的记录。
      query.andWhere(
        '(task.createdAt < :beforeCreatedAt OR (task.createdAt = :beforeCreatedAt AND task.id < :beforeId))',
        {
          beforeCreatedAt: dto.beforeCreatedAt,
          beforeId: dto.beforeId,
        },
      );
    }

    const items = await query.getMany();
    const last = items.at(-1);//at(-1) 是 ES2022 的新方法，等同于 items[items.length - 1]，但在 items 为空时不会抛错，而是返回 undefined。

    // 如果本页查询到的数量等于 limit，说明可能还有下一页。
    // 下一次请求把最后一条记录作为游标传回来。
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

  // 查询单个任务，并带出它的一对多运行记录 runs。
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

  // 使用乐观锁更新任务。
  // 客户端必须提交 expectedVersion，只有数据库当前 version 匹配时才允许更新。
  async update(id: string, dto: UpdateAgentTaskDto) {
    // patch 表示本次要 SET 的字段，不是完整 Entity。
    const patch: QueryDeepPartialEntity<AgentTask> = {
      // 使用 SQL 表达式让数据库在当前值基础上自增，而不是在应用层先读再加。
      version: () => '"version" + 1',
    };

    // PATCH 语义：只更新请求体里出现的字段。
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

    // 如果 patch 里只有 version，说明用户没有提供任何业务字段。
    if (Object.keys(patch).length === 1) {
      throw new BadRequestException('至少提供一个需要修改的字段');
    }

    // WHERE 条件同时带 id 和 version。
    // 如果 version 不匹配，affected 会是 0，表示数据已被别人修改。
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

  // 直接删除任务。
  // 因为 AgentRun 对 AgentTask 使用 onDelete: 'CASCADE'，删除任务时运行记录也会被删除。
  async remove(id: string) {
    const result = await this.tasks.delete(id);

    if (result.affected !== 1) {
      throw new NotFoundException(`Learning task ${id} not found`);
    }

    return { deleted: true };
  }

  // 创建一次任务运行记录，并同步把任务状态改成 running。
  // 这两个写入必须在同一个事务里，要么一起成功，要么一起失败。
  async createRun(taskId: string, dto: CreateAgentRunDto) {
    return this.dataSource.transaction(async (manager) => {
      // 事务中必须使用回调参数 manager，不能混用外部注入的 Repository。
      const task = await manager.findOneBy(AgentTask, { id: taskId });

      if (!task) {
        throw new NotFoundException(`Learning task ${taskId} not found`);
      }

      // manager.create() 只创建 Entity 实例，不会立即写入数据库。
      const run = manager.create(AgentRun, {
        taskId,
        status: AgentRunStatus.RUNNING,
        input: dto.input ?? {},
      });

      // save() 才真正 INSERT 到 learning_agent_runs。
      const savedRun = await manager.save(run);

      // 同一事务中更新任务状态。
      await manager.update(AgentTask, taskId, {
        status: AgentTaskStatus.RUNNING,
      });

      return savedRun;
    });
  }

  // 领取下一条 queued 任务。
  // 这里使用 QueryRunner 是为了手动控制同一条连接、事务和行锁。
  async claimNextQueuedTask(workerId: string) {
    const queryRunner = this.dataSource.createQueryRunner();

    // QueryRunner 使用前必须先连接，再开启事务。
    await queryRunner.connect();
    await queryRunner.startTransaction();

    try {
      // 这段 SQL 做了两件事：
      // 1. CTE next_task 找到一条可领取任务，并使用 FOR UPDATE SKIP LOCKED 加锁；
      // 2. 外层 UPDATE 把这条任务改为 running，并返回更新后的行。
      const rawRows: unknown = await queryRunner.query(
        `WITH next_task AS (
           SELECT id
           FROM learning_agent_tasks
           WHERE status = $1
             AND available_at <= CURRENT_TIMESTAMP
           ORDER BY available_at ASC, id ASC
           -- FOR UPDATE 锁住选中的行；SKIP LOCKED 跳过已被其他 worker 锁住的行。
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

      // 只有提交事务后，本次领取才真正生效，行锁也会释放。
      await queryRunner.commitTransaction();
      return rows[0] ?? null;
    } catch (error) {
      // 任意错误都回滚，避免任务状态被更新一半。
      await queryRunner.rollbackTransaction();
      throw error;
    } finally {
      // 无论成功失败，都必须释放连接，否则连接池会被耗尽。
      await queryRunner.release();
    }
  }

  // 按任务状态分组统计数量。
  // getRawMany 返回原始查询结果，不会自动映射成 Entity。
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
