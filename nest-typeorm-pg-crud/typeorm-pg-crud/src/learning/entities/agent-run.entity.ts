import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  JoinColumn,
  ManyToOne,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
} from 'typeorm';
import { AgentTask } from './agent-task.entity';

// AgentRunStatus 表示一次任务运行的状态。
export enum AgentRunStatus {
  RUNNING = 'running',
  SUCCEEDED = 'succeeded',
  FAILED = 'failed',
}

// @Entity 把 TypeScript 类映射到 PostgreSQL 表 learning_agent_runs。
@Entity('learning_agent_runs')
// 查询某个任务的运行历史时，通常按 taskId 过滤并按 createdAt 排序。
@Index('idx_learning_agent_runs_task_created', ['taskId', 'createdAt'])
export class AgentRun {
  // UUID 主键由数据库自动生成。
  @PrimaryGeneratedColumn('uuid')
  id: string;

  // 外键列，保存它属于哪个 AgentTask。
  @Column({ type: 'uuid', name: 'task_id' })
  taskId: string;

  // 本次运行的状态。
  @Column({
    type: 'enum',
    enum: AgentRunStatus,
    default: AgentRunStatus.RUNNING,
  })
  status: AgentRunStatus;

  // 本次运行的输入，使用 jsonb 保存不同 Agent 的不同输入结构。
  @Column({ type: 'jsonb', default: () => "'{}'::jsonb" })
  input: Record<string, unknown>;

  // 本次运行的输出。运行未完成或失败时可以为空。
  @Column({ type: 'jsonb', nullable: true })
  output: Record<string, unknown> | null;

  // 失败原因，成功时为空。
  @Column({ type: 'text', name: 'error_message', nullable: true })
  errorMessage: string | null;

  // 创建时间由数据库/TypeORM 自动写入。
  @CreateDateColumn({ type: 'timestamptz', name: 'created_at' })
  createdAt: Date;

  // 更新时间由数据库/TypeORM 自动维护。
  @UpdateDateColumn({ type: 'timestamptz', name: 'updated_at' })
  updatedAt: Date;

  // 多对一关系：多条运行记录属于同一个任务。
  // onDelete: 'CASCADE' 表示删除任务时，关联运行记录也会被删除。
  @ManyToOne(() => AgentTask, (task) => task.runs, { onDelete: 'CASCADE' })
  // JoinColumn 指定外键列名是 task_id。
  @JoinColumn({ name: 'task_id' })
  task: AgentTask;
}
