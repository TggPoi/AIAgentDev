import {
  Inject,
  Injectable,
  Logger,
  NotFoundException,
  OnApplicationBootstrap,
} from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { EntityManager } from 'typeorm';
import { Job } from './entities/job.entity';
import { JobAgentService } from '../ai/job-agent.service';

@Injectable()
export class JobService implements OnApplicationBootstrap {
  private readonly logger = new Logger(JobService.name);

  @Inject(EntityManager)
  private readonly entityManager: EntityManager;

  @Inject(SchedulerRegistry)
  private readonly schedulerRegistry: SchedulerRegistry;

  @Inject(JobAgentService)
  private readonly jobAgentService: JobAgentService;

  async onApplicationBootstrap() {

    // 应用启动后，自动注册数据库中所有 isEnabled=true 允许启用 的任务
    const enabledJobs = await this.entityManager.find(Job, {
      where: { isEnabled: true },
    });
    const cronJobs = this.schedulerRegistry.getCronJobs();
    const intervals = this.schedulerRegistry.getIntervals();
    const timeouts = this.schedulerRegistry.getTimeouts();

    //循环遍历数据库中的所有任务，对于每个任务，检查它是否已经在调度器中注册（通过 ID 判断）。如果已经注册了，就跳过；如果没有注册过，就调用 startRuntime 方法注册它。这样可以确保应用启动后，数据库中所有允许启用的任务都能被正确注册到调度器中，并且避免重复注册同一个任务。
    for (const job of enabledJobs) {

      // 已经注册了的就跳过（可能是重复的 isEnabled=true 记录，或者是上次应用运行时注册了但还没到下次执行时间的记录）
      const alreadyRegistered =
        (job.type === 'cron' && cronJobs.has(job.id)) ||
        (job.type === 'every' && intervals.includes(job.id)) ||
        (job.type === 'at' && timeouts.includes(job.id));

      if (alreadyRegistered) continue;

      // 没有注册过的就注册
      await this.startRuntime(job);
    }
  }

  //列出所有任务，并且标记出哪些任务正在调度器中运行（running）。
  //对于每个任务，根据它的类型和 ID，检查它是否在调度器中注册并且启用了，如果是就标记为 running=true，否则为 false。这样可以让用户清楚地看到每个任务的状态，方便管理和监控。
  async listJobs() {
    const jobs = await this.entityManager.find(Job, {
      order: { createdAt: 'DESC' },
    });

    const cronJobs = this.schedulerRegistry.getCronJobs();
    const intervalNames = this.schedulerRegistry.getIntervals();
    const timeoutNames = this.schedulerRegistry.getTimeouts();

    return jobs.map((job) => {
      //判断当前任务是否正在运行
      const running =
        job.isEnabled &&
        ((job.type === 'cron' && cronJobs.has(job.id)) ||
          (job.type === 'every' && intervalNames.includes(job.id)) ||
          (job.type === 'at' && timeoutNames.includes(job.id)));

      //返回任务信息和运行状态
      return {
        ...job,
        running,
      };
    });
  }

  //新增任务
  async addJob(
    input:
      | {//联合类型，input 的类型可以是以下三种之一，分别对应 cron、every 和 at 三种类型的任务，每种类型的任务需要提供不同的属性：
          type: 'cron';
          instruction: string;
          cron: string;
          isEnabled?: boolean;
        }
      | {
          type: 'every';
          instruction: string;
          everyMs: number;
          isEnabled?: boolean;
        }
      | {
          type: 'at';
          instruction: string;
          at: Date;
          isEnabled?: boolean;
        },
  ) {

    const entity = this.entityManager.create(Job, {
      instruction: input.instruction,
      type: input.type,
      cron: input.type === 'cron' ? input.cron : null,
      everyMs: input.type === 'every' ? input.everyMs : null,
      at: input.type === 'at' ? input.at : null,
      isEnabled: input.isEnabled ?? true,
      lastRun: null,
    });

    //数据库保存任务
    const saved = await this.entityManager.save(Job, entity);

    //如果在保存操作完成后，isEnabled已经为true，就直接执行
    if (saved.isEnabled) {
      await this.startRuntime(saved);
    }

    return saved;
  }

  //触发任务执行
  async toggleJob(jobId: string, enabled?: boolean) {

    const job = await this.entityManager.findOne(Job, { where: { id: jobId } });

    if (!job) throw new NotFoundException(`Job not found: ${jobId}`);

    const nextEnabled = enabled ?? !job.isEnabled;

    //更新数据库中任务的启用状态：在切换任务状态时，先检查这个任务当前的 isEnabled 字段和要切换到的状态是否不同，如果不同就更新数据库中这个任务的 isEnabled 字段为新的状态。
    //这样可以确保数据库中的任务状态与调度器中的状态保持一致，避免因为状态不同步而导致任务执行异常或者管理混乱。
    if (job.isEnabled !== nextEnabled) {
      job.isEnabled = nextEnabled;
      await this.entityManager.save(Job, job);
    }

    if (job.isEnabled) {
      await this.startRuntime(job);
    } else {
      this.stopRuntime(job);
    }

    return job;
  }

  private async startRuntime(job: Job) {
    //防止分布式多实例重复注册：先检查这个任务是否已经在调度器中注册了，如果已经注册了就直接返回，不再重复注册。这样可以避免同一个任务被重复注册多次，导致定时执行异常或者资源浪费。
    if (job.type === 'cron') {
      const cronJobs = this.schedulerRegistry.getCronJobs();

      const existing = cronJobs.get(job.id);

      if (existing) {
        existing.start();

        return;
      }

      const runtimeJob = this.createCronJob(job);

      this.schedulerRegistry.addCronJob(job.id, runtimeJob);
      runtimeJob.start();
      return;
    }

    if (job.type === 'every') {

      const names = this.schedulerRegistry.getIntervals();

      if (names.includes(job.id)) return;

      //判断当前任务的时间单位是否有效：如果是 every 类型的任务，需要提供一个有效的时间间隔（everyMs），并且这个时间间隔必须是一个正整数（单位毫秒）。
      // 如果提供的时间间隔无效，就抛出一个错误，提示用户检查输入。这样可以确保每个 every 类型的任务都有一个合理的执行频率，避免因为时间间隔设置不当而导致系统性能问题或者任务执行异常。
      if (typeof job.everyMs !== 'number' || job.everyMs <= 0) {
        throw new Error(`Invalid everyMs for job ${job.id}`);
      }

      const ref = setInterval(async () => {

        this.logger.log(`run job ${job.id}, ${job.instruction}`);

        //更新数据库中任务的状态为正在运行：在每次执行任务之前，先更新数据库中对应任务的 lastRun 字段为当前时间，这样可以记录每个任务的最新执行时间，方便后续查询和监控。
        await this.entityManager.update(Job, job.id, { lastRun: new Date() });

        try {
          //数据库状态更新完后，调用 JobAgentService 来执行这个任务的指令，并且把执行结果记录到日志中。
          const result = await this.jobAgentService.runJob(job.instruction);

          this.logger.log(`[job ${job.id}] ${result}`);
          
        } catch (e) {
          this.logger.error(
            `job ${job.id} agent execution error: ${(e as Error).message}`,
          );
        }
      }, job.everyMs);

      //把这个定时器的引用注册到调度器中，这样后续就可以通过调度器来管理这个定时器（比如取消或者修改）。同时也可以通过调度器来避免重复注册同一个任务。
      this.schedulerRegistry.addInterval(job.id, ref);
      return;
    }


    if (job.type === 'at') {

      const names = this.schedulerRegistry.getTimeouts();

      if (names.includes(job.id)) return;

      //当前任务类型的时间点是否有效：如果是 at 类型的任务，需要提供一个有效的时间点（at），并且这个时间点必须是一个合法的 ISO 时间字符串，并且不能是一个已经过去的时间。
      if (!job.at) {
        throw new Error(`Invalid at for job ${job.id}`);
      }

      //毫秒换算：计算当前时间点距离现在的毫秒数，如果这个时间点已经过去了，就抛出一个错误，提示用户检查输入。这样可以确保每个 at 类型的任务都有一个合理的执行时间，避免因为时间设置不当而导致任务无法执行或者立即执行。
      const delay = Math.max(0, job.at.getTime() - Date.now());

      //设置任务逻辑
      const ref = setTimeout(async () => {

        this.logger.log(`run job ${job.id}, ${job.instruction}`);
        //更新数据库任务状态为正在运行：在执行 at 类型的任务时，由于这个任务只会执行一次，所以在执行之前先更新数据库中对应任务的 lastRun 字段为当前时间，并且把 isEnabled 字段设置为 false，这样可以记录这个任务的最新执行时间，并且标记这个任务已经执行过了，避免后续再次执行。
        await this.entityManager.update(Job, job.id, {
          lastRun: new Date(),
          isEnabled: false, // at 类型只执行一次：执行完自动停用
        });

        try {

          const result = await this.jobAgentService.runJob(job.instruction);
          this.logger.log(`[job ${job.id}] ${result}`);

        } catch (e) {
          this.logger.error(
            `job ${job.id} agent execution error: ${(e as Error).message}`,
          );
        }

        try {
          //因为只执行一次，所以执行完后就从调度器中删除这个定时器，避免重复执行。
          this.schedulerRegistry.deleteTimeout(job.id);
        } catch {
          // ignore
        }
      }, delay);

      //任务逻辑 ref设置完成，注册到调度器中
      this.schedulerRegistry.addTimeout(job.id, ref);
      return;
    }
  }

  private stopRuntime(job: Job) {
    //cron类型的job调用stop停止，另外两个类型的任务直接删除，因为它们都是基于一次性定时器实现的，不需要像cron类型的任务那样支持停止和重启。
    //对于cron类型的任务，调用stop方法可以暂停这个任务的执行，直到下一次触发时间到来时才会继续执行；
    // 而对于every和at类型的任务，直接删除这个定时器就可以了，因为它们要么是基于setInterval实现的循环定时器，要么是基于setTimeout实现的一次性定时器，删除后就不会再触发了。
    if (job.type === 'cron') {
      const cronJobs = this.schedulerRegistry.getCronJobs();
      const runtimeJob = cronJobs.get(job.id);

      if (runtimeJob) runtimeJob.stop();

      return;
    }

    if (job.type === 'every') {
      try {
        this.schedulerRegistry.deleteInterval(job.id);
      } catch {
        // ignore
      }
      return;
    }

    if (job.type === 'at') {
      try {
        this.schedulerRegistry.deleteTimeout(job.id);
      } catch {
        // ignore
      }
      return;
    }
  }

  //解析cron表达式
  private createCronJob(job: Job) {

    const cronExpr = job.cron ?? '';

    return new CronJob(cronExpr, async () => {

      this.logger.log(`run job ${job.id}, ${job.instruction}`);
      await this.entityManager.update(Job, job.id, { lastRun: new Date() });

      try {
        const result = await this.jobAgentService.runJob(job.instruction);

        this.logger.log(`[job ${job.id}] ${result}`);
      } catch (e) {
        this.logger.error(
          `job ${job.id} agent execution error: ${(e as Error).message}`,
        );
      }
    });
  }
}