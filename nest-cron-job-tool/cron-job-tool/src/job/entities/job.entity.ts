import {
  Column,
  CreateDateColumn,
  Entity,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
} from 'typeorm';

//参考openclawd的设计，定义一个 Job 实体类，包含以下任务属性：
export type JobType = 'cron' | 'every' | 'at';

@Entity()
export class Job {

    // 使用 UUID 作为主键，确保分布式环境下的唯一性
    @PrimaryGeneratedColumn('uuid')
    id: string;

    //指令文本，比如“每天晚上 10 点提醒我写今日总结”，这个“写今日总结”就是指令文本
    @Column({ type: 'text' })
    instruction: string;

    @Column({ type: 'varchar', length: 10, default: 'cron' })
    type: JobType;

    // cron 类型使用（Cron 表达式）
    @Column({ type: 'varchar', length: 100, nullable: true })
    cron: string | null;

    // every 类型使用（间隔毫秒）
    @Column({ type: 'int', nullable: true })
    everyMs: number | null;

    // at 类型使用（指定触发时间点）
    @Column({ type: 'timestamp', nullable: true })
    at: Date | null;

    @Column({ default: true })
    isEnabled: boolean;

    @Column({ type: 'timestamp', nullable: true })
    lastRun: Date | null;

    @CreateDateColumn({ type: 'timestamp' })
    createdAt: Date;

    @UpdateDateColumn({ type: 'timestamp' })
    updatedAt: Date;
}