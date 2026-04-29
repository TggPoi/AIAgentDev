import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { AiModule } from './ai/ai.module';
import { config } from 'process';
import { ConfigModule } from '@nestjs/config';
import { SpeechModule } from './speech/speech.module';
import { ServeStaticModule } from '@nestjs/serve-static';
import { join } from 'path/win32';
import { EventEmitter } from 'stream';
import { EventEmitterModule } from '@nestjs/event-emitter';


@Module({
  imports: [
    AiModule,
    ConfigModule.forRoot({
      envFilePath: '.env',
      isGlobal: true,
    }),
    ServeStaticModule.forRoot({
      rootPath: join(__dirname, '..', 'public'),
    }),
    //事件监听器，增加最大监听数，避免内存泄漏警告
    EventEmitterModule.forRoot({
      maxListeners: 200,
    }),
    SpeechModule,
  ],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}
