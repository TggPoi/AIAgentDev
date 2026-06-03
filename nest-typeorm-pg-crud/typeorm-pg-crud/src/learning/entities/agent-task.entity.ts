import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  OneToMany,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
  VersionColumn,
} from 'typeorm';
import { AgentRun } from './agent-run.entity';

// AgentTaskStatus 表示任务生命周期中的状态。
// 使用 enum 可以让 TypeScript 和数据库 enum 保持同一组合法值。
export enum AgentTaskStatus {
  QUEUED = 'queued',
  RUNNING = 'running',
  SUCCEEDED = 'succeeded',
  FAILED = 'failed',
}

// @Entity 把 TypeScript 类映射到 PostgreSQL 表 learning_agent_tasks。
@Entity('learning_agent_tasks')
// 常规复合索引：适合按 status + availableAt 查询任务。
@Index('idx_learning_agent_tasks_status_available', ['status', 'availableAt'])
// 部分索引：只索引 queued 任务。
// 领取任务时只关心排队任务，部分索引可以减少索引体积和扫描范围。
@Index('idx_learning_agent_tasks_queued_available', ['availableAt', 'id'], {
  where: `"status" = 'queued'`,
})
export class AgentTask {
  // UUID 主键由数据库自动生成。
  @PrimaryGeneratedColumn('uuid')
  id: string;

  // 外部业务唯一键，用于 upsert 幂等写入。
  @Column({ type: 'text', name: 'external_key', unique: true })
  externalKey: string;

  // 任务标题，必填。
  @Column({ type: 'text' })
  title: string;

  // 可选任务说明；nullable: true 表示数据库允许 NULL。
  @Column({ type: 'text', nullable: true })
  description: string | null;

  // jsonb 保存结构不固定的补充信息，例如来源、标签、工具参数快照。
  @Column({ type: 'jsonb', default: () => "'{}'::jsonb" })
  metadata: Record<string, unknown>;

  // enum 列会把 AgentTaskStatus 中的值映射为数据库可接受的状态集合。
  @Column({
    type: 'enum',
    enum: AgentTaskStatus,
    default: AgentTaskStatus.QUEUED,
  })
  status: AgentTaskStatus;

  // 任务已经被领取或重试的次数。
  @Column({ type: 'int', name: 'attempt_count', default: 0 })
  attemptCount: number;

  // 任务最早可被领取的时间。
  // 失败重试时可以把它设置到未来，实现延迟重试。
  @Column({
    type: 'timestamptz',
    name: 'available_at',
    default: () => 'CURRENT_TIMESTAMP',
  })
  availableAt: Date;

  // 当前任务被哪个 worker 锁定的时间。
  @Column({ type: 'timestamptz', name: 'locked_at', nullable: true })
  lockedAt: Date | null;

  // 当前任务被哪个 worker 领取。
  @Column({ type: 'text', name: 'locked_by', nullable: true })
  lockedBy: string | null;

  // 乐观锁版本号。
  // TypeORM 在 save 场景中可以使用它；当前工程也手动在 update 中检查并递增它。
  @VersionColumn()
  version: number;

  // 创建时间由数据库/TypeORM 自动写入。
  @CreateDateColumn({ type: 'timestamptz', name: 'created_at' })
  createdAt: Date;

  // 更新时间由数据库/TypeORM 自动维护。
  @UpdateDateColumn({ type: 'timestamptz', name: 'updated_at' })
  updatedAt: Date;

  // 一个任务可以有多次运行记录。
  // 这是 AgentTask -> AgentRun 的一对多关系。
  @OneToMany(() => AgentRun, (run) => run.task)
  runs: AgentRun[];
}
