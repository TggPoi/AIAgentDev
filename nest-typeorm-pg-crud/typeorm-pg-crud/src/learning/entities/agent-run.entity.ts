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

export enum AgentRunStatus {
  RUNNING = 'running',
  SUCCEEDED = 'succeeded',
  FAILED = 'failed',
}

@Entity('learning_agent_runs')
@Index('idx_learning_agent_runs_task_created', ['taskId', 'createdAt'])
export class AgentRun {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'uuid', name: 'task_id' })
  taskId: string;

  @Column({
    type: 'enum',
    enum: AgentRunStatus,
    default: AgentRunStatus.RUNNING,
  })
  status: AgentRunStatus;

  @Column({ type: 'jsonb', default: () => "'{}'::jsonb" })
  input: Record<string, unknown>;

  @Column({ type: 'jsonb', nullable: true })
  output: Record<string, unknown> | null;

  @Column({ type: 'text', name: 'error_message', nullable: true })
  errorMessage: string | null;

  @CreateDateColumn({ type: 'timestamptz', name: 'created_at' })
  createdAt: Date;

  @UpdateDateColumn({ type: 'timestamptz', name: 'updated_at' })
  updatedAt: Date;

  @ManyToOne(() => AgentTask, (task) => task.runs, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'task_id' })
  task: AgentTask;
}
