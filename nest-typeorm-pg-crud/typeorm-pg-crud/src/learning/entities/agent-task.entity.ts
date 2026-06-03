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

export enum AgentTaskStatus {
  QUEUED = 'queued',
  RUNNING = 'running',
  SUCCEEDED = 'succeeded',
  FAILED = 'failed',
}

@Entity('learning_agent_tasks')
@Index('idx_learning_agent_tasks_status_available', ['status', 'availableAt'])
@Index('idx_learning_agent_tasks_queued_available', ['availableAt', 'id'], {
  where: `"status" = 'queued'`,
})
export class AgentTask {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'text', name: 'external_key', unique: true })
  externalKey: string;

  @Column({ type: 'text' })
  title: string;

  @Column({ type: 'text', nullable: true })
  description: string | null;

  @Column({ type: 'jsonb', default: () => "'{}'::jsonb" })
  metadata: Record<string, unknown>;

  @Column({
    type: 'enum',
    enum: AgentTaskStatus,
    default: AgentTaskStatus.QUEUED,
  })
  status: AgentTaskStatus;

  @Column({ type: 'int', name: 'attempt_count', default: 0 })
  attemptCount: number;

  @Column({
    type: 'timestamptz',
    name: 'available_at',
    default: () => 'CURRENT_TIMESTAMP',
  })
  availableAt: Date;

  @Column({ type: 'timestamptz', name: 'locked_at', nullable: true })
  lockedAt: Date | null;

  @Column({ type: 'text', name: 'locked_by', nullable: true })
  lockedBy: string | null;

  @VersionColumn()
  version: number;

  @CreateDateColumn({ type: 'timestamptz', name: 'created_at' })
  createdAt: Date;

  @UpdateDateColumn({ type: 'timestamptz', name: 'updated_at' })
  updatedAt: Date;

  @OneToMany(() => AgentRun, (run) => run.task)
  runs: AgentRun[];
}
