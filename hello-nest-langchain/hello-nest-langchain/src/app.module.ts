import { Module } from '@nestjs/common';
import { AppController } from './app.controller';
import { AppService } from './app.service';
import { BookModule } from './book/book.module';
import { AiModule } from './ai/ai.module';
import { ConfigModule } from '@nestjs/config';
import { ServeStaticModule } from '@nestjs/serve-static';
import { join } from 'path';

@Module({
  imports: [
    ServeStaticModule.forRoot({//nest 服务支持静态 html 文件访问
      rootPath: join(__dirname, '..', 'public'),//访问上一层目录的public文件夹，也就是根目录下的public文件夹
    }),
    BookModule,
    AiModule,
    ConfigModule.forRoot({
      isGlobal: true, //isGlobal 设置为 true 就是全局模块，也就是不用 imports 就可以注入里面的 provider
      envFilePath: '.env',
    }),
  ],
  controllers: [AppController],
  providers: [AppService],
})
export class AppModule {}