import { Inject, Module, OnApplicationBootstrap } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { AiModule } from './ai/ai.module';
import { ConfigModule } from '@nestjs/config/dist/config.module';
import { ConfigService } from '@nestjs/config/dist/config.service';
import { MailerModule } from '@nestjs-modules/mailer';
import { ServeStaticModule } from '@nestjs/serve-static/dist/serve-static.module';
import { join } from 'path/win32';
import { TypeOrmModule } from '@nestjs/typeorm';
import { UsersModule } from './users/users.module';
import { User } from './users/entities/user.entity';
import { CronExpression, ScheduleModule, SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { JobModule } from './job/job.module';
import { Job } from './job/entities/job.entity';
import { ToolModule } from './tool/tool.module';

@Module({
  imports: [
    ScheduleModule.forRoot(),//定时任务模块
    TypeOrmModule.forRoot({//数据库连接配置
      type: 'mysql',
      host: 'localhost',
      port: 3307,
      username: 'root',
      password: 'admin',
      database: 'hello',
      synchronize: true, //服务启动的时候自动建表
      connectorPackage: 'mysql2',
      logging: true, //打印 sql 语句日志
      entities: [User,Job],
    }),
    AiModule,
    ServeStaticModule.forRoot({//nest 服务支持静态 html 文件访问
      rootPath: join(__dirname, '..', 'public'),//访问上一层目录的public文件夹，也就是根目录下的public文件夹
    }),
    ConfigModule.forRoot({
      isGlobal: true, //isGlobal 设置为 true 就是全局模块，也就是不用 imports 就可以注入里面的 provider
      envFilePath: '.env',
    }),
    MailerModule.forRootAsync({
      inject: [ConfigService],
      useFactory: (configService: ConfigService) => ({
        transport: {
          host: configService.get<string>('MAIL_HOST'),
          port: Number(configService.get<string>('MAIL_PORT')),
          secure: configService.get<string>('MAIL_SECURE') === 'true',
          auth: {
            user: configService.get<string>('MAIL_USER'),
            pass: configService.get<string>('MAIL_PASS'),
          },
        },
        defaults: {
          from:
            configService.get<string>('MAIL_FROM')
        },
      }),
    }),
    UsersModule,
    JobModule,
    ToolModule,
  ],
  controllers: [AppController],
  providers: [AppService],
})

//AppModule 实现 OnApplicationBootstrap 接口，在应用启动后执行一些定时任务的注册测试
export class AppModule /*implements OnApplicationBootstrap*/ {

  //注入 SchedulerRegistry 来管理定时任务
  // @Inject(SchedulerRegistry)
  // schedulerRegistry: SchedulerRegistry;

  //在应用启动后注册一些定时任务的测试
  // async onApplicationBootstrap() {

  //   const job = new CronJob(CronExpression.EVERY_SECOND, () => {
  //     console.log('run job');
  //   });

  //   this.schedulerRegistry.addCronJob('job1', job);

  //   job.start();

  //   setTimeout(() => {
  //     this.schedulerRegistry.deleteCronJob('job1');
  //   }, 5000);

  //   const intervalRef = setInterval(() => {
  //     console.log('run interval job');
  //   }, 1000);

  //   this.schedulerRegistry.addInterval('interval1', intervalRef);

  //   setTimeout(() => {
  //     this.schedulerRegistry.deleteInterval('interval1');
  //   }, 5000);

  //   const timeoutRef = setTimeout(() => {
  //     console.log('run timeout job');
  //   }, 3000);

  //   this.schedulerRegistry.addTimeout('timeout1', timeoutRef);

  //   setTimeout(() => {
  //     this.schedulerRegistry.deleteTimeout('timeout1');
  //   }, 5000);
  // }
}
